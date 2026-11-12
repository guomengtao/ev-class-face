# -*- coding: utf-8 -*-
"""EV Sonoma 组包器：真实照片背景 + 圆头胶囊七段 + 课程进度/流光动画。

基于 Daymatter 壳（与 Aurora 同槽结构），但三处独立：
  1) bg9 换成风景照（RGBA8 色型 6，与原槽编码一致），并烘入渐变暗蒙版保证文字可读；
  2) 时间字形改为圆头胶囊七段（PIL 直绘 2 色硬边，不经字体、不抗锯齿）；
  3) lua 用 20 个小 Object 拼环形刻度进度 + 1s 彗星拖尾流光，全段 pcall 保护。
"""
import re, sys, tempfile, struct
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tools"))
from shared.face_container import FaceImage
from shared import rle
import build_aurora as B
from PIL import Image, ImageDraw, ImageFont
import datetime

BASE = HERE / "dist" / "Band9" / "Band9-Daymatter-v1.0.0.face"
SRC = HERE / "faces" / "sonoma"
ASSETS = SRC / "assets"; ASSETS.mkdir(parents=True, exist_ok=True)
AUR = HERE / "faces" / "aurora" / "main.lua"
SLOT = "_lua/daymatter/"
W, H = 192, 490
DIG_Y, CELL_W, DIG_H = 68, 34, 56
DX = [7, 43, 79, 115, 151]
FACE_ID, FACE_NAME, VER = "9798252662", "EV-Sonoma", "1.1.0"
AMBER = (240, 163, 43); C_STAT = (127, 216, 188); C_MAIN = (238, 244, 255)
C_DIM = (175, 190, 215); C_LO = (120, 138, 170)
PHOTO = ASSETS / "photo_src.png"           # Sonoma 风景照 192×490（已入库，构建可复现）
SEG = {'0':'abcdef','1':'bc','2':'abged','3':'abgcd','4':'fgbc',
       '5':'afgcd','6':'afgecd','7':'abc','8':'abcdefg','9':'abfgcd'}

def seg_rects(th=6):
    hm = DIG_H / 2
    return {
      'a': (th+2, 0, CELL_W-th-2, th),
      'g': (th+2, int(hm-th/2), CELL_W-th-2, int(hm+th/2)),
      'd': (th+2, DIG_H-th, CELL_W-th-2, DIG_H),
      'f': (0, th+2, th, int(hm-th/2-2)),
      'b': (CELL_W-th, th+2, CELL_W, int(hm-th/2-2)),
      'e': (0, int(hm+th/2+2), th, DIG_H-th-2),
      'c': (CELL_W-th, int(hm+th/2+2), CELL_W, DIG_H-th-2),
    }

def make_bg():
    """照片 + 渐变暗蒙版，烘进 PNG 本身（设备真机也能保证文字对比度）。"""
    p = Image.open(PHOTO).convert("RGBA")
    if p.size != (W, H): p = p.resize((W, H), Image.LANCZOS)
    shade = Image.new("RGBA", (W, H), (0,0,0,0)); sd = ImageDraw.Draw(shade)
    # RULES §3.5：照片实测 y370-445 是亮黄绿(亮度188)，最需压暗；旧曲线底部
    # alpha 反而衰减到 18，白字/灰字直接糊在亮绿上。改为「上轻下重」反向补偿。
    for y in range(H):
        t = y / H
        a = int(120 + 95 * t)
        sd.line((0, y, W, y), fill=(10, 16, 34, a))
    out = Image.alpha_composite(p, shade)
    path = ASSETS / "bg_sonoma.png"; out.save(path, optimize=True)
    assert path.stat().st_size < 145528, f"背景 {path.stat().st_size}B 爆槽"
    # 预览块是 RLE 像素流（槽仅 31156B），全彩照片最省 197KB 压不进去。
    # 用同一构图派生的 64 色版做切换页缩略图；真机 bg9 仍是全彩。
    q = out.convert("RGB").quantize(colors=64, method=Image.MEDIANCUT,
                                    dither=Image.NONE).convert("RGB")
    q64 = ASSETS / "bg_sonoma_preview64.png"; q.save(q64, optimize=True)
    from shared import rle as _r
    print(f"  背景 RGBA8 {path.stat().st_size:6d} / 145528 B  (色型 6，与原 bg9 一致)")
    print(f"  预览派生 64 色参考 RLE {len(_r.encode(q.tobytes()))}B（后续自适应量化入槽）")
    return path, q64

