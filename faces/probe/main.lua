-- EV Probe v1 · 表盘能力探测（不对外发布，只为回答一个问题：
-- 金属指针表盘该走 transform_angle 旋转，还是走 60 角度查表？）
--
-- 为什么需要它：lua 沙盒的 API 白名单是从官方例程反推的，文档里查不到。
-- lvgl.Image / transform_angle / Animation / Canvas 走各自不同的固件路径，
-- 猜错的代价是整款表盘做废。装一次 probe，全部问清楚。
--
-- 结果同时「画在屏上」（结论唯一可靠的回传通道）和 print 到日志。
local lvgl = require("lvgl")
local W, H = lvgl.HOR_RES(), lvgl.VER_RES()

local B = lvgl.BUILTIN_FONT
local function F(size)
    local ok, f = pcall(lvgl.Font, "MiSans-Regular", size)
    if ok and f then return f end
    return B.MONTSERRAT_14
end
-- @@PROFILE_BEGIN@@
-- 机型 profile：构建时由 build.py 按 devices/<device>.json 整块替换。
-- probe 全用绝对坐标（本表盘只有一次性用途），这里只留安全区做排版基准。
local P = {
  safe_top = 96, safe_bottom = 394,
}
-- @@PROFILE_END@@

local VERSION = "v1.0.0"

local C_BG = 0x08090C
local C_TEXT = 0xE8EDF5
local C_OK = 0x53E08A
local C_NO = 0xFF6B6B
local C_DIM = 0x5A6274
local C_NEEDLE = 0xFF9F45

-- ---------- 屏幕三件套：缺 EVENT_BUBBLE 长按就进不了切换页 ----------
local scr = lvgl.Object(nil, {
    w = W, h = H, x = 0, y = 0,
    bg_color = C_BG, bg_opa = lvgl.OPA(100),
    border_width = 0, pad_all = 0, radius = 0,
})
scr:clear_flag(lvgl.FLAG.SCROLLABLE)
scr:add_flag(lvgl.FLAG.EVENT_BUBBLE)

local ATM, ATL = nil, nil
pcall(function() ATM = lvgl.ALIGN.TOP_MID end)
pcall(function() ATL = lvgl.ALIGN.TOP_LEFT end)

-- 居中版：进度条与时间都用它；x 参数仅在退化路径（无 ALIGN）下当左偏移
local function label(x, y, h, font, color, text, mid)
    local p = {
        h = h, text = text or "", text_font = font, text_color = color,
        bg_opa = 0, border_width = 0, pad_all = 0,
    }
    if mid and ATM then
        p.align = { type = ATM, x_ofs = 0, y_ofs = y }
    elseif ATL then
        p.align = { type = ATL, x_ofs = x, y_ofs = y }
    else
        p.x, p.y = x, y
    end
    return lvgl.Label(scr, p)
end

local FONT_ROW = F(24)
local FONT_TAG = F(20)

-- ---------- 探测 ----------
local R = {}

