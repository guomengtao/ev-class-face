# -*- coding: utf-8 -*-
""".face 容器读写：只做等长替换，绝不改变文件总长与条目表。

头部关键位置（小米手环系列 .face）：

    0x00  5a a5 34 12        魔数
    0x05  bytes[5]           模拟器补丁标记，官方为 0
    0x1C  slotCount          表盘槽位数，Lua 无法注册更多槽（决定"设置"按钮）
    0x20  tail_offset        尾部预览块偏移指针
    0x28  10B  表盘 ID        设备识别同款表盘的主键，正式发布后固定
    0x68  24B  表盘名
    0x110..0x200  16B/条 资源条目表（3B size + 1B namelen + 16B reserved + name + content）
"""
import struct

MAGIC = bytes.fromhex("5aa53412")
ENTRY_OFF, ENTRY_END, ENTRY_STRIDE = 0x110, 0x200, 16
ID_OFF, NAME_OFF = 0x28, 0x68
NAME_LEN = 24


class FaceImage:
    def __init__(self, path):
        self.path = path
        self.data = bytearray(open(path, "rb").read())
        assert self.data[:4] == MAGIC, "不是 .face 容器"

    # --- 头部 ---
    @property
    def tail(self):
        return struct.unpack_from("<I", self.data, 0x20)[0]

    def preview_meta(self):
        w, h = struct.unpack_from("<HH", self.data, self.tail + 4)
        plen = struct.unpack_from("<I", self.data, self.tail + 8)[0]
        return w, h, plen

    def preview_header(self):
        """官方 8 字节 RLE 头，原样保留。"""
        return bytes(self.data[self.tail + 12:self.tail + 20])

    def set_identity(self, face_id, name):
        self.data[5] = 0  # 清除模拟器补丁标记，否则真机行为异常
        self.data[ID_OFF:ID_OFF + 10] = face_id.encode()[:10].ljust(10, b"\0")
        self.data[NAME_OFF:NAME_OFF + NAME_LEN] = name.encode()[:NAME_LEN].ljust(NAME_LEN, b"\0")

    def info(self):
        return {
            "size": len(self.data),
            "slot_count": struct.unpack_from("<H", self.data, 0x1C)[0],
            "id": bytes(self.data[ID_OFF:ID_OFF + 10]).rstrip(b"\0").decode("ascii", "ignore"),
            "name": bytes(self.data[NAME_OFF:NAME_OFF + NAME_LEN]).rstrip(b"\0").decode("ascii", "ignore"),
            "patch_flag": self.data[5],
        }

    # --- 资源条目 ---
    def entries(self):
        out = {}
        for off in range(ENTRY_OFF, ENTRY_END, ENTRY_STRIDE):
            _a, _b, bo, bs = struct.unpack_from("<IIII", self.data, off)
            if bo == 0 or bo >= len(self.data):
                continue
            nl = self.data[bo + 3]
            cs = int.from_bytes(self.data[bo:bo + 3], "little")
            name = self.data[bo + 20:bo + 20 + nl].decode("ascii")
            out[name] = (bo + 20 + nl, cs, bs)
        return out

    # --- 注入 ---
    def inject_resource(self, name, payload):
        """等长写入资源块，返回 (原长, 块容量)。"""
        entries = self.entries()
        assert name in entries, f"基底缺少 {name}: {list(entries)}"
        coff, cs, _bs = entries[name]
        assert len(payload) <= cs, f"{name} {len(payload)}B 超过块容量 {cs}B"
        pad = cs - len(payload)
        body = payload if pad == 0 else payload + b"--" + b" " * max(0, pad - 3) + b"\n"
        self.data[coff:coff + cs] = body
        return len(payload), cs

    def inject_preview(self, rle_payload):
        _w, _h, plen = self.preview_meta()
        assert len(rle_payload) <= plen, f"预览 {len(rle_payload)}B 超过 {plen}B"
        t = self.tail
        self.data[t + 12:t + 12 + plen] = rle_payload.ljust(plen, b"\0")
        return plen

    def save(self, out):
        open(out, "wb").write(bytes(self.data))
        return len(self.data)
