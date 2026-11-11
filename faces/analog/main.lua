-- EV 白盘 v1 · 复刻 macOS 时钟的极简白盘指针表
--
-- 选型理由（对照 Mac 上那六个）：
--   带 1-12 数字 + 60 根细刻度的两款，要先解决 12 个 label 定宽和 60 根刻度定位，
--   而且细刻度必须按角度旋转才好看，旋转能力还没证实（probe 在跑）；
--   数字时钟那款不是指针表；
--   剩下这款只有「白盘 + 12 根灰粗刻度 + 两根黑针 + 橙秒针」，零文字、零细刻度。
--   更关键：它的 12 根刻度全部是**同一方向（竖条）**，不随角度旋转 ——
--   这正好是「只改 x/y 就能画」的范围，能 1:1 复刻。
--
-- 三条实现约束（前面几款真机踩出来的）：
--   1) 指针不用 transform_angle，用沿方向排布的方块拼，靠近中心粗、靠近尖端细，
--      192 宽的屏上看着就是一根锥形针（截图里的针本来就是锥形）。
--   2) 不用贴图（Image 未证实可用），盘面就是一块纯白圆。
--   3) 对象数压在 60 以内（每个 Object 都吃 LVGL 堆内存）。
--
-- 课程表数据层由 build.py 从 shared/lua/schedule_core.lua 注入。
local lvgl = require("lvgl")
local W, H = lvgl.HOR_RES(), lvgl.VER_RES()

local B = lvgl.BUILTIN_FONT
local function F(size)
    local ok, f = pcall(lvgl.Font, "MiSans-Regular", size)
    if ok and f then return f end
    ok, f = pcall(lvgl.Font, "MiSans-Demibold", size, "normal")
    if ok and f then return f end
    return B.MONTSERRAT_14
end
-- @@PROFILE_BEGIN@@
local P = {
  safe_top = 96, safe_bottom = 394,
}
-- @@PROFILE_END@@

local VERSION = "v1.0.0"

-- ---------- 配色：近黑底 + 纯白盘 + 灰刻度 + 黑针 + 橙秒针（照抄截图）----------
local C_BG    = 0x000000          -- 纯黑（用户 2026-11-11 定：三款表盘底色统一纯黑）
local C_DIAL  = 0xF7F7F5
local C_TICK  = 0x8E8E93
local C_HAND  = 0x16161A
local C_SEC   = 0xF5A623
local C_SUBJ  = 0xF7F7F5
local C_STAT  = 0xF5A623
local C_NEXT  = 0x9AA0AC
local C_DIM   = 0x4A4E58

-- ---------- 版式 ----------
-- 盘不能太大：盘底必须给课程文字留出干净的黑底，白字压在白盘上等于消失。
-- 84 半径时盘底到 274，课程首行 290，真机上只差 16px，缩略图上直接糊在一起。
local CXC, CYC = 96, 186
local R = 82                      -- 白盘半径 → y 104..268（盘再小就成贴纸了）
local TICK_R = 71                 -- 刻度中心半径：贴着盘边，盘心留白才像表盘

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
-- 缺这一行，触摸事件不上抛，系统收不到长按 → 进不了表盘切换页
scr:add_flag(lvgl.FLAG.EVENT_BUBBLE)

-- ---------- 触摸命中：装饰对象必须「不抢按下 + 事件上抛」----------
-- 这是 v1.0.8 之前漏掉的一半：scr 加了 EVENT_BUBBLE 只是「自己愿意上抛」，
-- 但 lvgl 的普通 Object 默认 CLICKABLE=1，按下会被最上层那块方块吃掉，
-- 事件根本到不了 scr → 系统收不到长按 → 只有标签区域（Label 默认不可点击，
-- 事件穿透到 scr）能换表盘，盘面/刻度/指针上长按毫无反应。
-- 结论：每一个纯装饰对象建完立刻 clear CLICKABLE，并顺手补 EVENT_BUBBLE。
-- 复盘：docs/表盘预览与长按修复复盘-20261111.md §4（含验收：盘面/刻度/指针/文字四处长按）。
local function passive(o)
    pcall(function() o:clear_flag(lvgl.FLAG.CLICKABLE) end)
    pcall(function() o:add_flag(lvgl.FLAG.EVENT_BUBBLE) end)
    return o
end

local function box(x, y, w, h, color, radius)
    return passive(lvgl.Object(scr, {
        w = w, h = h, x = math.floor(x), y = math.floor(y),
        bg_color = color, bg_opa = lvgl.OPA(100),
        radius = radius or 0, border_width = 0, pad_all = 0,
    }))
