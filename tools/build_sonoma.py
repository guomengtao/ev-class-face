# -*- coding: utf-8 -*-
"""EV Sonoma 组包器 v2：一份 LAYOUT 同时驱动「切换页预览块」与「运行时 lua」。

v1.2.0 复盘（2026-11-12 装机反馈）：
  1) 预览块是包内 192x490 RLE 立绘，**由本脚本生成**，设备只解码显示、不重绘。
     旧版 compose() 输出直角矩形 → 切换页露出两个方角；官方 Daymatter 立绘
     是自带胶囊遮罩的图形，不是真机截图。旧版还把照片降成 64 色再整体量化到
     8~16 色 + 抗锯齿小字 → 模糊、对比度低。
  2) 旧版 compose() 自己画「数学 / 语文 8:00 / EVfSonoma」，包内 lua 根本没有
     这些控件 → 装机后课程与名字全空，截图与真机不一致（违反 RULES §3.4-7）。
  3) 旧版动画用 Object:set{bg_color/bg_opa}（未实证 API）+ 上课中才跑 + 4x9px
     小刻度 → 既不动也看不见。
  4) 旧版电量与版本号同一行 label(436) 落在底部圆角区；空数据兜底是空字符串。

现在：
  * LAYOUT / PALETTE 单一配置，预览块、lua、设备等效截图三处同源；
  * make_preview() 直出扁平高对比图形 + 胶囊遮罩，固定调色板硬边无量化模糊；
  * 动画只用已实证 API（faces/class 生产盘同款 Object:set{x/w} + lvgl.Timer），
    装饰件一律 clear CLICKABLE + EVENT_BUBBLE，不再赌 bg_color；
  * 空数据兜底显示「无课 / 日期 / 周几」，底部两行独立且上移出圆角区。
"""
import io
import math
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tools"))
from shared.face_container import FaceImage
from shared import rle
import build_aurora as B
from PIL import Image, ImageDraw, ImageFont, ImageStat

BASE = HERE / "dist" / "Band9" / "Band9-Daymatter-v1.0.0.face"
SRC = HERE / "faces" / "sonoma"
ASSETS = SRC / "assets"; ASSETS.mkdir(parents=True, exist_ok=True)
AUR = HERE / "faces" / "aurora" / "main.lua"
SLOT = "_lua/daymatter/"
W, H = 192, 490
FACE_ID, FACE_NAME, VER = "9798252662", "EV-Sonoma", "1.2.0"

# ---------------------------------------------------------------------------
# 唯一版式配置：预览块 / 包内 lua / 设备等效截图 / 对比度断言全部读这里
# ---------------------------------------------------------------------------
LAYOUT = dict(
    # 胶囊 radius=96 → y<96 两侧收窄，整宽内容一律从 y>=96 起排，避免外圈数字被弧边切
    time_y=100, dx=(7, 43, 79, 115, 151), cell_w=34, dig_h=56,
    band_x=12, band_y=176, band_w=168, band_h=16, comet_w=30,
    cur_y=222, up_y=300, dn_y=336,
    name_y=376, ver_y=410,
    name="EVfSonoma", ver="v" + VER,
    capsule_r=96,          # 官方 Daymatter 立绘实测：192 宽 → 半圆端 = radius 96
)
DIG_Y = LAYOUT["time_y"]
DX = list(LAYOUT["dx"])

# 预览块固定调色板：扁平、硬边、高对比；不量化、不抖动、不抗锯齿糊边
PALETTE = dict(
    corner=(10, 15, 28),
    bg=(10, 18, 34),
    hill1=(38, 32, 68),
    hill2=(24, 48, 38),
    panel=(18, 34, 58),
    track=(28, 48, 78),
    amber=(240, 163, 43),
    comet=(255, 240, 205),
    white=(238, 244, 255),
    dim=(175, 190, 215),
)
AMBER = PALETTE["amber"]; C_MAIN = PALETTE["white"]; C_DIM = PALETTE["dim"]
PHOTO = ASSETS / "photo_src.png"
SEG = {'0':'abcdef','1':'bc','2':'abged','3':'abgcd','4':'fgbc',
       '5':'afgcd','6':'afgecd','7':'abc','8':'abcdefg','9':'abfgcd'}


