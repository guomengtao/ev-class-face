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
