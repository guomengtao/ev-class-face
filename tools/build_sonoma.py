# -*- coding: utf-8 -*-
"""EV Sonoma 组包器：真实照片背景 + 圆头胶囊七段 + 课程进度/流光动画。

基于 Daymatter 壳（与 Aurora 同槽结构），但三处独立：
  1) bg9 换成风景照（RGBA8 色型 6，与原槽编码一致），并烘入渐变暗蒙版保证文字可读；
  2) 时间字形改为圆头胶囊七段（PIL 直绘 2 色硬边，不经字体、不抗锯齿）；
  3) lua 增加纯 LVGL 进度条 + 1s 流光 Timer，全部 pcall 保护，失败不影响主表盘。
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
FACE_ID, FACE_NAME, VER = "9798252662", "EV-Sonoma", "1.0.1"
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
    for y in range(H):
        t = y / H
        if t < 0.12: a = int(25 + 95*t/0.12)
        elif t < 0.48: a = 120
        else: a = max(18, int(120 - 82*(t-0.48)/0.52))
        sd.line((0, y, W, y), fill=(8, 14, 26, a))
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
    print(f"  预览用 64 色派生版 RLE {len(_r.encode(q.tobytes()))}B / 31156B")
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
-- ---------- 课程进度 + 流光（纯 LVGL 几何，不占图片槽） ----------
-- A 档：refresh() 按课时比例改填充宽度；B 档：1s Timer 让高亮块在已完成区间跑动。
-- 整段 pcall 保护：固件若不支持某个 Object 属性，进度条不显示，主表盘照常工作。
local PB_X, PB_Y, PB_W, PB_H = 26, 140, 140, 8
_G.ev_apply_progress = function() end
_G.ev_tick_anim = function() end
pcall(function()
    local bg = lvgl.Object(scr, { w=PB_W, h=PB_H, x=PB_X, y=PB_Y,
        bg_color=0x22304C, bg_opa=255, radius=4, border_width=0 })
    local fill = lvgl.Object(scr, { w=1, h=PB_H, x=PB_X, y=PB_Y,
        bg_color=0xF0A32B, bg_opa=255, radius=4, border_width=0 })
    local glow = lvgl.Object(scr, { w=22, h=PB_H, x=PB_X, y=PB_Y,
        bg_color=0xFFD58A, bg_opa=0, radius=4, border_width=0 })
    pcall(function()
        bg:clear_flag(lvgl.FLAG.SCROLLABLE)
        fill:clear_flag(lvgl.FLAG.SCROLLABLE)
        glow:clear_flag(lvgl.FLAG.SCROLLABLE)
    end)
    local phase = 0
    _G.ev_apply_progress = function()
        local p = _G.ev_progress or 0
        pcall(function()
            fill:set { w = math.max(1, math.floor(PB_W * p)) }
            glow:set { bg_opa = (_G.ev_in_class and _G.ev_screen_on) and 200 or 0 }
        end)
    end
    _G.ev_tick_anim = function()
        if not (_G.ev_in_class and _G.ev_screen_on) then return end
        phase = (phase + 1) % 20
        local span = math.max(1, math.floor(PB_W * (_G.ev_progress or 0)))
        pcall(function()
            glow:set { x = PB_X + math.floor((phase / 20) * span),
                       bg_opa = 140 + math.floor(70 * math.abs(math.sin(phase / 3))) }
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
    t = t.replace(old, old + '\n    _G.ev_sonoma_anim = lvgl.Timer { period = 1000, cb = function() _G.ev_tick_anim() end }', 1)
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
                  '-- 版式（ev-six v5 合规）：图片数字时间 / 状态进度带 / 当前课44px / 上下节课24px', 1)
    p = SRC / "main.lua"; p.write_text(t, encoding="utf-8")
    print(f"  lua 源码 {p.stat().st_size} B（进度条 + 1s 流光 Timer 已注入，pcall 保护）")
    return p

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
        d2 = ImageDraw.Draw(canvas)
        canvas.paste(g, (DX[i], DIG_Y), g)
    # RULES.md §3：字号只取 24/44，禁 <24px 小字；状态用进度/颜色表达，不写「上课中」
    f24, f44 = pick(24), pick(44)
    def centered(text, y, font, color):
        w = d.textlength(text, font=font); d.text(((W-w)/2, y), text, font=font, fill=color)
    # 进度带 y=140（时间下方）：y=440 起属胶囊底部圆角禁放区，两端会被裁
    d.rounded_rectangle((26,140,166,148), radius=4, fill=(34,48,76))
    d.rounded_rectangle((26,140,26+int(140*0.68),148), radius=4, fill=AMBER)
    gx = 26 + int(140*0.68*0.55)
    d.rounded_rectangle((gx,140,min(gx+22,166),148), radius=4, fill=(255,213,138))
    centered("数学", 190, f44, C_MAIN)
    # 等效字数 ≤6P：语文 8:00 ≈5.3P / 英语 13:30 ≈5.9P（原「上 语文 08:00」≈6.3P 越界）
    d.text((20, 290), "语文 8:00", font=f24, fill=C_DIM)
    d.text((20, 330), "英语 13:30", font=f24, fill=C_DIM)
    # RULES.md §2：底部只放表盘英文名 + 三位版本号，各 24px 独立成行
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
    d.text((36, 24), f'EVfSonoma v{VER} · 照片背景 + 圆头数码管 + 课程进度/流光', font=pick(22), fill=(242,246,255))
    d.text((36, ch-60), f'照片背景 · 圆头七段 · 状态进度带 1s 流光 · 底部 EVfSonoma + v{VER}', font=pick(15), fill=(150,168,196))
    d.text((36, ch-36), '动画仅在上课中 + 亮屏启用；Object 绘制 pcall 保护，失败不白屏', font=pick(15), fill=(150,168,196))
    c.save(out); return out

def main():
    print("=== EV Sonoma 组包 ===")
    bg, bg64 = make_bg(); lua_path = make_lua()
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
    print(f"  回读自检  ✓ 预览 {w2}x{h2}/{n}px  ✓ 包内 lua 含 1s 流光 Timer 与进度逻辑")
    return 0

if __name__ == "__main__":
    sys.exit(main())