def seg_rects(th=6):
    hm = LAYOUT["dig_h"] / 2
    cw = LAYOUT["cell_w"]
    return {
      'a': (th+2, 0, cw-th-2, th),
      'g': (th+2, int(hm-th/2), cw-th-2, int(hm+th/2)),
      'd': (th+2, LAYOUT["dig_h"]-th, cw-th-2, LAYOUT["dig_h"]),
      'f': (0, th+2, th, int(hm-th/2-2)),
      'b': (cw-th, th+2, cw, int(hm-th/2-2)),
      'e': (0, int(hm+th/2+2), th, LAYOUT["dig_h"]-th-2),
      'c': (cw-th, int(hm+th/2+2), cw, LAYOUT["dig_h"]-th-2),
    }


def make_bg():
    """真机背景：照片 + 上轻下重渐变暗蒙版（RULES §3.2/§3.5）。"""
    p = Image.open(PHOTO).convert("RGBA")
    if p.size != (W, H): p = p.resize((W, H), Image.LANCZOS)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(shade)
    for y in range(H):
        a = int(120 + 95 * y / H)
        sd.line((0, y, W, y), fill=(10, 16, 34, a))
    out = Image.alpha_composite(p, shade)
    path = ASSETS / "bg_sonoma.png"; out.save(path, optimize=True)
    assert path.stat().st_size < 145528, f"背景 {path.stat().st_size}B 爆槽"
    print(f"  背景 RGBA8 {path.stat().st_size:6d} / 145528 B")
    return path


def render_glyphs(tmp):
    files = {}
    for ch, name in [(str(d), f"{d}.png") for d in range(10)] + [(":", "mao.png")]:
        im = Image.new("P", (LAYOUT["cell_w"], LAYOUT["dig_h"]), 0)
        im.putpalette([0, 0, 0] + list(AMBER))
        d = ImageDraw.Draw(im)
        if ch == ":":
            d.rounded_rectangle((14, 19, 20, 25), radius=3, fill=1)
            d.rounded_rectangle((14, 34, 20, 40), radius=3, fill=1)
        else:
            R = seg_rects()
            for s in SEG[ch]: d.rounded_rectangle(R[s], radius=3, fill=1)
        p = tmp / f"slot_{name}"
        im.save(p, optimize=True, transparency=0)
        B._slim(p)
        files[name] = p
    mx = max(p.stat().st_size for p in files.values())
    assert mx <= 276, f"最大字形 {mx}B 超过最小槽 276B"
    return files


