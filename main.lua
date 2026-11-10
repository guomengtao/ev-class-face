-- EV 课程提醒表盘 v4 · 小米手环 9 跑道屏 192x490
-- v4: 12小时制 / MiSans-Demibold 加粗 / 时间自适应宽度 TOP_MID 居中 /
--     每行<=6字 / 字号 44-30-28-24-22 / 双行短码诊断 / 多候选路径 + 写端回执探针
-- 数据链路见 数据联动与大圈回归-详细排查方案-20261110.md
local lvgl = require("lvgl")
local W, H = lvgl.HOR_RES(), lvgl.VER_RES()

-- ---------- 共享文件：多候选路径，消除 internal://files 物理映射不确定性 ----------
local PKG = "com.application.watch.classschedule"
local QDIR = "/data/quickapp/files/" .. PKG .. "/"
local CANDIDATES = {
    QDIR .. "class.txt",                                   -- P1 Var 同款
    QDIR .. "files/class.txt",                             -- P2
    QDIR .. "internal/files/class.txt",                    -- P3
    "/data/quickapp/files/class.txt",                      -- P4
    "/data/user/0/" .. PKG .. "/files/class.txt",          -- P5
    "/data/data/" .. PKG .. "/files/class.txt",            -- P6
    QDIR .. "cache/class.txt",                             -- P7
    "/data/quickapp/files/ev/class.txt",                   -- P8 快应用侧备用 URI
    "/data/quickapp/system/" .. PKG .. "/usr.db",          -- P9 storage 原始库（写端失灵时直读）
    "/data/quickapp/system/" .. PKG .. "/usr.db.backup",   -- P10
}
local PROBE_DIRS = {
    "/tmp/",
    "/data/app/watchface/market/882610317/",
    "/data/app/watchface/market/882610316/",
    QDIR,
}
local THEME_FILE = "/tmp/ev_face_theme.txt"

-- ---------- 配色（轻触切换） ----------
local THEMES = {
    { name = "深海蓝", bg = 0x0B2036, time = 0xFFFFFF, accent = 0x7FD4FF, sub = 0xFFD479, hint = 0x8FB4D4 },
    { name = "暮光紫", bg = 0x1A1030, time = 0xFFE9A8, accent = 0xD9A8FF, sub = 0x9BE8B0, hint = 0xBCA6DC },
    { name = "松林绿", bg = 0x10241C, time = 0xE8FFF0, accent = 0x8FE3B0, sub = 0xFFC98F, hint = 0x9FC4AC },
    { name = "暖霞橙", bg = 0x241414, time = 0xFFF0E8, accent = 0xFF9E8F, sub = 0xFFD98F, hint = 0xDCAFA4 },
}
local theme_idx = 1

-- ---------- 字体：官方 Band9 实证的粗体 MiSans-Demibold ----------
local B = lvgl.BUILTIN_FONT
local function F(size, fallback)
    local ok, f = pcall(lvgl.Font, "MiSans-Demibold", size, "normal")
    if ok and f then return f end
    ok, f = pcall(lvgl.Font, "MiSans-Regular", size)
    if ok and f then return f end
    return fallback
end
local FONT_TIME = F(44, B.MONTSERRAT_32 or B.MONTSERRAT_14)
local FONT_SUBJ = F(30, B.MONTSERRAT_32 or B.MONTSERRAT_14)
local FONT_STAT = F(28, B.MONTSERRAT_24 or B.MONTSERRAT_14)
local FONT_BODY = F(24, B.MONTSERRAT_14)
local FONT_INFO = F(24, B.MONTSERRAT_14)   -- 诊断行也放大到 24，之前 22 在真机上偏小
local FONT_VER  = F(20, B.MONTSERRAT_14)   -- 版本号行

local VERSION = "v1.0.0"

-- 居中三重保险：官方 TOP_MID 常量 + text_align 多候选（含数字 1=LV_TEXT_ALIGN_CENTER）
local ATM = nil
pcall(function() ATM = lvgl.ALIGN.TOP_MID end)
local TA = nil
pcall(function() TA = lvgl.TEXT_ALIGN.CENTER end)
if TA == nil then pcall(function() TA = lvgl.LABEL_ALIGN.CENTER end) end
if TA == nil then TA = 1 end

