#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# preview_emulator.sh —— Lua 真表盘在 Vela 模拟器「一键出画」
#
# 用法：
#   bash tools/preview_emulator.sh                       # 默认：xiaomi_band，输出到 docs/screenshots/
#   bash tools/preview_emulator.sh --out /tmp/a.png      # 指定带壳截图路径
#   bash tools/preview_emulator.sh --no-up               # 复用已在跑的实例（省 25s）
#   bash tools/preview_emulator.sh --keep                # 跑完不停机，留给下一轮看画面
#   bash tools/preview_emulator.sh --face /path/x.face   # 指定 resource.bin 的 .face 基底
#
# 一条命令做完：取 EvFleet 票据 → 起/复用默认实例 → 等 guest 就绪 → 铺完整表盘包
#   → 前台常驻 miwear 宿主 → dd 取帧 → RGB565 解码 → 套机身外壳 → 归还票据。
#
# 铁律（2026-11-11 实测）：
#   * 只允许 AVD=xiaomi_band（默认实例）；evc-xiaomi_band-buddy-1 永不触碰。
#   * 绝不 `adb reboot`（qemu 上等于终止进程）；重载只走 `vela down` + `vela up`。
#   * EvFleet 票据 **5 分钟硬上限**，超时会被 reconcile 连带杀掉实例；本脚本
#     自己取票、全流程 < 2 分钟、trap 里无条件归还。
#   * 「帧缓冲全黑/纯色」不等于渲染链不通：必须看 宿主进程 / Lua stdout / 取帧通道 三个信号。
# ---------------------------------------------------------------------------
set -Eeuo pipefail
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${EVFF_WORK:-/tmp/evff-preview}"
AVD="xiaomi_band"
FACE_ID="167210065"
ADB="/opt/homebrew/bin/adb"
ADB_SERVER_PORT=5038                 # 独立 daemon，隔离同机其它会话对 5037 的重启
RPK_DEFAULT="/Users/Banner/Documents/guomengtao/ev/class-schedule/dist/com.application.watch.classschedule.release.1.9.197.rpk"
VELA_SRC="/Users/Banner/Documents/guomengtao/ev/ev-emu-cli"

OUT=""
FACE=""
NO_UP=0
KEEP=0
NO_RPK=0
PURPOSE="EVFF Lua表盘预览一键出画"

while [ $# -gt 0 ]; do
  case "$1" in
    --out)    OUT="$2"; shift 2;;
    --face)   FACE="$2"; shift 2;;
    --no-up)  NO_UP=1; shift;;
    --keep)   KEEP=1; shift;;
    --no-rpk) NO_RPK=1; shift;;
    --avd)    AVD="$2"; shift 2;;
    -h|--help) sed -n '2,24p' "$0"; exit 0;;
    *) echo "[EVFF] 未知参数 $1" >&2; exit 2;;
  esac
done

# ── 硬闸：实例边界 ──────────────────────────────────────────────────────────
if [ "$AVD" != "xiaomi_band" ]; then
  echo "[EVFF] ⛔ 拒绝：本命令只允许默认实例 xiaomi_band（收到 $AVD）。" >&2
  echo "       确需其它 AVD 请走 [[NEED]] 由 Leader 转用户拍板，不得自行启动/改 manifest。" >&2
  exit 2
fi

STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="${OUT:-$REPO/docs/screenshots/EVFF-Lua运行帧-带壳-$STAMP.png}"
mkdir -p "$WORK" "$REPO/docs/screenshots" "$(dirname "$OUT")"
LOG="$WORK/run-$STAMP.log"