# ---------------------------------------------------------------------------
# 运行时 lua：数据层沿用 Aurora（已实证），UI 段按 LAYOUT 重写
# ---------------------------------------------------------------------------
UI_TMPL = r'''
-- ---------- 字体（只有 24/44 两档，ev-six v5）----------
local function F(size)
    local ok, f = pcall(lvgl.Font, "MiSans-Demibold", size, "normal")
    if ok and f then return f end
    ok, f = pcall(lvgl.Font, "MiSans-Regular", size)
    if ok and f then return f end
    return lvgl.BUILTIN_FONT.MONTSERRAT_20
end
local F24, F44 = F(24), F(44)
local C_MAIN, C_DIM = 0xEEF4FF, 0x9BA6C4

local scr = lvgl.Object(nil, { w = W, h = H, bg_opa = 0, border_width = 0, pad_all = 0 })
scr:clear_flag(lvgl.FLAG.SCROLLABLE)
scr:add_flag(lvgl.FLAG.EVENT_BUBBLE)

-- 装饰件必须清 CLICKABLE（否则吃掉长按、进不了切换页）+ 上抛事件
local function passive(o)
    if not o then return nil end
    pcall(function() o:clear_flag(lvgl.FLAG.CLICKABLE) end)
    pcall(function() o:clear_flag(lvgl.FLAG.SCROLLABLE) end)
    pcall(function() o:add_flag(lvgl.FLAG.EVENT_BUBBLE) end)
    return o
end
local function img(path, x, y)
    local w = scr:Image { src = path, x = x, y = y }
    return passive(w)
end
local function label(y, h, font, color, text)
    return passive(lvgl.Label(scr, {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
        align = { type = lvgl.ALIGN.TOP_MID, x_ofs = 0, y_ofs = y },
    }))
end

img(SCRIPT_PATH .. "bg9.png", 0, 0)

-- 时间：5 张图片数字，取槽由组包器按容量 best-fit 回填（勿手改）
local DX = { 7, 43, 79, 115, 151 }
local DFILE = { "0.png","1.png","2.png","3.png","4.png","5.png","6.png","7.png","8.png","9.png" }
local COLON = "mao.png"
local dig = {}
for i = 1, 5 do dig[i] = img(SCRIPT_PATH .. DFILE[1], DX[i], @TIME_Y@) end

-- ---------- 进度/流光带：只用 faces/class 生产盘已实证的 API ----------
-- lvgl.Object 构造 + set{x} / set{w} + lvgl.Timer；不碰 set{bg_color/bg_opa}。
-- 静态轨道 + 课程完成度填充 + 一颗来回扫的高亮彗星，永远在动、永远看得见。
local BAND_X, BAND_Y, BAND_W, BAND_H = @BAND_X@, @BAND_Y@, @BAND_W@, @BAND_H@
local COMET_W, ANIM_STEPS = @COMET_W@, 12
local track, fill, comet
pcall(function()
    track = passive(lvgl.Object(scr, { x = BAND_X, y = BAND_Y, w = BAND_W, h = BAND_H,
        bg_color = 0x1C304E, bg_opa = 255, border_width = 0, radius = 8 }))
    fill = passive(lvgl.Object(scr, { x = BAND_X, y = BAND_Y, w = 8, h = BAND_H,
        bg_color = 0xF0A32B, bg_opa = 255, border_width = 0, radius = 8 }))
    comet = passive(lvgl.Object(scr, { x = BAND_X, y = BAND_Y, w = COMET_W, h = BAND_H,
        bg_color = 0xFFF0CD, bg_opa = 255, border_width = 0, radius = 8 }))
end)

local l_cur  = label(@CUR_Y@, 60, F44, C_MAIN, "")
local l_up   = label(@UP_Y@, 32, F24, C_DIM, "")
local l_dn   = label(@DN_Y@, 32, F24, C_DIM, "")
-- RULES §2：底部两行独立，24px，上移出圆角禁放区；电量不进底部
local l_name = label(@NAME_Y@, 32, F24, C_MAIN, "@NAME@")
local l_ver  = label(@VER_Y@, 32, F24, C_MAIN, "@VERSION@")

local WD = { "周日","周一","周二","周三","周四","周五","周六" }
local function two(n) return (n < 10) and ("0" .. n) or tostring(n) end
local function hm(mins) return tostring(mins // 60) .. ":" .. two(mins % 60) end
local function today() return os.date("*t", os.time()) end
local function dow(t) return ((t.wday or 1) == 1) and 7 or ((t.wday or 2) - 1) end

-- 空数据兜底：不留白、不写品牌名、不写看不见的小字（RULES §1.2 / §3.3）
local function fallback_rows()
    local t = today()
    l_cur:set { text = "无课" }
    l_up:set  { text = string.format("%d月%d日", t.month, t.day) }
    l_dn:set  { text = WD[t.wday or 1] or "" }
end

local function progress_value()
    local t = today(); local mins = (t.hour or 0) * 60 + (t.min or 0)
    local list = schedule[dow(t)] or {}
    if #list == 0 then return 0.35 + 0.65 * mins / 1440 end
    local done = 0
    for _, c in ipairs(list) do if c.finish <= mins then done = done + 1 end end
    for _, c in ipairs(list) do
        if c.start <= mins and mins < c.finish then
            return (done + (mins - c.start) / math.max(1, c.finish - c.start)) / #list
        end
    end
    return done / #list
end

_G.ev_progress = 0
_G.ev_screen_on = true
_G.ev_apply_progress = function() end
_G.ev_tick_anim = function() end
pcall(function()
    _G.ev_apply_progress = function()
        pcall(function()
            local pw = math.max(8, math.floor(BAND_W * math.max(0, math.min(1, _G.ev_progress or 0))))
            _G.ev_fill_base = pw
            fill:set { w = pw }
        end)
    end
    local phase, step = 0, 1
    _G.ev_tick_anim = function()
        if _G.ev_screen_on == false then return end
        phase = phase + step
        if phase >= ANIM_STEPS - 1 then step = -1 end
        if phase <= 0 then step = 1 end
        pcall(function()
            comet:set { x = BAND_X + math.floor((BAND_W - COMET_W) * phase / (ANIM_STEPS - 1)) }
        end)
        -- 双保险：set{w} 是 faces/class 生产盘 Timer 内已实证的调用，
        -- 即使某机型不支持 set{x}（或彗星创建失败），填充带呼吸也一定在动
        pcall(function()
            local base = _G.ev_fill_base or 8
            local pulse = math.floor(7 * math.sin(phase * math.pi / (ANIM_STEPS - 1)))
            fill:set { w = math.max(8, base + pulse) }
        end)
    end
end)

local function rows3()
    local t = today(); local mins = (t.hour or 0) * 60 + (t.min or 0)
    local list = schedule[dow(t)] or {}
    local prev, cur, nxt = nil, nil, nil
    for _, c in ipairs(list) do
        if c.start <= mins and mins < c.finish then cur = c end
        if c.finish <= mins then prev = c end
        if c.start > mins and not nxt then nxt = c end
    end
    l_cur:set { text = cut((cur and cur.name) or (nxt and nxt.name) or "无课", 3) }
    l_up:set  { text = prev and (cut(prev.name, 3) .. " " .. hm(prev.start))
                       or string.format("%d月%d日", t.month, t.day) }
    l_dn:set  { text = nxt and (cut(nxt.name, 3) .. " " .. hm(nxt.start)) or (WD[t.wday or 1] or "") }
end

local last_min = -1
local sig_cache = "#none"
local function refresh()
    local t = today(); local h, m = t.hour or 0, t.min or 0
    if m ~= last_min then
        last_min = m
        dig[1]:set { src = SCRIPT_PATH .. DFILE[h // 10 + 1] }
        dig[2]:set { src = SCRIPT_PATH .. DFILE[h % 10 + 1] }
        dig[3]:set { src = SCRIPT_PATH .. COLON }
        dig[4]:set { src = SCRIPT_PATH .. DFILE[m // 10 + 1] }
        dig[5]:set { src = SCRIPT_PATH .. DFILE[m % 10 + 1] }
    end
    local ok = pcall(function()
        local text = read_shared()
        local sig = text or "#none"
        if sig ~= sig_cache then parse_schedule(text); sig_cache = sig end
        rows3()
    end)
    if not ok then fallback_rows() end
    _G.ev_progress = progress_value()
    _G.ev_apply_progress()
end

function ScreenStateChangedCB(pre, now, reason)
    _G.ev_screen_on = (now == "ON")
    if now == "ON" then refresh() end
end
pcall(function()
    _G.ev_sonoma_refresh = lvgl.Timer { period = 10000, cb = function() refresh() end }
end)
pcall(function()
    _G.ev_sonoma_anim = lvgl.Timer { period = 220, cb = function() _G.ev_tick_anim() end }
end)
refresh()
print("EV_SONOMA_V2", W, H, VERSION, "courses=" .. course_count)
'''


