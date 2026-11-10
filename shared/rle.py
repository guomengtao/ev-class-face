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
