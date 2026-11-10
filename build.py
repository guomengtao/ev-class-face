#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一构建入口：一款表盘 × 一个机型 = 一个 .face 包。

    python3 build.py --face class --device band9            # 版本号 patch 自动 +1
    python3 build.py --face class --device band9 --no-bump   # 同版本再出一个机型
    python3 build.py --face class --device band10pro --preview-only

约定（三条，改之前先想清楚）：
  * ID 标识「表盘产品」，跨机型共用、正式发布后永久固定；
  * 包(.face) 标识「表盘产品 × 机型」，必须每机型一个；
  * 版本号跟表盘产品走，一个版本号对应 N 个机型的包。
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from shared.face_container import FaceImage           # noqa: E402
from shared import preview as preview_mod            # noqa: E402
from shared import rle                               # noqa: E402

P_BEGIN, P_END = "-- @@PROFILE_BEGIN@@", "-- @@PROFILE_END@@"


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def bump_version(vf, do_bump):
    data = {"major": 1, "minor": 0, "patch": 0}
    if vf.exists():
        data.update(load_json(vf))
    old = "v%d.%d.%d" % (data["major"], data["minor"], data["patch"])
    if do_bump:
        data["patch"] += 1
        vf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    new = "v%d.%d.%d" % (data["major"], data["minor"], data["patch"])
    return old, new


def profile_lua(dev):
    """机型 profile → Lua 字面量表，构建时整块替换源码里的 @@PROFILE@@ 段。

    通用化：不再假定「时间/课程/状态」那套固定字段，
    凡是 devices/<机型>.json 里 fonts / rows 出现的键都会原样导出为
    f_<key> / y_<key> / h_<key> / w_<key>。
    这样加一款表盘只需加 faces/<name>/ + 在 rows 里补它的行，
    不用回来改构建器；老字段(subj/stat/ver/bar_w/bar_h)保留别名做兼容。
    """
    kv = [("safe_top", dev["safe_area"]["top"]),
          ("safe_bottom", dev["safe_area"]["bottom"])]
    fonts = dev.get("fonts") or {}
    for k, v in fonts.items():
        kv.append(("f_" + k, v))
    for alias, src in (("f_subj", "f_subject"), ("f_stat", "f_status"),
                       ("f_ver", "f_version")):
        if src in dict(kv):
            kv.append((alias, dict(kv)[src]))
    rows = dev.get("rows") or {}
    for k, v in rows.items():
        kv.append(("y_" + k, v["y"]))
        if "h" in v:
            kv.append(("h_" + k, v["h"]))
        if "w" in v:
            kv.append(("w_" + k, v["w"]))
    if "bar" in rows:
        kv.append(("bar_w", rows["bar"].get("w")))
        kv.append(("bar_h", rows["bar"].get("h")))
    body = ",\n".join("  %s = %s" % (k, v) for k, v in kv)
    return "%s\nlocal P = {\n%s,\n}\n%s" % (P_BEGIN, body, P_END)


CORE_DIR = HERE / "shared" / "lua"


def expand_includes(src):
    """把 -- @@INCLUDE:<name>@@ 整块换成 shared/lua/<name>.lua。

    课程表数据层是全表盘共用的（读共享文件 / 解析 usr.db / 算状态），
    放进 core 后，加一款新表盘只要写 UI，不会各抄一份解析逻辑。
    """
    def sub(m):
        f = CORE_DIR / (m.group(1) + ".lua")
        if not f.exists():
            raise SystemExit("缺少 core 片段: %s" % f)
        return f.read_text(encoding="utf-8")
    return re.sub(r"^-- @@INCLUDE:([A-Za-z0-9_]+)@@\s*$", sub, src, flags=re.M)


def inject_lua(src, dev, ver):
    if P_BEGIN not in src or P_END not in src:
        raise SystemExit("源码缺少 @@PROFILE@@ 标记段，无法注入机型参数")
    head, rest = src.split(P_BEGIN, 1)
    _old, tail = rest.split(P_END, 1)
    out = expand_includes(head) + profile_lua(dev) + expand_includes(tail)
    out, n = re.subn(r'local VERSION = "v[0-9.]+"', 'local VERSION = "%s"' % ver, out, count=1)
    if n != 1:
        raise SystemExit("源码里找不到 VERSION 常量，无法注入版本号")
    return out


def minify(src):
    """去注释 + 去缩进。基底 lua 块只有 13616B，完整源码通常放不下。"""
    out = [ln.strip() for ln in src.split("\n")
           if ln.strip() and not ln.strip().startswith("--")]
    return "\n".join(out) + "\n"