def make_lua():
    head = AUR.read_text(encoding="utf-8").split("-- ===== 数据层结束 =====")[0]
    head = head.replace("-- EV Aurora v1.0.0 · 视觉系课程表盘（Daymatter 壳）",
                        f"-- EVfSonoma v{VER} · 照片背景课程表盘（Daymatter 壳）")
    head = re.sub(r'local VERSION = "[^"]*"', f'local VERSION = "v{VER}"', head, count=1)
    assert 'local VERSION = "v' + VER + '"' in head
    ui = UI_TMPL
    for k, v in {
        "TIME_Y": LAYOUT["time_y"], "BAND_X": LAYOUT["band_x"], "BAND_Y": LAYOUT["band_y"],
        "BAND_W": LAYOUT["band_w"], "BAND_H": LAYOUT["band_h"], "COMET_W": LAYOUT["comet_w"],
        "CUR_Y": LAYOUT["cur_y"], "UP_Y": LAYOUT["up_y"], "DN_Y": LAYOUT["dn_y"],
        "NAME_Y": LAYOUT["name_y"], "VER_Y": LAYOUT["ver_y"],
        "NAME": LAYOUT["name"], "VERSION": LAYOUT["ver"],
    }.items():
        ui = ui.replace("@" + k + "@", str(v))
    assert not re.search(r"@[A-Z_]+@", ui), "模板占位符未替换完"
    t = head + "-- ===== 数据层结束 =====\n" + ui
    # RULES §1：屏内不得有品牌文字；§2：底部不得出现电量
    for bad in ("EV课程表", "EV Publisher", "EV Face", "请开课程表", "systemStatusBattery"):
        assert bad not in t, f"lua 仍含禁用文本 {bad}"
    assert t.count('local VERSION = "v' + VER + '"') == 1
    p = SRC / "main.lua"; p.write_text(t, encoding="utf-8")
    print(f"  lua 源码 {p.stat().st_size} B（LAYOUT 同源 / set{{x,w}}+Timer 动画）")
    return p


