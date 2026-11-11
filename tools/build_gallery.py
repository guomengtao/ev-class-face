#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_gallery.py —— 一条命令生成「EV 表盘展示页」（docs/gallery/index.html）

三源合并（不猜、不造）：
  ① data/face-registry.json   台账：28 包的体积/来源/许可/注入状态（tools/face_inventory.py 刷新）
  ② gh release list/view       真实 asset 名、tag、下载直链（在线拉取，落 releaseCache 供离线兜底）
  ③ data/gallery.json          显式 verified 映射 + 预览图取证文件路径

准入铁律（主列表）：
  只有 gallery.json 的 verified[] 中「三项校验全过」的包才进主列表——
    a) registryKey 在台账里存在；
    b) 预览图取证文件真实存在（人眼已确认含课程行，courseRowText 留档）；
    c) releaseTag/releaseFace 在该 tag 的真实 asset 列表里（在线）或 releaseCache 里（离线）。
  缺任一项 → 该包降级进「候选 · 未达标」并写明缺什么；宁可主列表只有 1 条，也不凑数。

增量机制：后续 M1/M2/M3 交付新 EV 包后——
  1) python3 tools/face_inventory.py         # 刷新台账（若尚未入账）
  2) 在 data/gallery.json 的 verified[] 加一条显式映射（含取证图 + release asset）
  3) python3 tools/build_gallery.py          # 重跑即自动出现，页面数据全内联

用法：
  python3 tools/build_gallery.py             # 在线（拉 gh release，更新 releaseCache）
  python3 tools/build_gallery.py --offline   # 离线（只用 releaseCache + URL 兜底拼接）
  python3 tools/build_gallery.py --check     # 只校验并打印结果，不写文件
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "face-registry.json"
GALLERY_CFG = ROOT / "data" / "gallery.json"
OUT = ROOT / "docs" / "gallery" / "index.html"

KB = 1024
SIZE_BUCKETS = [
    ("<100KB", lambda b: b < 100 * KB),
    ("100~300KB", lambda b: 100 * KB <= b < 300 * KB),
    ("300~600KB", lambda b: 300 * KB <= b < 600 * KB),
    (">600KB", lambda b: b >= 600 * KB),
]

# ── 预览图来源三档（不许一律写「模拟器」）──────────────────────────────────
#   device   模拟器真帧：真跑模拟器跑出来的图（本项目的 preview_emulator.sh 只铺
#            自己的模板 lua、不执行改造包 lua，所以现状下这类基本为空——如实留档，不硬凑）
#   synthetic 合成渲染帧：底图=包内 RLE 预览块解码的 192×490 真立绘，文字=改造包
#            注入的课程分支实跑结果，套官方皮肤外壳。非设备实拍。
#   raw      包内预览原图：只有底图、无课程行 → 只能进候选区。
TIER_LABEL = {
    "device": "模拟器真帧",
    "synthetic": "合成渲染帧",
    "embedded": "包内预览原图（含课程行）",
    "raw": "包内预览原图（无课程行）",
}
TIER_DESC = {
    "device": "真跑模拟器渲染出的画面",
    "synthetic": "包内预览底图 + 注入逻辑实跑文案 + 官方皮肤外壳，非设备实拍",
    "embedded": "直接取 .face 包内预览块原图，课程行由包内原生渲染，未经模拟器、未合成",
    "raw": "包内自带预览图，只有底图、课程行没有",
}
# 主列表准入：只认 device / synthetic（raw 无课程行，进候选）
TIER_QUALIFIED = {"device", "synthetic", "embedded"}

# 台账 verdict → 人话（候选卡上直接展示，让 Tom 一眼看出能不能捞）
VERDICT_LABEL = {
    "ready": "ready · 槽位够，可直接注入",
    "ready_shorten": "ready_shorten · 需截短腾槽后注入",
    "no_lua": "no_lua · 无 Lua 块，不可注入",
    "hard": "hard · 余量极小，需重构",
    "hard_compress": "hard_compress · 需压缩重构",
}


def resolve_preview_tier(preview_path: Path, declared: str | None, key: str, warnings: list[str]) -> str:
    """定档：显式声明优先，但 device 声明必须有 provenance 佐证，否则降级。

    provenance 文件约定：<png>.provenance.json（与图同目录同名）。
    """
    prov = {}
    prov_path = preview_path.with_suffix(".provenance.json")
    if prov_path.exists():
        try:
            prov = json.loads(prov_path.read_text(encoding="utf-8"))
        except Exception:  # noqa
            prov = {}

    tier = (declared or "").strip()
    if tier and tier not in TIER_LABEL:
        warnings.append("%s：previewTier=%r 非法，忽略显式声明" % (key, tier))
        tier = ""

    if not tier:
        # 无显式声明 → 读 provenance 自动定档
        if prov:
            schema = str(prov.get("schema") or "")
            if prov.get("deviceReal") is True:
                tier = "device"
            elif "synthetic" in schema or prov.get("deviceReal") is False:
                tier = "synthetic"
        if not tier:
            tier = "raw"
            warnings.append("%s：无 previewTier 声明、无 provenance，按「包内预览原图」定档" % key)

    # 防冒充：声明 device 但 provenance 明确 deviceReal=false → 降级
    if tier == "device" and prov.get("deviceReal") is False:
        warnings.append("%s：声明「模拟器真帧」但 provenance 记录 deviceReal=false，已降级为合成渲染帧" % key)
        tier = "synthetic"
    if tier == "device" and not prov:
        warnings.append("%s：声明「模拟器真帧」但无 provenance 佐证，请补取证文件" % key)
    return tier


