# -*- coding: utf-8 -*-
"""从第三方 .face 包里提取 192×490 真实预览图（立绘），落到 docs/screenshots/previews/。

为什么需要这个工具：
  官方包内**没有**叫 preview.png 的封面资源，预览立绘就是包里某一张尺寸恰为
  192×490 的 RLE 资源。要区分「表盘立绘」和「图标/指针/数字切片」，唯一可靠的
  判据是**解码后像素数**：192*490*3 = 282,240 字节。

条目结构（逆向，与 tools/face_inventory.find_lua_blocks 同口径）：
  header = type(1) + size(3, LE) + nlen(1) + 16B 保留
  name   = name_start .. name_start+nlen
  payload= name_end .. name_end+size

用法：
  python3 tools/extract_previews.py                 # 全量
  python3 tools/extract_previews.py --limit 3       # 先试 3 个
  python3 tools/extract_previews.py --only Band9-Monika-v1.2.0.face
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared import rle as rle_mod  # noqa: E402

OUT = ROOT / "docs" / "screenshots" / "previews"
MANIFEST = ROOT / "data" / "previews.json"

BAND9 = (192, 490)
PRO = (336, 480)
TARGETS = {BAND9, PRO}

NAME_RE = re.compile(rb"[A-Za-z0-9_./\-]{1,80}\.(rle|png|jpg|jpeg|bin|img)", re.I)


def enum_entries(d: bytes) -> list[dict]:
    """枚举包内所有资源条目（不依赖文件类型白名单，靠头部自校验）。"""
    out, seen = [], set()
    for m in NAME_RE.finditer(d):
        ns = m.start()
        hs = ns - 21
        if hs < 0:
            continue
        size = int.from_bytes(d[hs + 1:hs + 4], "little")
        nlen = d[hs + 4]
        name = d[ns:ns + nlen]
        off = ns + nlen
        if not name or name != m.group(0):
            continue
        if off + size > len(d) or size < 32:
            continue
        if (name, off) in seen:
            continue
        seen.add((name, off))
        out.append({
            "name": name.decode("utf-8", "replace"),
            "ext": m.group(1).decode().lower(),
            "header": hs,
            "type": d[hs],
            "size": size,
            "off": off,
        })
    return out


def parse_rle_header(raw: bytes):
    """返回 (body, blksize)；非标准头返回 (raw, 3)。"""
    if len(raw) >= 8 and raw[:4] == b"\xe0\x21\xa5\x5a":
        return raw[8:], raw[4] or 3
    return raw, 3


def decode_to_pixels(raw: bytes):
    """解出 RGB 像素；失败返回 None。"""
    body, blksize = parse_rle_header(raw)
    try:
        px = rle_mod.decode(body, blksize=blksize)
    except Exception:
        return None
    if not px:
        return None
    return bytes(px), blksize


def save_png(px: bytes, blksize: int, size: tuple[int, int], dst: Path) -> bool:
    from PIL import Image
    w, h = size
    if len(px) < w * h * blksize:
        return False
    mode = "RGB" if blksize >= 3 else "L"
    stride = blksize
    buf = bytearray()
    for y in range(h):
        row = px[y * w * stride:(y + 1) * w * stride]
        for x in range(w):
            buf += row[x * stride:x * stride + (3 if blksize >= 3 else 1)]
    img = Image.frombytes(mode, (w, h), bytes(buf))
    img.save(dst)
    return True


def extract(p: Path) -> dict:
    d = p.read_bytes()
    es = enum_entries(d)
    rec = {"file": p.name, "size": len(d), "entries": len(es),
           "hit": None, "decoded": 0, "candidates": []}

    rles = [e for e in es if e["ext"] == "rle"]
    for e in rles:
        raw = d[e["off"]:e["off"] + e["size"]]
        got = decode_to_pixels(raw)
        rec["decoded"] += 1
        if not got:
            continue
        px, blksize = got
        npx = len(px) // blksize
        for size in TARGETS:
            if npx == size[0] * size[1]:
                rec["candidates"].append({"name": e["name"], "size": list(size)})
                rec["hit"] = {"name": e["name"], "size": list(size), "blksize": blksize}
                break
        if rec["hit"]:
            break

    # 没有 RLE 立绘的包，退一步找 PNG/JPG 里尺寸匹配的（少数包是位图封面）
    if not rec["hit"]:
        for e in [x for x in es if x["ext"] in ("png", "jpg", "jpeg")]:
            raw = d[e["off"]:e["off"] + e["size"]]
            try:
                from io import BytesIO
                from PIL import Image
                im = Image.open(BytesIO(raw))
                if im.size in TARGETS:
                    rec["hit"] = {"name": e["name"], "size": list(im.size), "blksize": None}
                    im.convert("RGB").save(OUT / (p.stem + ".png"))
                    break
            except Exception:
                continue
    elif rec["hit"]["blksize"] is not None:
        name, size = rec["hit"]["name"], tuple(rec["hit"]["size"])
        e = next(x for x in es if x["name"] == name)
        raw = d[e["off"]:e["off"] + e["size"]]
        got = decode_to_pixels(raw)
        if got:
            save_png(got[0], got[1], size, OUT / (p.stem + ".png"))
            rec["png"] = str((OUT / (p.stem + ".png")).relative_to(ROOT))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "dist" / "Band9"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(Path(args.dist).glob("*.face"))
    if args.only:
        files = [f for f in files if f.name == args.only]
    if args.limit:
        files = files[:args.limit]

    rows = []
    for p in files:
        try:
            rec = extract(p)
        except Exception as e:                                    # noqa: BLE001
            rec = {"file": p.name, "error": str(e)[:120]}
        rows.append(rec)
        flag = "✅" if rec.get("hit") else "❌"
        print("%s %-42s 条目=%-3s rle=%-3s %s" % (
            flag, rec["file"], rec.get("entries"), rec.get("decoded"),
            ("→ %s %s" % (rec["hit"]["name"], rec["hit"]["size"])) if rec.get("hit") else "无 192×490 立绘"))

    hit = [r for r in rows if r.get("hit")]
    print("\n合计 %d 个包，出图 %d 个，缺图 %d 个" % (len(rows), len(hit), len(rows) - len(hit)))
    if len(rows) > 1:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("清单 →", MANIFEST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