def render_glyphs(tmp):
    files = {}
    for ch, name in [(str(d), f"{d}.png") for d in range(10)] + [(":", "mao.png")]:
        im = Image.new("P", (CELL_W, DIG_H), 0)
        im.putpalette([0,0,0] + list(AMBER))   # 只 2 色：PLTE 6B，写满 256 色会多 768B 直接爆槽
        d = ImageDraw.Draw(im)
        if ch == ":":
            d.rounded_rectangle((14,19,20,25), radius=3, fill=1)
            d.rounded_rectangle((14,34,20,40), radius=3, fill=1)
        else:
            R = seg_rects()
            for s in SEG[ch]: d.rounded_rectangle(R[s], radius=3, fill=1)
        p = tmp / f"slot_{name}"
        im.save(p, optimize=True, transparency=0)
        B._slim(p)
        files[name] = p
    mx = max(p.stat().st_size for p in files.values())
    print("  圆头字形 " + " ".join(f"{n[:-4]}:{p.stat().st_size}B" for n,p in files.items()))
    assert mx <= 276, f"最大字形 {mx}B 超过最小槽 276B"
    return files

def make_lua():
    t = AUR.read_text(encoding="utf-8")
    t = re.sub(r'local VERSION = "[^"]*"', f'local VERSION = "v{VER}"', t, count=1)
    inject = r'''
-- ---------- 环形分段刻度进度 + 彗星流光（纯 LVGL Object，不占图片槽） ----------
-- 位置：时间下方中部焦点区（RULES §3.2 不靠下）；20 段沿圆周，进度点亮，
-- 0.5s Timer 让「彗星头 + 2 段拖尾」只在已完成区间循环跑，替代死板的单条填充。
-- 只用已实证的 lvgl.Object / lvgl.Timer；arc / Anim / Line 无真机显示实证，不赌。
-- 整段 pcall 保护：任一属性不支持则环不显示，主表盘照常工作。
local RING_CX, RING_CY, RING_R, RING_N = 96, 174, 38, 20
local R_ON, R_OFF = 0xF0A32B, 0x415A85
local R_HOT, R_MID, R_TAIL = 0xFFEBC0, 0xFFC069, 0xC87A22
_G.ev_apply_progress = function() end
_G.ev_tick_anim = function() end
pcall(function()
    local segs = {}
    for i = 1, RING_N do
        local a = -math.pi / 2 + (i - 1) * 2 * math.pi / RING_N
        local x = math.floor(RING_CX + RING_R * math.cos(a) - 2)
        local y = math.floor(RING_CY + RING_R * math.sin(a) - 4)
        local o = lvgl.Object(scr, { x = x, y = y, w = 4, h = 9,
            bg_color = R_OFF, bg_opa = 255, radius = 2, border_width = 0 })
        pcall(function() o:clear_flag(lvgl.FLAG.SCROLLABLE) end)
        segs[i] = o
    end
    local core = lvgl.Object(scr, { x = RING_CX - 4, y = RING_CY - 4, w = 8, h = 8,
        bg_color = R_ON, bg_opa = 255, radius = 4, border_width = 0 })
    pcall(function() core:clear_flag(lvgl.FLAG.SCROLLABLE) end)
    local lit, phase = 0, 0
    _G.ev_apply_progress = function()
        local p = _G.ev_progress or 0
        lit = math.floor(RING_N * p + 0.5)
        pcall(function()
            for i = 1, RING_N do
                segs[i]:set { bg_color = (i <= lit) and R_ON or R_OFF }
            end
            core:set { bg_opa = (_G.ev_in_class and _G.ev_screen_on) and 255 or 80 }
        end)
    end
    _G.ev_tick_anim = function()
        if not (_G.ev_in_class and _G.ev_screen_on) or lit < 1 then return end
        phase = (phase + 1) % lit
        pcall(function()
            for i = 1, RING_N do
                segs[i]:set { bg_color = (i <= lit) and R_ON or R_OFF }
            end
            for k = 0, 2 do
                local idx = ((phase - k) % lit) + 1
                segs[idx]:set { bg_color = (k == 0) and R_HOT or ((k == 1) and R_MID or R_TAIL) }
            end
        end)
    end
end)

'''
    assert 'local function refresh()' in t
    t = t.replace('local function refresh()', inject + 'local function refresh()', 1)
    anchor = '    -- 状态块（24px，底色区域已压进背景图）'
    calc = '''    if cur then
        _G.ev_in_class = true
        _G.ev_progress = math.max(0, math.min(1, (mins - cur.start) / math.max(1, cur.finish - cur.start)))
    else
        _G.ev_in_class = false
        _G.ev_progress = 0
    end
'''
    assert anchor in t
    t = t.replace(anchor, calc + anchor, 1)
    t = t.replace('        rows3()', '        rows3()\n        _G.ev_apply_progress()', 1)
    t = t.replace('    if now == "ON" then refresh() end',
                  '    _G.ev_screen_on = (now == "ON")\n    if now == "ON" then refresh() end', 1)
    old = '_G.ev_aurora_timer = lvgl.Timer { period = 10000, cb = function() refresh() end }'
    assert old in t
    t = t.replace(old, old + '\n    _G.ev_sonoma_anim = lvgl.Timer { period = 500, cb = function() _G.ev_tick_anim() end }', 1)
    t = t.replace('refresh()\nprint("EV_AURORA_V1"',
                  '_G.ev_screen_on = true\nrefresh()\nprint("EV_SONOMA_V1"', 1)
    # RULES.md §1.2：兜底文案不得用品牌名，改留空；运行时状态由进度/颜色表达
    t = t.replace('"EV课程表"', '""')
    # RULES.md §3.3：「上课中」「今日结束」是看不见的小字，删文字、留状态色 + 进度带
    for st, col in (("上课中", "C_STAT"), ("今日结束", "C_DIM")):
        src = f'l_stat:set {{ text = "{st}", text_color = {col} }}'
        assert src in t, f"运行时状态文字未匹配: {st}"
        t = t.replace(src, f'l_stat:set {{ text = "", text_color = {col} }}')
    # 注释也不留继承来的品牌名与旧版本号（RULES.md §2.3 四处同源）
    t = t.replace('-- EV Aurora v1.0.0 · 视觉系课程表盘（Daymatter 壳）',
                  f'-- EVfSonoma v{VER} · 照片背景课程表盘（Daymatter 壳）', 1)
    t = t.replace('-- 版式（ev-six v5 合规）：图片数字时间 / 上课中状态块 / 当前课44px / 上下节课24px',
                  '-- 版式（ev-six v5 合规）：图片数字时间 / 环形刻度进度 / 当前课44px / 上下节课24px', 1)
    p = SRC / "main.lua"; p.write_text(t, encoding="utf-8")
    print(f"  lua 源码 {p.stat().st_size} B（环形刻度 + 0.5s 流光 Timer 已注入，pcall 保护）")
    return p