log() { printf '[EVFF %s] %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG"; }
die() { log "⛔ $*"; exit 1; }

command -v vela  >/dev/null || die "缺 vela（~/.local/bin/vela）"
command -v fleet >/dev/null || die "缺 fleet"
[ -x "$ADB" ]                 || die "缺 $ADB"
[ -f "$VELA_SRC/vela.py" ]    || die "缺 $VELA_SRC/vela.py（套壳用）"

TICKET=""
IID=""
cleanup() {
  rc=$?
  trap - EXIT
  if [ -n "$TICKET" ]; then
    fleet release "$TICKET" >/dev/null 2>&1 && log "票据 $TICKET 已归还" || log "票据 $TICKET 归还失败（可能已被硬上限回收）"
  fi
  if [ "$KEEP" -eq 0 ] && [ "$rc" -eq 0 ]; then
    log "提示：实例保留（TTL 到点自动回收）；如需立刻停：vela down $IID"
  fi
  log "日志 $LOG  退出码 $rc"
  exit "$rc"
}
trap cleanup EXIT

# ── 1) 票据（必须在本脚本内取，且 5 分钟内跑完） ────────────────────────────
log "① 申请 EvFleet 胶囊屏票据（5 分钟硬上限）"
TJSON="$(fleet request --shapes capsule --purpose "$PURPOSE" --wait 90 --json 2>&1)" || die "fleet request 失败：$TJSON"
TICKET="$(printf '%s' "$TJSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["ticket"]["ticket"])')" || die "解析票据失败：$TJSON"
log "   票据 $TICKET 已到手"

# ── 2) 起机 / 复用 ─────────────────────────────────────────────────────────
IID="$AVD-11000"
if [ "$NO_UP" -eq 1 ] && vela ls 2>/dev/null | grep -q "^$AVD-"; then
  log "② 复用已在跑的实例（--no-up）"
else
  log "② vela up $AVD（绝不 adb reboot）"
  if [ "$NO_RPK" -eq 0 ] && [ -f "$RPK_DEFAULT" ]; then
    vela up "$AVD" --rpk "$RPK_DEFAULT" --wait --ttl 10m --purpose "$PURPOSE" 2>&1 | tee -a "$LOG" || die "vela up 失败"
  else
    vela up "$AVD" --wait --ttl 10m --purpose "$PURPOSE" 2>&1 | tee -a "$LOG" || die "vela up 失败"
  fi
fi
LS="$(vela ls 2>&1)"
IID="$(printf '%s' "$LS" | grep "^$AVD-" | awk '{print $1}' | head -1)"
[ -n "$IID" ] || die "vela ls 里找不到 $AVD 实例"
CONSOLE="${IID##*-}"
ADBPORT=$((CONSOLE + 1))
P="127.0.0.1:$ADBPORT"
log "   实例 $IID · console=$CONSOLE · adb=$P · 屏=192x490 RGB565"

# ── 3) 等 guest 完全就绪（≥20s，8s 拉宿主必失败） ───────────────────────────
log "③ 等 guest 就绪 22s"
sleep 22

# ── 4) 独立 adb daemon，清残留端口后只连当前实例 ────────────────────────────
ADBC="$ADB -P $ADB_SERVER_PORT"
for x in 11001 11003 11005; do $ADBC disconnect "127.0.0.1:$x" >/dev/null 2>&1 || true; done
$ADBC connect "$P" 2>&1 | tee -a "$LOG"
$ADBC devices 2>&1 | tee -a "$LOG"
$ADBC -s "$P" shell "echo EVFF_GUEST_OK" 2>&1 | tee -a "$LOG" || die "guest 不响应 adb"

# ── 5) 造包：resource.bin / preview.bin / config.json / lua/*.lua / 注册表 ────
log "④ 生成完整表盘包（ID=$FACE_ID，type=1/in_use=1）"
D="/data/app/watchface/market/$FACE_ID"
DEP="$WORK/deploy"; mkdir -p "$DEP/lua"

if [ -z "$FACE" ]; then
  for c in \
    "$REPO/dist/Band9/Band9-Oneline-v1.0.1.face" \
    "$REPO/dist/_source/Band9/EV-Class-Face-Band9-v1.0.0.face" \
    "/Users/Banner/Documents/WorkBuddy-log/Tom/2026-11-10-10-54-34/表盘成品-DigitalTime-MiBand8Pro.patched.face"; do
    [ -f "$c" ] && FACE="$c" && break
  done
fi
if [ -n "$FACE" ] && [ -f "$FACE" ]; then
  cp "$FACE" "$DEP/resource.bin"