end

local function label(y, h, font, color, text)
    local p = {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
    }
    if ATM then p.align = { type = ATM, x_ofs = 0, y_ofs = y } else p.x, p.y = 0, y end
    return passive(lvgl.Label(scr, p))
end

-- ---------- 1. 白盘（带一圈极淡描边，硬切边在真机上有锯齿感）----------
box(CXC - R, CYC - R, R * 2, R * 2, C_DIAL, R)
passive(lvgl.Object(scr, {
    w = R * 2, h = R * 2, x = CXC - R, y = CYC - R,
    bg_opa = 0, radius = R, border_width = 1, border_color = 0xE2E2DE, pad_all = 0,
}))

-- ---------- 2. 12 根刻度：全部竖条，不按角度旋转 ----------
-- 截图里 3 点、6 点、9 点的刻度也是竖条，这正是能 1:1 复刻的原因。
-- 12/3/6/9 四根加长加深，给盘面一点层次（不加对象，只是参数不同）。
for h = 0, 11 do
    local major = (h % 3 == 0)
    local rad = h * 30 * math.pi / 180
    local tx = CXC + TICK_R * math.sin(rad)
    local ty = CYC - TICK_R * math.cos(rad)
    local tw, th = major and 8 or 6, major and 22 or 15
    box(tx - tw / 2, ty - th / 2, tw, th, major and 0x5E5E63 or C_TICK, 3)
end

-- ---------- 3. 指针：锥形点阵 ----------
-- 关键：每段方块必须**大于步长**，段与段重叠成实心锥形。
-- 之前分针末端 4px 方块配 5.3px 步长，段间露缝，真机上看就是一串断点 —— 「粗糙」的主因。
local hand_h, hand_m, hand_s = {}, {}, {}

local function build(dots, n, w0, w1, len, color)
    for i = 1, n do
        local t = (i - 1) / math.max(1, n - 1)
        local sz = math.floor(w0 + (w1 - w0) * t + 0.5)
        dots[i] = {
            obj = box(-40, -40, sz, sz, color, 1),
            sz = sz,
            d = (i - 1) * (len / math.max(1, n - 1)),
        }
    end
end
-- 步长 = len/(n-1)：时针 6.7→最小块 7、分针 5.3→最小块 6、秒针 4.2→最小块 4
build(hand_h, 8, 11, 7, 44, C_HAND)       -- 时针 44px
build(hand_m, 14, 9, 6, 70, C_HAND)       -- 分针 70px（尖到刻度内侧）
build(hand_s, 16, 5, 4, 62, C_SEC)        -- 秒针 62px（铺满到刻度内侧，截断的秒针像瑕疵）

local function place(dots, ang)
    local rad = ang * math.pi / 180
    local dx, dy = math.sin(rad), -math.cos(rad)
    for i = 1, #dots do
        local it = dots[i]
        local d = it.sz
        it.obj:set {
            x = math.floor(CXC + dx * it.d - d / 2),
            y = math.floor(CYC + dy * it.d - d / 2),
        }
    end
end

-- 中心橙点（截图里盘心就是一个橙点，外面压一点点黑）
box(CXC - 5, CYC - 5, 10, 10, C_SEC, 5)
box(CXC - 2, CYC - 2, 4, 4, C_HAND, 2)

-- ---------- 4. 课程信息（默认注入，与 class/clock 共用同一份数据层）----------
-- 行距按「字号 + 4~6px 空气」给，三行贴在一起在 192 宽的屏上会读成一坨。
local l_subj = label(292, 34, F(30), C_SUBJ, "读取课表中")
local l_stat = label(326, 28, F(24), C_STAT, "")
local l_next = label(352, 26, F(22), C_NEXT, "")
local l_ver  = label(378, 18, F(16), C_DIM, VERSION)

local sig_cache = "#none"

local function refresh()
    local t = os.date("*t", os.time())
    local hour = t.hour or 0
    local min = t.min or 0
    local sec = t.sec or 0

    place(hand_h, (hour % 12) * 30 + min * 0.5)
    place(hand_m, min * 6)
    place(hand_s, sec * 6)

    -- 整段 pcall：一次文件读取异常不该把表盘拖黑（表盘一崩，长按切换也不响应）
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
    _G.ev_white_timer = lvgl.Timer { period = 20000, cb = function() refresh() end }
end)

refresh()
print("EV_WHITE_V1", W, H, VERSION, "courses=" .. course_count)
