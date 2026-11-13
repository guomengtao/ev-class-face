-- EV 石英 v5 · 巨型分体时间 + 周几月日 / 上课信息（科目·状态·下节）
-- v5: 修两处硬伤 —— 补 EVENT_BUBBLE（长按进不去切换页）、全表字号提到 24-44（原来 14-20 真机上看不见）
-- v6: 加「背景开关」测试版 —— 双击表盘切换 采用课表背景 / 用本表盘默认纯黑。
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
-- 表盘逻辑只有一份，坐标与字号全部来自这里，源码不写死任何屏幕尺寸。
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
local C_BG    = 0x000000          -- 纯黑（用户 2026-11-11 定：三款表盘底色统一纯黑）
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
    border_width = 0, pad_all = 0, radius = 0,
})
scr:clear_flag(lvgl.FLAG.SCROLLABLE)
-- 关键：不加上抛，触摸事件止于本层，系统收不到长按 → 进不了表盘切换页。
scr:add_flag(lvgl.FLAG.EVENT_BUBBLE)

-- ---------- 背景开关（测试版，仅 EV 石英；状态存在表盘自己这边） ----------
-- 约定：全局只有一份 bg.png / cfg.txt，本表盘自己决定是否采用；
-- 不采用就完全保持纯黑底，与旧版逐像素一致。
-- 状态文件用 /tmp（历史 THEME_FILE 与探针档同目录，已实证表盘可写）；
-- 文件名自带表盘标识，不依赖系统分配的表盘 ID，中心侧无需维护任何名单。
local SW_FILE = "/tmp/ev_bg_clock.txt"
local BG_DIRS = {
    "/data/quickapp/files/com.application.watch.classschedule/",
    "/data/quickapp/files/",
    "/tmp/",
}
local PNG_SIG = "\137PNG\r\n\26\n"
local function is_png(p)
    local ok, f = pcall(io.open, p, "rb")
    if not ok or not f then return false end
    local h = nil
    pcall(function() h = f:read(8) end)
    pcall(function() f:close() end)
    return h == PNG_SIG
end
local function bg_find()
    for _, d in ipairs(BG_DIRS) do
        local p = d .. "bg.png"
        if is_png(p) then return p end
    end
    return nil
end
local function sw_load()
    local ok, f = pcall(io.open, SW_FILE, "r")
    if not ok or not f then return 0 end
    local s = nil
    pcall(function() s = f:read(1) end)
    pcall(function() f:close() end)
    return s == "1" and 1 or 0
end
local function sw_save(v)
    pcall(function()
        local f = io.open(SW_FILE, "w")
        if f then f:write(v == 1 and "1" or "0"); f:close() end
    end)
end

local bg_path = bg_find()
local bg_on = (sw_load() == 1) and (bg_path ~= nil)
local batt_txt = ""
local function ver_line()
    return VERSION .. (batt_txt ~= "" and ("  " .. batt_txt) or "")
           .. (bg_on and "  BG开" or "  BG关")
end
local bg_img, bg_dim = nil, nil
pcall(function()
    bg_img = scr:Image {
        src = bg_path or (BG_DIRS[1] .. "bg.png"),
        x = 0, y = 0, w = W, h = H,
    }
    if bg_img then
        bg_img:clear_flag(lvgl.FLAG.SCROLLABLE)
        bg_img:add_flag(lvgl.FLAG.EVENT_BUBBLE)
        -- 图片默认 CLICKABLE 会吃掉长按，必须清掉
        pcall(function() bg_img:clear_flag(lvgl.FLAG.CLICKABLE) end)
        if not bg_on then pcall(function() bg_img:add_flag(lvgl.FLAG.HIDDEN) end) end
    end
    bg_dim = lvgl.Object(scr, {
        w = W, h = H, x = 0, y = 0,
        bg_color = 0x000000,
        bg_opa = bg_on and lvgl.OPA(45) or lvgl.OPA(0),
        border_width = 0, radius = 0, pad_all = 0,
    })
    if bg_dim then
        pcall(function() bg_dim:clear_flag(lvgl.FLAG.CLICKABLE) end)
        pcall(function() bg_dim:add_flag(lvgl.FLAG.EVENT_BUBBLE) end)
    end
end)

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
local l_hh   = label(P.y_hh, P.h_hh, FONT_BIG, C_HH, "--")
local l_mm   = label(P.y_mm, P.h_mm, FONT_BIG, C_MM, "--")
local l_subj = label(P.y_c_subj, P.h_c_subj, FONT_SUBJ, C_HH, "读取课表中")
local l_stat = label(P.y_c_stat, P.h_c_stat, FONT_STAT, C_WDAY, "")
local l_next = label(P.y_c_next, P.h_c_next, FONT_NEXT, C_HINT, "")
local l_ver  = label(P.y_version, P.h_version, FONT_VER, C_DIM, ver_line())