def check_contrast(bg_path):
    """RULES §3.5：每条文字行与照片背景的对比度硬断言，1:1 可读性程序化把关。"""
    from PIL import ImageStat
    im = Image.open(bg_path).convert("RGB")
    def rl(rgb):
        def f(c):
            c /= 255.0
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = rgb
        return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b)
    rows = [(60, 130, '时间56px', rl(AMBER), 3.0),
            (232, 292, '当前课44px', rl(C_MAIN), 3.0),
            (300, 368, '课程行24px', rl(C_DIM), 4.5),
            (378, 446, '底部24px', rl(C_DIM), 4.5)]
    for y0, y1, label, Lt, need in rows:
        Lb = rl(tuple(ImageStat.Stat(im.crop((20, y0, 172, y1))).mean))
        cr = (max(Lt, Lb) + 0.05) / (min(Lt, Lb) + 0.05)
        print(f"  对比度 {label:12s} {cr:4.2f}:1  (需 >= {need})")
        assert cr >= need, f"{label} 对比度 {cr:.2f}:1 不足 {need}:1"

def pick(size):
    for c in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/System/Library/Fonts/STHeiti Medium.ttc", "/Library/Fonts/Arial Unicode.ttf"):
        try: return ImageFont.truetype(c, size)
        except OSError: pass
    raise SystemExit("无中文字体")

