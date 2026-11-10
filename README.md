# EV Faces · 小米手环 Lua 表盘（多表盘 · 多机型）

一个仓库承载**多款表盘 × 多个机型**。当前两款：

| 表盘 | 目录 | ID | 风格 | 内容 |
|---|---|---|---|---|
| EV 课程提醒 | `faces/class/` | `882610318` | 信息卡片：深海蓝 + 圆角卡片 + 多行小字 | 时间 / 状态 / 科目 / 已上·下课分钟 / 下节 / 进度条 |
| EV 石英 | `faces/clock/` | `882610319` | 极简挂钟：石墨黑 + 无卡片 + 超大字重 | 周几 / 月日 / 巨型分体时分 / 电量条 |

## 目录结构（加新表盘只碰 `faces/`）

```
ev-class-face/
├── build.py                  # 唯一构建入口：表盘 × 机型 → 一个 .face
├── devices/                  # 机型档案（屏幕/安全区/字号/行坐标），全表盘共用
│   ├── band9.json            #   小米手环 9  192×490 跑道屏
│   └── band10pro.json        #   小米手环 10 Pro 336×480 方屏
├── faces/
│   ├── class/
│   │   ├── face.json         # 元信息：id / name_en / devices / rows / preview_style
│   │   ├── main.lua          # 表盘逻辑（含 @@PROFILE@@ 注入段）
│   │   ├── version.json      # major/minor/patch
│   │   └── base/band9.face   # 官方基底（容器骨架 + 预览图占位）
│   └── clock/                # 同构，加表盘 = 复制这个目录
├── shared/
│   ├── face_container.py     # .face 解析 / 等长注入 / 改 ID 与名字
│   ├── rle.py                # 官方预览 RLE 编解码（blksize=3）
│   └── preview.py            # 长按切换页缩略图渲染（跟随 rows + 风格）
└── dist/                     # 产物：<face>-<device>-<ver>.face / .png
```

**三条边界**，决定了这套结构：

1. **ID 标识「表盘产品」**，跨机型共用、发布后永久固定；不同表盘必须不同 ID
2. **`.face` 包标识「表盘产品 × 机型」**，每机型一个包，内容彼此独立
3. **版本号跟表盘产品走**，一个版本号对应 N 个机型的包（`--no-bump` 出第 2、3 个机型）

## 构建

```bash
python3 build.py --face class --device band9        # 版本 patch 自动 +1，出包 + 缩略图
python3 build.py --face clock --device band9 --no-bump   # 同版本出另一机型
python3 build.py --face clock --device band10pro --preview-only   # 无基底时只能出缩略图
```

构建器做四件事，任一不过直接退出，不产生半成品：

- 用 `devices/<机型>.json` **整块替换** `main.lua` 里的 `@@PROFILE_BEGIN@@…@@PROFILE_END@@`
- 注入 `local VERSION`，同时画进缩略图
- 校验基底预览头 `e0 21 a5 5a` / `blksize==3` / 分辨率与屏幕一致
- `luac -p` 语法检查 + 超块容量自动 minify + RLE 解码自校验

## 为什么「一套代码 + 一套参数」但「一机型一个包」

位置和字号**没有自适应**：LVGL for Vela 是像素级定位，字号是固件编译期档位，
按系数缩放会掉到不存在的字号上。能自适应的只有对齐方式（`align` / `lvgl.pct()`）。
所以：**源码一份**（逻辑与排版意图），**参数一机型一份**（`devices/*.json`），**包一机型一个**。

## 机型档案字段

```jsonc
{
  "screen": [192, 490],
  "safe_area": {"top": 96, "bottom": 394},   // 跑道屏硬件安全矩形
  "content_width": 160,
  "fonts": {"time": 44, "big": 72, ...},     // 任意键，导出为 P.f_<key>
  "rows": {
    "time":  {"y": 100, "h": 48, "role": "time"},   // role 决定缩略图配色
    "hh":    {"y": 172, "h": 78, "font": "big"},    // font 复用别的字号
    "div":   {"y": 168, "w": 64, "h": 2},
    "bar":   {"y": 200, "w": 132, "h": 5},
    "info1": {"y": -100, "h": 22}                   // 负 y = 渲染但不显示
  }
}
```