-- 电量角标：做法照抄 Monika —— dataman.subscribe("systemStatusBattery")，值需 //256。
-- 版本号行同时承载「背景开/关」状态，不额外占槽位。
pcall(function()
    local dataman = require("dataman")
    dataman.subscribe("systemStatusBattery", l_ver, function(obj, encoded)
        local lvl = encoded // 256
        if type(lvl) ~= "number" or lvl < 0 or lvl > 100 then return end
        batt_txt = lvl .. "%"
        obj:set { text = ver_line() }
    end)
end)

local WD = { "周日", "周一", "周二", "周三", "周四", "周五", "周六" }
local function two(n) return (n < 10) and ("0" .. n) or tostring(n) end

local sig_cache = "#none"

local function refresh()
    local t = os.date("*t", os.time())
    l_hh:set { text = two(t.hour) }
    l_mm:set { text = two(t.min) }
    l_wday:set { text = string.format("%s  %d月%d日", WD[(t.wday or 1)] or "—",
                                      t.month or 1, t.day or 1) }

    -- 上课信息：与 class 表盘共用同一份数据层与状态机。
    -- 整段 pcall：真机上一次文件读取异常 / 课表格式意外，都不该把表盘拖黑
    -- （表盘一崩，长按切换也不响应，表现就是「长按没反应」）。
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

-- ---------- 开关交互：双击（单次轻触保持无操作，避免抬腕误触） ----------
local function bg_apply()
    pcall(function()
        if bg_on then
            bg_img:set { src = bg_path }
            pcall(function() bg_img:clear_flag(lvgl.FLAG.HIDDEN) end)
            bg_dim:set { bg_opa = lvgl.OPA(45) }
        else
            pcall(function() bg_img:add_flag(lvgl.FLAG.HIDDEN) end)
            bg_dim:set { bg_opa = lvgl.OPA(0) }
        end
    end)
    l_ver:set { text = ver_line() }
end
local function bg_sync()
    if not bg_on then return end
    local p = bg_find()
    if p and p ~= bg_path then
        bg_path = p
        pcall(function() bg_img:set { src = p } end)
    end
end
local last_tap = -10
scr:onevent(lvgl.EVENT.CLICKED, function()
    local t = os.time()
    if t - last_tap > 1 then last_tap = t; return end
    last_tap = -10
    local next_on = not bg_on
    if next_on then
        local p = bg_find()
        if p then bg_path = p else next_on = false end
    end
    if next_on == bg_on then return end
    bg_on = next_on
    sw_save(bg_on and 1 or 0)
    bg_apply()
end)

function ScreenStateChangedCB(pre, now, reason)
    if now == "ON" then bg_sync() refresh() end
end
pcall(function()
    _G.ev_clock_timer = lvgl.Timer { period = 10000, cb = function() refresh() end }
end)

refresh()
print("EV_QUARTZ_V6", W, H, VERSION, "courses=" .. course_count,
      "bg=" .. tostring(bg_on), "path=" .. tostring(bg_path))