else
  python3 - <<'PY'
from pathlib import Path
b=bytearray(128)
b[0:4]=bytes((0x5a,0xa5,0x34,0x12))
b[0x20:0x24]=(128).to_bytes(4,'little')
Path('/tmp/evff-preview/deploy/resource.bin').write_bytes(b)
PY
  log "   ⚠️ 未找到 .face 基底，使用最小 128B 容器（无图片资源时够用）"
fi
python3 - "$DEP/resource.bin" "$FACE_ID" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); b=bytearray(p.read_bytes())
if bytes(b[:4]) != bytes((0x5a,0xa5,0x34,0x12)):
    raise SystemExit(f"不是 .face 容器：magic={b[:4].hex()}")
b[5]=10                                  # ID 长度字节，必须补 10
i = sys.argv[2].encode()
b[40:50]=b'\x00'*10; b[40:40+len(i)]=i  # 0x28 偏移写表盘 ID
p.write_bytes(b)
print(f"   resource.bin {len(b)}B magic={b[:4].hex()} bytes[5]={b[5]} id={bytes(b[40:50])}")
PY

cat > "$DEP/config.json" <<'JSON'
{"theme_id":"0","color_group_count":"0","color_group_index":"0","pos_table_index":"0","pos_table_count":"0","recolor":"0","color_hex":"0","cur_photo_idx":"-1","photo_list":[],"portrait_album_list":[],"pointer_cfg":{"layout_uid":"","slot_uid":"","ref_id":""},"dial_cfg":{"layout_uid":"","slot_uid":"","ref_id":""},"data_item_cfg":[],"font_item_cfg":[]}
JSON

# 纯 LVGL 最小脚本：不加载图片、不用 reloader；首行 print 用来证明 Lua 真的被执行
cat > "$DEP/lua/main.lua" <<'LUA'
-- EVFF preview chain · minimal LVGL watchface (real runtime frame)
print("EVFF_PREVIEW_LUA_ENTER")
local lvgl = require("lvgl")
local W = lvgl.HOR_RES()
local H = lvgl.VER_RES()
local scr = lvgl.Object(nil, {
    w = W, h = H, bg_color = 0x0B2036,
    bg_opa = lvgl.OPA(100), border_width = 0, pad_all = 0
})
scr:clear_flag(lvgl.FLAG.SCROLLABLE)
local font = lvgl.BUILTIN_FONT.MONTSERRAT_14
pcall(function() font = lvgl.BUILTIN_FONT.MONTSERRAT_28 or font end)
local label = lvgl.Label(scr, {
    text = "EVFF OK", align = lvgl.ALIGN.CENTER,
    text_font = font, text_color = 0xFFFFFF
})
print("EVFF_PREVIEW_LOADED", W, H, tostring(label))
LUA
# 两套入口命名都铺（band9 固件见过 main_themeN.lua，10Pro 用 main.lua）
for n in main_theme1 main_theme2 main_theme3; do cp "$DEP/lua/main.lua" "$DEP/lua/$n.lua"; done

# preview.bin / uidmap.map：优先从 guest 内置表盘取真文件，失败则占位
$ADBC -s "$P" pull /data/app/watchface/builtin/362120001/preview.bin "$DEP/preview.bin" >/dev/null 2>&1 \
  || printf 'EVFFPREVIEW' > "$DEP/preview.bin"
$ADBC -s "$P" pull /data/app/watchface/builtin/362120001/uidmap.map "$DEP/uidmap.map" >/dev/null 2>&1 || true
$ADBC -s "$P" pull /data/app/watchface/watchface_list.json "$DEP/watchface_list.base.json" >/dev/null 2>&1 || true
python3 - "$DEP/watchface_list.base.json" "$DEP/watchface_list.json" "$FACE_ID" <<'PY'
import json, sys
from pathlib import Path
src, dst, fid = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.loads(Path(src).read_text())
except Exception:
    d = {"update_info": {"firmware_version": "0.0.1", "update_complete": "1"}, "watchface_list": []}
