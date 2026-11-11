#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""face_inventory.py —— 表盘包盘点与分类台账

用法:
    python3 tools/face_inventory.py                 # 扫描 dist/Band9 并刷新台账
    python3 tools/face_inventory.py --dir dist/Band9

产出:
    data/face-registry.json     机读权威台账（state 字段由人/Worker 维护，扫描不覆盖）
    FACE-STATUS.md              人读分类清单

判定口径与 /tmp/evff-course/make.py 的 find_lua_block 完全一致（已在 Monika 包实测通过）。
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

# 实测注入量：数据层 3051B + UI 段 652B
INJECT_EST = 3703
# Monika 包实测：截短 71 条提示字符串可腾出 3815B，按 4000B 作为乐观上界
SHORTEN_MAX = 4000

VERDICT_LABEL = {
    "ready": "✅ 可直改",
    "ready_shorten": "🟡 截短后可改",
    "hard_compress": "🔶 需解压后改",
    "hard": "🔶 待逐个分析",
    "hard_small": "❌ 槽太小",
    "no_lua": "❌ 非 Lua 表盘",
}
VERDICT_ORDER = ["ready", "ready_shorten", "hard_compress", "hard", "hard_small", "no_lua"]

STATE_LABEL = {
    "candidate": "待改造",
    "in_progress": "改造中",
    "adapted": "已接入课程提醒",
    "installed": "已上真机验证",
    "rejected": "不合适·已淘汰",
}


def find_lua_blocks(d):
    """识别包内所有可注入的 lua 块（与 make.py 同口径）。"""
    out, seen = [], set()
    for m in re.finditer(rb"[A-Za-z0-9_./\-]{1,80}\.lua", d):
        ns = m.start()
        hs = ns - 21                      # 块头：type(1)+size(3)+nlen(1)+16B+name(nlen)
        if hs < 0:
            continue
        size = int.from_bytes(d[hs + 1:hs + 4], "little")
        nlen = d[hs + 4]
        name = d[ns:ns + nlen]
        off = ns + nlen
        if name != m.group(0) or off + size > len(d) or size < 64:
            continue
        content = d[off:off + size]
        # 明文 Lua 判据：头部可打印率高 + 含函数关键字。
        # 不能只查 `local `——部分包（如 EXMars 的 _lua/mars3/smash.lua）
        # 主块开头是注释/表定义，`local ` 出现在更后面，会被漏掉。
        head = content[:800]
        printable = sum(1 for c in head if 32 <= c < 127 or c in (9, 10, 13))
        if not head or printable < len(head) * 0.85:
            continue                      # 加密/字节码，无明文可改
        if b"function" not in content[:4000]:
            continue
        if (name, off) in seen:
            continue
        seen.add((name, off))
        stripped = content.rstrip(b" \r\n")
        out.append({
            "name": name.decode("utf-8", "replace"),
            "header": hs, "type": d[hs], "size": size, "off": off,
            "used": len(stripped), "free": size - len(stripped),
            "crlf": content.count(b"\r\n") > 0,
        })
    return out


def grade(blocks, total):
    if not blocks:
        return "no_lua", "无 lua 块：纯资源表盘，无法注入课程提醒"
    extra = f"（包内共 {len(blocks)} 个 lua 块，取 slot 最大者（修复前误取 free 最大，退化到最小块） `{{}}`）" if len(blocks) > 1 else ""
    # ① 有块余量直接够 → 可直改
    fit = [b for b in blocks if b["free"] >= INJECT_EST]
    if fit:
        return "ready", f"余量 {fit[0]['free']}B ≥ 注入 {INJECT_EST}B，可直接注入" + \
            (extra.format(fit[0]["name"]) if extra else "")
    b = max(blocks, key=lambda x: x["size"])
    free, size, used = b["free"], b["size"], b["used"]
    ex = extra.format(b["name"]) if extra else ""
    # ② 槽位本身装得下，靠截短腾空间
    max_save = min(SHORTEN_MAX, int(used * 0.5))
    if size >= INJECT_EST and free + max_save >= INJECT_EST:
        return "ready_shorten", f"余量 {free}B，截短可腾 ~{max_save}B 后塞入 {INJECT_EST}B" + ex
    # ③ 大包 + 小槽 = 块结构非标准（二次压缩），不能当"可直改"
    if total > 2_000_000 and size < 30_000:
        return "hard_compress", f"{total // 1024}KB 大包却只解析出 {size}B 的 lua 槽，疑似二次压缩，需先定位真实 lua 段" + ex
    if size < INJECT_EST:
        return "hard", f"块槽 {size}B < 注入 {INJECT_EST}B，块结构非标准，需逐个读代码" + ex
    return "hard", f"余量 {free}B / 槽 {size}B，需逐个分析" + ex


