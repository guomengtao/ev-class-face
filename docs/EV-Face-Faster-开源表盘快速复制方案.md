# EV Face Faster（EVFF）· 开源表盘快速复制与课程注入方案

> 版本 v1.0 · 2026-11-11
> 一句话：**不再手搓表盘。找到现成的开源表盘 → 挖出它的 lua → 塞进课程信息 → 等长拼回 → 装上手环。**

---

## 0. 为什么要有这套方案

我们前期的做法是自己从零写 lua（class / clock / analog 三款），代价是：

| 问题 | 表现 |
|---|---|
| 手搓指针 | 用一排小方块拼方向，段与段之间留缝，真机上就是"一串灰点"，怎么调都粗糙 |
| 手搓布局 | 字号、行高、圆角遮罩全靠试，改一轮装一轮，一轮 5 分钟 |
| 能力盲区 | 不知道固件支持什么（能不能旋转？能不能读电量？），只能猜 |

而开源社区（尤其官方自己的示例仓库）里，这些能力全是**已经被验证过的现成代码**。所以策略改成：

**先找，再改；能抄绝不自研。**

---

## 1. 开源表盘从哪找

按命中率排序，**优先第 1 条，它包含官方示例**：

### 1.1 官方 lua 表盘示例仓库（首选）

```
https://github.com/m0tral/MiWatchLuaWatchfaces
```

这是社区维护的官方 lua 表盘示例集合，覆盖 MiBand 8 Pro / 9 / 9 Pro / 10 / 10 Pro / 11、Redmi Watch 系列、Mi Watch S3/S4/S5。

关键目录：

| 路径 | 内容 | 价值 |
|---|---|---|
| `MiBand9/TempControl/app/lua/main.lua` | 手环 9 官方 lua 表盘**最小骨架**（134 行） | 所有表盘的起点模板 |
| `MiBand9/watchface_366269993/` | 手环 9 **官方库存表盘**完整工程（`.fprj` + `_lua/*.rle` + 预览图） | 学真实产品怎么写 |
| `MiBand9Pro/PointerTest/app/lua/main.lua` | **原生 Pointer 指针控件**示例 | 指针表盘的唯一正解 |
| `MiBand9Pro/AnalogTimeTest/` | 指针表盘完整示例 | 同上 |
| `MiBand8Pro/AnalogTimeAnimated/app/lua/image.lua` | 平滑秒针 + 动画 + 点击事件 | 动画表盘参考 |

### 1.2 第三方开源表盘（拿整包直接用）

| 项目 | 说明 |
|---|---|
| `github.com/sf-yuzifu/Monika` | 二次元立绘表盘，GPL v3，`release/monika-band9.bin` 就是完整 `.face`，**lua 明文可改** |
| `github.com/NineBomb/EXMars` | 火星表盘移植版，AGPL-3.0，含 `capability.json` / `uidmap.map` |
| `github.com/m0tral/EasyFace` | 表盘编译器（仅 Windows），`.fprj` → `.face` |
| `bandbbs.cn`（米坛社区） | 资源最多，但需登录下载，脚本拿不到 |

### 1.3 找的时候看三个指标

1. **机型对不对**：必须 `band9` / 192×490；9 Pro 是 336×480，不通用
2. **lua 是否明文**：包里搜得到 `local `、`lvgl.` 就能改；只有字节码或纯图片就只能当底图
3. **体积**：几百 KB 通常是 lua 表盘（可改）；几 MB 多是纯图片拼接（改不动）

---

## 2. 挖出包里的 lua

`.face` 容器里，lua 通常是明文源码，按块存放。以 Monika 为例：

```
块结构： 1B type(00) | 3B size(LE) | 1B nameLen | 16B reserved | name | content
```

实测 Monika（band9）：

| 字段 | 值 |
|---|---|
| lua 块偏移 | `327938` |
| lua 块大小 | `31789` |
| lua 块名 | `_lua/monika/monika.lua` |
| 后续块 | `_lua/monika/msg.png` 等资源 |

**提取脚本（Python）**：

```python
d = open('monika-band9.bin','rb').read()
OFF, SIZE = 327938, 31789          # 从块头读出来，不要写死
lua = d[OFF:OFF+SIZE]
open('monika.lua','wb').write(lua)
```

块头定位方法：搜 `_lua/` 或者 `.lua` 名字串，往前推 `1+3+1+16` 字节就是块头。

> 💡 **校准技巧**：用 `size` 反推。Monika 提取出 31789 字节、605 行；Python 文本模式读出来是 31184 字节 —— 差的正好是**605 个 `\r\n`**。说明原包用 CRLF 换行，**写回时必须用 CRLF**，否则整体长度对不上。