L = d.get("watchface_list", [])
for x in L: x["in_use"] = "0"          # 其余全部置 0，否则会走内置盘路径
ent = {"id": fid, "name": "EVFF-Preview", "name_translation": [], "version": "0",
       "type": "1", "in_use": "1", "is_delete": "0", "editable": "0",
       "support_album": "0", "support_AOD": "0", "support_dark_mode": "0", "sku": "0",
       "power_consumption": "3", "support_literal": "0", "theme_count": "1",
       "color_table": [], "color_group_table": [], "trial_period": "0",
       "theme_type_info": [{"name": "", "type": "0"}]}
L = [x for x in L if str(x.get("id")) != fid] + [ent]
d["watchface_list"] = L
Path(dst).write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n")
print(f"   watchface_list.json entries={len(L)} type1={[x['id'] for x in L if x['type']=='1']} in_use1={[x['id'] for x in L if x['in_use']=='1']}")
PY

# ── 6) 推包 ────────────────────────────────────────────────────────────────
log "⑤ 推包到 $D"
$ADBC -s "$P" shell "mkdir -p $D"  >/dev/null 2>&1 || $ADBC -s "$P" shell "mkdir $D" >/dev/null 2>&1 || true
$ADBC -s "$P" shell "mkdir -p $D/lua" >/dev/null 2>&1 || $ADBC -s "$P" shell "mkdir $D/lua" >/dev/null 2>&1 || true
for f in resource.bin preview.bin config.json uidmap.map; do
  [ -f "$DEP/$f" ] && $ADBC -s "$P" push "$DEP/$f" "$D/$f" >/dev/null 2>&1 \
    && log "   + $f" || log "   ! $f 推送跳过"
done
for f in main.lua main_theme1.lua main_theme2.lua main_theme3.lua; do
  $ADBC -s "$P" push "$DEP/lua/$f" "$D/lua/$f" >/dev/null 2>&1 || die "$f 推送失败"
done
$ADBC -s "$P" push "$DEP/watchface_list.json" /data/app/watchface/watchface_list.json >/dev/null 2>&1 || die "注册表推送失败"
log "   + lua/（main.lua + main_theme1~3）+ watchface_list.json"

# ── 7) 前台常驻宿主 ────────────────────────────────────────────────────────
# 关键：`adb shell miwear` 这条连接必须一直活着，宿主才不被回收。
# 不能用 ( cmd & ) 嵌套子 shell —— 子 shell 立刻退出后 adb 连接会被收走（实测
# 11:18 那轮 stdout=0B、ps 里只剩 miwear_activity_service、帧全 0）。
# 必须是当前 shell 的直接后台作业 + 保留 PID，并在整个取帧期间保持脚本存活。
MWLOG="$WORK/miwear-$STAMP.log"
: > "$MWLOG"
# 底缘点一下唤醒显示层（vela shot 同款），不改变画面内容
$ADBC -s "$P" emu event mouse 96 487 0 1 >/dev/null 2>&1 || true
$ADBC -s "$P" emu event mouse 96 487 0 0 >/dev/null 2>&1 || true
HOST_OK=0
for attempt in 1 2 3; do
  log "⑥ 前台常驻 miwear 宿主（第 $attempt 次尝试）"
  $ADBC -s "$P" shell "miwear" > "$MWLOG" 2>&1 &
  MW_PID=$!
  sleep 10
  if $ADBC -s "$P" shell ps 2>&1 | grep -q 'miwear-pm'; then HOST_OK=1; break; fi
  log "   ⚠️ 宿主未起（miwear-pm 缺席），3s 后重试"
  kill "$MW_PID" >/dev/null 2>&1 || true
  sleep 3
done
[ "$HOST_OK" -eq 1 ] || die "miwear 宿主三次均未常驻（查 $LOG 与 $MWLOG）"
sleep 4                              # 再给 LVGL 4s 画完
log "   信号1 宿主进程："
$ADBC -s "$P" shell ps 2>&1 | grep -i miwear | tee -a "$LOG" || log "   （无 miwear！）"
log "   信号2 Lua stdout："
head -12 "$MWLOG" 2>/dev/null | tee -a "$LOG"
log "   stdout 字节数 $(wc -c < "$MWLOG")"