def scan(root):
    rows = {}
    for p in sorted(glob.glob(os.path.join(root, "*.face"))):
        fn = os.path.basename(p)
        d = open(p, "rb").read()
        blocks = find_lua_blocks(d)
        verdict, why = grade(blocks, len(d))
        fit = [b for b in blocks if b["free"] >= INJECT_EST]
        big = (fit[0] if fit else max(blocks, key=lambda x: x["size"])) if blocks else None
        rows[fn] = {
            "bytes": len(d),
            "kb": round(len(d) / 1024),
            "magic_ok": d[:4].hex() in ("5aa53412", "12a5555a"),
            "verdict": verdict,
            "reason": why,
            "nLuaBlocks": len(blocks),
            "lua": None if not big else {
                "name": big["name"], "slot": big["size"],
                "used": big["used"], "free": big["free"], "crlf": big["crlf"],
            },
        }
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="dist/Band9")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上两级）")
    args = ap.parse_args()

    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    face_dir = os.path.join(root, args.dir)
    if not os.path.isdir(face_dir):
        sys.exit(f"[err] 目录不存在：{face_dir}")

    reg_path = os.path.join(root, "data", "face-registry.json")
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    old = {}
    if os.path.exists(reg_path):
        try:
            old = json.load(open(reg_path)).get("faces", {})
        except Exception:
            pass

    fresh = scan(face_dir)
    merged = {}
    for fn, tech in fresh.items():
        prev = old.get(fn, {})
        merged[fn] = {
            **tech,
            # 人工/Worker 维护字段：扫描不覆盖
            "state": prev.get("state", "candidate"),
            "source": prev.get("source", ""),
            "license": prev.get("license", ""),
            "screenshot": prev.get("screenshot", ""),
            "evVersion": prev.get("evVersion", ""),
            "realDeviceRound": prev.get("realDeviceRound", 0),
            "note": prev.get("note", ""),
        }
    # 保留已从目录移走的条目（历史记录）
    for fn, prev in old.items():
        if fn not in merged:
            merged[fn] = {**prev, "missing": True}

    reg = {
        "updatedAt": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S+0800"),
        "dir": args.dir,
        "count": len(fresh),
        "totalMB": round(sum(v["bytes"] for v in fresh.values()) / 1048576, 1),
        "faces": merged,
    }
    json.dump(reg, open(reg_path, "w"), ensure_ascii=False, indent=1)

    # ── 生成人读清单 ──
    by_verdict = {k: [] for k in VERDICT_ORDER}
    for fn, v in merged.items():
        if v.get("missing"):
            continue
        by_verdict[v["verdict"]].append((fn, v))

    L = []
    L.append("# 开源表盘分类台账（FACE-STATUS）\n")
    L.append(f"> 自动生成于 {reg['updatedAt']} · 共 **{reg['count']}** 个包 / "
             f"**{reg['totalMB']}MB** · 机读权威：`data/face-registry.json`\n")
    L.append("> 本表由 `python3 tools/face_inventory.py` 刷新；`state` 列由人或 Worker 维护，扫描不会覆盖。\n")
    L.append("## 一、按可改造性分类\n")
    L.append("| 判定 | 数量 | 包体积合计 | 含义 |")
    L.append("|---|---|---|---|")
    for k in VERDICT_ORDER:
        items = by_verdict[k]
        if not items:
            continue
        mb = sum(v["bytes"] for _, v in items) / 1048576
        desc = {
            "ready": "lua 槽余量够直接插 3.7KB 注入段",
            "ready_shorten": "先截短包内提示字符串腾空间，再注入",
            "hard_compress": "包内二次压缩，需先定位解压后的 lua 块",
            "hard": "结构特殊，需逐个读代码",
            "hard_small": "lua 槽物理空间不足",
            "no_lua": "纯资源表盘，无 lua 运行逻辑，放弃",
        }[k]
        L.append(f"| {VERDICT_LABEL[k]} | {len(items)} | {mb:.1f}MB | {desc} |")
    L.append("")
    L.append("## 二、明细\n")
    L.append("| 状态 | 判定 | KB | 包名 | lua 块 | 槽位 | 余量 | 来源/许可 |")
    L.append("|---|---|---|---|---|---|---|---|")
    order_state = ["installed", "adapted", "in_progress", "candidate", "rejected"]
    flat = [x for k in VERDICT_ORDER for x in by_verdict[k]]
    flat.sort(key=lambda x: (order_state.index(x[1].get("state", "candidate"))
                             if x[1].get("state") in order_state else 9,
                             VERDICT_ORDER.index(x[1]["verdict"]), x[0]))
    for fn, v in flat:
        lua = v.get("lua") or {}
        src = v.get("source") or "—"
        lic = v.get("license") or "—"
        if len(src) > 42:
            src = src[:39] + "…"
        L.append(f"| {STATE_LABEL.get(v.get('state'), v.get('state'))} | "
                 f"{VERDICT_LABEL.get(v['verdict'], v['verdict'])} | {v['kb']} | `{fn}` | "
                 f"{('`' + lua['name'] + '`') if lua else '—'} | "
                 f"{str(lua.get('slot', '—')) + 'B' if lua else '—'} | "
                 f"{str(lua.get('free', '—')) + 'B' if lua else '—'} | {src} / {lic} |")
    L.append("")
    L.append("## 三、状态口径\n")
    L.append("| state | 含义 | 谁维护 |")
    L.append("|---|---|---|")
    L.append("| `candidate` | 待改造，已确认技术可行 | 扫描默认值 |")
    L.append("| `in_progress` | 正在注入课程提醒 | Worker 认领时置位 |")
    L.append("| `adapted` | 已注入且 luac 校验通过，有截图 | Worker 交付时置位 |")
    L.append("| `installed` | 已上真机验证过 | Leader 装机后置位 |")
    L.append("| `rejected` | 放弃（非 Lua / 槽太小 / 代码难改） | 评估人置位 |")
    L.append("")
    open(os.path.join(root, "FACE-STATUS.md"), "w").write("\n".join(L))

    c = Counter(v["verdict"] for v in fresh.values())
    print(f"[inventory] {len(fresh)} 个包 / {reg['totalMB']}MB → {reg_path}")
    print("[inventory] " + " · ".join(f"{VERDICT_LABEL[k]} {c[k]}" for k in VERDICT_ORDER if c[k]))
    print(f"[inventory] 人读清单 → {os.path.join(root, 'FACE-STATUS.md')}")


if __name__ == "__main__":
    main()
