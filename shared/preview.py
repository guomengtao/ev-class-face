# -*- coding: utf-8 -*-
"""表盘切换卡片缩略图生成。

四个必须守住的坑（都实际踩过）：

1) 字体路径写错会静默 fallback 到不支持中文的 load_default()，
   缩略图里中文全变豆腐块。macOS 上 PingFang.ttc **不存在**，
   可用的是 Hiragino Sans GB / STHeiti。
2) 内容铺满整屏 → 设备按跑道形（两端半径 96 半圆）遮罩裁切后，
   整块纯色被裁成一坨巨大圆形，即「超大的圆圈」。
   要么做「渐变底 + 居中圆角卡片」，要么让内容居中且四周留暗场。
3) 缩略图排版**必须和 lua 用同一份 rows/fonts**，否则改布局后
   预览图还停在旧排布，真机装上去和长按预览对不上。
4) 同一份 devices/*.json 被多款表盘共用 → 每款表盘必须在 face.json 的
   "rows" 里声明自己用哪几行，否则会画出别款表盘的行
   （实测：石英表盘串到了课程表那根进度条，压在时分数字上）。

尺寸、排版、配色全部从 profile + face.json 推导，不写死任何一行的 y。
"""
CN_FONTS = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
)
LAT_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
) + CN_FONTS

DEFAULT_FONTS = {"time": 46, "subject": 32, "status": 30, "body": 26,
                 "info": 26, "version": 18}
# 行 → 配色角色。可用 rows.<key>.role 指定；也可用 face.json 的
# preview_style.roles 整体覆盖（换一款表盘就换一套色）。
ROLE_COLOR = {
    "time": (255, 255, 255), "hh": (255, 246, 232), "mm": (255, 179, 71),
    "status": (255, 212, 121), "accent": (127, 212, 255),
    "sub": (255, 212, 121), "hint": (143, 180, 212),
}
SKIP_ROWS = {"info1", "info2", "div", "bar", "bbar", "version"}
BAR_ROWS = ("bar", "bbar")
LAT_KEYS = ("time", "big", "hh", "mm")   # batt 行有中文，别用拉丁字体


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _rgb(s, default):
    s = s or default
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


def _visible(dev, used):
    rows = dev.get("rows") or {}
    out = {}
    for k, v in rows.items():
        if not isinstance(v, dict) or v.get("y", -1) < 0:
            continue
        if used is not None and k not in used:
            continue
        out[k] = v
    return out


