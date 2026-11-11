-- EV 课程提醒表盘 v4 · 小米手环 9 跑道屏 192x490
-- v4: 12小时制 / MiSans-Demibold 加粗 / 时间自适应宽度 TOP_MID 居中 /
--     每行<=6字 / 字号 44-30-28-24-22 / 双行短码诊断 / 多候选路径 + 写端回执探针
-- 数据链路见 数据联动与大圈回归-详细排查方案-20261110.md
local lvgl = require("lvgl")
local W, H = lvgl.HOR_RES(), lvgl.VER_RES()

-- ---------- 配色：固定纯黑（2026-11-11 用户定：去掉轻触切换背景） ----------
-- 历史沿革：早期是 4~5 套主题用 scr 的 CLICKED 事件轮换，索引存 THEME_FILE。
-- 现已按要求删除切换能力——不读、不写主题索引，底色恒定 #000000；
-- 前景（白字 / 青蓝点缀 / 暖橙辅助）保留不变，变的只是「底色永远不换」。
-- 注意：删掉 CLICKED 监听后，scr 仍然是可点击对象，系统长按进切换页依旧有效。
local th = {
    bg = 0x000000, time = 0xFFFFFF,
    accent = 0x7FD4FF, sub = 0xFFD479, hint = 0x8FB4D4,
}

-- ---------- 字体：官方 Band9 实证的粗体 MiSans-Demibold ----------
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
  f_time = 44, f_subj = 30, f_stat = 28, f_body = 24, f_info = 24, f_ver = 20,
  y_time = 102, h_time = 52,
  y_stat = 154, h_stat = 30,
  y_subj = 184, h_subj = 40,
  y_d1 = 226, h_d1 = 28,
  y_d2 = 254, h_d2 = 28,
  y_next = 282, h_next = 28,
  y_bar = 314, bar_w = 132, bar_h = 6,
  y_ver = 326, y_i1 = 350, y_i2 = 370, h_small = 24,
}
-- @@PROFILE_END@@

local FONT_TIME = F(P.f_time, B.MONTSERRAT_32 or B.MONTSERRAT_14)
local FONT_SUBJ = F(P.f_subj, B.MONTSERRAT_32 or B.MONTSERRAT_14)
local FONT_STAT = F(P.f_stat, B.MONTSERRAT_24 or B.MONTSERRAT_14)
local FONT_BODY = F(P.f_body, B.MONTSERRAT_14)
local FONT_INFO = F(P.f_info, B.MONTSERRAT_14)
local FONT_VER  = F(P.f_ver, B.MONTSERRAT_14)   -- 版本号行

local VERSION = "v1.0.0"


-- 居中三重保险：官方 TOP_MID 常量 + text_align 多候选（含数字 1=LV_TEXT_ALIGN_CENTER）
local ATM = nil
pcall(function() ATM = lvgl.ALIGN.TOP_MID end)
local TA = nil
pcall(function() TA = lvgl.TEXT_ALIGN.CENTER end)
if TA == nil then pcall(function() TA = lvgl.LABEL_ALIGN.CENTER end) end
if TA == nil then TA = 1 end

-- @@INCLUDE:schedule_core@@