-- ---------- 课表 ----------
local schedule = {}
for d = 1, 7 do schedule[d] = {} end
local last_signature, course_count = "", 0
local probe_dir, diag_a, diag_b, tick = nil, "未探测", "未读取", 0

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

-- ---------- S0 自检：os.execute 是否可用 + 找到可写目录 ----------
local function find_probe_dir()
    if probe_dir then return probe_dir end
    for _, d in ipairs(PROBE_DIRS) do
        local p = d .. "ev_probe.txt"
        pcall(function() os.execute('echo EV_PROBE_OK > "' .. p .. '"') end)
        local f = io.open(p, "r")
        if f then
            local t = f:read("*a") or ""
            f:close()
            if t:find("EV_PROBE_OK") then
                probe_dir = d
                return d
            end
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

-- 写端回执 class_status.txt：一次分清「写端没写」和「表盘读不到」
local function probe_status(d)
    local tmp = d .. "ev_status.tmp"
    for _, src in ipairs(CANDIDATES) do
        local dir = src:match("^(.*/)")
        if dir then
            local t = copy_to_tmp(dir .. "class_status.txt", tmp)
            if t then return t end
        end
    end
    return nil
end

local function read_shared()
    local d = find_probe_dir()
    if not d then diag_a = "探针不通"; return nil end
    local tmp = d .. "ev_class.tmp"
    for i, src in ipairs(CANDIDATES) do
        local t = copy_to_tmp(src, tmp)
        if t then
            diag_a = "路径P" .. i
            return t
        end
    end
    -- 动态兜底：find 一次，只跑一次
    if not _G.ev_find_done then
        _G.ev_find_done = true
        local out = d .. "ev_find.txt"
        pcall(function() os.execute('find /data /sdcard -name "class*.txt" > "' .. out .. '"') end)
        local f = io.open(out, "r")
        if f then
            for line in f:lines() do
                if line:sub(1, 1) == "/" and line:find("class") then
                    local t = copy_to_tmp(line, tmp)
                    if t then diag_a = "找到文件"; return t end
                end
            end
            f:close()
        end
    end
    diag_a = "没文件"
    return nil
end

-- 星期中文映射：手环 usr.db 实证，原始结构里 day 是「星期一」而不是 1..7
local DAYCN = { ["星期一"] = 1, ["星期二"] = 2, ["星期三"] = 3, ["星期四"] = 4,
                ["星期五"] = 5, ["星期六"] = 6, ["星期日"] = 7, ["星期天"] = 7 }

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

    -- ① 快应用导出格式（扁平）：{"day":1,"name":"语文","start":"08:00","end":"08:45"}
    for obj in text:gmatch("%b{}") do
        local day = tonumber(obj:match('"day"%s*:%s*(%d+)') or "")
        if day then
            local name = obj:match('"name"%s*:%s*"(.-)"')
            local st = hm(obj:match('"start"%s*:%s*"(.-)"') or "")
            local en = hm(obj:match('"end"%s*:%s*"(.-)"') or "")
            add_course(day, name, st, en)
        end
    end

    -- ② 快应用 storage 原始格式（嵌套）：
    --    [{"day":"星期一","classes":[{"name":"语文","time":"08:00 - 08:40"}]}]
    --    写端没导出时，表盘直接读 usr.db 也能出课，不再依赖快应用配合。
    if course_count == 0 then
        for gday, body in text:gmatch('"day"%s*:%s*"([^"]+)"%s*,%s*"classes"%s*:%s*%[(.-)%]') do
            local di = DAYCN[gday] or tonumber(gday)
            -- 同一天已解析过就跳过：usr.db 里可能存着 allCourses_0 / allCourses_1 多套课表，
            -- 不设这道闸会把第二套也叠进同一周。
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

-- ---------- 时间：12 小时制 ----------
local function now_t() return os.date("*t", os.time()) end
local function today_index(t) return t.wday == 1 and 7 or (t.wday - 1) end
local function fmt_time(t)
    local h = t.hour % 12
    if h == 0 then h = 12 end
    return string.format("%02d:%02d", h, t.min)   -- 22:27 -> 10:27，固定 5 字符宽度
end

