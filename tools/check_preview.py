#!/usr/bin/env python3
""".face 包体检：预览块必须「恰好」解出 w*h 个像素。

背景（2026-11-11）：长按切换页缩略图退化成一个大圈，根因是包内预览块的 RLE
流被 pad_to() 用「重复指令」填满槽位，每填 4 字节多解出 127 个假像素，
整块解出 13 倍像素 → 设备解码溢出 → 退化成占位图形。
自研包全部超标 6~15 倍，官方/第三方包全部恰好 1.00 倍、零剩余字节。

用法：
    python3 tools/check_preview.py                 # 扫 dist/ 下所有 .face
    python3 tools/check_preview.py a.face b.face   # 只查指定包
    echo $?                                        # 0 全通过 / 1 有坏包

自研包的比值必须是 1.00；非 1.00 一律不出包（详情见
docs/表盘预览与长按修复复盘-20261111.md）。
"""
import sys
import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.face_container import FaceImage  # noqa: E402
from shared import rle                       # noqa: E402


def check(path):
    fi = FaceImage(path)
    w, h, plen = fi.preview_meta()
    body = bytes(fi.data[fi.tail + 20:fi.tail + 20 + plen])
    px, used = rle.decode_px_count(body, 3)
    want = w * h
    info = fi.info()
    return {
        "name": Path(path).name,
        "w": w, "h": h,
        "px": px, "want": want,
        "ratio": (px / want) if want else 0,
        "used": used, "cap": plen - 8,
        "rest": len(body) - used,
        "id": info.get("id"), "title": info.get("name"),
        "ok": px == want,
    }


def main(argv):
    targets = argv[1:] or sorted(glob.glob("dist/**/*.face", recursive=True))
    if not targets:
        print("没找到 .face 包")
        return 2
    bad = 0
    print(f"{'包':44s}{'尺寸':>9s}{'解码px':>10s}{'比值':>7s}{'流/槽位':>15s}{'余B':>6s}  判定")
    for t in targets:
        try:
            r = check(t)
        except Exception as e:                    # 坏容器也算失败
            print(f"{Path(t).name:44s}  读取失败: {e}")
            bad += 1
            continue
        flag = "OK" if r["ok"] else "❌ 坏（预览会退化）"
        if not r["ok"]:
            bad += 1
        dims = "%dx%d" % (r["w"], r["h"])
        use = "%d/%d" % (r["used"], r["cap"])
        print(f"{r['name']:44s}{dims:>9s}{r['px']:>10d}"
              f"{r['ratio']:>7.2f}{use:>15s}{r['rest']:>6d}  {flag}")
    print(f"\n共 {len(targets)} 个包，坏 {bad} 个")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