-- ---------- UI：y=96..394 安全矩形区，字号全线上调 ----------
local scr = lvgl.Object(nil, {
    w = W, h = H, x = 0, y = 0,
    bg_color = th.bg, bg_opa = lvgl.OPA(100),
    border_width = 0, pad_all = 0,
    -- 必须显式 radius=0：LVGL 默认样式带圆角，亮色底会被裁成一块圆角大色块，
    -- 在切换页/真机上就是用户反复看到的「大圆圈」。深色表盘看不出来，亮色表盘特别明显。
    radius = 0,
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

-- 日期 + 周几：替换原来无课/下课时显示的「EV课程表」（2026-11-11 用户要求）。
-- 位置沿用课程名那行（y_subj），有课时仍是课名，占位时才显示日期；
-- 刷新周期 60s，跨天会自动跟着变。
local WEEK_CN = { "日", "一", "二", "三", "四", "五", "六" }
local function date_line()
    local t = os.date("*t", os.time())
    return string.format("%d/%d 周%s", t.month, t.day, WEEK_CN[t.wday] or "")
end

local l_time = time_label(P.y_time, P.h_time, FONT_TIME, th.time, "--:--")
local l_stat = label(P.y_stat, P.h_stat, FONT_STAT, th.accent, "读取课表中")
local l_subj = label(P.y_subj, P.h_subj, FONT_SUBJ, th.time, date_line())
local l_d1   = label(P.y_d1, P.h_d1, FONT_BODY, th.sub, "")
local l_d2   = label(P.y_d2, P.h_d2, FONT_BODY, th.sub, "")
local l_next = label(P.y_next, P.h_next, FONT_BODY, th.accent, "")

-- 课程进度条：上课中按已上比例填充，视觉上给「还剩多久」一个直觉
local BAR_W, BAR_H = P.bar_w, P.bar_h
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
-- 另：普通 Object 默认 CLICKABLE=1 会**吃掉按下事件**，让系统收不到长按
-- （症状：进度条那一条长按没反应，别处长按正常）。装饰件一律 clear CLICKABLE + 上抛。
local function passive(o)
    if not o then return nil end
    pcall(function() o:clear_flag(lvgl.FLAG.CLICKABLE) end)
    pcall(function() o:add_flag(lvgl.FLAG.EVENT_BUBBLE) end)
    return o
end
pcall(function()
    bar_bg = passive(lvgl.Object(scr, {
        w = BAR_W, h = BAR_H, bg_color = 0x1E3A52, bg_opa = lvgl.OPA(100),
        border_width = 0, radius = 3,
    }))
    bar_fg = passive(lvgl.Object(scr, {
        w = 0, h = BAR_H, bg_color = th.accent, bg_opa = lvgl.OPA(100),
        border_width = 0, radius = 3,
    }))
    place(bar_bg, P.y_bar)
    place(bar_fg, P.y_bar)
end)

local l_ver  = label(P.y_ver, P.h_small, FONT_VER, th.hint, VERSION)
local l_info1 = label(P.y_i1, P.h_small, FONT_VER, th.hint, "未探测")
local l_info2 = label(P.y_i2, P.h_small, FONT_VER, th.hint, "未读取")

-- 主题切换已移除（apply_theme / load_theme / save_theme 一并删除）：
-- 上面创建控件时颜色就直接取自常量 th，运行时无需再刷一遍配色。
-- 也不再触碰 THEME_FILE，避免旧存档（曾存过 2/3/4）把手环重新带回彩色底。

local function refresh()
    tick = tick + 1
    local text = read_shared()
    local sig = text or "#none"
    if sig ~= last_signature then parse_schedule(text); last_signature = sig end
    local s = compute()
    l_time:set { text = s.time }
    l_stat:set { text = s.status }
    -- 课程名行：compute() 的「今日无课」「今日结束」两个分支不写 subject，
    -- 它保持初值 "EV课程表"（品牌名占位）。占位一律换成日期 + 周几；
    -- 有课的分支（即将上课/上课中/课间休息）仍然显示课名。
    if s.subject == "" or s.subject == "EV课程表" then
        l_subj:set { text = date_line() }
    else
        l_subj:set { text = s.subject }
    end
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

-- 轻触不再切换背景（2026-11-11 用户要求：底色永远纯黑）。
-- 这里**故意不注册** EVENT.CLICKED：scr 仍是可点击对象，系统长按进表盘切换页不受影响；
-- 屏幕内任何位置轻触都变成无操作，不会再把底色切走。
refresh()
print("EV_CLASS_BAND9_V4", W, H, "rows=" .. #labels, "courses=" .. course_count, diag_a, diag_b)
