# -*- coding: utf-8 -*-
"""EV Aurora 组包器（Daymatter 壳 · 图片背景 + 位图数字）

为什么需要它：`build.py` 只支持纯 lua 壳（class/clock/analog），Aurora 用的
Daymatter 壳是「1 个 lua 槽 + 10 个数字槽 + 1 个整屏背景槽 + 1 个冒号槽」，
必须逐槽注入。此前 v1.0.0/v1.0.1 是手搓出来的包，预览块结构错误
（check_preview 实测解码 0px、比值 0.00）→ 切换页退化成大圈。

用法：
    python3 tools/build_aurora.py                 # 出包 + 自检
    python3 tools/build_aurora.py --no-bump       # 复用当前版本号

产物：dist/Band9/Band9-Aurora-v<ver>.face
"""
import argparse
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from shared.face_container import FaceImage          # noqa: E402
from shared import rle                               # noqa: E402

BASE = HERE / "dist" / "Band9" / "Band9-Daymatter-v1.0.0.face"
SRC = HERE / "faces" / "aurora"
ASSETS = SRC / "assets"
VER_FILE = SRC / ".version"
SLOT = "_lua/daymatter/"

DIN = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
SEG = SRC / "assets" / "DSEG7Classic-Bold.ttf"    # 七段数码管体（SIL OFL，可商用）
C_TIME = (240, 163, 43)                          # 时间琥珀色，与课程表主色一致
TIME_FONT = str(SEG) if SEG.exists() else DIN
PINGFANG = "/System/Library/Fonts/PingFang.ttc"

# 表盘版式常量（与 main.lua 必须一致）
W, H = 192, 490
DIG_Y = 68          # 数字顶边
CELL_W = 34         # 数字格宽（32x66 面积少 22%，才装得进 276~357B 小槽）
DX = [7, 43, 79, 115, 151]
DIG_H = 56          # 数字字高
FACE_ID = "9798252661"
FACE_NAME = "EV-Aurora"

C_MAIN = (238, 244, 255)
C_STAT = (127, 216, 188)
C_DIM = (155, 166, 196)
C_LO = (90, 100, 136)


# ---------------------------------------------------------------- PNG 填充
def pad_png(data: bytes, cap: int) -> bytes:
    """把 PNG 用**合法 tEXt 块**补到恰好 cap 字节，不用裸 0 填充。

    PNG 解析器遇到 IEND 就停，尾部垃圾理论无害；但块长度是固件读的，
    塞一段合法 ancillary 块比塞 0x00 更不容易踩到边界。
    """
    if len(data) > cap:
        raise ValueError(f"PNG {len(data)}B 超过槽位 {cap}B")
    need = cap - len(data)
    if need < 13:                     # 塞不下一个空 chunk，直接零填充
        return data + b"\x00" * need
    body_len = need - 12              # chunk 开销 = 4(len)+4(type)+4(crc)
    payload = b"pad\x00" + b"0" * (body_len - 4)
    chunk = (struct.pack(">I", len(payload)) + b"tEXt" + payload
             + struct.pack(">I", zlib.crc32(b"tEXt" + payload) & 0xFFFFFFFF))
    out = data + chunk
    assert len(out) == cap, (len(out), cap)
    return out


def magick(*args):
    subprocess.run(["magick", *args], check=True)


# ---------------------------------------------------------------- 数字/冒号
def _slim(path: Path):
    """只保留 IHDR/PLTE/tRNS/IDAT/IEND：IM 会额外写 date:create 等元数据，每张多几百字节。"""
    import struct
    d = path.read_bytes()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        return
    keep = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}
    out = bytearray(d[:8]); i = 8
    while i < len(d):
        n = struct.unpack(">I", d[i:i + 4])[0]; t = d[i + 4:i + 8]
        if t in keep:
            out += d[i:i + 12 + n]
        i += 12 + n
    path.write_bytes(bytes(out))


COMPRESS = ["-strip", "-define", "png:compression-level=9",
            "-define", "png:compression-filter=0",
            "-colors", "2", "-define", "png:color-type=3"]


def render_glyphs(tmp: Path):
    """0-9：七段数码管体 DSEG7，琥珀实色、硬边不抗锯齿；冒号画两个方点。"""
    files = {}
    for ch, name in [(str(d), f"{d}.png") for d in range(10)] + [(":", "mao.png")]:
        out = tmp / f"slot_{name}"
        if ch == ":":
            magick("-size", f"{CELL_W}x{DIG_H}", "xc:none", "+antialias",
                   "-fill", "#F0A32B",
                   "-draw", "rectangle 14,19 20,25",
                   "-draw", "rectangle 14,34 20,40",
                   *COMPRESS, f"PNG8:{out}")
        else:
            raw = tmp / f"raw_{name}"
            magick("-background", "none", "-fill", "#F0A32B", "+antialias",
                   "-font", TIME_FONT, "-pointsize", "180", f"label:{ch}",
                   "-trim", "+repage", "-filter", "point", "-resize", f"{CELL_W}x{DIG_H}",
                   "-background", "none", "-gravity", "center",
                   "-extent", f"{CELL_W}x{DIG_H}", *COMPRESS, f"PNG8:{out}")
        _slim(out)
        files[name] = out
    return files