local function add(tag, state)
    R[#R + 1] = { tag = tag, state = state }
end

-- fn 返回 false = API 不存在；跑崩了 pcall 捕获 = ERR；两者都算「不可用」
local function T(tag, fn)
    local ok, r = pcall(fn)
    if not ok then add(tag, "ERR") return end
    add(tag, (r == false) and "NO" or "OK")
end

-- 探针对象统一放在屏外，避免影响可视化区域
local function offscreen(opts)
    opts.x, opts.y = -40, -40
    opts.bg_opa = 0
    opts.border_width = 0
    opts.pad_all = 0
    return lvgl.Object(scr, opts)
end

T("obj", function() return lvgl.Object ~= nil end)
T("label", function() return lvgl.Label ~= nil end)
T("image", function() return lvgl.Image ~= nil end)

-- 核心问题一：矩形能不能旋转（指针的基础）
T("angle", function()
    local o = offscreen({ w = 8, h = 8 })
    o:set { transform_angle = 300 }
    return true
end)

-- 核心问题二：旋转轴能不能改（指针要绕表心转，不是绕自己中心）
T("pivot", function()
    local o = offscreen({ w = 8, h = 8 })
    o:set { transform_angle = 300, transform_pivot_x = 4, transform_pivot_y = 4 }
    return true
end)

-- 核心问题三：图片（图片表盘 / 指针贴图的前提）
T("img_src", function()
    local o = lvgl.Image(scr, { src = "lua/a.png", w = 8, h = 8, x = -40, y = -40 })
    return o ~= nil
end)

T("anim", function() return (lvgl.Anim ~= nil) or (lvgl.Animation ~= nil) end)
T("line", function() return lvgl.Line ~= nil end)
T("canvas", function() return lvgl.Canvas ~= nil end)

-- ---------- 可视化：一根真指针（同时是 pivot 的活体探针）----------
-- 判读方法（只看这一根杆就够了）：
--   指针在 hub 周围转、永远从 hub 出发 → angle 可用 且 pivot 可用，金属指针表盘可以直接做
--   指针中点不动、两头一起转           → angle 可用 但 pivot 被忽略，得改用「等长双杆」
--   指针完全不动                       → angle 不可用，退化到 60 角度查表定位光点
local CXC, CYC = W // 2, 240
local NEEDLE_LEN, NEEDLE_W = 78, 6

local hub = lvgl.Object(scr, {
    w = 10, h = 10, x = CXC - 5, y = CYC - 5,
    bg_color = C_TEXT, bg_opa = lvgl.OPA(100),
    radius = 5, border_width = 0, pad_all = 0,
})
-- 杆的顶部对齐 hub，pivot 摆在杆底（= hub 中心）→ 才会绕表心转
local needle = lvgl.Object(scr, {
    w = NEEDLE_W, h = NEEDLE_LEN,
    x = CXC - NEEDLE_W // 2, y = CYC - NEEDLE_LEN,
    bg_color = C_NEEDLE, bg_opa = lvgl.OPA(100),
    radius = 3, border_width = 0, pad_all = 0,
})
pcall(function()
    needle:set { transform_pivot_x = NEEDLE_W // 2, transform_pivot_y = NEEDLE_LEN }
end)

local l_time = label(0, 96, 30, F(30), C_TEXT, "--:--", true)
local l_note = label(0, 130, 22, FONT_TAG, C_DIM, "", true)

-- ---------- 结论行 ----------
local rows = {}
local BASE_Y = 300
for i = 1, 7 do
    rows[i] = label(8, BASE_Y + (i - 1) * 26, 24, FONT_TAG, C_DIM, "")
end

local function paint()
    for i = 1, 7 do
        local r = R[i]
        local lb = rows[i]
        if not r then lb:set { text = "" }
        else
            lb:set { text = r.tag .. " " .. r.state,
                     text_color = (r.state == "OK") and C_OK or C_NO }
        end
    end
end

-- ---------- 刷新 ----------
local function refresh()
    local t = os.date("*t", os.time())
    local hh = t.hour or 0
    local mm = t.min or 0
    l_time:set { text = string.format("%02d:%02d", hh, mm) }
    -- LVGL 的 angle 单位是 0.1 度；分钟一圈 360° → 每分钟 60 个 0.1°
    local ang = mm * 60
    pcall(function() needle:set { transform_angle = ang } end)
    l_note:set { text = "angle=" .. ang }
    paint()
end

function ScreenStateChangedCB(pre, now, reason)
    if now == "ON" then refresh() end
end
pcall(function()
    _G.ev_probe_timer = lvgl.Timer { period = 15000, cb = function() refresh() end }
end)

refresh()

-- 日志侧结论：面板看不到细节时用它兜底
local parts = {}
for i = 1, #R do parts[#parts + 1] = R[i].tag .. "=" .. R[i].state end
print("EV_PROBE", VERSION, table.concat(parts, " "))