---

## 3. 改造：先看它有什么，再决定加什么

拿到 lua 先做三件事，不要急着改：

### 3.1 找"能力入口"

```bash
grep -n "dataman.subscribe\|lvgl.Timer\|:Image{\|:Label{\|getregistry" monika.lua
```

Monika 的实际结论（可直接抄）：

| 能力 | 写法 | 备注 |
|---|---|---|
| 电量 | `dataman.subscribe("systemStatusBattery", obj, cb)`，值 `//256` | **关键：必须除以 256** |
| 时间 | `dataman.subscribe("timeMinuteLow"/"timeSecond", ...)` | 秒级订阅，不需要自己造定时器 |
| 图片 | `root:Image { src = path }` + `widget:get_img_size()` | 图片表盘可行 |
| 动画 | `widget:Anim { run, start_value, end_value, time }` | 原生控件 |
| 字体 | `lvgl.Font(name, size)`，失败降级 | 内置 `MiSans-Regular` / `MiSans-Demibold` |
| 指针 | `widgets.__index.Pointer(root, {pivot=, angleRange=, src=})` | 来自 `debug.getregistry()["widgets"]` |

### 3.2 找"要塞进去的位置"

- 先看它的布局变量（Monika 是 `DEVICE.layout` / `DEVICE.xxxY`）
- 找**空闲纵坐标区间**：Monika 时间 y=294、日期 y=364、充电区 y=461 → 课程信息放 **y=390** 正合适
- 找现成的文字创建函数复用（Monika 的 `imageGroup.setText()` 已封装好 Label 参数）

### 3.3 算空间：这是最容易翻车的地方

**表盘 lua 槽位是写死的，容量一字节不能多。**

Monika 实测：`lua 块 31789B / 31789B` —— **顶格用满、零余量**。

要插代码必须先腾空间。安全的让出方式（按风险从低到高）：

1. ✅ **缩短对话/提示类字符串**（Monika 的 `text = "..."`，每条约 25 字截到 8 字，40 条就省 2KB）—— 只改字符串内容，不动结构，零语法风险
2. ⚠️ 删除整个功能块（连带要改引用，风险高）
3. ❌ 扩容 lua 槽（要移位后续所有块 + 重建块表，没验证过，别碰）

---

## 4. 注入课程信息（标准模板）

### 4.1 数据层（插在 `uiCreate()` 之前）

```lua
-- ===== EV 课程模块 =====
local EVS={{},{},{},{},{},{},{}}
local function evh(s) local h,m=(s or ""):match("(%d+):(%d+)"); if not h then return 0 end; return tonumber(h)*60+tonumber(m) end
local function eva(d,n,a,b) if d and n and a and b and b>a then local t=EVS[d]; t[#t+1]={n=n,a=a,b=b} end end
local function evp(txt)
  -- ① 快应用导出格式：{"day":1,"name":"语文","start":"08:00","end":"08:45"}
  for o in txt:gmatch("%b{}") do
    local d=tonumber(o:match('"day"%s*:%s*(%d+)') or "")
    if d then eva(d,o:match('"name"%s*:%s*"(.-)"'),evh(o:match('"start"%s*:%s*"(.-)"')),evh(o:match('"end"%s*:%s*"(.-)"'))) end
  end
  -- ② storage 原始格式：[{"day":"星期一","classes":[{"name":"语文","time":"08:00 - 08:40"}]}]
  local W={["星期一"]=1,["星期二"]=2,["星期三"]=3,["星期四"]=4,["星期五"]=5,["星期六"]=6,["星期日"]=7,["周日"]=7}
  for gd,body in txt:gmatch('"day"%s*:%s*"([^"]+)"%s*,%s*"classes"%s*:%s*%[(.-)%]') do
    local di=W[gd]
    if di and #EVS[di]==0 then
      for o in body:gmatch("%b{}") do
        local a,b=(o:match('"time"%s*:%s*"([^"]*)"') or ""):match("(%d+:%d+)%s*%-%s*(%d+:%d+)")
        eva(di,o:match('"name"%s*:%s*"(.-)"'),evh(a),evh(b))
      end
    end
  end
  for d=1,7 do table.sort(EVS[d],function(x,y) return x.a<y.a end) end
end
local function evload()
  local P={"/data/quickapp/files/class.txt",
           "/data/user/0/com.application.watch.classschedule/files/class.txt",
           "/data/quickapp/files/ev/class.txt",
           "/data/quickapp/system/com.application.watch.classschedule/usr.db"}
  for _,p in ipairs(P) do
    local f=io.open(p,"r")
    if f then local t=f:read("*a"); f:close(); if t and #t>10 then evp(t) return true end end
  end
end
```

