-- @face-core: 课程表数据层（所有表盘默认注入，加表盘不要再抄一遍）
-- 依赖：调用方需先声明 lvgl 与实际屏幕尺寸；本段不创建任何 UI。
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

