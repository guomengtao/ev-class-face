#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建小米手环 9（跑道屏 192x490）EV 课程提醒表盘 .face。

与旧版 build_face_v2.py 的关键差异：

* 基底用 Band 9 原生 .face（lua_calculator_band9.face），不是 8 Pro 方屏包。
* 预览编码必须与官方一致：
    官方 RLE 头 = e0 21 a5 5a | 03 e8 44 00
                   magic        blksize=3 (RGB888), len
    其后**直接**是 RLE 流（ctrl + 像素），没有 LVGL image header。
  旧版用 LVGLImage.RLEImage.to_rle() 生成的是
    blksize=4 (ARGB8888) + 12 字节 LVGL v9 image header (0x19 10 00 00 ...)
  设备按 blksize=3 解，结果只剩底色 —— 真机上表现为「蓝色大空圈」。
  本脚本自包含实现 RGB888 / blksize=3 的 LVGL RLE 编码，并原样保留官方 8 字节头。
* 等长替换：文件总长、条目表、所有偏移、头部字段一律不动。

用法：
    python3 build_face_band9.py                       # 用默认素材构建主推包
    python3 build_face_band9.py --out /tmp/x.face    # 指定输出
"""
import argparse
import hashlib
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_BASE = HERE / "表盘成品-LuaCalculator-MiBand9-官方基底.face"
DEFAULT_LUA = HERE / "class_face_band9.lua"
DEFAULT_OUT = HERE / "EV课程提醒表盘-Band9-共享文件版.face"
DEFAULT_PNG = HERE / "预览图-EV课程提醒-192x490.png"

# v4 换新 ID：设备可能按表盘 ID 缓存切换卡片缩略图，同 ID 覆盖安装不刷新 →
# 这是「本来好的又坏成大圈 / 重复出现」的假设 H1，换 ID 用来证伪。
FACE_ID = b"882610317"
FACE_NAME = b"EV Class Face"
ENTRY_OFF, ENTRY_END, ENTRY_STRIDE = 0x110, 0x200, 16


def parse_entries(d):
    out = {}
    for off in range(ENTRY_OFF, ENTRY_END, ENTRY_STRIDE):
        _a, _b, bo, bs = struct.unpack_from("<IIII", d, off)
        if bo == 0 or bo >= len(d):
            continue
        nl = d[bo + 3]
        cs = int.from_bytes(d[bo:bo + 3], "little")
        name = d[bo + 20:bo + 20 + nl].decode("ascii")
        out[name] = (bo + 20 + nl, cs, bs)
    return out


def rle_encode(px, blksize=3, maxrun=127):
    """LVGL RLE：ctrl<0x80 = 重复 n 次 + 1 像素；ctrl|0x80 = 后跟 n 个非重复像素。"""
    n = len(px) // blksize
    blocks = [px[i * blksize:(i + 1) * blksize] for i in range(n)]
    out = bytearray()
    i = 0
    while i < n:
        j = i + 1
        while j < n and blocks[j] == blocks[i] and j - i < maxrun:
            j += 1
        run = j - i
        if run >= 2:
            out.append(run)
            out += blocks[i]
            i = j
        else:
            buf = []
            k = i
            while k < n and len(buf) < maxrun:
                m = k + 1
                while m < n and blocks[m] == blocks[k] and m - k < 2:
                    m += 1
                if m - k >= 2:
                    break
                buf.append(blocks[k])
                k += 1
            if not buf:
                buf.append(blocks[k])
                k += 1
            out.append(0x80 | len(buf))
            for b in buf:
                out += b
            i = k
    return bytes(out)


def rle_decode(body, blksize=3):
    px = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        i += 1
        if c == 0:
            break
        if c & 0x80:
            cnt = c & 0x7f
            if cnt == 0:
                break
            blk = body[i:i + cnt * blksize]
            i += cnt * blksize
            px += blk
        else:
            blk = body[i:i + blksize]
            i += blksize
            if len(blk) < blksize:
                break
            px += blk * c
    return bytes(px)


def build_preview_png(w, h, path):
    """v1.0.0 预览图：跑道底 + 居中卡片。

    旧版两个硬伤（就是「长按切换页又成大圈」的根因）：
      1) 字体路径 /System/Library/Fonts/PingFang.ttc 在本机不存在 → 静默 fallback 到
         load_default()（不支持中文）→ 缩略图里全是豆腐块 ▯▯▯。
      2) 内容铺满 y=60..450 整屏 → 设备按跑道形（两端半径 96 半圆）遮罩裁切后，
         整块纯深蓝被裁成一坨巨大的圆/胶囊，即用户说的「超大的圆圈」。
    现在：垂直渐变底（两端收拢）+ 中间一块带描边的圆角卡片承载全部信息，
    视觉主体是卡片而非整屏色块，任何裁切下都能读出层次。
    """
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (w, h), (10, 28, 48))
    dr = ImageDraw.Draw(im)

    top, mid, bot = (8, 20, 36), (17, 44, 70), (8, 20, 36)
    for y in range(h):
        t = y / (h - 1)
        if t < 0.5:
            k, a, b = t / 0.5, top, mid
        else:
            k, a, b = (t - 0.5) / 0.5, mid, bot
        c = tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))
        dr.line([(0, y), (w, y)], fill=c)

    CN = "/System/Library/Fonts/Hiragino Sans GB.ttc"
    LAT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

    def font(p, sz):
        for cand in (p, CN, "/System/Library/Fonts/STHeiti Medium.ttc"):
            try:
                return ImageFont.truetype(cand, sz)
            except Exception:
                continue
        return ImageFont.load_default()

    big = font(LAT, 46)
    mid_f = font(CN, 27)
    sml = font(CN, 20)
    tip = font(CN, 17)

    cx0, cy0, cx1, cy1 = 12, 118, w - 12, 378
    dr.rounded_rectangle([cx0, cy0, cx1, cy1], radius=20,
                         fill=(16, 42, 68), outline=(46, 88, 124), width=1)
    cx = w // 2
    for y, txt, f, col in [
        (150, "10:14", big, (255, 255, 255)),
        (186, "上课中", sml, (255, 212, 121)),
        (217, "语文", mid_f, (255, 255, 255)),
        (252, "已上10分", sml, (255, 212, 121)),
        (277, "下课35分", sml, (255, 212, 121)),
        (305, "下节数学", sml, (127, 212, 255)),
    ]:
        dr.text((cx, y), txt, font=f, fill=col, anchor="mm")

    bar_l, bar_r = cx0 + 20, cx1 - 20
    dr.rounded_rectangle([bar_l, 330, bar_r, 336], radius=3, fill=(30, 58, 82))
    dr.rounded_rectangle([bar_l, 330, bar_l + int((bar_r - bar_l) * 0.35), 336],
                         radius=3, fill=(127, 212, 255))
    dr.text((cx, 410), "v1.0.0", font=tip, fill=(122, 158, 190))
    im.save(path)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_BASE))
    ap.add_argument("--lua", default=str(DEFAULT_LUA))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--png", default=str(DEFAULT_PNG))
    ap.add_argument("--face-id", default=FACE_ID.decode())
    ap.add_argument("--name", default=FACE_NAME.decode())
    ap.add_argument("--no-preview", action="store_true", help="保留官方预览图，只注入 Lua")
    args = ap.parse_args()

    src = Path(args.src)
    d = bytearray(src.read_bytes())
    assert d[:4] == bytes.fromhex("5aa53412"), "不是 .face 容器"
    tail = struct.unpack_from("<I", d, 0x20)[0]
    w, h = struct.unpack_from("<HH", d, tail + 4)
    plen = struct.unpack_from("<I", d, tail + 8)[0]
    print(f"基底 {src.name}: {len(d)}B  tail={tail:#x}  preview={w}x{h} len={plen}  bytes[5]={d[5]}")

    # 1) ID / 名称（只改这两处，其余头部与官方基底逐字节一致，保留 slotCount 等结构）
    idb = args.face_id.encode()[:10]
    nb = args.name.encode()[:24]
    d[5] = 0
    d[0x28:0x32] = idb.ljust(10, b"\0")
    d[0x68:0x80] = nb.ljust(24, b"\0")

    # 2) 等长注入 lua/main.lua
    lua = Path(args.lua).read_bytes()
    entries = parse_entries(d)
    assert "lua/main.lua" in entries, f"基底缺少 lua/main.lua: {list(entries)}"
    coff, cs, bs = entries["lua/main.lua"]
    assert len(lua) <= cs, f"Lua {len(lua)}B 超过块容量 {cs}B"
    pad = cs - len(lua)
    payload = lua if pad == 0 else lua + b"--" + b" " * max(0, pad - 3) + b"\n"
    d[coff:coff + cs] = payload
    f = Path(tempfile.mktemp(suffix=".lua"))
    f.write_bytes(payload)
    r = subprocess.run(["luac", "-p", str(f)], capture_output=True)
    f.unlink()
    print(f"注入 lua/main.lua: {len(lua)}B 源码 + {pad}B 补齐 = {cs}B  luac -p = {r.returncode}")
    assert r.returncode == 0, r.stderr.decode()

    # 3) 预览：官方 blksize=3 RGB888 纯 RLE，8 字节头原样保留
    if not args.no_preview:
        im = build_preview_png(w, h, args.png)
        px = bytearray()
        for (r_, g_, b_) in im.convert("RGB").getdata():
            px += bytes((r_, g_, b_))
        body = rle_encode(px, blksize=3)
        official_header = bytes(d[tail + 12:tail + 20])  # e0 21 a5 5a 03 e8 44 00
        assert official_header[:4] == bytes.fromhex("e021a55a"), \
            f"RLE magic 异常 {official_header[:4].hex()}"
        assert official_header[4] & 0x0f == 3, f"blksize 不是 3: {official_header.hex()}"
        payload = official_header + body
        assert len(payload) <= plen, f"预览 {len(payload)}B 超过 {plen}B"
        decoded = rle_decode(body, 3)
        assert decoded == bytes(px), f"RLE 解码不一致 {len(decoded)} vs {len(px)}"
        d[tail + 12:tail + 12 + plen] = payload.ljust(plen, b"\0")
        print(f"预览等长替换: {w}x{h} RGB888 blksize=3  body={len(body)}B  解码还原 {len(decoded)}B ✓")
        print(f"  RLE 头原样: {official_header.hex(' ')}")

    out = Path(args.out)
    out.write_bytes(bytes(d))
    md5 = hashlib.md5(bytes(d)).hexdigest()
    print(f"\nOK -> {out}  {len(d)}B  md5={md5}")
    print(f"   id={bytes(d[0x28:0x32])!r} name={bytes(d[0x68:0x7c]).rstrip(bytes([0]))!r}"
          f"  总长不变={len(d) == len(src.read_bytes())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
