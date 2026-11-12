-- EVfSonoma v1.1.0 · 照片背景课程表盘（Daymatter 壳）
-- 版式（ev-six v5 合规）：图片数字时间 / 环形刻度进度 / 当前课44px / 上下节课24px
local lvgl = require("lvgl")
local W, H = lvgl.HOR_RES(), lvgl.VER_RES()
local VERSION = "v1.1.0"

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
local F24 = F(24)
local F44 = F(44)

local C_MAIN = 0xEEF4FF
local C_STAT = 0x7FD8BC
local C_DIM  = 0x9BA6C4
local C_LO   = 0x5A6488

-- ---------- 场景骨架（长按事件必须上抛，否则进不去切换页）----------
local scr = lvgl.Object(nil, {
    w = W, h = H, bg_opa = 0, border_width = 0, pad_all = 0,
})
scr:clear_flag(lvgl.FLAG.SCROLLABLE)
scr:add_flag(lvgl.FLAG.EVENT_BUBBLE)

local function img(path, x, y)
    local w = scr:Image { src = path, x = x, y = y }
    w:clear_flag(lvgl.FLAG.SCROLLABLE)
    w:add_flag(lvgl.FLAG.EVENT_BUBBLE)
    return w
end
local function label(y, h, font, color, text)
    return lvgl.Label(scr, {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
        align = { type = lvgl.ALIGN.TOP_MID, x_ofs = 0, y_ofs = y },
    })
end

-- 背景（整屏插画，assets/bg9.png）
img(SCRIPT_PATH .. "bg9.png", 0, 0)

-- 时间：5 张图片数字（34x72，等宽步进 34，居中 x0=11）
local DX = { 11, 45, 79, 113, 147 }
local DFILE = { "0.png","1.png","2.png","3.png","4.png","5.png","6.png","7.png","8.png","9.png" }
-- 冒号单独一个常量：组包时槽位是动态分配的，它和 DFILE 里的槽名可能互换，
-- 绝不能用「全局替换 mao.png」的办法改名（v1.0.19 就是这么把数字 5 换成冒号的）
local COLON = "mao.png"
local dig = {}
for i = 1, 5 do dig[i] = img(SCRIPT_PATH .. DFILE[1], DX[i], 52) end

-- 课程层（y 按 192x490 版式实排）
local l_stat = label(180, 34, F24, C_STAT, "")
local l_cur  = label(252, 60, F44, C_MAIN, "")
local l_up   = label(356, 32, F24, C_DIM, "")
local l_dn   = label(398, 32, F24, C_DIM, "")
local l_ver  = label(436, 30, F24, C_LO, VERSION)

pcall(function()
    local dataman = require("dataman")
    dataman.subscribe("systemStatusBattery", l_ver, function(obj, encoded)
        local lvl = encoded // 256
        if type(lvl) ~= "number" or lvl < 0 or lvl > 100 then return end
        obj:set { text = lvl .. "%  " .. VERSION }
    end)
end)

local function two(n) return (n < 10) and ("0" .. n) or tostring(n) end
local function hms(mins) return two(mins // 60) .. ":" .. two(mins % 60) end

local sig_cache = "#none"
local last_min = -1

local function rows3()
    local t = os.date("*t", os.time())
    local mins = (t.hour or 0) * 60 + (t.min or 0)
    local day = (t.wday or 1) == 1 and 7 or (t.wday - 1)
    local list = schedule[day] or {}
    local prev, cur, nxt = nil, nil, nil
    for _, c in ipairs(list) do
        if c.start <= mins and mins < c.finish then cur = c end
        if c.finish <= mins then prev = c end
        if c.start > mins and not nxt then nxt = c end
    end
    if cur then
        _G.ev_in_class = true
        _G.ev_progress = math.max(0, math.min(1, (mins - cur.start) / math.max(1, cur.finish - cur.start)))
    else
        _G.ev_in_class = false
        _G.ev_progress = 0
    end
    -- 状态块（24px，底色区域已压进背景图）
    if cur then l_stat:set { text = "", text_color = C_STAT }
    elseif nxt then
        if nxt.start - mins <= 15 then l_stat:set { text = "即将上课", text_color = 0xEF9F27 }
        else l_stat:set { text = "课间休息", text_color = C_STAT } end
    elseif #list > 0 then l_stat:set { text = "", text_color = C_DIM }
    else l_stat:set { text = "今日无课", text_color = C_DIM } end
    -- 当前课 44px（无课则显示下节或占位）
    local main = cur and cur.name or (nxt and nxt.name) or ""
    l_cur:set { text = cut(main, 3) }
    -- 上 / 下节课（24px，≤6P："上 语文 08:00"）
    l_up:set { text = prev and ("上 " .. cut(prev.name, 3) .. " " .. hms(prev.start)) or "" }
    l_dn:set { text = nxt and ("下 " .. cut(nxt.name, 3) .. " " .. hms(nxt.start)) or "" }
end


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

local function refresh()
    local t = os.date("*t", os.time())
    local h, m = t.hour or 0, t.min or 0
    if m ~= last_min then
        last_min = m
        local hs = two(h); local ms = two(m)
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
        _G.ev_apply_progress()
        if not text then l_up:set { text = "" }; l_dn:set { text = "请开课程表" } end
    end)
    if not ok then
        l_stat:set { text = "" }
        l_cur:set { text = "数据未就绪" }
        l_up:set { text = "" }; l_dn:set { text = "" }
    end
end

function ScreenStateChangedCB(pre, now, reason)
    _G.ev_screen_on = (now == "ON")
    if now == "ON" then refresh() end
end
pcall(function()
    _G.ev_aurora_timer = lvgl.Timer { period = 10000, cb = function() refresh() end }
    _G.ev_sonoma_anim = lvgl.Timer { period = 500, cb = function() _G.ev_tick_anim() end }
end)
_G.ev_screen_on = true
refresh()
print("EV_SONOMA_V1", W, H, VERSION, "courses=" .. course_count)