# ---------------------------------------------------------------------------
# 预览块：扁平高对比图形 + 胶囊遮罩（官方立绘惯例，不是设备截图）
# ---------------------------------------------------------------------------
def pick(size):
    for c in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/System/Library/Fonts/STHeiti Medium.ttc", "/Library/Fonts/Arial Unicode.ttf"):
        try: return ImageFont.truetype(c, size)
        except OSError: pass
    raise SystemExit("无中文字体")


def snap_palette(im):
    """固定调色板硬边映射：无抖动、无多级量化，缩略图不发虚。"""
    colors = list(PALETTE.values())
    pal = Image.new("P", (1, 1))
    pal.putpalette([v for c in colors for v in c] + [0] * (768 - 3 * len(colors)))
    return im.quantize(palette=pal, dither=Image.NONE).convert("RGB")


def capsule_mask():
    """官方 Daymatter 立绘同款半圆端；4x 画弧缩回二值化，边缘平滑无虚边。"""
    S = 4
    big = Image.new("L", (W * S, H * S), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, W * S - 1, H * S - 1),
                                          radius=LAYOUT["capsule_r"] * S, fill=255)
    return big.resize((W, H), Image.LANCZOS).point(lambda p: 255 if p >= 128 else 0)


def apply_capsule(im):
    return Image.composite(im, Image.new("RGB", (W, H), PALETTE["corner"]), capsule_mask())