def log(*a):
    print("[gallery]", *a, file=sys.stderr)


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def now_bj() -> str:
    return datetime.now(timezone(__import__("datetime").timedelta(hours=8))).strftime(
        "%Y-%m-%dT%H:%M:%S+0800"
    )


def gh_json(args: list[str]) -> object:
    """gh <args> --json ... 返回解析后的 JSON；失败返回 None（静默降级）。"""
    cmd = ["gh"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            log("gh 失败（降级）:", " ".join(cmd), "->", r.stderr.strip()[:200])
            return None
        return json.loads(r.stdout)
    except Exception as e:  # noqa
        log("gh 异常（降级）:", repr(e))
        return None


def fetch_releases(repo: str, offline: bool, old_cache: dict) -> dict:
    """返回 {tag: {publishedAt, assets:{name:{size,url,state}}}}。在线成功即覆盖缓存。"""
    if offline:
        log("离线模式：使用 releaseCache（%d tag）" % len(old_cache))
        return old_cache

    tags = gh_json(["release", "list", "--repo", repo, "--json", "tagName,publishedAt"])
    cache: dict = {}
    if not tags:
        log("在线拉取 tag 列表失败 → 回落 releaseCache")
        return old_cache
    for t in tags:
        tag = t.get("tagName")
        if not tag:
            continue
        view = gh_json(["release", "view", tag, "--repo", repo, "--json", "publishedAt,assets"])
        if not view:
            continue
        assets = {}
        for a in view.get("assets", []):
            assets[a["name"]] = {
                "size": a.get("size"),
                "url": a.get("url"),
                "state": a.get("state"),
            }
        cache[tag] = {"publishedAt": view.get("publishedAt") or t.get("publishedAt"), "assets": assets}
    if not cache:
        log("在线拉取 assets 全失败 → 回落 releaseCache")
        return old_cache
    log("在线拉取 %d tag，asset 合计 %d" % (len(cache), sum(len(v["assets"]) for v in cache.values())))
    return cache


def model_of(filename: str) -> str:
    m = re.match(r"(Band\d+Pro|Band\d+)-", filename)
    return m.group(1) if m else "未知"


def size_bucket(b: int) -> str:
    for name, fn in SIZE_BUCKETS:
        if fn(b):
            return name
    return "未知"


def src_license_bucket(source: str, license_: str) -> str:
    """来源与许可 → 四选一：自研 / MIT / GPL / 未声明。"""
    if "自研" in source:
        return "自研"
    lic = (license_ or "").strip()
    if "MIT" in lic:
        return "MIT"
    if "GPL" in lic:  # 覆盖 GPL-3.0 / AGPL-3.0（同为 GPL 家族）
        return "GPL"
    return "未声明"


def has_class_reminder(f: dict) -> bool:
    """是否已接入课程提醒（注入了课程逻辑）。依据：evVersion 非空 或 note 含已内联 schedule_core。"""
    if (f.get("evVersion") or "").strip():
        return True
    if "schedule_core" in (f.get("note") or ""):
        return True
    return False


def kb_of(b: int) -> int:
    return round(b / KB)


def b64_data_uri(p: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def build(offline: bool, check: bool):
    missing_files = [p for p in (REGISTRY, GALLERY_CFG) if not p.exists()]
    if missing_files:
        log("致命：缺数据源", [str(p) for p in missing_files])
        sys.exit(2)

    registry = load_json(REGISTRY)
    cfg = load_json(GALLERY_CFG)
    faces = registry.get("faces", {})
    repo = cfg.get("repo", "guomengtao/ev-class-face")
    rel_base = cfg.get("releaseBase", "https://github.com/guomengtao/ev-class-face/releases/download")

    releases = fetch_releases(repo, offline, cfg.get("releaseCache", {}))

    verified_list = cfg.get("verified", [])
    verified_map = {v["registryKey"]: v for v in verified_list}

    # ── 主列表准入校验（三项全过才进）──────────────────────────────────────
    qualified: list[dict] = []
    warnings: list[str] = []
    for v in verified_list:
        key = v["registryKey"]
        reasons = []
        f = faces.get(key)
        if not f:
            reasons.append("台账无此包")
        prev = (ROOT / v["preview"]) if not v["preview"].startswith("/") else Path(v["preview"])
        tier = "raw"
        if not prev.exists():
            reasons.append("预览图取证文件缺失：" + v["preview"])
        else:
            tier = resolve_preview_tier(prev, v.get("previewTier"), key, warnings)
            if tier not in TIER_QUALIFIED:
                reasons.append("预览图仅为「%s」，无课程行" % TIER_LABEL[tier])
        tag = v.get("releaseTag")
        fa = v.get("releaseFace")
        rel = releases.get(tag) if tag else None
        asset = rel.get("assets", {}).get(fa) if rel else None
        if offline and not asset:
            # 离线兜底：允许拼 URL，但明确标注未在线校验（不冒充已验证）
            durl = "%s/%s/%s" % (rel_base, tag, fa)
            url_verified = False
            log("离线：%s 的 asset 不在缓存，URL 未在线校验" % key)
        elif not asset:
            reasons.append("Release %s 无 asset %s" % (tag, fa))
            durl = ""
            url_verified = False
        else:
            durl = asset.get("url") or "%s/%s/%s" % (rel_base, tag, fa)
            url_verified = True
            # 体积交叉校验：Release asset 与台账 bytes 差异 >1KB 记警告
            if asset.get("size") and f and abs(asset["size"] - f["bytes"]) > KB:
                warnings.append("%s：Release asset %dB 与台账 %dB 不一致" % (key, asset["size"], f["bytes"]))

        if reasons:
            warnings.append("%s 降级进候选区：%s" % (key, "；".join(reasons)))
            log("WARN", key, "降级：", "；".join(reasons))
            continue

        png_url = "%s/%s/%s" % (rel_base, tag, v.get("releasePng") or "")
        pub = (rel or {}).get("publishedAt") or registry.get("updatedAt") or now_bj()
        qualified.append({
            "key": key,
            "name": v.get("displayName") or key,
            "model": v.get("model") or model_of(key),
            "bytes": f["bytes"],
            "kb": kb_of(f["bytes"]),
            "source": f.get("source") or "—",
            "license": (f.get("license") or "未声明").strip() or "未声明",
            "reminder": "已接入",
            "verified": True,
            "preview": b64_data_uri(prev),
            "previewSrc": png_url,
            "previewTier": tier,
            "previewTierLabel": TIER_LABEL[tier],
            "previewTierDesc": TIER_DESC[tier],
            "recoverLevel": "-",
            "recoverLabel": "已达标",
            "download": durl,
            "urlVerified": url_verified,
            "courseRowText": v.get("courseRowText", ""),
            "evidence": v.get("classReminderEvidence", ""),
            "updated": pub,
            "updatedLabel": "Release " + str(tag),
            "note": f.get("note") or "",
        })

    qualified_keys = {q["key"] for q in qualified}

    # ── 候选区：台账其余全部，逐条写「为什么没进主列表」+ 可捞性判定 ──────────
    def base_of(k: str) -> str:
        """去掉 -v1.0.1.face 版本段，用于识别同系列（重复包检测）。"""
        return re.sub(r"-v\d[\d.]*\.face$", "", k)

    series: dict[str, list[str]] = {}
    for k in faces:
        series.setdefault(base_of(k), []).append(k)

    candidates: list[dict] = []
    for key, f in faces.items():
        if key in qualified_keys:
            continue
        b = f["bytes"]
        lua = f.get("lua") or {}
        free = lua.get("free")
        verdict = f.get("verdict") or ""
        reminder = has_class_reminder(f)

        # —— 未进主列表的具体原因：按台账证据写，不一律套同一句 ——
        reasons: list[str] = []
        if verdict == "no_lua":
            reasons.append("无 Lua 块 · 物理上不可注入")
        elif verdict in ("hard", "hard_compress"):
            reasons.append("Lua 槽仅余 %sB · 注入需重构（判定 %s）" % (free if free is not None else "?", verdict))
        if reminder:
            reasons.append("已注入课程提醒，但缺含课程行的取证预览图")
        else:
            reasons.append("尚未注入课程提醒")
        sibs = [x for x in series.get(base_of(key), []) if x != key]
        dup_main = [x for x in sibs if x in qualified_keys]
        if dup_main:
            reasons.append("与主列表 %s 同系列重复" % dup_main[0])
        elif sibs:
            reasons.append("同系列另有 %d 个版本（如 %s）" % (len(sibs), sibs[0]))
        if b > 1500 * KB:
            reasons.append("体积 %d KB 偏大（>1.5MB），装机收益低" % kb_of(b))
        if not (f.get("license") or "").strip():
            reasons.append("未声明 LICENSE · 再分发有风险")
        if key not in verified_map:
            reasons.append("未登记达标映射 · 无 Release 下载直链")

        # —— 可捞性：一眼看出能不能捞出来改 ——
        if verdict == "no_lua":
            rlevel, rlabel = "C", "C 不可注入"
        elif verdict in ("hard", "hard_compress"):
            rlevel, rlabel = "C", "C 需重构"
        elif reminder:
            rlevel, rlabel = "A", "A 已注入仅缺取证"
        elif verdict == "ready":
            rlevel, rlabel = "A", "A 直接可注入"
        else:
            rlevel, rlabel = "B", "B 需截短腾槽"

        candidates.append({
            "key": key,
            "name": re.sub(r"-[v]\d[\d.]*$", "", key.replace(".face", "")).replace("Band9-", "", 1),
            "model": model_of(key),
            "bytes": b,
            "kb": kb_of(b),
            "source": f.get("source") or "—",
            "license": (f.get("license") or "未声明").strip() or "未声明",
            "reminder": "已接入" if reminder else "未接入",
            "verified": False,
            "missing": reasons,
            "luaFree": free,
            "luaFreeLabel": ("%dB" % free) if free is not None else "—",
            "luaSlot": ("%s / %s B" % (lua.get("used"), lua.get("slot"))) if lua else "无 Lua 块",
            "luaName": lua.get("name") or "—",
            "verdict": verdict,
            "verdictLabel": VERDICT_LABEL.get(verdict, verdict or "—"),
            "recoverLevel": rlevel,
            "recoverLabel": rlabel,
            "state": f.get("state") or "—",
            "updated": registry.get("updatedAt") or now_bj(),
            "updatedLabel": "台账刷新",
        })

    cards = qualified + candidates
    models = sorted({c["model"] for c in cards}, key=lambda x: (x == "未知", x))
    dims = {
        "models": models,
        "reminder": ["已接入", "未接入"],
        "size": [x[0] for x in SIZE_BUCKETS],
        "source": ["自研", "MIT", "GPL", "未声明"],
    }
    recover_order = [
        "A 已注入仅缺取证", "A 直接可注入", "B 需截短腾槽",
        "C 需重构", "C 不可注入", "已达标",
    ]
    present = {c["recoverLabel"] for c in cards}
    dims["recover"] = [x for x in recover_order if x in present]
    recover_stats = {lb: sum(1 for c in candidates if c["recoverLabel"] == lb) for lb in recover_order}
    tier_stats = {k: sum(1 for c in qualified if c["previewTier"] == k) for k in TIER_LABEL}
    data = {
        "meta": {
            "generatedAt": now_bj(),
            "total": len(faces),
            "qualified": len(qualified),
            "candidates": len(candidates),
            "registryUpdated": registry.get("updatedAt", ""),
            "offline": offline,
            "warnings": warnings,
            "recoverStats": {k: v for k, v in recover_stats.items() if v},
            "tierStats": {k: v for k, v in tier_stats.items() if v},
            "tierLabel": TIER_LABEL,
            "tierDesc": TIER_DESC,
        },
        "dims": dims,
        "cards": cards,
    }

    log("达标 %d / 候选 %d / 总计 %d；警告 %d" % (len(qualified), len(candidates), len(faces), len(warnings)))

    if check:
        print(json.dumps({"meta": data["meta"], "qualified": [q["key"] for q in qualified]}, ensure_ascii=False, indent=2))
        return

    html = render(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    log("已生成", OUT, "(%d 字节)" % OUT.stat().st_size)

    # 回填 releaseCache（仅内容变化时写，保证幂等 + 离线可重跑）
    if not offline:
        old = cfg.get("releaseCache", {})
        if old != releases:
            cfg["releaseCache"] = releases
            GALLERY_CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            log("已回填 releaseCache 到", GALLERY_CFG)


def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("/*__DATA__*/", "const DATA = " + payload + ";")


# Lucide 内联 SVG（不引 CDN，遵守 §3.14 图标一律 Lucide）
I_FILTER = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>'
I_DOWN = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
I_CHECK = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
I_CHEV = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>'
I_IMG = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>'
I_EXT = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EV 表盘 · 展示与下载</title>
<style>
  :root{
    --bg:#f5f6f8; --card:#ffffff; --ink:#1c2027; --sub:#636b78; --line:#e4e7ec;
    --brand:#4f46e5; --brand-soft:#eef2ff; --ok:#15803d; --ok-soft:#dcfce7;
    --warn:#b45309; --warn-soft:#fef3c7; --chip:#f1f3f6; --shadow:0 1px 3px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.05);
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;font-size:14px;line-height:1.5}
  .wrap{max-width:1180px;margin:0 auto;padding:0 20px 60px}
  header.top{background:linear-gradient(135deg,#1e2333,#2d3550);color:#fff;padding:30px 20px 26px}
  header.top .inner{max-width:1180px;margin:0 auto}
  .brandline{display:flex;align-items:center;gap:10px;font-size:13px;letter-spacing:.06em;color:#aab3c9;text-transform:uppercase}
  .brandline b{color:#fff;font-size:12px;border:1px solid #4b5677;border-radius:6px;padding:2px 8px;font-weight:600}
  h1{margin:12px 0 6px;font-size:26px;letter-spacing:-.01em}
  .sub{color:#b9c1d4;font-size:13px}
  .stats{display:flex;gap:26px;margin-top:20px;flex-wrap:wrap}
  .stat{display:flex;flex-direction:column}
  .stat .n{font-size:28px;font-weight:700;line-height:1}
  .stat .l{font-size:12px;color:#aab3c9;margin-top:6px}
  .stat.ok .n{color:#7ee2a8}
  .toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:22px 0 16px}
  .btn{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:9px 14px;border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;box-shadow:var(--shadow);transition:.15s}
  .btn:hover{border-color:var(--brand);color:var(--brand)}
  .btn[aria-expanded="true"]{background:var(--brand-soft);border-color:var(--brand);color:var(--brand)}
  .sortbox{margin-left:auto;display:flex;align-items:center;gap:8px;color:var(--sub);font-size:12px}
  select{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:8px 10px;border-radius:9px;font-size:13px;cursor:pointer}
  .filter-panel{display:none;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow);margin-bottom:20px}
  .filter-panel.open{display:block}
  .frow{display:grid;grid-template-columns:120px 1fr;gap:14px;padding:10px 0;border-bottom:1px dashed var(--line);align-items:start}
  .frow:last-child{border-bottom:0}
  .flabel{font-weight:600;font-size:13px;padding-top:6px;color:#4b5563}
  .chips{display:flex;gap:8px;flex-wrap:wrap}
  .chip{border:1px solid var(--line);background:var(--chip);color:var(--sub);padding:6px 12px;border-radius:999px;font-size:12px;font-weight:600;cursor:pointer;user-select:none;transition:.12s}
  .chip:hover{border-color:var(--brand);color:var(--brand)}
  .chip.on{background:var(--brand);border-color:var(--brand);color:#fff}
  .fhint{font-size:12px;color:var(--sub);margin-top:2px}
  .section-h{display:flex;align-items:center;gap:10px;margin:26px 2px 14px;font-size:16px;font-weight:700}
  .section-h .cnt{font-size:12px;font-weight:600;color:var(--sub);background:var(--chip);padding:2px 9px;border-radius:999px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(216px,1fr));gap:18px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;box-shadow:var(--shadow);display:flex;flex-direction:column}
  .shot{width:100%;aspect-ratio:192/490;background:#000;border-radius:96px;overflow:hidden;position:relative;display:flex;align-items:center;justify-content:center}
  .shot img{width:100%;height:100%;object-fit:contain;display:block}
  .shot.ph{background:repeating-linear-gradient(135deg,#fafbfc,#fafbfc 10px,#f2f4f7 10px,#f2f4f7 20px);color:#9aa3b2;border:1px dashed var(--line)}
  .shot .ph-in{display:flex;flex-direction:column;align-items:center;gap:8px;font-size:11px;padding:10px;text-align:center}
  .cname{margin:13px 2px 2px;font-size:15px;font-weight:700;line-height:1.3}
  .fname{margin:3px 2px 0;font-size:11px;color:var(--sub);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
  .badges{display:flex;gap:6px;flex-wrap:wrap;margin:10px 2px 0}
  .badge{font-size:11px;font-weight:600;padding:3px 8px;border-radius:6px}
  .badge.ok{background:var(--ok-soft);color:var(--ok);display:inline-flex;align-items:center;gap:3px}
  .badge.no{background:#f1f3f6;color:#6b7280}
  .badge.lic{background:var(--brand-soft);color:var(--brand)}
  .badge.warn{background:var(--warn-soft);color:var(--warn)}
  .size{font-size:22px;font-weight:800;margin:12px 2px 0;letter-spacing:-.02em}
  .size small{font-size:12px;font-weight:600;color:var(--sub);letter-spacing:0}
  .bytes{font-size:11px;color:var(--sub);margin:1px 2px 0}
  .meta{font-size:11px;color:var(--sub);margin:9px 2px 0;line-height:1.6}
  .dl{display:flex;align-items:center;justify-content:center;gap:7px;margin-top:auto;padding:10px;border-radius:10px;background:var(--brand);color:#fff;text-decoration:none;font-size:13px;font-weight:700;transition:.15s}
  .dl:hover{background:#4338ca}
  .dl.disabled{background:#f1f3f6;color:#9aa3b2;cursor:not-allowed}
  .miss{background:#fffbeb;border:1px solid #fde68a;border-radius:9px;padding:8px 10px;margin-top:10px;font-size:11px;color:var(--warn);line-height:1.6}
  .miss b{display:block;font-size:11px;margin-bottom:3px}
  .badge.tier{background:#e0f2fe;color:#0369a1}
  .badge.tier.syn{background:#ede9fe;color:#5b21b6}
  .badge.tier.raw{background:#f1f3f6;color:#6b7280}
  .rec{font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px}
  .rec.A{background:#dcfce7;color:#15803d}
  .rec.B{background:#fef3c7;color:#b45309}
  .rec.C{background:#f1f3f6;color:#6b7280}
  .rec.-{background:#eef2ff;color:#4f46e5}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:3px 8px;margin:10px 2px 0;font-size:11px;color:var(--sub);line-height:1.5}
  .kv b{color:#4b5563;font-weight:600;white-space:nowrap}
  .legend{display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:11px;color:var(--sub);margin:0 2px 16px;padding:11px 14px;background:var(--card);border:1px solid var(--line);border-radius:11px;line-height:1.6}
  .legend .li{display:inline-flex;align-items:center;gap:6px}
  .legend b{color:#4b5563}
  .cand-stat{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
  details.cand{border:1px solid var(--line);background:var(--card);border-radius:14px;box-shadow:var(--shadow);margin-top:12px}
  details.cand>summary{list-style:none;cursor:pointer;padding:15px 20px;font-weight:700;display:flex;align-items:center;gap:10px}
  details.cand>summary::-webkit-details-marker{display:none}
  details.cand>summary .chev{margin-left:auto;transition:.15s;color:var(--sub)}
  details.cand[open]>summary .chev{transform:rotate(180deg)}
  .cand-body{padding:0 20px 20px}
  .cand-note{font-size:12px;color:var(--sub);background:var(--chip);padding:10px 12px;border-radius:9px;margin-bottom:16px}
  .empty{text-align:center;color:var(--sub);padding:50px 20px;border:1px dashed var(--line);border-radius:14px;background:var(--card)}
  footer{margin-top:36px;padding-top:18px;border-top:1px solid var(--line);font-size:11px;color:var(--sub);line-height:1.8}
  code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:11px}
  @media(max-width:600px){
    .grid{grid-template-columns:1fr}
    h1{font-size:22px}
    .frow{grid-template-columns:1fr;gap:4px}
    .sortbox{margin-left:0;width:100%;justify-content:space-between}
    .stats{display:grid;grid-template-columns:repeat(2,1fr);gap:16px 12px}
  }
</style>
</head>
<body>
<header class="top"><div class="inner">
  <div class="brandline"><b>EV</b> FACE GALLERY <span>· 课程表真表盘</span></div>
  <h1>EV 表盘 · 展示与下载</h1>
  <div class="sub">已接入课程提醒、且预览图可见课程行的成品表盘。点「筛选」按机型 / 课程提醒 / 体积 / 来源许可过滤，下载直链指向 GitHub Release。</div>
  <div class="stats">
    <div class="stat"><span class="n" id="s-total">—</span><span class="l">台账总包数</span></div>
    <div class="stat ok"><span class="n" id="s-ok">—</span><span class="l">已达标（主列表）</span></div>
    <div class="stat"><span class="n" id="s-cand">—</span><span class="l">候选 · 未达标</span></div>
    <div class="stat"><span class="n" id="s-show">—</span><span class="l">当前筛选命中</span></div>
  </div>
</div></header>

<div class="wrap">
  <div class="toolbar">
    <button class="btn" id="filter-toggle" aria-expanded="false" onclick="toggleFilter()">__I_FILTER__ 筛选</button>
    <div class="sortbox"><label for="sort">排序</label>
      <select id="sort" onchange="render()">
        <option value="size-asc" selected>体积从小到大</option>
        <option value="size-desc">体积从大到小</option>
        <option value="name">名称</option>
        <option value="updated">更新时间</option>
      </select>
    </div>
  </div>

  <div class="filter-panel" id="filter-panel"></div>

  <div class="legend" id="tier-legend"></div>

  <div class="section-h">主列表 · 已达标 <span class="cnt" id="c-qualified">0</span></div>
  <div class="grid" id="grid"></div>
  <div class="empty" id="grid-empty" style="display:none">当前筛选下没有已达标表盘。放宽筛选条件试试。</div>

  <details class="cand" id="cand">
    <summary>__I_CHEV__ <span>候选 · 未达标（<span id="c-cand">0</span>）</span> <span class="chev">__I_CHEV__</span></summary>
    <div class="cand-body">
      <div class="cand-note">这些包<b>不进主列表</b>。每张卡片写明三件事：<b>为什么没进</b>（缺课程行 / 无 Lua 块 / 槽位不足 / 同系列重复 / 体积过大 / 未发布）、<b>Lua 槽余量</b>、<b>可捞性</b>——A 级是能直接捞出来改的，B 级要先截短腾槽，C 级不建议动。用「筛选 → 可捞性」可一键筛出 A 级。</div>
      <div class="cand-stat" id="cand-stat"></div>
      <div class="grid" id="cand-grid"></div>
      <div class="empty" id="cand-empty" style="display:none">当前筛选下没有候选包。</div>
    </div>
  </details>

  <footer>
    <div id="f-meta"></div>
    <div>数据源：<code>data/face-registry.json</code>（台账） + <code>gh release list/view</code>（真实资产与直链） + <code>data/gallery.json</code>（显式达标映射与取证图）。页面数据已全内联，<code>file://</code> 双击可直接打开，不请求任何外部 JSON / CDN。</div>
    <div>准入判据：主列表项须同时满足 ① 已注入课程提醒（能显示上课中 / 已上多少分 / 下节什么课），② 预览图为「模拟器真帧」或「合成渲染帧」且逐行可见课程行，③ Release 资产真实存在。三者缺一即降级为候选，不用未改造包凑数。</div>
    <div>图片来源口径：<b>模拟器真帧</b>=真跑模拟器渲染；<b>合成渲染帧</b>=包内 RLE 预览底图 + 注入的课程分支实跑文案 + 官方皮肤外壳（非设备实拍）；<b>包内预览原图</b>=只有底图无课程行。档位由 <code>&lt;图&gt;.provenance.json</code> 佐证，声明「模拟器真帧」但 provenance 记 deviceReal=false 会被自动降级。</div>
  </footer>
</div>

<script>
/*__DATA__*/
const F={
  models:new Set(), reminder:new Set(), size:new Set(), source:new Set(), recover:new Set()
};
function toggleFilter(){
  const p=document.getElementById('filter-panel'),b=document.getElementById('filter-toggle');
  const open=p.classList.toggle('open'); b.setAttribute('aria-expanded',open?'true':'false');
}
function buildFilters(){
  const wrap=document.getElementById('filter-panel');
  const rows=[
    ['models','手环型号',DATA.dims.models,'仅显示已有数据的机型'],
    ['reminder','课程提醒状态',DATA.dims.reminder,'是否已注入课程提醒逻辑'],
    ['size','包体积区间',DATA.dims.size,'原始 .face 体积'],
    ['source','来源与许可',DATA.dims.source,'自研 / 开源许可 / 未声明'],
    ['recover','可捞性（候选区）',DATA.dims.recover||[],'A=能捞出来改 / B=要截短腾槽 / C=不建议'],
  ];
  wrap.innerHTML=rows.map(([k,label,vals,hint])=>
    `<div class="frow"><div class="flabel">${label}</div><div><div class="chips">`+
    vals.map(v=>`<span class="chip" data-dim="${k}" data-value="${v}" onclick="pick(this)">${v}</span>`).join('')+
    `</div><div class="fhint">${hint} · 可多选（同维度取“或”，跨维度取“且”）</div></div></div>`
  ).join('');
}
function pick(el){
  const k=el.dataset.dim,v=el.dataset.value,s=F[k];
  s.has(v)?s.delete(v):s.add(v); el.classList.toggle('on'); render();
}
function bucketSize(b){return b<102400?'<100KB':b<307200?'100~300KB':b<614400?'300~600KB':'>600KB';}
function bucketSrc(c){
  if(c.source.includes('自研'))return '自研';
  const l=(c.license||''); if(l.includes('MIT'))return 'MIT'; if(l.includes('GPL'))return 'GPL'; return '未声明';
}
function passes(c){
  if(F.models.size&&!F.models.has(c.model))return false;
  if(F.reminder.size&&!F.reminder.has(c.reminder))return false;
  if(F.size.size&&!F.size.has(bucketSize(c.bytes)))return false;
  if(F.source.size&&!F.source.has(bucketSrc(c)))return false;
  if(F.recover.size&&!F.recover.has(c.recoverLabel))return false;
  return true;
}
function sortCards(a,b){
  const v=document.getElementById('sort').value;
  if(v==='size-asc')return a.bytes-b.bytes;
  if(v==='size-desc')return b.bytes-a.bytes;
  if(v==='name')return a.name.localeCompare(b.name,'zh-CN');
  if(v==='updated')return (b.updated||'').localeCompare(a.updated||'');
  return 0;
}
function badgeSrc(c){return `<span class="badge lic">${bucketSrc(c)}</span>`;}
function badgeTier(c){
  if(!c.previewTierLabel)return '';
  const k=c.previewTier==='synthetic'?' syn':c.previewTier==='raw'?' raw':'';
  return `<span class="badge tier${k}" title="${c.previewTierDesc||''}">${c.previewTierLabel}</span>`;
}
function badgeRec(c){
  if(!c.recoverLabel)return '';
  return `<span class="rec ${c.recoverLevel||'-'}">${c.recoverLabel}</span>`;
}
function cardHtml(c){
  const reminder=c.reminder==='已接入'
    ? `<span class="badge ok">__I_CHECK__ 已接入课程提醒</span>`
    : `<span class="badge no">未接入课程提醒</span>`;
  if(c.verified){
    const dl=c.download
      ? `<a class="dl" href="${c.download}" target="_blank" rel="noopener noreferrer">__I_DOWN__ 下载 .face __I_EXT__</a>`
      : `<div class="dl disabled">无可用下载直链</div>`;
    const uv=c.urlVerified?'':`<div class="miss"><b>下载直链未在线校验</b>离线生成，请连网后重跑 build_gallery.py</div>`;
    return `<div class="card">
      <div class="shot"><img src="${c.preview}" alt="${c.name} 预览图"></div>
      <div class="cname">${c.name}</div>
      <div class="fname">${c.key}</div>
      <div class="badges">${reminder}${badgeTier(c)}${badgeSrc(c)}</div>
      <div class="size">${c.kb} <small>KB</small></div>
      <div class="bytes">${c.bytes.toLocaleString()} 字节 · ${c.model}</div>
      <div class="meta">来源：${c.source}<br>许可：${c.license}<br>更新：${c.updatedLabel} ${c.updated}<br>图片来源：${c.previewTierLabel}</div>
      ${uv}${dl}
    </div>`;
  }
  const kv=`<div class="kv">
    <b>Lua 槽余量</b><span>${c.luaFreeLabel}${(c.luaFree!==null&&c.luaFree!==undefined&&c.luaFree<800)?' · 不足 800B':''}</span>
    <b>判定档</b><span>${c.verdictLabel}</span>
    <b>槽位占用</b><span>${c.luaSlot}</span>
    <b>台账状态</b><span>${c.state}</span>
  </div>`;
  const miss=`<div class="miss"><b>为什么没进主列表</b>${c.missing.map(m=>'· '+m).join('<br>')}</div>`;
  return `<div class="card">
    <div class="shot ph"><div class="ph-in">__I_IMG__<span>无达标预览图<br>（不含可辨认课程行）</span></div></div>
    <div class="cname">${c.name}</div>
    <div class="fname">${c.key}</div>
    <div class="badges">${reminder}${badgeRec(c)}${badgeSrc(c)}</div>
    <div class="size">${c.kb} <small>KB</small></div>
    <div class="bytes">${c.bytes.toLocaleString()} 字节 · ${c.model}</div>
    <div class="meta">来源：${c.source}<br>许可：${c.license}</div>
    ${kv}${miss}<div class="dl disabled">未发布下载</div>
  </div>`;
}
function render(){
  const all=DATA.cards.filter(passes);
  const q=all.filter(c=>c.verified).sort(sortCards);
  const cd=all.filter(c=>!c.verified).sort(sortCards);
  document.getElementById('grid').innerHTML=q.map(cardHtml).join('');
  document.getElementById('cand-grid').innerHTML=cd.map(cardHtml).join('');
  document.getElementById('grid-empty').style.display=q.length?'none':'block';
  document.getElementById('cand-empty').style.display=cd.length?'none':'block';
  document.getElementById('c-qualified').textContent=q.length;
  document.getElementById('c-cand').textContent=cd.length;
  document.getElementById('s-show').textContent=all.length;
  const st=DATA.meta.recoverStats||{};
  document.getElementById('cand-stat').innerHTML=Object.keys(st).map(k=>
    `<span class="rec ${k[0]==='A'?'A':k[0]==='B'?'B':'C'}">${k}：${st[k]} 个</span>`).join('');
}
function buildLegend(){
  const ts=DATA.meta.tierStats||{}, tl=DATA.meta.tierLabel||{}, td=DATA.meta.tierDesc||{};
  const parts=Object.keys(tl).map(k=>{
    const cls=k==='synthetic'?' syn':k==='raw'?' raw':'';
    return `<span class="li"><span class="badge tier${cls}">${tl[k]}</span>${td[k]||''}${ts[k]?`<b>· ${ts[k]} 个</b>`:''}</span>`;
  });
  document.getElementById('tier-legend').innerHTML=
    `<b>图片来源分档（不是设备实拍就不要标成实拍）</b>`+parts.join('')+
    `<span class="li" style="color:#94a3b8">模拟器只铺模板 lua、不执行改造包 lua，故无「模拟器真帧」</span>`;
}
function init(){
  document.getElementById('sort').value='size-asc';
  document.getElementById('s-total').textContent=DATA.meta.total;
  document.getElementById('s-ok').textContent=DATA.meta.qualified;
  document.getElementById('s-cand').textContent=DATA.meta.candidates;
  document.getElementById('f-meta').innerHTML=
    `生成时间：${DATA.meta.generatedAt} · 台账更新：${DATA.meta.registryUpdated || '—'} · 生成模式：${DATA.meta.offline?'离线':'在线'}`;
  buildFilters(); render();
}
init();
</script>
</body>
</html>
"""
# 注入 Lucide 图标（在模块加载时替换，避免与 CSS 大括号冲突）
TEMPLATE = (TEMPLATE
    .replace("__I_FILTER__", I_FILTER).replace("__I_DOWN__", I_DOWN)
    .replace("__I_CHECK__", I_CHECK).replace("__I_CHEV__", I_CHEV)
    .replace("__I_IMG__", I_IMG).replace("__I_EXT__", I_EXT))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="只用 releaseCache，不联网")
    ap.add_argument("--check", action="store_true", help="只校验打印，不写 HTML")
    args = ap.parse_args()
    build(args.offline, args.check)
