# -*- coding: utf-8 -*-
"""LVGL RLE 编解码（预览图专用）。

官方 Band 9 表盘预览编码格式（逆向结论，勿改）：

    头部 8 字节  e0 21 a5 5a | 03 e8 44 00
                 magic        blksize=3(RGB888), 数据长度
    其后**直接**是 RLE 流，没有 LVGL v9 image header。

用 LVGLImage.RLEImage.to_rle() 生成的是 blksize=4 + 12 字节 image header，
设备按 blksize=3 解，只剩底色 —— 真机上表现为「蓝色大空圈」。
"""


def encode(px, blksize=3, maxrun=127):
    """ctrl<0x80：后跟 1 个像素、重复 ctrl 次；ctrl|0x80：后跟 ctrl 个非重复像素。"""
    n = len(px) // blksize
    blocks = [px[i * blksize:(i + 1) * blksize] for i in range(n)]
    out = bytearray()
    i = 0
    while i < n:
        j = i + 1
        while j < n and blocks[j] == blocks[i] and j - i < maxrun:
            j += 1
        run = j - i
        if run >= 2:
            out.append(run)
            out += blocks[i]
            i = j
        else:
            buf = []
            k = i
            while k < n and len(buf) < maxrun:
                m = k + 1
                while m < n and blocks[m] == blocks[k] and m - k < 2:
                    m += 1
                if m - k >= 2:
                    break
                buf.append(blocks[k])
                k += 1
            if not buf:
                buf.append(blocks[k])
                k += 1
            out.append(0x80 | len(buf))
            for b in buf:
                out += b
            i = k
    return bytes(out)


def decode(body, blksize=3):
    px = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        i += 1
        if c == 0:
            break
        if c & 0x80:
            cnt = c & 0x7f
            if cnt == 0:
                break
            blk = body[i:i + cnt * blksize]
            i += cnt * blksize
            px += blk
        else:
            blk = body[i:i + blksize]
            i += blksize
            if len(blk) < blksize:
                break
            px += blk * c
    return bytes(px)


def runs_of(px, blksize=3, maxrun=127):
    """把像素序列切成 [(color_bytes, count)]，count ≤ maxrun。"""
    n = len(px) // blksize
    out = []
    i = 0
    while i < n:
        c = px[i * blksize:(i + 1) * blksize]
        j = i + 1
        while j < n and j - i < maxrun and px[j * blksize:(j + 1) * blksize] == c:
            j += 1
        out.append((bytes(c), j - i))
        i = j
    return out


def decode_px_count(body, blksize=3):
    """严格解码：返回 (解出的像素数, 消耗的字节数)。越界即停，绝不虚增计数。"""
    i, px, L = 0, 0, len(body)
    while i < L:
        ctrl = body[i]
        i += 1
        if ctrl == 0:
            break
        if ctrl & 0x80:
            cnt = ctrl & 0x7F
            if cnt == 0 or i + cnt * blksize > L:
                break
            i += cnt * blksize
            px += cnt
        else:
            if i + blksize > L:
                break
            i += blksize
            px += ctrl
    return px, i