def draw_band(d, phase=5, progress=0.68):
    L = LAYOUT
    x, y, w, h, cw = L["band_x"], L["band_y"], L["band_w"], L["band_h"], L["comet_w"]
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=PALETTE["track"])
    fw = max(8, int(w * progress))
    d.rounded_rectangle((x, y, x + fw, y + h), radius=h // 2, fill=PALETTE["amber"])
    cx = x + int((w - cw) * phase / 11)
    d.rounded_rectangle((cx, y, cx + cw, y + h), radius=h // 2, fill=PALETTE["comet"])


def make_preview(glyphs, out):
    """切换页立绘：扁平几何、少量大元素、高对比，不做照片缩略（官方惯例）。"""
    L = LAYOUT
    im = Image.new("RGB", (W, H), PALETTE["bg"]); d = ImageDraw.Draw(im)
    # 两块扁平山形呼应真机照片，纯色块不产生渐变/量化糊边
    d.polygon([(0, 300), (72, 246), (140, 292), (192, 258), (192, H), (0, H)],
              fill=PALETTE["hill1"])
    d.polygon([(0, 366), (66, 322), (132, 358), (192, 330), (192, H), (0, H)],
              fill=PALETTE["hill2"])
    d.rounded_rectangle((L["band_x"] - 4, L["band_y"] - 6,
                         L["band_x"] + L["band_w"] + 4, L["band_y"] + L["band_h"] + 6),
                        radius=12, fill=PALETTE["panel"])
    for i, ch in enumerate(['0', '8', ':', '0', '0']):
        name = "mao.png" if ch == ":" else f"{ch}.png"
        g = Image.open(glyphs[name]).convert("RGBA")
        im.paste(g, (L["dx"][i], L["time_y"]), g)
    draw_band(d)
    f24 = pick(24)
    def centered(text, y, color):
        w = d.textlength(text, font=f24); d.text(((W - w) / 2, y), text, font=f24, fill=color)
    centered(L["name"], L["name_y"], PALETTE["white"])
    centered(L["ver"], L["ver_y"], PALETTE["white"])
    im = snap_palette(apply_capsule(im))
    im.save(out)
    return out


def check_preview_contrast(prev):
    """预览块 WCAG 断言：时间 44px+ ≥3:1，底部 24px ≥4.5:1。"""
    im = Image.open(prev).convert("RGB")
    def rl(rgb):
        def f(c):
            c /= 255.0
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])
    def cr(a, b):
        la, lb = rl(a), rl(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    pairs = [("时间 56px", PALETTE["amber"], PALETTE["bg"], 3.0),
             ("底部 24px", PALETTE["white"], PALETTE["hill2"], 4.5),
             ("版本号 24px", PALETTE["white"], PALETTE["hill2"], 4.5),
             ("彗星/轨道", PALETTE["comet"], PALETTE["track"], 3.0)]
    for label, fg, bg, need in pairs:
        v = cr(fg, bg)
        print(f"  预览对比度 {label:12s} {v:5.2f}:1  (需 >= {need})")
        assert v >= need, f"{label} 对比度不足"
    # 程序化确认四角确实被遮罩吃掉（不是直角矩形）
    px = im.load()
    for x, y in ((0, 0), (191, 0), (0, 489), (191, 489)):
        assert px[x, y] == PALETTE["corner"], f"预览 {x},{y} 不是胶囊圆角底色"


def check_contrast(bg_path):
    """真机照片背景逐行 WCAG 断言（RULES §3.4-8）。"""
    im = Image.open(bg_path).convert("RGB")
    def rl(rgb):
        def f(c):
            c /= 255.0
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = rgb
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    rows = [(100, 156, '时间56px', rl(AMBER), 3.0),
            (222, 282, '当前课44px', rl(C_MAIN), 3.0),
            (300, 368, '课程行24px', rl(C_DIM), 4.5),
            (376, 442, '底部24px', rl(C_MAIN), 4.5)]
    for y0, y1, label, Lt, need in rows:
        Lb = rl(tuple(ImageStat.Stat(im.crop((20, y0, 172, y1))).mean))
        cr = (max(Lt, Lb) + 0.05) / (min(Lt, Lb) + 0.05)
        print(f"  真机对比度 {label:12s} {cr:4.2f}:1  (需 >= {need})")
        assert cr >= need, f"{label} 对比度 {cr:.2f}:1 不足 {need}:1"


# ---------------------------------------------------------------------------
# 设备等效截图：只读成品包，按包内 lua 的 LAYOUT 常量渲染，杜绝「预览画一套」
# ---------------------------------------------------------------------------
def pkg_slot(im, name):
    coff, cs, _ = im.entries()[name]
    raw = bytes(im.data[coff:coff + cs])
    end = raw.find(b"IEND") + 8
    return raw[:end] if end >= 8 else raw


def render_device_view(face_path, out, hh=20, mm=46):
    im = FaceImage(face_path)
    lua = pkg_slot(im, SLOT + "daymatter.lua").decode("utf-8", "ignore")
    # 版式同源断言：包内常量必须等于构建器 LAYOUT
    for k, v in (("BAND_X", LAYOUT["band_x"]), ("BAND_Y", LAYOUT["band_y"]),
                 ("BAND_W", LAYOUT["band_w"]), ("NAME", LAYOUT["name"]),
                 ("VERSION", LAYOUT["ver"])):
        token = str(v) if k in ("BAND_X", "BAND_Y", "BAND_W") else f'"{v}"'
        assert token in lua, f"包内 lua 缺少同源常量 {k}={token}"
    dx = [int(v) for v in re.search(r"local DX = \{([^}]*)\}", lua).group(1).replace(" ", "").split(",")]
    df = re.findall(r'"([^"]+\.png)"', re.search(r"local DFILE = \{([^}]*)\}", lua).group(1))
    co = re.search(r'local COLON = "([^"]+)"', lua).group(1)
    y = int(re.search(r"dig\[i\] = img\(SCRIPT_PATH \.\. DFILE\[1\], DX\[i\], (\d+)\)", lua).group(1))
    canvas = Image.open(io.BytesIO(pkg_slot(im, SLOT + "bg9.png"))).convert("RGBA")
    for i, ch in enumerate([hh // 10, hh % 10, ":", mm // 10, mm % 10]):
        name = co if ch == ":" else df[ch]
        g = Image.open(io.BytesIO(pkg_slot(im, SLOT + name))).convert("RGBA")
        canvas.alpha_composite(g, (dx[i], y))
    d = ImageDraw.Draw(canvas)
    draw_band(d, phase=5, progress=0.86)
    f24, f44 = pick(24), pick(44)
    def centered(text, yy, font, color):
        w = d.textlength(text, font=font); d.text(((W - w) / 2, yy), text, font=font, fill=color)
    centered("无课", LAYOUT["cur_y"], f44, C_MAIN)
    centered("11月12日", LAYOUT["up_y"], f24, C_DIM)
    centered("周四", LAYOUT["dn_y"], f24, C_DIM)
    centered(LAYOUT["name"], LAYOUT["name_y"], f24, C_MAIN)
    centered(LAYOUT["ver"], LAYOUT["ver_y"], f24, C_MAIN)
    view = apply_capsule(canvas.convert("RGB"))
    view.resize((W * 2, H * 2), Image.NEAREST).save(out)
    return out


def showcase(preview_png, device_png, out):
    """2 联验收图：左=切换页立绘（成品包解码），右=设备等效渲染（成品包解码）。"""
    a = Image.open(preview_png).convert("RGB").resize((W * 2, H * 2), Image.NEAREST)
    b = Image.open(device_png).convert("RGB")
    gap, top, bottom = 28, 88, 74
    cw = W * 2 * 2 + gap * 3
    c = Image.new("RGB", (cw, top + H * 2 + bottom), (8, 13, 24)); d = ImageDraw.Draw(c)
    d.text((gap, 20), f'EVfSonoma v{VER} · 双通道同源验收', font=pick(24), fill=(242, 246, 255))
    d.text((gap, 54), '左：切换页立绘（包内 RLE 解码）   右：设备等效渲染（包内 lua 版式）',
           font=pick(16), fill=(150, 168, 196))
    c.paste(a, (gap, top)); c.paste(b, (gap * 2 + W * 2, top))
    d.text((gap, top + H * 2 + 16), '胶囊遮罩 / 扁平 9 色 / 无量化模糊 / 高对比',
           font=pick(16), fill=(150, 168, 196))
    d.text((gap, top + H * 2 + 42), 'set{x,w}+Timer 扫光 / 空数据兜底 / 底部两行出圆角区',
           font=pick(16), fill=(150, 168, 196))
    c.save(out); return out


def main():
    print("=== EV Sonoma 组包 v2 ===")
    bg = make_bg(); check_contrast(bg); lua_path = make_lua()
    lua_src = lua_path.read_text(encoding="utf-8")
    im = FaceImage(BASE)
    pw, ph, plen = im.preview_meta()
    assert (pw, ph) == (W, H)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td); glyphs = render_glyphs(tmp)
        png_slots = [(k, v[1]) for k, v in im.entries().items()
                     if k.startswith(SLOT) and k.endswith(".png")]
        free = [(k, c) for k, c in png_slots if k.split("/")[-1] in
                {f"{d}.png" for d in range(10)} | {"before_9.png", "later_9.png", "mao.png"}]
        pool = sorted(free, key=lambda x: x[1]); assign = {}
        for size, name, _ in sorted(((p.stat().st_size, n, p) for n, p in glyphs.items()), reverse=True):
            hit = next(((i, sl) for i, (sl, cap) in enumerate(pool) if cap >= size), None)
            if not hit: raise SystemExit(f"槽位不足：{name} {size}B")
            assign[name] = pool.pop(hit[0])[0]
        short = {n: a.split("/")[-1] for n, a in assign.items()}
        dig_map = ", ".join(f'"{short[f"{d}.png"]}"' for d in range(10))
        t = re.sub(r'local DFILE = \{[^}]*\}', f'local DFILE = {{ {dig_map} }}', lua_src, count=1)
        t = re.sub(r'local COLON = "[^"]*"', f'local COLON = "{short["mao.png"]}"', t, count=1)
        t = re.sub(r'local DX = \{[^}]*\}', 'local DX = { ' + ', '.join(str(v) for v in DX) + ' }', t, count=1)
        names = re.findall(r'"([^"]+\.png)"', re.search(r'local DFILE = \{([^}]*)\}', t).group(1))
        colon = re.search(r'local COLON = "([^"]+)"', t).group(1)
        assert len(names) == 10 and len(set(names)) == 10 and colon not in names
        for d in range(10): assert assign[f"{d}.png"] == SLOT + names[d]
        assert assign["mao.png"] == SLOT + colon
        used, cap = im.inject_resource(SLOT + "daymatter.lua", t.encode("utf-8"))
        print(f"  lua 注入 {used:6d} / {cap:6d} B")
        im.inject_resource(SLOT + "bg9.png", bg.read_bytes())
        cap_of = dict(free)
        for name, path in glyphs.items():
            im.inject_resource(assign[name], B.pad_png(path.read_bytes(), cap_of[assign[name]]))
        prev = tmp / "preview.png"; make_preview(glyphs, prev); check_preview_contrast(prev)
        px = Image.open(prev).convert("RGB").tobytes()
        assert len(px) == W * H * 3 and len(rle.encode(px)) <= plen - 8, "预览图过于复杂，压不进槽位"
        body = rle.encode_exact(px, plen - 8)
        assert rle.decode_px_count(body)[0] == W * H
        im.inject_preview(im.preview_header() + body)
        print(f"  预览块 {len(body)+8:6d} / {plen:6d} B  解码 {W*H}px 零剩余（扁平 9 色 + 胶囊遮罩）")
        for hh, mm in ((8, 0), (17, 15), (9, 5), (23, 59), (0, 0)):
            for i, ch in enumerate([hh // 10, hh % 10, ":", mm // 10, mm % 10]):
                nm = colon if ch == ":" else names[ch]
                want = glyphs["mao.png" if ch == ":" else f"{ch}.png"].read_bytes()
                off = im.entries()[SLOT + nm][0]
                assert bytes(im.data[off:off + len(want)]) == want, f"{hh:02d}:{mm:02d} 第{i+1}格错"
        print("  取槽自检  08:00 / 17:15 / 09:05 / 23:59 / 00:00 五格全命中")
    im.set_identity(FACE_ID, FACE_NAME)
    out = HERE / "dist" / "Band9" / f"Band9-Sonoma-v{VER}.face"
    size = im.save(out); print(f"\n出包 {out.name}  {size}B  id={FACE_ID}")

    # 回读成品包：预览块 + lua 全部以「包里实际是什么」为准
    chk = FaceImage(out); w2, h2, p2 = chk.preview_meta()
    b2 = bytes(chk.data[chk.tail + 20:chk.tail + 20 + p2 - 8])
    assert (w2, h2) == (W, H) and rle.decode_px_count(b2)[0] == W * H
    final = pkg_slot(chk, SLOT + "daymatter.lua").decode("utf8", "ignore")
    assert "ev_sonoma_anim" in final and "comet:set { x" in final
    for bad in ("EV课程表", "systemStatusBattery", "set { bg_color", "请开课程表"):
        assert bad not in final, f"包内 lua 仍含 {bad}"
    ppx = rle.decode(b2, blksize=3)
    prev_png = HERE / "docs" / "design" / f"EV-Sonoma-切换页立绘-v{VER}.png"
    prev_png.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGB", (W, H), ppx[:W * H * 3]).save(prev_png)
    dev_png = HERE / "docs" / "design" / f"EV-Sonoma-设备等效-v{VER}.png"
    render_device_view(out, dev_png)
    shot = HERE / "docs" / "design" / f"EV-Sonoma-双通道验收-v{VER}.png"
    showcase(prev_png, dev_png, shot)
    print(f"  回读自检  ✓ 预览 {w2}x{h2}/{W*H}px  ✓ lua 同源  ✓ 立绘 {prev_png.name}")
    print(f"  验收图   {shot.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