def render(dev, ver, path, sample=None, style=None, rows_used=None):
    """按机型 + 表盘风格画预览图。

    dev        devices/<name>.json
    sample     face.json 的 preview_sample（按行 key 取文字）
    style      face.json 的 preview_style：bg / card / roles / div_color ...
    rows_used  face.json 的 rows：本款表盘用到的行，防止串到别款表盘的行
    """
    from PIL import Image, ImageDraw

    style = style or {}
    w, h = dev["screen"]
    s = (h / 490.0 + w / 192.0) / 2.0

    def S(v):
        return int(round(v * s))

    fonts = dict(DEFAULT_FONTS)
    fonts.update(dev.get("fonts") or {})
    rows = _visible(dev, rows_used)
    lines = sorted(((k, r["y"], r.get("h", 30)) for k, r in rows.items()
                    if k not in SKIP_ROWS), key=lambda x: x[1])
    bar_key = next((k for k in BAR_ROWS if k in rows), None)
    bar = rows.get(bar_key) if bar_key else None
    div = rows.get("div")
    vrow = rows.get("version")
    roles = dict(ROLE_COLOR)
    roles.update(style.get("roles") or {})

    # ---- 背景：默认两段渐变；换表盘用 style.bg 给三段色 ----
    bg = style.get("bg") or ["#081424", "#112C46", "#081424"]
    im = Image.new("RGB", (w, h), (10, 28, 48))
    dr = ImageDraw.Draw(im)
    c0, c1, c2 = (_rgb(bg[0], "#081424"), _rgb(bg[1], "#112C46"), _rgb(bg[2], "#081424"))
    for y in range(h):
        t = y / max(1, h - 1)
        if t < 0.5:
            k, a, b = t / 0.5, c0, c1
        else:
            k, a, b = (t - 0.5) / 0.5, c1, c2
        dr.line([(0, y), (w, y)],
                fill=tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)))

    # ---- 卡片：默认开，石英这类无卡片风格在 face.json 里关掉 ----
    if style.get("card", True):
        cw = dev.get("content_width") or max(120, int(w * 0.83))
        pad_x = max(4, S(6))
        cx0 = (w - cw) // 2 - pad_x
        cx1 = (w + cw) // 2 + pad_x
        first_y = lines[0][1] if lines else dev.get("safe_area", {}).get("top", 0)
        last_y = first_y + 200
        if vrow:
            last_y = vrow["y"] + vrow.get("h", 20)
        elif bar:
            last_y = bar["y"] + bar.get("h", 6)
        cy0 = max(2, first_y - S(9))
        cy1 = min(h - 3, last_y + S(7))
        dr.rounded_rectangle(
            [cx0, cy0, cx1, cy1], radius=max(6, S(20)),
            fill=_rgb(style.get("card_fill"), "#102A44"),
            outline=_rgb(style.get("card_line"), "#2E587C"),
            width=max(1, S(1)))

    # ---- 分割线 ----
    if div:
        dw = div.get("w", int(w * 0.3))
        dh = max(1, div.get("h", 2))
        dl = (w - dw) // 2
        dr.rectangle([dl, div["y"], dl + dw, div["y"] + dh],
                     fill=_rgb(style.get("div_color"), "#3A4150"))

    # ---- 文字：位置取 rows 的 y + h/2，字号取 fonts（row.font 可指定字体键） ----
    smp = sample or {}
    cx = w // 2
    for key, y, rh in lines:
        txt = smp.get(key)
        if not txt:
            continue
        fkey = rows[key].get("font") or key
        fsize = fonts.get(fkey, fonts.get("body", 26))
        f = _font(LAT_FONTS if fkey in LAT_KEYS else CN_FONTS, fsize)
        col = roles.get(rows[key].get("role") or key, (255, 255, 255))
        dr.text((cx, y + rh // 2), txt, font=f, fill=col, anchor="mm")

    # ---- 进度条 / 电量条 ----
    if bar:
        bh = max(2, bar.get("h", 6))
        bw = min(dev.get("content_width") or w, bar.get("w", w))
        bl = (w - bw) // 2
        by = bar["y"]
        dr.rounded_rectangle([bl, by, bl + bw, by + bh], radius=bh // 2,
                             fill=_rgb(style.get("bar_bg"), "#1E3A52"))
        pct = float(style.get("bar_pct", 0.35))
        dr.rounded_rectangle([bl, by, bl + int(bw * pct), by + bh], radius=bh // 2,
                             fill=roles.get("accent", (127, 212, 255)))

    # ---- 电量角标：macOS 口径的电池图标 + 百分比，贴在版本号那一行右侧 ----
    if vrow and style.get("battery", True):
        pct = int(style.get("battery_pct", 82))
        iw = max(7, w // 8)
        ih = max(4, iw * 9 // 20)
        pad_r = max(2, S(4))
        slot = max(14, w // 6)
        px = w - pad_r - slot
        iy = vrow["y"] + max(0, (vrow.get("h", 20) - ih) // 2)
        ix = px - 3 - iw
        hint = roles.get("hint", (138, 147, 166))
        dr.rounded_rectangle([ix, iy, ix + iw - 2, iy + ih], radius=2,
                             outline=hint, width=1)
        inner = max(1, iw - 4)
        fw = max(0, int(inner * pct / 100))
        if fw:
            fcol = roles.get("accent", (127, 212, 255))
            if pct <= 15:
                fcol = (255, 107, 107)
            elif pct <= 35:
                fcol = (255, 179, 71)
            dr.rectangle([ix + 1, iy + 2, ix + fw, iy + ih - 2], fill=fcol)
        dr.rectangle([ix + iw - 1, iy + 2, ix + iw, iy + ih - 2], fill=hint)
        f = _font(LAT_FONTS, fonts.get("batt", fonts.get("version", 18)))
        dr.text((px + 2, iy + ih // 2), "%d%%" % pct, font=f, fill=hint, anchor="lm")

    # ---- 版本号 ----
    if vrow:
        f = _font(LAT_FONTS, fonts.get("version", 18))
        dr.text((cx, vrow["y"] + vrow.get("h", 20) // 2), ver, font=f,
                fill=_rgb(style.get("ver_color"), "#7A9EBE"), anchor="mm")

    # ---- 四角压暗（vignette）----
    # 跑道屏/圆角屏会把满幅亮色图裁成一整块亮圆的错觉，切换页里就读成「大圆圈」。
    # 把屏幕圆角之外的区域压到近黑，读图时先看到屏幕形状，而不是一团色块。
    vig = style.get("vignette")
    if vig:
        k = int(vig) if isinstance(vig, (int, float)) else 1
        r = max(8, int(min(w, h) * 0.28))
        dark = (int(0x05 * k), int(0x08 * k), int(0x0C * k))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
        base = Image.new("RGB", (w, h), dark)
        im = Image.composite(im, base, mask)

    im.save(path)
    return im