- 构建器**不假定字段名**：`fonts`/`rows` 里出现的键原样导出成 `P.f_xxx / P.y_xxx / P.h_xxx / P.w_xxx`
- 同一份 `devices/*.json` 被多款表盘共用，每款表盘在 `face.json` 的 `rows` 里声明**自己用哪几行**
  （踩过：石英表盘串到了课程表那根进度条，压在时分数字上）

## 表盘 ID 与版本号（重要约定）

`.face` 头 `0x28..0x32` 的 10 字节 ID 是设备识别同款表盘的主键：

- 设备的 `watchface_list.json` 以 ID 为键；**同 ID 覆盖安装 = 原地升级**，配色与列表位置保留
- 换 ID = 设备认为这是另一款表盘，旧的不删，切换列表越堆越多
  （开发期吃过亏：`882610315/316/317/318` 四个残留在列表里）

`version.json` 保存 `major/minor/patch`，每次构建**自动 patch +1** 并写回；`--no-bump` 只读不改。
major/minor 手动改，走语义化版本。

## 数据来源（class 表盘）

表盘不存课表，读快应用 EV 课程表导出的共享文件：

```
/data/quickapp/files/com.application.watch.classschedule/class.txt
格式：[{"day":1,"name":"语文","start":"08:00","end":"08:45"}, ...]
```

`os.execute('cat ... > tmp')` 绕过沙箱再 `io.open`；亮屏 + 每 60s 各刷新一次。
兜底：直读 storage 原始库 `/data/quickapp/system/<包名>/usr.db`（`[{day:"星期一",classes:[{name,time}]}]`）。

## 缩略图（长按切换页）

- 字体：`Hiragino Sans GB`（macOS 上 **PingFang.ttc 不存在**，写错会静默变豆腐块）
- 有中文的行不能用拉丁字体（踩过：`电量` 变成 `□□`）
- 整屏纯色会被跑道遮罩裁成「超大圆圈」：要么做居中圆角卡片，要么像石英表那样四周留暗场
- 排版、字号、配色全部来自 `devices/*.json` + `face.json.preview_style`，与真机同源

## Lua 能力边界（已核实）

数据订阅走 `dataman`，值统一 **256 倍编码**（取用 `value // 256`），`2147483647` 表示无效。

| 能力 | 接口 | 状态 |
|---|---|---|
| 电量 | `dataman.subscribe("systemStatusBattery", obj, cb)` | 官方 Band9 在用，石英表盘已接 |
| 步数 | `dataman.subscribe("healthStepCount", ...)` | 键名已确认 |
| 心率 | `dataman.subscribe("healthHeartRate", ...)` | 键名已确认 |
| 压力 | `dataman.subscribe("healthPressureIndex", ...)` | 0–100 |
| 海拔 | `dataman.subscribe("systemSensorFusionAltitude", ...)` | 米 |
| 时间/日期 | `os.date("*t", os.time())` | 已用于石英表盘 |
| 多页面 | 多个 `lvgl.Object` 根 + 显隐切换 | LVGL 原生支持 |
| 动画 | `obj:Anim{...}` | 官方样本在用 |
| 触摸 | `onevent(lvgl.EVENT.CLICKED)` | class 用于换配色 |
| 文件读写 | `io.open` + `os.execute('cat ...')` | 表盘目录、`/tmp` 可读写 |

**反向回传的限制**：表盘能写文件，但真机读不到其他快应用私有目录；
「表盘 → 快应用」需走公共路径（`/tmp`），实测快应用侧 `readText` 对 `/tmp` 返回 301，**此路未通**。

## 版本

- v1.0.0 课程提醒首个可用版本：数据链路打通、跑道屏排版、进度条、版本号
- v1.0.x 布局迭代：行距加大、去掉路径诊断行、版本号贴底、缩略图跟随机型 rows
- clock v1.0.0 石英表盘：巨型分体时分 + 周几 / 月日 / 电量
