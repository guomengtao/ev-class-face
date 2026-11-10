-- EV 石英 v4 · 巨型分体时间 + 周几 / 月日 / 电量图标 / 上课信息（科目·状态·下节）
-- 设计取向与 class 表盘刻意拉开距离：
--   class = 信息面板（多行小字、冷青强调、课程进度条）
--   clock = 石英挂钟（超大字重、上下分体数字、暖白/琥珀双色、细分割线、无卡片）
-- 课程表数据层由 build.py 从 shared/lua/schedule_core.lua 注入，不在此重复实现。
local lvgl = require("lvgl")
local W, H = lvgl.HOR_RES(), lvgl.VER_RES()

local B = lvgl.BUILTIN_FONT
local function F(size, fallback)
    local ok, f = pcall(lvgl.Font, "MiSans-Demibold", size, "normal")
    if ok and f then return f end
    ok, f = pcall(lvgl.Font, "MiSans-Regular", size)
    if ok and f then return f end
    return fallback
end
-- @@PROFILE_BEGIN@@
-- 机型 profile：构建时由 build.py 按 devices/<device>.json 整块替换。
local P = {
  safe_top = 96, safe_bottom = 394,
  f_wday = 16, f_mday = 16, f_big = 50, f_csubj = 20, f_cstat = 16,
  f_cnext = 14, f_batt = 14, f_version = 16,
  y_wday = 100, h_wday = 20,
  y_mday = 122, h_mday = 20,
  y_div = 154, w_div = 56, h_div = 2,
  y_hh = 166, h_hh = 54,
  y_mm = 224, h_mm = 54,
  y_c_subj = 288, h_c_subj = 22,
  y_c_stat = 314, h_c_stat = 18,
  y_c_next = 340, h_c_next = 16,
  y_version = 376, h_version = 18,
}
-- @@PROFILE_END@@

local VERSION = "v1.0.0"

local FONT_WDAY = F(P.f_wday, B.MONTSERRAT_14)
local FONT_MDAY = F(P.f_mday, B.MONTSERRAT_14)
local FONT_BIG  = F(P.f_big, B.MONTSERRAT_32 or B.MONTSERRAT_14)
local FONT_SUBJ = F(P.f_csubj, B.MONTSERRAT_14)
local FONT_STAT = F(P.f_cstat, B.MONTSERRAT_14)
local FONT_NEXT = F(P.f_cnext, B.MONTSERRAT_14)
local FONT_BATT = F(P.f_batt, B.MONTSERRAT_14)
local FONT_VER  = F(P.f_version, B.MONTSERRAT_14)

-- ---------- 配色：石墨黑底 + 暖白小时 + 琥珀分钟 ----------
local C_BG    = 0x0E0F12
local C_HH    = 0xFFF6E8
local C_MM    = 0xFFB347
local C_WDAY  = 0x7FD4FF
local C_HINT  = 0x8A93A6
local C_DIV   = 0x2A2F3A
local C_DIM   = 0x4A5160

-- @@INCLUDE:schedule_core@@

local ATM, ATL = nil, nil
pcall(function() ATM = lvgl.ALIGN.TOP_MID end)
pcall(function() ATL = lvgl.ALIGN.TOP_LEFT end)

local scr = lvgl.Object(nil, {
    w = W, h = H, x = 0, y = 0,
    bg_color = C_BG, bg_opa = lvgl.OPA(100),
    border_width = 0, pad_all = 0,
})
scr:clear_flag(lvgl.FLAG.SCROLLABLE)

local function label(y, h, font, color, text)
    local p = {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
    }
    if ATM then p.align = { type = ATM, x_ofs = 0, y_ofs = y } else p.x, p.y = 0, y end
    return lvgl.Label(scr, p)
end
-- 角标用：左上角绝对定位
local function label_at(x, y, h, font, color, text)
    local p = {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
    }
    if ATL then p.align = { type = ATL, x_ofs = x, y_ofs = y } else p.x, p.y = x, y end
    return lvgl.Label(scr, p)
end
local function place(o, x, y)
    if ATL then o:set { align = { type = ATL, x_ofs = x, y_ofs = y } }
    else o:set { x = x, y = y } end
end

local l_wday = label(P.y_wday, P.h_wday, FONT_WDAY, C_WDAY, "—")
local l_mday = label(P.y_mday, P.h_mday, FONT_MDAY, C_HINT, "—")
local l_hh   = label(P.y_hh, P.h_hh, FONT_BIG, C_HH, "--")
local l_mm   = label(P.y_mm, P.h_mm, FONT_BIG, C_MM, "--")
local l_subj = label(P.y_c_subj, P.h_c_subj, FONT_SUBJ, C_HH, "读取课表中")
local l_stat = label(P.y_c_stat, P.h_c_stat, FONT_STAT, C_WDAY, "")
local l_next = label(P.y_c_next, P.h_c_next, FONT_NEXT, C_HINT, "")
local l_ver  = label(P.y_version, P.h_version, FONT_VER, C_DIM, VERSION)

-- ---------- 分割线 ----------
local DIV_W, DIV_H = P.w_div, math.max(1, P.h_div)
pcall(function()
    local div = lvgl.Object(scr, {
        w = DIV_W, h = DIV_H, bg_color = C_DIV, bg_opa = lvgl.OPA(100),
        border_width = 0, radius = 0,
    })
    place(div, math.floor((W - DIV_W) / 2), P.y_div)
end)

local WD = { "周日", "周一", "周二", "周三", "周四", "周五", "周六" }
local function two(n) return (n < 10) and ("0" .. n) or tostring(n) end

local sig_cache = "#none"

local function refresh()
    local t = os.date("*t", os.time())
    l_hh:set { text = two(t.hour) }
    l_mm:set { text = two(t.min) }
    l_wday:set { text = WD[(t.wday or 1)] or "—" }
    l_mday:set { text = string.format("%d月%d日", t.month or 1, t.day or 1) }

    -- 上课信息：与 class 表盘共用同一份数据层与状态机
    local text = read_shared()
    local sig = text or "#none"
    if sig ~= sig_cache then parse_schedule(text); sig_cache = sig end
    local s = compute()
    l_subj:set { text = cut(s.subject, 6) }
    l_stat:set { text = cut(s.status or "", 7) }
    if not text then l_next:set { text = "请开课程表" }
    elseif (s.next or "") == "" then l_next:set { text = "" }
    else l_next:set { text = cut(s.next, 8) } end

end

function ScreenStateChangedCB(pre, now, reason)
    if now == "ON" then refresh() end
end
pcall(function()
    _G.ev_clock_timer = lvgl.Timer { period = 10000, cb = function() refresh() end }
end)

refresh()
print("EV_QUARTZ_V4", W, H, VERSION, "courses=" .. course_count)