def compose(glyphs, bg, out):
    canvas = Image.open(bg).convert("RGB"); d = ImageDraw.Draw(canvas)
    for i, ch in enumerate(['0','8',':','0','0']):
        name = "mao.png" if ch == ":" else f"{ch}.png"
        g = Image.open(glyphs[name]).convert("RGBA")
        canvas.paste(g, (DX[i], DIG_Y), g)
    # RULES §3：字号只取 24/44；状态用非文字表达，不写「上课中」
    f24, f44 = pick(24), pick(44)
    def centered(text, y, font, color):
        w = d.textlength(text, font=font); d.text(((W-w)/2, y), text, font=font, fill=color)
    # 环形分段刻度：坐标公式与包内 lua 完全同源（RULES §3.4-7），预览展示 phase=3 的一帧
    import math
    RING_CX, RING_CY, RING_R, RING_N = 96, 174, 38, 20
    R_ON, R_OFF = AMBER, (65, 90, 133)
    R_TRAIL = [(255, 235, 192), (255, 192, 105), (200, 122, 34)]
    lit = int(RING_N * 0.68 + 0.5); phase = 3
    for i in range(1, RING_N + 1):
        a = -math.pi / 2 + (i - 1) * 2 * math.pi / RING_N
        x = int(RING_CX + RING_R * math.cos(a) - 2)
        y = int(RING_CY + RING_R * math.sin(a) - 4)
        col = R_ON if i <= lit else R_OFF
        for k in range(3):
            if lit > 0 and ((phase - k) % lit) + 1 == i: col = R_TRAIL[k]
        d.rounded_rectangle((x, y, x + 4, y + 9), radius=2, fill=col)
    d.ellipse((RING_CX-4, RING_CY-4, RING_CX+4, RING_CY+4), fill=AMBER)
    centered("数学", 232, f44, C_MAIN)
    d.text((20, 300), "语文 8:00", font=f24, fill=C_DIM)
    d.text((20, 334), "英语 13:30", font=f24, fill=C_DIM)
    # RULES §2：底部只放表盘英文名 + 三位版本号，各 24px 独立成行，末行 ≤448
    d.text((20, 378), "EVfSonoma", font=f24, fill=C_MAIN)
    d.text((20, 412), f"v{VER}", font=f24, fill=C_DIM)
    canvas.save(out)
    return out

def showcase(prev, out):
    """2x 展示图：胶囊圆角 + 标题，供设计评审。"""
    S = 2
    big = Image.open(prev).convert("RGB").resize((W*S, H*S), Image.LANCZOS)
    mask = Image.new("L", (W*S, H*S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,W*S-1,H*S-1), radius=96*S, fill=255)
    cw, ch = 760, H*S + 190
    c = Image.new("RGB", (cw, ch), (9,15,28)); OX, OY = (cw-W*S)//2, 76
    c.paste(big, (OX, OY), mask); d = ImageDraw.Draw(c)
    d.text((36, 24), f'EVfSonoma v{VER} · 环形刻度进度 + 彗星流光', font=pick(22), fill=(242,246,255))
    d.text((36, ch-60), '20 段环形刻度 + 0.5s 彗星拖尾 · 上轻下重暗蒙版 · 对比度硬断言', font=pick(15), fill=(150,168,196))
    d.text((36, ch-36), 'WCAG 对比度断言 · 动画仅上课中+亮屏 · 全段 pcall 保护', font=pick(15), fill=(150,168,196))
    c.save(out); return out

