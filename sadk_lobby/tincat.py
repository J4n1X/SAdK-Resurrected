"""
TinCat transport layer: CRC32, frame (header) build/parse, and the low-level
binary reader/writer primitives used by the message codec.

Wire encodings (reverse-engineered, must stay byte-exact):
  * scalars  : little-endian, fixed width
  * LBOOL    : single byte (0/1)
  * STRING N : int32 length prefix (length INCLUDES the trailing NUL) + bytes,
               encoded iso-8859-15. None => length 0 (4 zero bytes).
               "" (empty) => length 1 + a single NUL byte (distinct from None!).
  * MEMBLOCK : int32 length prefix + raw bytes. None => length 0.
"""
import struct

from . import config

_ENCODING = "iso-8859-15"


# ── CRC32 (TinCat polynomial 0xEDB88320, init 0, no final xor) ─────────────────
def _build_crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = 0xEDB88320 ^ (c >> 1) if c & 1 else c >> 1
        t.append(c)
    return t


_CRC_TABLE = _build_crc_table()


def crc32(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]) & 0xFFFFFFFF
    return crc


# ── Frame (28-byte TinCat header) ─────────────────────────────────────────────
def build_frame(from_id, to_id, msg_type, payload, unknown1=0):
    hdr = struct.pack(
        "<IIIIIII",
        config.MAGIC, from_id, to_id, msg_type, unknown1, len(payload), crc32(payload),
    )
    return hdr + payload


def parse_header(buf):
    """Parse a 28-byte header; returns a dict (caller must ensure len>=PREFIX_SIZE)."""
    magic, from_, to_, typ, unk1, psz, csum = struct.unpack_from("<IIIIIII", buf)
    return dict(Magic=magic, From=from_, To=to_, Type=typ,
                Unknown1=unk1, PayloadSize=psz, Checksum=csum)


def build_handshake_payload(conn_id, username_raw, unknown1):
    u = (username_raw + b"\x00" * config.HANDSHAKE_USERNAME_SIZE)[:config.HANDSHAKE_USERNAME_SIZE]
    return (struct.pack("<II", config.MAGIC, conn_id) + u
            + config.REPLY_PASSWORD + struct.pack("<i", unknown1))


def app_payload(ptype, body, magic=None):
    """App-payload prefix: Magic + Type1 + Type2 (Type1==Type2) + body.

    `magic` selects the TinCat comm layer (and thus which per-type PropertySet template
    deserializes the frame). Defaults to the lobby magic 0x26B6; village/world msgs (1000+)
    MUST pass the village comm-layer magic (config.VILLAGE_PAYLOAD_MAGIC) instead.
    """
    if magic is None:
        magic = config.PAYLOAD_MAGIC
    return struct.pack("<HHH", magic, ptype, ptype) + body


# ── Field-level string / blob helpers (module-level, byte-exact w/ legacy) ─────
def str_field(s):
    if s is None:
        return struct.pack("<i", 0)
    b = (s + "\x00").encode(_ENCODING)
    return struct.pack("<i", len(b)) + b


def bytes_field(b):
    if b is None:
        return struct.pack("<i", 0)
    return struct.pack("<i", len(b)) + b


# ── BinaryReader ──────────────────────────────────────────────────────────────
class BinaryReader:
    def __init__(self, data, pos=0):
        self._d = data
        self._p = pos

    @property
    def pos(self):
        return self._p

    def u8(self):
        v = self._d[self._p]; self._p += 1; return v

    def i8(self):
        v = struct.unpack_from("b", self._d, self._p)[0]; self._p += 1; return v

    def u16(self):
        v = struct.unpack_from("<H", self._d, self._p)[0]; self._p += 2; return v

    def i16(self):
        v = struct.unpack_from("<h", self._d, self._p)[0]; self._p += 2; return v

    def u32(self):
        v = struct.unpack_from("<I", self._d, self._p)[0]; self._p += 4; return v

    def i32(self):
        v = struct.unpack_from("<i", self._d, self._p)[0]; self._p += 4; return v

    def boolean(self):
        return self.u8() != 0

    def string(self):
        n = self.i32()
        if n <= 0:
            return None
        v = self._d[self._p:self._p + n]; self._p += n
        return v.rstrip(b"\x00").decode(_ENCODING, "replace")

    def blob(self):
        n = self.i32()
        if n <= 0:
            return None
        v = self._d[self._p:self._p + n]; self._p += n
        return v

    def peek_u16(self):
        return struct.unpack_from("<H", self._d, self._p)[0]

    def remaining(self):
        return len(self._d) - self._p

    # legacy aliases
    bool_ = boolean


# ── BinaryWriter ──────────────────────────────────────────────────────────────
class BinaryWriter:
    def __init__(self):
        self._b = bytearray()

    def u8(self, v):    self._b += struct.pack("<B", v & 0xFF); return self
    def i8(self, v):    self._b += struct.pack("<b", v); return self
    def u16(self, v):   self._b += struct.pack("<H", v & 0xFFFF); return self
    def i16(self, v):   self._b += struct.pack("<h", v); return self
    def u32(self, v):   self._b += struct.pack("<I", v & 0xFFFFFFFF); return self
    def i32(self, v):   self._b += struct.pack("<i", v); return self
    def boolean(self, v): self._b += struct.pack("<B", 1 if v else 0); return self
    def string(self, s):  self._b += str_field(s); return self
    def blob(self, b):    self._b += bytes_field(b); return self
    def raw(self, b):     self._b += b; return self

    def getvalue(self):
        return bytes(self._b)