### 4.2 状态机（返回两行文字）

```lua
local function evc()
  local t=os.date("*t",os.time()); local m=t.hour*60+t.min
  local di=t.wday==1 and 7 or (t.wday-1); local L=EVS[di] or {}
  local function C(s,n) return (s or ""):sub(1,n) end
  if #L==0 then return "今日无课","" end
  if m<L[1].a then return C(L[1].n,4),"还有"..(L[1].a-m).."分" end
  for i=1,#L do
    local c=L[i]
    if m>=c.a and m<c.b then return C(c.n,4),(L[i+1] and ("下节"..C(L[i+1].n,3)) or "本节最后") end
    if i<#L and m>=c.b and m<L[i+1].a then return C(L[i+1].n,4),"还有"..(L[i+1].a-m).."分" end
  end
  return "今日结束",""
end
```

### 4.3 UI（插在主布局创建完之后）

```lua
    evload()
    local cg=lvgl.Object(root,{x=0,y=390,w=192,h=60,bg_opa=0,border_width=0,pad_all=0})
    local e1=lvgl.Label(cg,{x=0,y=0,w=192,h=30,text="",text_color='#F2EDE4',text_font=textFont(),font_size=16})
    local e2=lvgl.Label(cg,{x=0,y=30,w=192,h=24,text="",text_color='#8C93A6',text_font=textFont(),font_size=16})
    -- 中文居中：一个字 16px，#s//3 是字数
    local function evx(s) local n=#s//3 local x=(192-n*16)//2 if x<0 then x=0 end return x end
    local function evr() local a,b=evc() e1:set{text=a,x=evx(a)} e2:set{text=b,x=evx(b)} end
    evr()
    local evt=lvgl.Timer{period=60000,repeat_count=-1,cb=function() if active then evr() end end}
```

### 4.4 三条硬规则（踩过的坑，写死记住）

1. **居中必须自己算 x**：盒子从 `x=0` 起、宽 = 整屏宽（192）。跑道屏两端是半圆，从 `x=6` 起且左对齐的内容会被圆角遮罩**裁掉**，看起来像"没显示"。
2. **不要在底部挤第二个 label**：底部只有一行 16px 高，单开一个角标必然和版本号重叠。要显示电量就**并进版本号同一行**：`VERSION .. "  " .. lvl .. "%"`。
3. **换行符保持 CRLF**：原包是 CRLF，写成 LF 会少 N 个字节，长度对不上就要靠补空格硬凑，容易出错。

---

## 5. 拼回并安装

```python
d    = bytearray(open('monika-band9.bin','rb').read())
new  = open('monika_new.lua','rb').read()
OFF, SIZE = 327938, 31789
assert len(new) == SIZE                     # 必须等长
d[OFF:OFF+SIZE] = new
open('out.face','wb').write(bytes(d))
```

**拼回后必做三步校验**：

```bash
luac -p new.lua                  # 1. 语法（Mac: brew install lua）
# 2. 长度必须 == 原 size；不足用空格补（lua 尾部空格合法），超出必须继续截
# 3. 回读比对：chk[OFF:OFF+SIZE] == new
```

安装：

```bash
ev-install --force -w 28 dist/Band9-xxx-v1.0.0.face
sleep 6
ev-install -r | head -3          # 读 AstroBox 无障碍树里的安装历史，看到"安装成功"才算完
```

> 回执读不到时（无障碍树返回空），通常是手环息屏，解锁后重跑 `ev-install -r` 即可。

---

## 6. 文件命名与目录结构（**重要，必须遵守**）

### 6.1 命名规则

```
{机型}-{原表盘名}-v{版本}.face
```

- **机型放开头**，全大写驼峰：`Band9` / `Band9Pro` / `Band10` / `Band10Pro` / `Band11`
- **中间是原表盘名**，保持原名便于回溯来源
- **末尾带版本**，方便对比回滚
- **其他乱七八糟的名字一律不写**（不要加 `ev-`、`final`、`new`、`copy2`、日期前缀）

示例：

```
✅ Band9-Monika-v1.0.0.face
✅ Band9-Monika-EV-v1.1.0.face      # EV 改造版，加 -EV 后缀区分原版
✅ Band9-Quartz-v1.0.13.face
✅ Band9Pro-AnalogTime-v1.0.0.face
❌ monika-ev-band9.face             # 机型在尾部，排序乱
❌ class-band9-v1.0.13.face         # 同上
❌ Band9-表盘-final-ok-2.face        # 花名
```

### 6.2 目录结构

