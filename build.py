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

    # 行的短别名：老表盘源码里写的是 y_subj / y_stat / y_ver / y_i1 / y_i2 / h_small，
    # 而 devices 里的规范键是 subject / status / version / info1 / info2。
    # 只招字体别名不招行别名，会让这些引用全变 nil（label 的 y_ofs/h 丢失 → 多行挤在顶部）。
    alias_rows = {
        "y_subj": ("subject", "y"), "h_subj": ("subject", "h"),
        "y_stat": ("status", "y"),  "h_stat": ("status", "h"),
        "y_ver":  ("version", "y"),
        "y_i1":   ("info1", "y"),   "y_i2":   ("info2", "y"),
        "h_small": ("version", "h"),
    }
    seen = dict(kv)
    for alias, (src_key, kind) in alias_rows.items():
        v = rows.get(src_key, {}).get(kind)
        if v is not None and alias not in seen:
            kv.append((alias, v))
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
    out, n = re.subn(r'local VERSION = "[^"]*"', 'local VERSION = "%s"' % ver, out, count=1)
    if n != 1:
        raise SystemExit("源码里找不到 VERSION 常量，无法注入版本号")
    return out


def check_profile_refs(src):
    """构建期硬校验：源码里引用到的 P.<key> 必须都出现在注入的 profile 表里。

    踩过的坑：只给字体加短别名、没给行加，导致 P.y_subj/P.h_subj 全为 nil，
    label 的 y_ofs 与 h 丢失 → 多行文字叠在屏幕顶部，真机看起来「表盘坏了」。
    luac -p 只查语法，查不出这种 nil，所以必须在这里拦。
    """
    m = re.search(r"local P = \{(.*?)\n\}", src, re.S)
    if not m:
        raise SystemExit("profile 段缺失")
    defined = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", m.group(1)))
    refs = set(re.findall(r"\bP\.([A-Za-z_][A-Za-z0-9_]*)", src))
    missing = sorted(refs - defined)
    if missing:
        raise SystemExit("profile 缺少键（运行时会 nil）: %s" % ", ".join(missing))
    return len(refs)


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
    ap.add_argument("--allow-preview-mismatch", action="store_true",
                    help="基底预览尺寸与机型屏幕不一致时继续（跨机型试造用，预览块保持基底原样）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--base", default=None,
                    help="覆盖基底文件名（faces/<face>/base/ 下）：band9.face=13616B，band9-large.face=17287B")
    args = ap.parse_args()

    fdir = HERE / "faces" / args.face
    fmeta = load_json(fdir / "face.json")
    dev = load_json(HERE / "devices" / (args.device + ".json"))
    vf = fdir / fmeta["version"]

    if args.device not in fmeta.get("devices", []):
        raise SystemExit(f"表盘 {args.face} 未声明支持机型 {args.device}（face.json devices）")

    old_ver, ver = bump_version(vf, do_bump=not (args.no_bump or args.preview_only))
    # 底部署名：把表盘自己的名字并进版本行（EV Class v1.0.11 / EV Quartz v1.0.7）。
    # 多条表盘装在同一只表上时，长按切换页与表盘底部都靠这行区分，避免「哪个是哪个」。
    # 不新增 label 行，只替换 VERSION 字符串内容 —— class 的 lua 块只剩三百多字节余量。
    short = fmeta.get("short_name") or fmeta.get("name_en") or args.face
    ver_label = "%s %s" % (short, ver)
    src = (fdir / fmeta["lua"]).read_text(encoding="utf-8")
    lua = inject_lua(src, dev, ver_label)
    nref = check_profile_refs(lua)
    print(f"  profile 引用自检通过：{nref} 个 P.<key> 全部有定义")

    w, h = dev["screen"]
    png = HERE / "dist" / ("%s-%s-%s.png" % (args.face, args.device, ver))
    png.parent.mkdir(exist_ok=True)
    preview_mod.render(dev, ver_label, png, fmeta.get("preview_sample"),
                       fmeta.get("preview_style"), fmeta.get("rows"))

    print(f"[{args.face}] {dev['label']}  {w}x{h}  版本 {old_ver} -> {ver}")
    print(f"  profile 注入: {dev['name']}  safe={dev['safe_area']['top']}..{dev['safe_area']['bottom']}"
          f"  字号={list(dev['fonts'].values())}")
    print(f"  缩略图 -> {png.name}")

    if args.preview_only:
        return 0

    base_name = args.base or dev.get("base")
    if not base_name:
        raise SystemExit(f"机型 {args.device} 未提供官方基底 .face：{dev.get('base_note', '')}")

    img = FaceImage(fdir / "base" / base_name)
    pw, ph, plen = img.preview_meta()
    hdr = img.preview_header()
    assert hdr[:4] == bytes.fromhex("e021a55a"), "基底预览 RLE magic 异常"
    assert hdr[4] & 0x0f == 3, f"基底预览 blksize 不是 3: {hdr.hex()}"
    if (pw, ph) != (w, h) and not args.allow_preview_mismatch:
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
        raw = rle.encode(px, blksize=3)
        decoded = rle.decode(raw, 3)
        assert decoded == bytes(px), "RLE 解码自校验失败"
        # 预览块必须「稠密且恰好」：解出像素数 == w*h，且流吃满槽位。
        # 旧 pad_to() 往里塞重复指令，每 4B 多解出 127 个假像素（实测 3.66~14.8 倍），
        # 设备解码溢出后退化成占位图形 —— 长按切换页「一个大圈」的根因。
        cap_body = plen - len(hdr)          # plen 是预览区总容量（含 8B 头）
        body = rle.encode_exact(px, cap_body, 3)
        npix, used = rle.decode_px_count(body, 3)
        assert len(body) == cap_body and used == cap_body, (len(body), used, cap_body)
        assert npix == w * h, ("预览像素数必须正好等于屏幕像素", npix, w * h)
        assert rle.decode(body, 3) == bytes(px), "稠密封装后解码与原图不一致"
        img.inject_preview(hdr + body)
        print(f"  预览 RGB888 blksize=3  原流={len(raw)}B → 稠密封装={len(body)}B/上限{cap_body}B  "
              f"解码 {npix}px={w}x{h} ✓ 零剩余字节")

    out = Path(args.out) if args.out else HERE / "dist" / ("%s-%s-%s.face" % (args.face, args.device, ver))
    size = img.save(out)
    info = img.info()
    print(f"  -> {out.name}  {size}B  md5={hashlib.md5(out.read_bytes()).hexdigest()[:8]}")
    print(f"     id={info['id']}  name={info['name']}  slotCount={info['slot_count']}  bytes[5]={info['patch_flag']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