-- ---------- 状态机：每行 <=6 字 ----------
local function compute()
    local t = now_t()
    local mins = t.hour * 60 + t.min
    local di = today_index(t)
    local today = schedule[di] or {}
    local out = {
        status = "今日无课", subject = "EV课程表", d1 = "", d2 = "", next = "",
        time = fmt_time(t), today_n = #today,
    }
    local function find_next()
        for k = 0, 6 do
            local d = ((di - 1 + k) % 7) + 1
            if k == 0 then
                for i = 1, #today do
                    if today[i].start > mins then return "下节" .. cut(today[i].name, 3) end
                end
            elseif #schedule[d] > 0 then
                return "下节" .. cut(schedule[d][1].name, 3)
            end
        end
        return ""
    end
    if #today == 0 then out.next = find_next(); return out end
    if mins < today[1].start then
        out.status = "即将上课"; out.subject = cut(today[1].name, 4)
        out.d1 = "还有" .. (today[1].start - mins) .. "分"
        out.next = today[2] and ("之后" .. cut(today[2].name, 3)) or ""
        return out
    end
    for i = 1, #today do
        local c = today[i]
        if mins >= c.start and mins < c.finish then
            out.status = "上课中"; out.subject = cut(c.name, 4)
            out.d1 = "已上" .. (mins - c.start) .. "分"
            out.d2 = "下课" .. (c.finish - mins) .. "分"
            out.prog = (mins - c.start) / (c.finish - c.start)
            out.next = today[i + 1] and ("下节" .. cut(today[i + 1].name, 3)) or "本节最后"
            return out
        end
        if i < #today and mins >= c.finish and mins < today[i + 1].start then
            local nx = today[i + 1]
            out.status = "课间休息"; out.subject = cut(nx.name, 4)
            out.d1 = "还有" .. (nx.start - mins) .. "分"
            out.next = "下节" .. cut(nx.name, 3)
            return out
        end
    end
    out.status = "今日结束"; out.next = find_next()
    return out
end

-- ---------- UI：y=96..394 安全矩形区，字号全线上调 ----------
local th = THEMES[theme_idx]
local scr = lvgl.Object(nil, {
    w = W, h = H, x = 0, y = 0,
    bg_color = th.bg, bg_opa = lvgl.OPA(100),
    border_width = 0, pad_all = 0,
})
scr:clear_flag(lvgl.FLAG.SCROLLABLE)
scr:add_flag(lvgl.FLAG.EVENT_BUBBLE)