```
ev-class-face/
├── dist/
│   ├── Band9/                      ← 192×490  deviceType=366
│   │   ├── Band9-Monika-EV-v1.1.0.face
│   │   ├── Band9-Quartz-v1.0.13.face
│   │   ├── Band9-Analog-v1.0.8.face
│   │   └── Band9-Class-v1.0.14.face
│   ├── Band9Pro/                   ← 336×480
│   ├── Band10/
│   ├── Band10Pro/
│   ├── Band11/
│   └── _source/                    ← 第三方原始包（未改造，留作回滚）
│       └── Band9/Monika-original.face
├── faces/                          ← 我们自己手搓的工程（build.py 用）
│   ├── class/
│   ├── clock/
│   ├── analog/
│   └── probe/
├── shared/
│   ├── lua/schedule_core.lua       ← 课程数据层（所有表盘共用）
│   ├── preview.py                  ← 缩略图渲染
│   ├── rle.py                      ← 预览块 RLE 编码
│   └── face_container.py           ← Gen1 格式读写
├── devices/                        ← 机型参数（band9.json 等）
└── docs/
    └── EV-Face-Faster-开源表盘快速复制方案.md   ← 本文档
```

**下一会话接手时，按这个顺序找东西：**

1. 要装机 → `dist/Band{版本}/`
2. 要改手搓表盘 → `faces/{名字}/main.lua`，跑 `python3 build.py --face {名字} --device band9`
3. 要改第三方表盘 → 源码在 `/tmp/mwlf/`（会话级，可能已清），原包在 `dist/_source/`
4. 要改课程逻辑 → 只改 `shared/lua/schedule_core.lua`，所有表盘一起生效

### 6.3 机型兼容性（发布时必须标注）

| 机型 | 分辨率 | deviceType | 能否复用 Band9 的包 |
|---|---|---|---|
| 小米手环 9 | 192×490 | 366 | — |
| 小米手环 9 Pro | 336×480 | 不同 | ❌ 分辨率不同，排版全乱 |
| 小米手环 10 / 10 Pro | 各自不同 | 不同 | ❌ |

**结论：`.face` 包跨机型不能通用。** 发布时必须：
1. 文件名带机型前缀
2. 说明里写清 `deviceType` 和分辨率
3. 建议给 `ev-install` 加一道**装机前校验**：读包内 `deviceType`，与目标手环不匹配就拒绝安装

---

## 7. 完整流程（照做）

```
① 找  ──→ 官方示例仓库优先；第三方包看机型 / lua 是否明文 / 体积
② 挖  ──→ 定位 _lua/*.lua 块头（1+3+1+16 字节前推），取 offset+size，导出
③ 读  ──→ grep dataman.subscribe / :Image{ / :Label{ / getregistry，列出它已具备的能力
④ 算  ──→ 确认 lua 槽容量；顶格用满就先截短提示字符串腾空间
⑤ 注  ──→ 插数据层（uiCreate 之前）+ UI 段（主布局之后），课程两行、居中、y≈390
⑥ 拼  ──→ CRLF 换行、等长替换、补空格补齐
⑦ 验  ──→ luac -p 语法 → 长度 == size → 回读比对
⑧ 装  ──→ ev-install → ev-install -r 读回执
⑨ 名  ──→ dist/Band{机型}/Band{机型}-{原名}-v{版本}.face
```

---

## 8. 已知能力清单（持续补充）

| 能力 | 是否可用 | 来源 |
|---|---|---|
| `dataman.subscribe` 读电量 / 时间 / 步数 / 心率 | ✅ | Monika / TempControl |
| 值编码 `//256` | ✅ | Monika |
| `lvgl.Image` + `get_img_size` | ✅ | 官方库存表盘 |
| `widget:Anim` 动画 | ✅ | 官方库存表盘 / AnalogTimeAnimated |
| `dataman.subscribe("timeSecond")` 秒级 | ✅ | Monika / TempControl |
| `widgets.__index.Pointer` 指针旋转 | ⚠️ 仅 9 Pro 示例验证，**band9 未验证** | PointerTest |
| `io.open` 读文件 | ✅ | 我们的 schedule_core |
| `os.execute` | ✅ | 实测可用 |
| 震动 | ❌ 表盘不支持，快应用仅 short/long 且不能常驻 | — |

---

## 9. 下一步

1. 把 `dist/` 按 6.2 的结构整理一次，原有包全部改名迁入 `dist/Band9/`
2. 给 `ev-install` 加 deviceType 校验
3. 用 `Pointer` 控件做第一款**真旋转指针表盘**（先在 band9 上验证 Pointer 是否可用，不行再退回查表角度）
4. 继续扩充开源来源：`MiBand10` / `MiBand11` 目录、米坛社区（需手动下载）、EXMars
