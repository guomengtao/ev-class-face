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
5) 「四周留 16px 矩形深色边」挡不住跑道屏裁切：band9 的 192×490 是
   胶囊（capsule）屏，两端半圆半径 = 屏宽/2 = 96px，遮罩边界是弧线，
   矩形 inset 只在四个直边生效，弧线内侧仍是满幅亮色渐变 —— 设备一裁，
   亮色一直顶到弧线边界，读出来就是「超大圆圈」。
   根治要在渲染层按真实遮罩几何压暗边界（safe_frame），而不是靠配置绕过。

尺寸、排版、配色全部从 profile + face.json 推导，不写死任何一行的 y。
"""
# 中文行只认这一组，且首位必须是 Hiragino Sans GB。
# ⚠️ macOS 上 /System/Library/Fonts/PingFang.ttc **不存在**（实测 OSError），
#    写进来的话 _font 会一路 fallback 到 load_default()，中文静默变豆腐块。
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


def _font(paths, size, cjk=False):
    """加载字体。cjk=True 时**拒绝静默 fallback**：宁可构建失败，也不出豆腐块。

    踩过的坑：字体路径写错（如 PingFang.ttc）→ truetype 抛异常 → 一路
    fallback 到 load_default() → 中文全是 □□，而构建器毫无察觉照常出包。
    现在中文行会校验「字体确实能渲染汉字」，不满足直接抛错。
    """
    from PIL import ImageFont
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
            if cjk:
                # 拉丁字体（Arial Bold 等）不含汉字，getmask 会渲染成空格/豆腐块。
                # 用「课」的字形宽度是否 >= 半个字号」粗判是否真有中文字形。
                bb = f.getbbox("课")
                if not bb or (bb[2] - bb[0]) < size * 0.5:
                    continue
            return f
        except Exception:
            continue
    if cjk:
        raise RuntimeError(
            "中文行找不到可用中文字体（拒绝静默出豆腐块）。"
            "macOS 上 PingFang.ttc 不存在；正确路径："
            "/System/Library/Fonts/Hiragino Sans GB.ttc。候选：%r" % (list(paths),))
    return ImageFont.load_default()


def _has_cjk(text):
    return any("\u3400" <= ch <= "\u9fff" for ch in (text or ""))


def _capsule_edge_darken(im, dev, style):
    """按真实跑道屏（capsule）几何，把遮罩边界内侧压暗，根治「大圆圈」。

    192×490 跑道屏 = 中段矩形 + 上下两个半径 w/2 的半圆。设备长按切换页
    按这个形状裁切预览图：只要亮色一直顶到弧线边界，裁出来就是一整块
    明亮胶囊轮廓（用户说的「超大圆圈」）。矩形 inset 只压四条直边，
    对弧线无效 —— 这是前几轮反复修不掉的原因。

    这里按「每个像素到遮罩边界的距离」生成羽化 alpha：
      * 边界外 / 紧贴边界 → 近黑（与设备黑底一致，看不出轮廓）
      * 往内 guard 像素渐变回原图
    几何全部由 dev['screen'] 推导，不写死机型；guard / 暗场色由
    face.json.preview_style 的 safe_guard / frame_color 提供，保证与
    缩略图配置同源。guard 默认 w*0.14（band9 ≈ 26px），经验值：既能
    盖住弧线边界的全部亮色，又吃不到居中的文字行。

    中段矩形两侧也压暗（左右是直边，同样会形成亮边），但只在 x 方向，
    不影响 rows 里的文字（文字居中且在 content_width 内）。

    与旧 vignette 的区别：vignette 用 rounded_rectangle(radius=min(w,h)*0.28)
    压四角，半径算错（跑道屏真实圆角是 w/2=96，不是 53），实测「更糟」；
    本函数按每个像素到真实胶囊边界的距离计算，弧线上处处生效。

    ⚠️ RLE 容量约束（实测踩坑）：连续羽化会让每一行水平方向逐像素变色，
    RLE 的重复块全部失效，编码从 24KB 涨到 56KB，超过 band9-large 壳的
    52988B 预览槽位，build.py 的 len(body)==cap_body 断言直接失败。
    所以 alpha 必须**阶梯量化**（safe_levels 档），让水平方向重新出现
    连续同色段。这是「能出包」的硬条件，不是可选优化。
    """
    from PIL import Image
    import math

    w, h = im.size
    r = w / 2.0                      # 跑道屏两端半圆半径 = 屏宽/2
    cy_top, cy_bot = r, h - 1 - r
    guard = float(style.get("safe_guard") or max(12, int(w * 0.14)))
    # 阶梯量化：把连续 alpha 归一到 levels 档。连续羽化会让每行逐像素变色，
    # RLE 重复块失效导致预览块溢出；量化后相邻像素大量同色，重新可压缩。
    levels = max(2, int(style.get("safe_levels") or 8))
    edge = tuple(int(v) for v in (style.get("frame_color") or (5, 8, 12)))

    def _step(dist):
        t = max(0.0, min(1.0, dist / guard))
        s = t * t * (3 - 2 * t)                 # smoothstep
        return int(255 * round(s * levels) / levels)

    alpha = bytearray(w * h)
    for y in range(h):
        if y < cy_top:
            dy = y - cy_top
            for x in range(w):
                dx = x - (w - 1) / 2.0
                alpha[y * w + x] = _step(r - math.sqrt(dx * dx + dy * dy))
        elif y > cy_bot:
            dy = y - cy_bot
            for x in range(w):
                dx = x - (w - 1) / 2.0
                alpha[y * w + x] = _step(r - math.sqrt(dx * dx + dy * dy))
        else:
            for x in range(w):
                alpha[y * w + x] = _step(min(x, w - 1 - x))

    mask = Image.frombytes("L", (w, h), bytes(alpha))
    base = Image.new("RGB", (w, h), edge)
    return Image.composite(im, base, mask)


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
    # 布局覆盖：指针/图案类表盘的行坐标是表盘自己算的（不走 devices 的通用行），
    # 不覆盖就会「缩略图里字在中间、真机字在底部」。
    for k, ov in (style.get("rows_override") or {}).items():
        base = dict(rows.get(k) or {})
        base.update(ov)
        rows[k] = base
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

    # ---- 圆盘（指针表盘）：切换页的缩略图必须看得出「这是块表」----
    # 早前只用 rows 画文字，缩略图里空得只剩几行字，和真机完全不像。
    # 这里把 lua 的盘面用同一套几何重画一遍：拉丝按弦长裁、刻度按 sin/cos 定位。
    dial = style.get("dial")
    if dial:
        import math as _m
        cx = int(dial.get("cx") or w // 2)
        cy = int(dial.get("cy") or 190)
        r = int(dial.get("r") or 84)
        fill = _rgb(dial.get("fill"), "#14161C")

        dr.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], fill=fill)

        # 拉丝（指针表盘不需要，白盘类不传 brush 就跳过）
        brushes = dial.get("brush")
        if brushes:
            bl = [_rgb(c, "#1E222A") for c in brushes]
            ir = r - 9
            k = 0
            for dy in range(-ir, ir + 1, 10):
                half = int((ir * ir - dy * dy) ** 0.5)
                if half > 2:
                    dr.rectangle([cx - half, cy + dy, cx + half - 1, cy + dy + 6],
                                 fill=bl[k % len(bl)])
                k += 1
        if dial.get("rim"):
            dr.ellipse([cx - r, cy - r, cx + r, cy + r],
                       outline=_rgb(dial["rim"], "#39404C"), width=2)
        if dial.get("inner"):
            dr.ellipse([cx - r + 5, cy - r + 5, cx + r - 5, cy + r - 5],
                       outline=_rgb(dial["inner"], "#2B313C"), width=1)

        # 刻度：一律竖条（截图里那款极简白盘的刻度不随角度旋转）
        tick_c = _rgb(dial.get("tick_color"), "#8E8E93")
        tw = int(dial.get("tick_w") or 6)
        th = int(dial.get("tick_h") or 16)
        tr = int(dial.get("tick_r") or (r - 17))
        for hd in range(12):
            rad = hd * 30 * _m.pi / 180.0
            tx, ty = cx + tr * _m.sin(rad), cy - tr * _m.cos(rad)
            dr.rounded_rectangle([tx - tw / 2, ty - th / 2, tx + tw / 2, ty + th / 2],
                                 radius=3, fill=tick_c)

        hh_v = float(dial.get("hh", 10))
        mm_v = float(dial.get("mm", 10))

        def _tip(deg, ln):
            rad = deg * _m.pi / 180.0
            return (cx + ln * _m.sin(rad), cy - ln * _m.cos(rad))

        dr.line([(cx, cy), _tip((hh_v % 12) * 30 + mm_v * 0.5, 40)],
                fill=_rgb(dial.get("hh_color"), "#16161A"), width=9)
        dr.line([(cx, cy), _tip(mm_v * 6, 64)],
                fill=_rgb(dial.get("mm_color"), "#16161A"), width=7)
        sec_v = dial.get("sec")
        if sec_v is not None:
            dr.line([(cx, cy), _tip(float(sec_v) * 6, tr + 5)],
                    fill=_rgb(dial.get("sec_color"), "#F5A623"), width=2)
        dr.ellipse([cx - 5, cy - 5, cx + 5, cy + 5],
                   fill=_rgb(dial.get("hub_color"), "#F5A623"))

    # ---- 卡片：默认开，石英这类无卡片风格在 face.json 里关掉 ----
    # card_w 可覆盖宽度：默认 content_width(160)+pad 会铺到 172/192 近满幅，
    # 居中圆角卡片要明显收窄，四周留出暗场才不会被遮罩读成「一整块圆」。
    if style.get("card", True):
        cw = int(style.get("card_w") or (dev.get("content_width") or max(120, int(w * 0.83))))
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
        # 中文行强制走 CN_FONTS 且开启硬校验：文本里有汉字就不能用拉丁字体，
        # 也不能静默 fallback 到 load_default() 变成豆腐块。
        is_cjk = _has_cjk(txt)
        f = _font(CN_FONTS if is_cjk else (LAT_FONTS if fkey in LAT_KEYS else CN_FONTS),
                  fsize, cjk=is_cjk)
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

    # ---- 四周留深色边（inset）----
    # 矩形直边处理（对跑道屏弧线无效，仅作为直边保险，弧度交给 safe_frame）。
    # ⚠️ vignette 分支会重新赋值 im，这里必须重新绑定 dr，否则 inset 画在旧
    #    Image 对象上被 Composite 结果覆盖 —— 之前同时开两者时 inset 静默失效。
    ins = style.get("inset")
    if ins:
        ins = int(ins)
        edge = style.get("inset_color") or [0x05, 0x08, 0x0C]
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, w - 1, ins - 1], fill=tuple(edge))
        dr.rectangle([0, h - ins, w - 1, h - 1], fill=tuple(edge))
        dr.rectangle([0, 0, ins - 1, h - 1], fill=tuple(edge))
        dr.rectangle([w - ins, 0, w - 1, h - 1], fill=tuple(edge))

    # ---- 跑道屏安全暗场（safe_frame）----
    # 根治「大圆圈」：按 devices/*.json 的 screen 推导胶囊遮罩几何，把弧线
    # 边界内侧羽化压到近黑，亮色内容退到中间安全区。任何遮罩下读到的都是
    # 「深色边框 + 居中圆角卡片」，不会再出现整块明亮胶囊轮廓。
    if style.get("safe_frame"):
        im = _capsule_edge_darken(im, dev, style)

    im.save(path)
    return im