local labels = {}
-- 普通行：不设 w，让标签宽度自适应文字，配合 TOP_MID 天然水平居中。
-- 旧写法给 w=W 再靠 text_align 居中，但 lvgl.TEXT_ALIGN 常量在部分固件取不到，
-- 取不到就静默退化成左对齐 —— 跑道屏上整列文字贴左边缘，非常难看。
local function label(y, h, font, color, text)
    local p = {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
    }
    if ATM then p.align = { type = ATM, x_ofs = 0, y_ofs = y } else p.x, p.y = 0, y end
    if TA then p.text_align = TA end
    local o = lvgl.Label(scr, p)
    labels[#labels + 1] = o
    return o
end
-- 时间行：不设 w，自适应文字宽度 + TOP_MID，天然水平居中，不依赖 text_align
local function time_label(y, h, font, color, text)
    local p = {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
    }
    if ATM then p.align = { type = ATM, x_ofs = 0, y_ofs = y } else p.x, p.y = 0, y end
    local o = lvgl.Label(scr, p)
    labels[#labels + 1] = o
    return o
end

local l_time = time_label(102, 52, FONT_TIME, th.time, "--:--")
local l_stat = label(154, 30, FONT_STAT, th.accent, "读取课表中")
local l_subj = label(184, 40, FONT_SUBJ, th.time, "EV课程表")
local l_d1   = label(226, 28, FONT_BODY, th.sub, "")
local l_d2   = label(254, 28, FONT_BODY, th.sub, "")
local l_next = label(282, 28, FONT_BODY, th.accent, "")

-- 课程进度条：上课中按已上比例填充，视觉上给「还剩多久」一个直觉
local BAR_W, BAR_H = 132, 6
local bar_x = math.floor((W - BAR_W) / 2)
local AL = nil
pcall(function() AL = lvgl.ALIGN.TOP_LEFT end)
local function place(o, y)
    if AL then o:set { align = { type = AL, x_ofs = bar_x, y_ofs = y } }
    else o:set { x = bar_x, y = y } end
end
local bar_bg, bar_fg
-- 进度条属于装饰件：任何机型上 lvgl.Object 参数不被支持时都不能拖垮整个表盘，
-- 因此创建过程整体 pcall，失败则只是少一根进度条，其余内容照常渲染。
pcall(function()
    bar_bg = lvgl.Object(scr, {
        w = BAR_W, h = BAR_H, bg_color = 0x1E3A52, bg_opa = lvgl.OPA(100),
        border_width = 0, radius = 3,
    })
    bar_fg = lvgl.Object(scr, {
        w = 0, h = BAR_H, bg_color = th.accent, bg_opa = lvgl.OPA(100),
        border_width = 0, radius = 3,
    })
    place(bar_bg, 314)
    place(bar_fg, 314)
end)

local l_ver  = label(326, 24, FONT_VER, th.hint, VERSION)
local l_info1 = label(350, 24, FONT_VER, th.hint, "未探测")
local l_info2 = label(370, 24, FONT_VER, th.hint, "未读取")

local function apply_theme()
    th = THEMES[theme_idx]
    scr:set { bg_color = th.bg }
    l_time:set { text_color = th.time }
    l_stat:set { text_color = th.accent }
    l_subj:set { text_color = th.time }
    l_d1:set   { text_color = th.sub }
    l_d2:set   { text_color = th.sub }
    l_next:set { text_color = th.accent }
    l_info1:set { text_color = th.hint }
    l_info2:set { text_color = th.hint }
    l_ver:set   { text_color = th.hint }
    pcall(function() bar_fg:set { bg_color = th.accent } end)
end
local function load_theme()
    local f = io.open(THEME_FILE, "r")
    if not f then return end
    local n = tonumber(f:read("*a") or "")
    f:close()
    if n and n >= 1 and n <= #THEMES then theme_idx = n end
end
local function save_theme()
    pcall(function()
        local f = io.open(THEME_FILE, "w")
        if f then f:write(tostring(theme_idx)); f:close() end
    end)
end

local function refresh()
    tick = tick + 1
    local text = read_shared()
    local sig = text or "#none"
    if sig ~= last_signature then parse_schedule(text); last_signature = sig end
    local s = compute()
    l_time:set { text = s.time }
    l_stat:set { text = s.status }
    l_subj:set { text = s.subject }
    l_d1:set   { text = s.d1 }
    l_d2:set   { text = s.d2 }
    l_next:set { text = s.next }
    pcall(function()
        local pw = math.floor(BAR_W * math.max(0, math.min(1, s.prog or 0)))
        bar_fg:set { w = pw }
    end)
    -- 每次刷新重设居中，防止 set text 后对齐被重置
    if TA then pcall(function() l_time:set { text_align = TA } end) end
    -- 诊断 B：数据状态 / 写端回执 / 今日节数 轮播，全部 <=6 字
    if not text then
        local d = probe_dir or find_probe_dir()
        local st = d and probe_status(d) or nil
        if st and st:find("^OK:") then diag_b = "写端OK"
        elseif st and st:find("WRITEFAIL:") then diag_b = "写失败" .. (st:match("WRITEFAIL:(%d+)") or "?")
        elseif st and st:find("READFAIL:") then diag_b = "回读失败"
        elseif st and st:find("BEGIN:") then diag_b = "写未回执"
        else diag_b = "无写端" end
        -- 读不到文件时，把「该干什么」直接顶到正文行，别让人对着小字猜
        l_next:set { text = "请开课程表" }
    elseif course_count == 0 then
        diag_b = "课表空"
        l_next:set { text = "课表无课程" }
    elseif tick % 2 == 0 then
        diag_b = "今日" .. s.today_n .. "节"
    else
        diag_b = "课表" .. course_count .. "条"
    end
    l_info1:set { text = diag_a }
    l_info2:set { text = diag_b }
end

function ScreenStateChangedCB(pre, now, reason)
    if pre ~= "ON" and now == "ON" then refresh() end
end
pcall(function()
    _G.ev_class_timer = lvgl.Timer { period = 60000, cb = function() refresh() end }
end)
scr:onevent(lvgl.EVENT.CLICKED, function()
    theme_idx = theme_idx % #THEMES + 1
    apply_theme(); save_theme(); refresh()
end)

load_theme(); apply_theme(); refresh()
print("EV_CLASS_BAND9_V4", W, H, "rows=" .. #labels, "courses=" .. course_count, diag_a, diag_b)