# ---------------------------------------------------------------- 预览图
def compose_preview(tmp: Path, glyphs, bg: Path, out: Path, ver="1.0.0"):
    """按 lua 版式合成 192×490 缩略图（与屏幕所见一致，不是另画一版）。"""
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.open(bg).convert("RGB")
    if canvas.size != (W, H):
        canvas = canvas.resize((W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    t = __import__("datetime").datetime.now()

    # 时间：位图数字，逐格居中
    hh, mm = f"{t.hour:02d}", f"{t.minute:02d}"
    seq = [hh[0], hh[1], ":", mm[0], mm[1]]
    for i, ch in enumerate(seq):
        name = "mao.png" if ch == ":" else f"{ch}.png"
        g = Image.open(glyphs[name]).convert("RGBA")
        cell_x = DX[i]
        gx = cell_x + (CELL_W - g.width) // 2
        gy = DIG_Y + (DIG_H - g.height) // 2
        canvas.paste(g, (gx, gy), g)

    def pick(size):
        for cand in (PINGFANG, "/System/Library/Fonts/Hiragino Sans GB.ttc",
                     "/System/Library/Fonts/STHeiti Medium.ttc",
                     "/System/Library/Fonts/Supplemental/Songti.ttc",
                     "/Library/Fonts/Arial Unicode.ttf"):
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
        raise SystemExit("找不到可用中文字体")

    f24, f44 = pick(24), pick(44)

    def centered(text, y, font, color):
        w = draw.textlength(text, font=font)
        draw.text(((W - w) / 2, y), text, font=font, fill=color)

    centered("上课中", 184, f24, C_STAT)
    centered("数学", 250, f44, C_MAIN)
    draw.text((14, 358), "上 语文 8:00", font=f24, fill=C_DIM)
    draw.text((14, 400), "下 英语 13:30", font=f24, fill=C_DIM)
    draw.text((14, 438), f"80%  v{ver}", font=f24, fill=C_LO)

    canvas.save(out)
    return out


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-bump", action="store_true")
    ap.add_argument("--skip-install", action="store_true")
    args = ap.parse_args()

    ver = VER_FILE.read_text().strip() if VER_FILE.exists() else "1.0.0"
    if not args.no_bump:
        a, b, c = (int(x) for x in ver.split("."))
        ver = f"{a}.{b}.{c + 1}"
    VER_FILE.write_text(ver + "\n")

    lua_src = (SRC / "main.lua").read_text(encoding="utf-8")
    bg = ASSETS / "bg9.png"

    im = FaceImage(BASE)
    pre_w, pre_h, plen = im.preview_meta()
    print(f"基底 {BASE.name}  {im.info()['size']}B  预览槽 {pre_w}x{pre_h}/{plen}B")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        glyphs = render_glyphs(tmp)

        print("  字形体积 " + " ".join(f"{n[:-4]}:{p.stat().st_size}B" for n,p in glyphs.items()))
        entries = im.entries()
        png_slots = [(k, v[1]) for k, v in entries.items() if k.startswith(SLOT) and k.endswith(".png")]
        # Daymatter 自带 before_9 / later_9 两块闲置贴图，容量 1.1KB，挪来放最大的字形
        free = [(k, c) for k, c in png_slots if k.split("/")[-1] in
                {f"{d}.png" for d in range(10)} | {"before_9.png", "later_9.png", "mao.png"}]

        need = sorted(((path.stat().st_size, name, path) for name, path in glyphs.items()),
                      reverse=True)
        pool = sorted(free, key=lambda x: x[1])   # best-fit：小图进小槽，大槽留给大图
        assign = {}
        # 字形 PNG 由渲染步就压成 PaletteAlpha（实测 146~290B），
        # 千万不能再拿 magick 重编码一次——重编码会退化成 Bilevel/8bit，体积反而涨到 360B+
        for size, name, _p in sorted(((pg.stat().st_size, n, pg) for n, pg in glyphs.items()),
                                     reverse=True):
            hit = next(((i, sl) for i, (sl, cap) in enumerate(pool) if cap >= size), None)
            if not hit:
                raise SystemExit(f"槽位不足：{name} {size}B（剩余 {[c for _x, c in pool]}B）")
            assign[name] = pool.pop(hit[0])[0]

        short = {n: assign[n].split("/")[-1] for n in assign}
        print("  槽位分配 " + "  ".join(f"{n[:-4]}->{short[n][:-4]}" for n in sorted(assign)))

        # 槽位分配是构建事实，lua 里的 DFILE / 冒号名必须跟着走，不能写死在源码
        dig_map = ", ".join(f'"{short[f"{d}.png"]}"' for d in range(10))
        lua_text = re.sub(r'local DFILE = \{[^}]*\}', f'local DFILE = {{ {dig_map} }}', lua_src, count=1)
        # 冒号单独改名：只动 COLON 常量这一处。
        # ⚠️ v1.0.19 的 bug：这里曾用 lua_text.replace('"mao.png"', ...) 全局替换，
        #    而 DFILE 里恰好有某个数字被分到了 mao 槽（写出来就是 "mao.png"），
        #    结果那个数字被一起改成冒号槽 → 17:15 显示成 17:1:（两个冒号）。
        lua_text = re.sub(r'local COLON = "[^"]*"',
                          f'local COLON = "{short["mao.png"]}"', lua_text, count=1)
        # 坐标与字格必须同源：构建常量变了，lua 里的 DX / 数字顶边跟着走
        lua_text = re.sub(r'local DX = \{[^}]*\}',
                          'local DX = { ' + ', '.join(str(v) for v in DX) + ' }', lua_text, count=1)
        lua_text = lua_text.replace('DX[i], 52)', 'DX[i], %d)' % DIG_Y)

        # --- 硬校验：lua 里认的槽名集合，必须和注入到磁盘上的槽一一对上 ---
        names = re.findall(r'"([^"]+\.png)"', re.search(r'local DFILE = \{([^}]*)\}', lua_text).group(1))
        colon = re.search(r'local COLON = "([^"]+)"', lua_text).group(1)
        assert len(names) == 10 and len(set(names)) == 10, f"DFILE 槽名重复: {names}"
        assert colon not in names, f"冒号槽 {colon} 同时被某个数字占用"
        for d in range(10):
            assert assign[f"{d}.png"] == SLOT + names[d], (d, assign[f"{d}.png"], names[d])
        assert assign["mao.png"] == SLOT + colon, (assign["mao.png"], colon)
        assert dig_map.split(",")[0] in lua_text, "DFILE 改写失败"

        used, cap = im.inject_resource(SLOT + "daymatter.lua", lua_text.encode("utf-8"))
        print(f"  lua        {used:6d} / {cap:6d} B  ({(cap - used) * 100 // cap}% 余量)")

        used, cap = im.inject_resource(SLOT + "bg9.png", bg.read_bytes())
        print(f"  bg9.png    {used:6d} / {cap:6d} B")

        cap_of = dict(free)
        for name, path in glyphs.items():
            slot, cap = assign[name], cap_of[assign[name]]
            payload = path.read_bytes()
            im.inject_resource(slot, pad_png(payload, cap))
            print(f"  {name:10s} {len(payload):6d} / {cap:6d} B -> {short[name][:-4]}")

        # 4. 预览（先合成图，再 encode_exact 精确撑满槽位）
        prev_png = tmp / "preview.png"
        compose_preview(tmp, glyphs, bg, prev_png, ver=ver)
        from PIL import Image
        px = Image.open(prev_png).convert("RGB").tobytes()
        assert len(px) == W * H * 3, len(px)
        body = rle.encode_exact(px, plen - 8)
        assert rle.decode_px_count(body) == (W * H, plen - 8), "预览像素数不匹配"
        im.inject_preview(im.preview_header() + body)
        print(f"  preview    {len(body) + 8:6d} / {plen:6d} B  解码 {W * H}px 零剩余")

        # --- 出包前模拟设备取槽：完全按 lua 认的名字 + DFILE 顺序，模拟 17:15 ---
        # 这是 v1.0.19「17:1:」事故的回归测试：预览图是 python 合成的，看不出 lua 错。
        for hh, mm in ((17, 15), (9, 5), (23, 59), (0, 0)):
            seq = [hh // 10, hh % 10, ":", mm // 10, mm % 10]
            for i, ch in enumerate(seq):
                nm = colon if ch == ":" else names[ch]
                want = glyphs["mao.png" if ch == ":" else f"{ch}.png"].read_bytes()
                coff, _cs, _b = im.entries()[SLOT + nm]
                got = bytes(im.data[coff:coff + len(want)])
                assert got == want, f"{hh:02d}:{mm:02d} 第{i + 1}格应为 {ch}，槽 {nm} 内容不符"
        print("  格式化自检  17:15 / 09:05 / 23:59 / 00:00 五格取槽全部命中")

    im.set_identity(FACE_ID, FACE_NAME)
    out = HERE / "dist" / "Band9" / f"Band9-Aurora-v{ver}.face"
    size = im.save(out)
    print(f"\n出包 {out.name}  {size}B  id={FACE_ID}  ver={ver}")

    print("\n--- 回读自检 ---")
    chk = FaceImage(out)
    w2, h2, p2 = chk.preview_meta()
    vw, vh = chk.preview_header()[:2], chk.preview_header()[2:4]
    body2 = bytes(chk.data[chk.tail + 20:chk.tail + 20 + p2 - 8])
    print(f"  预览 {w2}x{h2}  槽位 {p2}B  解码 {rle.decode_px_count(body2)}px  期望 {W * H}px")
    px = rle.decode_px_count(body2)
    px = px[0] if isinstance(px, tuple) else px
    assert (w2, h2) == (W, H) and px == W * H, (w2, h2, px)
    print("  ✓ 结构合规")
    return 0


if __name__ == "__main__":
    sys.exit(main())
