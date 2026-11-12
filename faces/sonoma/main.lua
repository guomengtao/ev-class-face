-- EVfSonoma v1.2.0 · 照片背景课程表盘（Daymatter 壳）
-- 版式（ev-six v5 合规）：图片数字时间 / 上课中状态块 / 当前课44px / 上下节课24px
local lvgl = require("lvgl")
local W, H = lvgl.HOR_RES(), lvgl.VER_RES()
local VERSION = "v1.2.0"

-- ===== 课程表数据层（内联自 shared/lua/schedule_core.lua，裁剪只读路径版）=====
local PKG = "com.application.watch.classschedule"
local QDIR = "/data/quickapp/files/" .. PKG .. "/"
local CANDIDATES = {
    QDIR .. "class.txt", QDIR .. "files/class.txt", QDIR .. "internal/files/class.txt",
    "/data/quickapp/files/class.txt", "/data/user/0/" .. PKG .. "/files/class.txt",
    "/data/data/" .. PKG .. "/files/class.txt", QDIR .. "cache/class.txt",
    "/data/quickapp/files/ev/class.txt",
    "/data/quickapp/system/" .. PKG .. "/usr.db", "/data/quickapp/system/" .. PKG .. "/usr.db.backup",
}
local PROBE_DIRS = { "/tmp/", "/data/app/watchface/market/882610317/", "/data/app/watchface/market/882610316/", QDIR }
local schedule = {}
for d = 1, 7 do schedule[d] = {} end
local last_signature, course_count = "", 0
local probe_dir = nil
local function chars(s)
    local t = {}
    for c in tostring(s or ""):gmatch("[%z\1-\127\194-\244][\128-\191]*") do t[#t + 1] = c end
    return t
end
local function cut(s, n)
    local t = chars(s)
    if #t <= n then return table.concat(t) end
    return table.concat(t, "", 1, n)
end
local function hm(s)
    if not s then return nil end
    local h, m = s:match("^(%d%d?):(%d%d)$")
    h, m = tonumber(h), tonumber(m)
    if not h or not m then return nil end
    return h * 60 + m
end
local DAYCN = { ["星期一"]=1, ["星期二"]=2, ["星期三"]=3, ["星期四"]=4, ["星期五"]=5, ["星期六"]=6, ["星期日"]=7, ["星期天"]=7 }
local function add_course(day, name, st, en)
    if not day or day < 1 or day > 7 or not name or not st or not en or en <= st then return end
    local l = schedule[day]
    l[#l + 1] = { name = name, start = st, finish = en }
    course_count = course_count + 1
end
local function split_range(tr)
    if not tr then return nil end
    local hs, ms, he, me = tr:match("(%d%d?):(%d%d)%s*%-%s*(%d%d?):(%d%d)")
    if not hs then return nil end
    return tonumber(hs) * 60 + tonumber(ms), tonumber(he) * 60 + tonumber(me)
end
local function parse_schedule(text)
    for d = 1, 7 do schedule[d] = {} end
    course_count = 0
    if not text then return end
    for obj in text:gmatch("%b{}") do
        local day = tonumber(obj:match('"day"%s*:%s*(%d+)') or "")
        if day then
            local name = obj:match('"name"%s*:%s*"(.-)"')
            local st = hm(obj:match('"start"%s*:%s*"(.-)"') or "")
            local en = hm(obj:match('"end"%s*:%s*"(.-)"') or "")
            add_course(day, name, st, en)
        end
    end
    if course_count == 0 then
        for gday, body in text:gmatch('"day"%s*:%s*"([^"]+)"%s*,%s*"classes"%s*:%s*%[(.-)%]') do
            local di = DAYCN[gday] or tonumber(gday)
            if di and #schedule[di] == 0 then
                for obj in body:gmatch("%b{}") do
                    local name = obj:match('"name"%s*:%s*"(.-)"')
                    local st, en = split_range(obj:match('"time"%s*:%s*"([^"]*)"'))
                    add_course(di, name, st, en)
                end
            end
        end
    end
    for d = 1, 7 do table.sort(schedule[d], function(a, b) return a.start < b.start end) end
end
local function find_probe_dir()
    if probe_dir then return probe_dir end
    for _, d in ipairs(PROBE_DIRS) do
        local p = d .. "ev_probe.txt"
        pcall(function() os.execute('echo EV_PROBE_OK > "' .. p .. '"') end)
        local f = io.open(p, "r")
        if f then
            local t = f:read("*a") or ""
            f:close()
            if t:find("EV_PROBE_OK") then probe_dir = d; return d end
        end
    end
    return nil
end
local function copy_to_tmp(src, tmp)
    pcall(function() os.execute('cat "' .. src .. '" > "' .. tmp .. '"') end)
    local f = io.open(tmp, "r")
    if not f then return nil end
    local t = f:read("*a") or ""
    f:close()
    if t == "" then return nil end
    return t
end
local function read_shared()
    local d = find_probe_dir()
    if not d then return nil end
    local tmp = d .. "ev_class.tmp"
    for _, src in ipairs(CANDIDATES) do
        local t = copy_to_tmp(src, tmp)
        if t then return t end
    end
    if not _G.ev_find_done then
        _G.ev_find_done = true
        local out = d .. "ev_find.txt"
        pcall(function() os.execute('find /data /sdcard -name "class*.txt" > "' .. out .. '"') end)
        local f = io.open(out, "r")
        if f then
            for line in f:lines() do
                if line:sub(1, 1) == "/" and line:find("class") then
                    local t = copy_to_tmp(line, tmp)
                    if t then return t end
                end
            end
            f:close()
        end
    end
    return nil
end
-- ===== 数据层结束 =====

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
for i = 1, 5 do dig[i] = img(SCRIPT_PATH .. DFILE[1], DX[i], 100) end

-- ---------- 进度/流光带：只用 faces/class 生产盘已实证的 API ----------
-- lvgl.Object 构造 + set{x} / set{w} + lvgl.Timer；不碰 set{bg_color/bg_opa}。
-- 静态轨道 + 课程完成度填充 + 一颗来回扫的高亮彗星，永远在动、永远看得见。
local BAND_X, BAND_Y, BAND_W, BAND_H = 12, 176, 168, 16
local COMET_W, ANIM_STEPS = 30, 12
local track, fill, comet
pcall(function()
    track = passive(lvgl.Object(scr, { x = BAND_X, y = BAND_Y, w = BAND_W, h = BAND_H,
        bg_color = 0x1C304E, bg_opa = 255, border_width = 0, radius = 8 }))
    fill = passive(lvgl.Object(scr, { x = BAND_X, y = BAND_Y, w = 8, h = BAND_H,
        bg_color = 0xF0A32B, bg_opa = 255, border_width = 0, radius = 8 }))
    comet = passive(lvgl.Object(scr, { x = BAND_X, y = BAND_Y, w = COMET_W, h = BAND_H,
        bg_color = 0xFFF0CD, bg_opa = 255, border_width = 0, radius = 8 }))
end)

local l_cur  = label(222, 60, F44, C_MAIN, "")
local l_up   = label(300, 32, F24, C_DIM, "")
local l_dn   = label(336, 32, F24, C_DIM, "")
-- RULES §2：底部两行独立，24px，上移出圆角禁放区；电量不进底部
local l_name = label(376, 32, F24, C_MAIN, "EVfSonoma")
local l_ver  = label(410, 32, F24, C_MAIN, "v1.2.0")

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
