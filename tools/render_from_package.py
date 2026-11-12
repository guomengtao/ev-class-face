# -*- coding: utf-8 -*-
"""从**成品 .face 包**反推渲染时间（设备等效截图）

背景：compose_preview 是拿构建期源码变量合成预览的，源码变量全对、包内 lua
文本错时（v1.0.19：DFILE 被全局替换污染，数字 5 变冒号），预览块照样画得
漂亮——预览图看不出 bug。本脚本只读成品包：解析包内 daymatter.lua 的
DX / 数字顶边 / DFILE / COLON，按 hh:mm 模拟设备取槽，把槽里的 PNG 贴到 bg9。

用法：
  python3 tools/render_from_package.py dist/Band9/Band9-Aurora-v1.0.20.face \
      --time 17:25 --out /tmp/a.png --scale 2
"""
import argparse
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from shared.face_container import FaceImage       # noqa: E402
from PIL import Image                            # noqa: E402

LUA = "_lua/daymatter/daymatter.lua"
PRE = "_lua/daymatter/"


def slot(im, name):
    coff, cs, _ = im.entries()[name]
    raw = bytes(im.data[coff:coff + cs])
    end = raw.find(b"IEND") + 8
    return raw[:end] if end >= 8 else raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("face")
    ap.add_argument("--time", default="17:25")
    ap.add_argument("--out", default="/tmp/render-from-package.png")
    ap.add_argument("--scale", type=int, default=2)
    a = ap.parse_args()

    im = FaceImage(a.face)
    lua = slot(im, LUA).decode("utf-8", "ignore")
    dx = [int(v) for v in re.search(r"local DX = \{([^}]*)\}", lua).group(1).replace(" ", "").split(",")]
    df = re.findall(r'"([^"]+\.png)"', re.search(r"local DFILE = \{([^}]*)\}", lua).group(1))
    m = re.search(r'local COLON = "([^"]+)"', lua)
    if m:                       # v1.0.20+ 用独立常量
        co = m.group(1)
    else:                       # v1.0.19 及更早：冒号名直接内联在 dig[3] 那行
        co = re.search(r'dig\[3\]:set \{ src = SCRIPT_PATH \.\. "([^"]+)"', lua).group(1)
    y = int(re.search(r"dig\[i\] = img\(SCRIPT_PATH \.\. DFILE\[1\], DX\[i\], (\d+)\)", lua).group(1))
    print(f"包内 lua  DX={dx} 顶边={y} COLON={co}")

    hh, mm = (int(x) for x in a.time.split(":"))
    seq = [hh // 10, hh % 10, ":", mm // 10, mm % 10]
    canvas = Image.open(io.BytesIO(slot(im, PRE + "bg9.png"))).convert("RGBA")
    picked = []
    for i, ch in enumerate(seq):
        name = co if ch == ":" else df[ch]
        g = Image.open(io.BytesIO(slot(im, PRE + name))).convert("RGBA")
        picked.append(f"{ch}->{name}")
        canvas.alpha_composite(g, (dx[i], y))
    print(f"{a.time} 取槽  " + "  ".join(picked))

    out = canvas.convert("RGB")
    if a.scale > 1:
        out = out.resize((out.width * a.scale, out.height * a.scale), Image.NEAREST)
    out.save(a.out)
    print(f"→ {a.out}  {out.width}x{out.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