# ── 8) 取帧 + 解码（dd 到 guest 文件再 pull；exec-out 直读必 error: closed） ──
FRAME=$((192 * 490 * 2))
log "⑦ 信号3 取帧 dd → pull → RGB565 解码"
$ADBC -s "$P" shell "dd if=/dev/fb0 of=/data/fbsnap.bin bs=$FRAME count=1" 2>&1 | tee -a "$LOG"
$ADBC -s "$P" pull /data/fbsnap.bin "$WORK/frame.raw" 2>&1 | tee -a "$LOG"
python3 - "$WORK/frame.raw" "$WORK/frame.png" "$WORK/stats.json" <<'PY'
import sys, json, struct, zlib
from pathlib import Path
src, out, stats = sys.argv[1], sys.argv[2], sys.argv[3]
w, h, bpp = 192, 490, 2
d = Path(src).read_bytes()[:w*h*bpp]
rgba = bytearray(w*h*4)
for i in range(0, len(d)-1, 2):
    v = d[i] | (d[i+1] << 8)
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    j = (i//2)*4
    rgba[j:j+4] = bytes((r*255//31, g*255//63, b*255//31, 255))
def chunk(t, x): return struct.pack('>I', len(x)) + t + x + struct.pack('>I', zlib.crc32(t+x) & 0xffffffff)
scan = b''.join(b'\x00' + bytes(rgba[y*w*4:(y+1)*w*4]) for y in range(h))
Path(out).write_bytes(b'\x89PNG\r\n\x1a\n'
    + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    + chunk(b'IDAT', zlib.compress(scan, 6)) + chunk(b'IEND', b''))
nz = sum(1 for b in d if b)
colors = len({d[i:i+2] for i in range(0, len(d)-1, 2)})
s = {"bytes": len(d), "nonzero": nz, "nonzero_ratio": round(nz/max(1, len(d)), 6),
     "sampled_nonzero": sum(1 for b in d[::37] if b), "sampled_total": len(d[::37]),
     "colors": colors, "png": out}
Path(stats).write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n")
print("   " + json.dumps(s, ensure_ascii=False))
PY

# ── 9) 套机身外壳（与 vela shot 同一套 skinframe，走官方产物证明） ───────────
log "⑧ 套机身外壳 → $OUT"
cp "$WORK/frame.png" "$WORK/framed.png"
SKIN="$(python3 - "$WORK/framed.png" "$AVD" "$IID" <<'PY'
import sys
sys.path.insert(0, "/Users/Banner/Documents/guomengtao/ev/ev-emu-cli")
import vela
png, avd, iid = sys.argv[1], sys.argv[2], sys.argv[3]
skin, why = vela.frame_in_place(png, avd, (192, 490), None,
                                serial="emulator-" + iid.rsplit("-", 1)[-1],
                                tool="ev-class-face/tools/preview_emulator.sh")
print(f"{skin or 'NONE'}: {why}")
PY
)"
log "   套壳结果：$SKIN"
cp "$WORK/framed.png" "$OUT"
# 归档时把 ev-shot/1 产物证明一起放到图旁边，否则全局截图闸会拒绝提交
if [ -f "$WORK/framed.provenance.json" ]; then
  cp "$WORK/framed.provenance.json" "${OUT%.png}.provenance.json"
  log "   产物证明 ${OUT%.png}.provenance.json"
fi

# ── 10) 验收判定：非零字节 + 颜色数 + Lua stdout ────────────────────────────
COLORS="$(python3 -c "import json;print(json.load(open('$WORK/stats.json'))['colors'])")"
STDOUT_BYTES="$(wc -c < "$MWLOG")"
log "⑨ 验收：colors=$COLORS stdout=${STDOUT_BYTES}B 带壳图=$OUT"
if [ "$COLORS" -lt 2 ]; then
  log "⛔ 帧仍是纯色（colors<2）：Lua 未出画。看 docs/预览链路恢复-20261111.md 失败排查表"
  exit 3
fi
log "✅ 出画完成"
