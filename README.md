# EV Class Face · 小米手环 9 Lua 表盘

把 EV 课程表的「即将上课 / 正在上课 / 下节课」放到手环表盘上，随用户改课实时联动。

## 特性

- 12 小时制大号时间（MiSans-Demibold 加粗、TOP_MID 水平居中）
- 状态机：即将上课 / 上课中 / 课间休息 / 今日结束 / 今日无课
- 课程进度条：上课中按已上比例填充
- 每行 ≤6 字，按跑道屏安全区 y=96..394 排版
- 轻触表面切换 4 套配色，选择持久化
- 版本号常驻底部（当前 v1.0.0）

## 数据来源

表盘自身不存课表，读快应用 EV 课程表导出的共享文件：

```
/data/quickapp/files/com.application.watch.classschedule/class.txt
格式：[{"day":1,"name":"语文","start":"08:00","end":"08:45"}, ...]
```

读取方式沿用 Var 课程表那套：`os.execute('cat ... > tmp')` 绕过沙箱，再 `io.open` 读临时文件；
亮屏（`ScreenStateChangedCB`）与每 60s 定时器各刷新一次。

兜底：若快应用未导出，直接读 storage 原始库
`/data/quickapp/system/<包名>/usr.db`，按 `[{day:"星期一",classes:[{name,time}]}]` 结构解析。

## 构建

```bash
python3 build_face.py --src <官方 Band9 基底.face> --lua main.lua --out out.face
```

- 基底必须是**小米手环 9**（192×490）原生 `.face`，用 8 Pro 方屏包会导致长按切换页异常
- 预览图 RLE 必须为官方格式：`e0 21 a5 5a | 03 e8 44 00`（blksize=3 RGB888 纯流），
  blksize=4 + LVGL 头会被设备解成只剩底色（「空蓝圈」）
- 预览图裁剪：整屏纯色块会被跑道遮罩裁成一坨「大圆」，需做居中卡片承载内容

## 版本

- v1.0.0 首个可用版本：数据链路打通、跑道屏排版、进度条、版本号

## 表盘 ID 与版本号（重要约定）

### ID：正式发布后**永久固定**，不再更换

`.face` 头 `0x28..0x32` 的 10 字节表盘 ID 是设备识别同款表盘的唯一主键：

- 设备的 `watchface_list.json` 以 ID 为键；同 ID 覆盖安装 = **原地升级**，用户设置（配色）、切换列表位置都保留
- 换 ID = 设备认为这是**另一款表盘**，旧的不会自动删，切换列表里会越堆越多（本项目开发期就吃过这个亏：`882610315/316/317/318` 四个残留在列表里）
- 上架/分发后 ID 变了，用户装新版会出现「表盘多了一个、旧的那个还在」

因此 **ID `882610318` 固定不变**，以后只走版本号。

> 开发期换 ID 只有一个合法用途：排查「设备按 ID 缓存切换卡片缩略图、同 ID 覆盖不刷新」这类问题时做对照。

### 版本号：第三位自动 +1

`version.json` 保存 `major/minor/patch`。每次执行 `build_face.py` 会**自动 patch +1** 并写回：

```
v1.0.1 → 构建一次 → v1.0.2
```

版本号同时注入两处：Lua 里的 `local VERSION`（表盘底部显示）+ 预览图右下角文字。
需要只读不改（重打同一版本、生成对照包）时加 `--no-bump`。

major/minor 手动改 `version.json` 即可，遵循语义化版本：破坏性变更 / 新功能 / 修复。

## Lua 表盘能力边界（已核实）

数据订阅走 `dataman` 模块，值统一 **256 倍编码**，取用必须 `value // 256`；`2147483647`（INT_MAX）表示无效。

| 能力 | 接口 | 状态 |
|---|---|---|
| 电量 | `dataman.subscribe("systemStatusBattery", obj, cb)` | 官方 Band9 表盘在用，可直接用 |
| 步数 | `dataman.subscribe("healthStepCount", ...)` | 键名已确认 |
| 心率 | `dataman.subscribe("healthHeartRate", ...)` | 键名已确认 |
| 压力 | `dataman.subscribe("healthPressureIndex", ...)` | 0–100 |
| 海拔 | `dataman.subscribe("systemSensorFusionAltitude", ...)` | 米 |
| 日出/日落 | `weatherCurrentSunRiseHour` 等 | 可用 |
| 时间/日期 | `timeHour`/`timeMinute`/`dateDay`/`dateWeek` | 可用 |
| 多页面 | 多个 `lvgl.Object` 根 + 显隐切换 / `lvgl.screen` 切换 | LVGL 原生支持 |
| 动画 | `obj:Anim{...}` | 官方样本在用 |
| 触摸 | `onevent(lvgl.EVENT.SHORT_CLICKED / LONG_CLICKED, cb)` | 已用于换配色 |
| 文件读写 | `io.open` + `os.execute('cat ...')` | 表盘目录、`/tmp` 可读写 |

**反向回传的限制**：表盘能写文件，但真机上**读不到其他快应用的私有目录**（官方明确限制）。
所以「表盘 → 快应用」回传需要走公共路径（如 `/tmp`）或由快应用主动来读，**未验证**，属于待实测项。