def lua_syntax_ok(payload):
    f = Path(tempfile.mktemp(suffix=".lua"))
    f.write_bytes(payload)
    r = subprocess.run(["luac", "-p", str(f)], capture_output=True)
    f.unlink()
    return r.returncode, r.stderr.decode("utf-8", "ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--face", required=True, help="faces/<name>")
    ap.add_argument("--device", required=True, help="devices/<name>.json")
    ap.add_argument("--no-bump", action="store_true", help="不改版本号（同版本出多机型时用）")
    ap.add_argument("--no-preview", action="store_true", help="保留基底预览图，只注入 Lua")
    ap.add_argument("--preview-only", action="store_true", help="只生成缩略图，不出包")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    fdir = HERE / "faces" / args.face
    fmeta = load_json(fdir / "face.json")
    dev = load_json(HERE / "devices" / (args.device + ".json"))
    vf = fdir / fmeta["version"]

    if args.device not in fmeta.get("devices", []):
        raise SystemExit(f"表盘 {args.face} 未声明支持机型 {args.device}（face.json devices）")

    old_ver, ver = bump_version(vf, do_bump=not (args.no_bump or args.preview_only))
    src = (fdir / fmeta["lua"]).read_text(encoding="utf-8")
    lua = inject_lua(src, dev, ver)

    w, h = dev["screen"]
    png = HERE / "dist" / ("%s-%s-%s.png" % (args.face, args.device, ver))
    png.parent.mkdir(exist_ok=True)
    preview_mod.render(dev, ver, png, fmeta.get("preview_sample"),
                       fmeta.get("preview_style"), fmeta.get("rows"))

    print(f"[{args.face}] {dev['label']}  {w}x{h}  版本 {old_ver} -> {ver}")
    print(f"  profile 注入: {dev['name']}  safe={dev['safe_area']['top']}..{dev['safe_area']['bottom']}"
          f"  字号={list(dev['fonts'].values())}")
    print(f"  缩略图 -> {png.relative_to(HERE)}")

    if args.preview_only:
        return 0

    base_name = dev.get("base")
    if not base_name:
        raise SystemExit(f"机型 {args.device} 未提供官方基底 .face：{dev.get('base_note', '')}")

    img = FaceImage(fdir / "base" / base_name)
    pw, ph, plen = img.preview_meta()
    hdr = img.preview_header()
    assert hdr[:4] == bytes.fromhex("e021a55a"), "基底预览 RLE magic 异常"
    assert hdr[4] & 0x0f == 3, f"基底预览 blksize 不是 3: {hdr.hex()}"
    if (pw, ph) != (w, h):
        raise SystemExit(f"基底预览 {pw}x{ph} 与机型屏幕 {w}x{h} 不一致，选错了基底？")

    img.set_identity(fmeta["id"], fmeta["name_en"])

    data = lua.encode("utf-8")
    for cand in (data, minify(lua).encode("utf-8")):
        cap = img.entries()["lua/main.lua"][1]
        if len(cand) <= cap:
            data = cand
            break
    rc, err = lua_syntax_ok(data)
    assert rc == 0, f"Lua 语法错误: {err}"
    n, cap = img.inject_resource("lua/main.lua", data)
    print(f"  lua {n}B / 块容量 {cap}B  (压缩={'是' if n < len(lua.encode('utf-8')) else '否'})  luac -p={rc}")

    if not args.no_preview:
        from PIL import Image
        px = bytearray()
        for (r_, g_, b_) in Image.open(png).convert("RGB").getdata():
            px += bytes((r_, g_, b_))
        body = rle.encode(px, blksize=3)
        decoded = rle.decode(body, 3)
        assert decoded == bytes(px), "RLE 解码自校验失败"
        img.inject_preview(hdr + body)
        print(f"  预览 RGB888 blksize=3  body={len(body)}B  解码还原 {len(decoded)}B ✓")

    out = Path(args.out) if args.out else HERE / "dist" / ("%s-%s-%s.face" % (args.face, args.device, ver))
    size = img.save(out)
    info = img.info()
    print(f"  -> {out.relative_to(HERE)}  {size}B  md5={hashlib.md5(out.read_bytes()).hexdigest()[:8]}")
    print(f"     id={info['id']}  name={info['name']}  slotCount={info['slot_count']}  bytes[5]={info['patch_flag']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