def encode_exact(px, target_len, blksize=3, maxrun=127):
    """把同一份像素编码成**恰好 target_len 字节**的 RLE 流（像素数一个不多）。

    设备侧硬语义（字节级实证，33 个包对比）：预览块必须「稠密且恰好」——
    官方 TicTacToe/LuaCalculator/Monika/Stride 等 14 个包全部是
    52996B 解出 94,080 px（192×490）、零剩余字节。

    旧 pad_to() 用重复指令把槽位填满，每 4 字节多解出 127 个**假像素**：
    Analog v1.0.8 实测解出 1,223,239 px（13 倍）、Class v1.0.15 3.66 倍、
    Quartz/Oneline/Smash/TempControl 5.9~14.8 倍。设备解码溢出后退化成
    占位图形 —— 这就是长按切换页「一个大圈」的根因，与配色/亮度无关。

    做法：像素数不动，只把字节数撑到槽位长度。
      * 长 run 拆成 p 段 → 每多一段 +4 字节（1 ctrl + 3 数据）
      * 挑一个 run 改写为字面块 → 同像素下多花 3n-3 字节，用于凑模 4 余数
    出口断言：len(out) == target_len 且解码像素数 == len(px)//blksize。
    """
    n = len(px) // blksize
    runs = runs_of(px, blksize, maxrun)
    base = 4 * len(runs)                      # 每个 run 1 ctrl + 3 数据
    slack = target_len - base
    if slack < 0:
        raise ValueError("像素过多：最省 %dB 已超槽位 %dB" % (base, target_len))

    conv = None                               # (run 下标, 字面块个数)
    need = slack % 4
    if need:
        best = None
        for idx, (_c, cnt) in enumerate(runs):
            if cnt < 2:
                continue
            for j in range(1, cnt + 1):
                d = 3 * cnt + j - 4           # run(4B) → 字面块(j + 3cnt)
                if d % 4 != need or d > slack:
                    continue
                if best is None or d < best[2]:
                    best = (idx, j, d)
                break
        if best is None:
            raise ValueError("凑不到模 4 余数 %d（slack=%d）" % (need, slack))
        conv = (best[0], best[1])
        slack -= best[2]

    splits = slack // 4
    if slack % 4:
        raise ValueError("slack 未能整除 4：%d" % slack)
    cap = sum(c - 1 for i, (_c, c) in enumerate(runs)
              if conv is None or i != conv[0])
    if splits > cap:
        raise ValueError("槽位余量过大：需 %d 次拆分，上限 %d" % (splits, cap))

    parts = [1] * len(runs)
    for i, (_c, cnt) in enumerate(runs):
        if conv is not None and i == conv[0]:
            continue
        if splits <= 0:
            break
        take = min(cnt - 1, splits)
        parts[i] = 1 + take
        splits -= take

    out = bytearray()
    pos = 0
    for i, (color, cnt) in enumerate(runs):
        seg = px[pos * blksize:(pos + cnt) * blksize]
        pos += cnt
        if conv is not None and i == conv[0]:
            j = conv[1]
            base_sz, rem = divmod(cnt, j)
            o = 0
            for k in range(j):
                sz = base_sz + (1 if k < rem else 0)
                out.append(0x80 | sz)
                out += seg[o * blksize:(o + sz) * blksize]
                o += sz
            continue
        p = parts[i]
        base_sz, rem = divmod(cnt, p)
        for k in range(p):
            # 重复块：ctrl(sz<0x80) + **一个** 像素块，解出 sz 个同色像素
            out.append(base_sz + (1 if k < rem else 0))
            out += color

    assert len(out) == target_len, (len(out), target_len)
    got, used = decode_px_count(bytes(out), blksize)
    assert got == n, ("解码像素数不符", got, n)
    assert used == target_len, ("流未吃满槽位", used, target_len)
    return bytes(out)


def pad_to(body, plen, blksize=3):
    """⛔ 已废弃：会解出假像素，禁止再用（保留仅为兼容旧脚本）。

    问题：每填 4 字节就多解出 127 个像素，实测使包内预览块解出 3.7~14.8 倍
    像素，设备长按切换页退化成占位大圈。替代品：encode_exact(px, plen)。
    """
    raise RuntimeError("pad_to 已废弃（会产生假像素）：改用 encode_exact(px, target_len)")


def _pad_to_legacy(body, plen, blksize=3):
    """旧实现（2026-11-11 起停用），仅作对照留档。"""
    pad = plen - len(body)
    if pad <= 0:
        return bytes(body)
    rest = pad % 4
    out = bytearray(body)
    if rest:
        n = {1: 4, 2: 3, 3: 2}[rest]        # 使 1+3n ≡ rest (mod 4)
        out.append(0x80 | n)
        out += b"\x00" * (n * blksize)
        pad -= 1 + n * blksize
    run = 127                                 # 每个块最多 127 次重复
    while pad >= 4:
        out.append(run)
        out += b"\x00" * blksize
        pad -= 4
    if pad:
        out += b"\x00" * pad
    assert len(out) == plen, (len(out), plen)
    return bytes(out)