def main():
    print("=== EV Sonoma 组包 ===")
    bg, bg64 = make_bg(); check_contrast(bg); lua_path = make_lua()
    lua_src = lua_path.read_text(encoding="utf-8")
    im = FaceImage(BASE)
    pw, ph, plen = im.preview_meta()
    print(f"基底 {BASE.name}  预览槽 {pw}x{ph}/{plen}B")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td); glyphs = render_glyphs(tmp)
        png_slots = [(k, v[1]) for k, v in im.entries().items()
                     if k.startswith(SLOT) and k.endswith(".png")]
        free = [(k, c) for k, c in png_slots if k.split("/")[-1] in
                {f"{d}.png" for d in range(10)} | {"before_9.png","later_9.png","mao.png"}]
        pool = sorted(free, key=lambda x: x[1]); assign = {}
        for size, name, _ in sorted(((p.stat().st_size, n, p) for n, p in glyphs.items()), reverse=True):
            hit = next(((i, sl) for i, (sl, cap) in enumerate(pool) if cap >= size), None)
            if not hit: raise SystemExit(f"槽位不足：{name} {size}B")
            assign[name] = pool.pop(hit[0])[0]
        short = {n: a.split("/")[-1] for n, a in assign.items()}
        print("  槽位分配 " + "  ".join(f"{n[:-4]}->{short[n][:-4]}" for n in sorted(assign)))
        dig_map = ", ".join(f'"{short[f"{d}.png"]}"' for d in range(10))
        t = re.sub(r'local DFILE = \{[^}]*\}', f'local DFILE = {{ {dig_map} }}', lua_src, count=1)
        t = re.sub(r'local COLON = "[^"]*"', f'local COLON = "{short["mao.png"]}"', t, count=1)
        t = re.sub(r'local DX = \{[^}]*\}', 'local DX = { ' + ', '.join(str(v) for v in DX) + ' }', t, count=1)
        t = t.replace('DX[i], 52)', f'DX[i], {DIG_Y})')
        names = re.findall(r'"([^"]+\.png)"', re.search(r'local DFILE = \{([^}]*)\}', t).group(1))
        colon = re.search(r'local COLON = "([^"]+)"', t).group(1)
        assert len(names) == 10 and len(set(names)) == 10
        assert colon not in names
        for d in range(10): assert assign[f"{d}.png"] == SLOT + names[d]
        assert assign["mao.png"] == SLOT + colon
        used, cap = im.inject_resource(SLOT + "daymatter.lua", t.encode("utf-8"))
        print(f"  lua 注入 {used:6d} / {cap:6d} B  ({(cap-used)*100//cap}% 余量)")
        ub, cb = im.inject_resource(SLOT + "bg9.png", bg.read_bytes())
        print(f"  bg9 注入 {ub:6d} / {cb:6d} B")
        cap_of = dict(free)
        for name, path in glyphs.items():
            slot = assign[name]; im.inject_resource(slot, B.pad_png(path.read_bytes(), cap_of[slot]))
        prev = tmp / "preview.png"; compose(glyphs, bg64, prev)
        from PIL import Image as PI
        base_img = PI.open(prev).convert("RGB")
        chosen = None
        for n in (64, 48, 32, 24, 16, 12, 8):
            q = base_img.quantize(colors=n, method=Image.MEDIANCUT,
                                  dither=Image.NONE).convert("RGB")
            raw = q.tobytes(); L = len(rle.encode(raw))
            if L <= plen - 8:
                chosen = (n, q, raw, L); break
        assert chosen, "预览图 RLE 无法压进槽位"
        px = chosen[2]
        print(f"  预览量化 {chosen[0]:2d} 色  RLE {chosen[3]:6d}B / {plen-8}B")
        assert len(px) == W*H*3
        body = rle.encode_exact(px, plen - 8)
        assert rle.decode_px_count(body) == (W*H, plen-8)
        im.inject_preview(im.preview_header() + body)
        print(f"  预览块 {len(body)+8:6d} / {plen:6d} B  解码 {W*H}px 零剩余")
        for hh, mm in ((8,0),(17,15),(9,5),(23,59),(0,0)):
            seq = [hh//10, hh%10, ":", mm//10, mm%10]
            for i, ch in enumerate(seq):
                nm = colon if ch == ":" else names[ch]
                want = glyphs["mao.png" if ch == ":" else f"{ch}.png"].read_bytes()
                off = im.entries()[SLOT+nm][0]
                assert bytes(im.data[off:off+len(want)]) == want, f"{hh:02d}:{mm:02d} 第{i+1}格错"
        print("  取槽自检  08:00 / 17:15 / 09:05 / 23:59 / 00:00 五格全命中")
        full = tmp / "full.png"; compose(glyphs, bg, full)
        shot = HERE / "docs" / "design" / "EV-Sonoma-预览-20261112.png"
        showcase(full, shot)
        print(f"  展示图 {shot.name} {shot.stat().st_size}B（按真机全彩背景合成）")
    im.set_identity(FACE_ID, FACE_NAME)
    out = HERE / "dist" / "Band9" / f"Band9-Sonoma-v{VER}.face"
    size = im.save(out); print(f"\n出包 {out.name}  {size}B  id={FACE_ID}")
    chk = FaceImage(out); w2,h2,p2 = chk.preview_meta()
    b2 = bytes(chk.data[chk.tail+20:chk.tail+20+p2-8])
    n = rle.decode_px_count(b2); n = n[0] if isinstance(n, tuple) else n
    assert (w2,h2) == (W,H) and n == W*H
    c,cs,_ = chk.entries()[SLOT+"daymatter.lua"]
    final = bytes(chk.data[c:c+cs]).decode("utf8","ignore")
    assert "ev_sonoma_anim" in final and "ev_apply_progress" in final
    print(f"  回读自检  ✓ 预览 {w2}x{h2}/{n}px  ✓ 包内 lua 含 0.5s 流光 Timer 与进度逻辑")
    return 0

if __name__ == "__main__":
    sys.exit(main())
