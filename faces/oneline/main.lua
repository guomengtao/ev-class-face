-- EV 一行 v1 · 单行超大时间(HH:MM) + 日期 + 课程(科目·状态·下节) + 电量版本
-- 与 class(信息面板)/clock(分体暖色石英)/analog(方块指针) 刻意拉开：
--   纯黑底 + 一行 64px 巨型时间 + 青色日期 + 底部课程条，极简无分割线。
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
local P = {}
-- @@PROFILE_END@@

local VERSION = "v1.0.0"

local FONT_TIME = F(64, B.MONTSERRAT_32 or B.MONTSERRAT_14)
local FONT_DATE = F(20, B.MONTSERRAT_14)
local FONT_SUBJ = F(22, B.MONTSERRAT_14)
local FONT_STAT = F(18, B.MONTSERRAT_14)
local FONT_NEXT = F(16, B.MONTSERRAT_14)
local FONT_VER  = F(16, B.MONTSERRAT_14)

-- ---------- 配色：纯黑底 + 白时间 + 青日期 + 琥珀状态 ----------
local C_BG    = 0x0B0C0F
local C_TIME  = 0xF4F6FA
local C_DATE  = 0x7FD4FF
local C_SUBJ  = 0xF4F6FA
local C_STAT  = 0xFFB347
local C_HINT  = 0x8A93A6
local C_DIM   = 0x4A5160

-- @@INCLUDE:schedule_core@@

local ATM, ATL = nil, nil
pcall(function() ATM = lvgl.ALIGN.TOP_MID end)
pcall(function() ATL = lvgl.ALIGN.TOP_LEFT end)

local scr = lvgl.Object(nil, {
    w = W, h = H, x = 0, y = 0,
    bg_color = C_BG, bg_opa = lvgl.OPA(100),
    border_width = 0, pad_all = 0, radius = 0,
})
scr:clear_flag(lvgl.FLAG.SCROLLABLE)
-- 关键：不加上抛，触摸事件止于本层，系统收不到长按 → 进不了表盘切换页。
scr:add_flag(lvgl.FLAG.EVENT_BUBBLE)

local function label(y, h, font, color, text)
    local p = {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
    }
    if ATM then p.align = { type = ATM, x_ofs = 0, y_ofs = y } else p.x, p.y = 0, y end
    return lvgl.Label(scr, p)
end

-- ---------- UI 布局 ----------
local l_time = label(148, 72, FONT_TIME, C_TIME, "--:--")   -- 单行超大 HH:MM
local l_date = label(232, 26, FONT_DATE, C_DATE, "—")
local l_subj = label(286, 26, FONT_SUBJ, C_SUBJ, "读取课表中")
local l_stat = label(316, 22, FONT_STAT, C_STAT, "")
local l_next = label(344, 20, FONT_NEXT, C_HINT, "")
local l_ver  = label(376, 18, FONT_VER, C_DIM, VERSION)

-- 电量：做法照抄 Monika —— dataman.subscribe("systemStatusBattery")，值需 //256。
-- 并进版本号那一行："EV OneLine v1.0.1  78%"，天然居中、不挤占。
pcall(function()
    local dataman = require("dataman")
    dataman.subscribe("systemStatusBattery", l_ver, function(obj, encoded)
        local lvl = encoded // 256
        if type(lvl) ~= "number" or lvl < 0 or lvl > 100 then return end
        obj:set { text = VERSION .. "  " .. lvl .. "%" }
    end)
end)

local WD = { "周日", "周一", "周二", "周三", "周四", "周五", "周六" }
local function two(n) return (n < 10) and ("0" .. n) or tostring(n) end

local sig_cache = "#none"

local function refresh()
    local t = os.date("*t", os.time())
    l_time:set { text = two(t.hour) .. ":" .. two(t.min) }
    l_date:set { text = string.format("%s  %d月%d日", WD[(t.wday or 1)] or "—",
                                      t.month or 1, t.day or 1) }

    -- 上课信息：与 class / clock 共用同一份数据层与状态机。整段 pcall 隔离文件异常。
    local ok = pcall(function()
        local text = read_shared()
        local sig = text or "#none"
        if sig ~= sig_cache then parse_schedule(text); sig_cache = sig end
        local s = compute() or {}
        l_subj:set { text = cut(s.subject or "EV课程表", 6) }
        l_stat:set { text = cut(s.status or "", 7) }
        if not text then l_next:set { text = "请开课程表" }
        elseif (s.next or "") == "" then l_next:set { text = "" }
        else l_next:set { text = cut(s.next, 8) } end
    end)
    if not ok then
        l_subj:set { text = "EV课程表" }
        l_stat:set { text = "数据未就绪" }
        l_next:set { text = "" }
    end
end

function ScreenStateChangedCB(pre, now, reason)
    if now == "ON" then refresh() end
end
pcall(function()
    _G.ev_oneline_timer = lvgl.Timer { period = 10000, cb = function() refresh() end }
end)

refresh()
print("EV_ONELINE_V1", W, H, VERSION, "courses=" .. course_count)
