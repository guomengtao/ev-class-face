# 开源表盘分类台账（FACE-STATUS）

> 自动生成于 2026-11-11T13:27:21+0800 · 共 **30** 个包 / **17.5MB** · 机读权威：`data/face-registry.json`

> 本表由 `python3 tools/face_inventory.py` 刷新；`state` 列由人或 Worker 维护，扫描不会覆盖。

## 一、按可改造性分类

| 判定 | 数量 | 包体积合计 | 含义 |
|---|---|---|---|
| ✅ 可直改 | 4 | 0.5MB | lua 槽余量够直接插 3.7KB 注入段 |
| 🟡 截短后可改 | 17 | 7.3MB | 先截短包内提示字符串腾空间，再注入 |
| 🔶 需解压后改 | 1 | 3.7MB | 包内二次压缩，需先定位解压后的 lua 块 |
| 🔶 待逐个分析 | 3 | 4.3MB | 结构特殊，需逐个读代码 |
| ❌ 非 Lua 表盘 | 5 | 1.7MB | 纯资源表盘，无 lua 运行逻辑，放弃 |

## 二、明细

| 状态 | 判定 | KB | 包名 | lua 块 | 槽位 | 余量 | 来源/许可 |
|---|---|---|---|---|---|---|---|
| 已上真机验证 | 🟡 截短后可改 | 52 | `Band9-LuaCalculator-v1.0.0.face` | `lua/main.lua` | 13616B | 2B | github.com/hassan-xsf/band-face-pack / MIT |
| 已上真机验证 | 🟡 截短后可改 | 739 | `Band9-Monika-v1.2.0.face` | `_lua/monika/monika.lua` | 31895B | 2B | github.com/sf-yuzifu/Monika/releases/v1… / GPL-3.0 |
| 已接入课程提醒 | ✅ 可直改 | 124 | `Band9-Analog-v1.0.8.face` | `lua/main.lua` | 17287B | 5545B | 自研 build.py / — |
| 已接入课程提醒 | ✅ 可直改 | 124 | `Band9-Class-v1.0.14.face` | `lua/main.lua` | 17287B | 3717B | 自研 build.py / — |
| 已接入课程提醒 | 🟡 截短后可改 | 124 | `Band9-Class-v1.0.15.face` | `lua/main.lua` | 17287B | 2780B | 自研 build.py / — |
| 已接入课程提醒 | 🟡 截短后可改 | 739 | `Band9-Monika-EV-v1.0.0.face` | `_lua/monika/monika.lua` | 31789B | 396B | gitee.com/sf-yuzifu/Monika / — |
| 已接入课程提醒 | 🟡 截短后可改 | 739 | `Band9-Monika-EV-v1.0.1.face` | `_lua/monika/monika.lua` | 31789B | 187B | — / — |
| 已接入课程提醒 | 🟡 截短后可改 | 739 | `Band9-Monika-EV-v1.1.0.face` | `_lua/monika/monika.lua` | 31789B | 120B | gitee.com/sf-yuzifu/Monika / — |
| 已接入课程提醒 | 🟡 截短后可改 | 739 | `Band9-Monika-EV-v1.2.0.face` | `_lua/monika/monika.lua` | 31895B | 120B | — / — |
| 已接入课程提醒 | 🟡 截短后可改 | 52 | `Band9-Oneline-v1.0.1.face` | `lua/main.lua` | 13616B | 2896B | 自研 build.py / — |
| 已接入课程提醒 | 🟡 截短后可改 | 52 | `Band9-Quartz-v1.0.13.face` | `lua/main.lua` | 13616B | 2229B | 自研 build.py / — |
| 待改造 | ✅ 可直改 | 124 | `Band9-Smash-v1.0.0.face` | `lua/main.lua` | 17287B | 5710B | github.com/m0tral/MiWatchLuaWatchfaces … / 未声明 |
| 待改造 | ✅ 可直改 | 124 | `Band9-TempControl-Large-v1.0.0.face` | `lua/main.lua` | 17287B | 6546B | github.com/m0tral/MiWatchLuaWatchfaces … / 未声明 |
| 待改造 | 🟡 截短后可改 | 197 | `Band9-Daymatter-v1.0.0.face` | `_lua/daymatter/daymatter.lua` | 14369B | 2B | github.com/sf-yuzifu/Daymatter_Watchfac… / 未声明 |
| 待改造 | 🟡 截短后可改 | 151 | `Band9-Expenses-v1.0.0.face` | `lua/main.lua` | 39168B | 2B | github.com/hassan-xsf/band-face-pack / MIT |
| 待改造 | 🟡 截短后可改 | 293 | `Band9-FlappyBird-v1.0.0.face` | `lua/main.lua` | 18816B | 2B | github.com/hassan-xsf/band-face-pack / MIT |
| 待改造 | 🟡 截短后可改 | 739 | `Band9-Monika-v1.0.0.face` | `_lua/monika/monika.lua` | 31789B | 2B | gitee.com/sf-yuzifu/Monika / — |
| 待改造 | 🟡 截短后可改 | 205 | `Band9-Stride-v1.0.0.face` | `lua/main.lua` | 24872B | 2B | github.com/hassan-xsf/band-face-pack / MIT |
| 待改造 | 🟡 截短后可改 | 52 | `Band9-TempControl-v1.0.0.face` | `lua/main.lua` | 13616B | 2875B | github.com/m0tral/MiWatchLuaWatchfaces … / 未声明 |
| 待改造 | 🟡 截短后可改 | 124 | `Band9-TicTacToe-v1.0.0.face` | `lua/main.lua` | 17287B | 2B | github.com/hassan-xsf/band-face-pack / MIT |
| 待改造 | 🔶 待逐个分析 | 1500 | `Band9-EXMars-v1.1.0.face` | `_lua/mars3/smash.lua` | 683B | 1B | github.com/NineBomb/EXMars / AGPL-3.0 |
| 待改造 | 🔶 待逐个分析 | 1445 | `Band9-EXMars-v2.0.0.face` | `_lua/SmoothlyLighttop/SmoothlyLight.lua` | 630B | 1B | github.com/NineBomb/EXMars / AGPL-3.0 |
| 待改造 | 🔶 待逐个分析 | 1472 | `Band9-EXMars-v3.0.0.face` | `_lua/mars3/smash.lua` | 625B | 1B | github.com/NineBomb/EXMars / AGPL-3.0 |
| 待改造 | ❌ 非 Lua 表盘 | 124 | `Band9-Probe-v1.0.1.face` | — | — | — | 自研 build.py / — |
| 不合适·已淘汰 | 🟡 截短后可改 | 1740 | `Band9-MonikaDefault-v1.0.0.face` | `_lua/monika/monika.lua` | 15245B | 1B | github.com/sf-yuzifu/Monika/releases/1.0.0 / GPL-3.0 |
| 不合适·已淘汰 | 🔶 需解压后改 | 3791 | `Band9-WatchDripGraph-v1.0.0.face` | `lua/image.lua` | 899B | 1B | github.com/miguelavh/LUA_Watchdrip_Watc… / 未声明 |
| 不合适·已淘汰 | ❌ 非 Lua 表盘 | 1069 | `Band9-AnalogFull-v1.0.0.face` | — | — | — | github.com/Vadim170/miband9-minimal-analog / 未声明 |
| 不合适·已淘汰 | ❌ 非 Lua 表盘 | 200 | `Band9-DaZiQingXi-v1.0.0.face` | — | — | — | github.com/Jovines/tsukimi-dango-watchf… / 未声明 |
| 不合适·已淘汰 | ❌ 非 Lua 表盘 | 160 | `Band9-FuGuShuMa-v1.0.0.face` | — | — | — | github.com/Jovines/tsukimi-dango-watchf… / 未声明 |
| 不合适·已淘汰 | ❌ 非 Lua 表盘 | 199 | `Band9-TongQinYiBiao-v1.0.0.face` | — | — | — | github.com/Jovines/tsukimi-dango-watchf… / 未声明 |

## 三、状态口径

| state | 含义 | 谁维护 |
|---|---|---|
| `candidate` | 待改造，已确认技术可行 | 扫描默认值 |
| `in_progress` | 正在注入课程提醒 | Worker 认领时置位 |
| `adapted` | 已注入且 luac 校验通过，有截图 | Worker 交付时置位 |
| `installed` | 已上真机验证过 | Leader 装机后置位 |
| `rejected` | 放弃（非 Lua / 槽太小 / 代码难改） | 评估人置位 |
