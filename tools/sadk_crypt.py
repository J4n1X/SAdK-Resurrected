"""
Decrypt the game's encrypted data files ("sadk" containers), byte-exact to the client's own reader.

Stated reason (HARNESS.md §3): the community converter AdKEd.exe is packed with MEW and crashes before
main() under Wine (jump to 0 / stack overflow, 64- and 32-bit prefixes alike), and neither the Ghidra nor the
Frida MCP converts files in bulk. This reimplements the game's code path, read through Ghidra
(mapping cache, sadk_noav.exe):

  NBase::gDecryptData            S 006e6660  header checks, then derive key -> descramble -> unpack -> CRC
  Crypto_InitKey128              S 006ee5d0  base key bdc28cbd f84b6730 f91b9bb4 f42e82f6
  FileCrypt_DeriveFileKey        S 006eeac0  key ^= 16 Park-Miller bytes seeded with CRC32(lower basename);
                                             .s2m / .aav keep the base key
  FileCrypt_XorScramble          S 006ee6b0  two XOR passes (symmetric)
  RandomGenerator::SetSeed       S 006ec2a0  seed bit-balancing with the bit-order table at 007fd528
  Rng_ParkMillerNext             S 006ec350  minimal-standard LCG (16807, 2^31-1)
  Lzss_Decode                    S 007630a0  Okumura LZSS: 1024-byte ring pre-filled with spaces up to 0x3f0, matches of 3-18 bytes
  crc32                          S 007627c0  zlib CRC-32

Container: u32 0x06091812, "sadk", u32 CRC32(plaintext), u32 CRC32(key16), u32 plaintext size, payload.
Every file is verified against the key CRC, the size and the data CRC from its own header.

Usage:  python3 tools/sadk_crypt.py decrypt <game data dir> <output dir>
        python3 tools/sadk_crypt.py file <encrypted file> [<output file>]
        python3 tools/sadk_crypt.py encrypt <plain file> <output file>   (key from the output file's name)
Output keeps the folder structure and file names; plain (unencrypted) files are not copied.
"""
import os
import struct
import sys
import zlib

VERSION = 0x06091812
MAGIC = b"sadk"
BASE_KEY = struct.pack("<4I", 0xBDC28CBD, 0xF84B6730, 0xF91B9BB4, 0xF42E82F6)
SEED_BIT_ORDER = (12, 23, 10, 25, 8, 27, 6, 29, 4, 30, 1, 22, 9, 13, 21, 0,
                  17, 26, 5, 15, 18, 28, 11, 2, 14, 3, 24, 7, 19, 16, 20, 31)


class ParkMiller:
    """ai::math::RandomGenerator: SetSeed S 006ec2a0 + Rng_ParkMillerNext S 006ec350."""

    def __init__(self, seed):
        s = seed & 0x7FFFFFFF
        bits = sum(1 for i in range(31) if s >> i & 1)
        if bits < 8:
            for i in range(8 - bits):
                s |= 1 << SEED_BIT_ORDER[i]
        if bits > 24:
            for i in range(32 - bits):
                s &= ~(1 << SEED_BIT_ORDER[i]) & 0xFFFFFFFF
        self.state = s & 0x7FFFFFFF if s else 1

    def next(self):
        st = self.state
        hi = (st >> 16) * 16807
        n = (st & 0xFFFF) * 16807 + ((hi & 0x7FFF) << 16)
        if n > 0x7FFFFFFF:
            n = (n & 0x7FFFFFFF) + 1
        n += hi >> 15
        if n > 0x7FFFFFFF:
            n = (n & 0x7FFFFFFF) + 1
        self.state = n
        return n


def file_key(name):
    """FileCrypt_DeriveFileKey: the key depends on the lower-case file name without folders."""
    base = name.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    key = bytearray(BASE_KEY)
    if base and base[-4:] not in (".s2m", ".aav"):
        rng = ParkMiller(zlib.crc32(base.encode("latin-1")))
        for i in range(16):
            key[i] ^= rng.next() & 0xFF
    return bytes(key)


def xor_scramble(data, key):
    """FileCrypt_XorScramble (in place). XOR with data-independent values: encrypts and decrypts."""
    size = len(data)
    rng = ParkMiller(zlib.crc32(key))
    stream = bytes(rng.next() & 0xFF for _ in range((rng.next() & 0x7F) + 0x80))
    n = len(stream)
    for i in range(size):
        data[i] ^= stream[i % n]
    table_len = (rng.next() & 0xF) + 0x11
    table = bytes(rng.next() & 0xFF for _ in range(table_len))
    pos = rng.next() % size if size else 0
    step = (rng.next() & 0x1FFF) + 0x2000
    while pos < size:
        data[pos] ^= table[(key[pos % 16] ^ pos) % table_len]
        pos += step


def lzss_decode(src):
    """Lzss_Decode S 007630a0 (Okumura lzss.c)."""
    ring = bytearray(b" " * 1024)
    r = 0x3F0
    out = bytearray()
    i, n, flags = 0, len(src), 0
    while True:
        flags >>= 1
        if not flags & 0x100:
            if i >= n:
                break
            flags = src[i] | 0xFF00
            i += 1
        if flags & 1:
            if i >= n:
                break
            c = src[i]
            i += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) & 0x3FF
        else:
            if i + 1 >= n:
                break
            p = src[i] | (src[i + 1] & 0xF0) << 4
            length = (src[i + 1] & 0x0F) + 3
            i += 2
            for k in range(length):
                c = ring[(p + k) & 0x3FF]
                out.append(c)
                ring[r] = c
                r = (r + 1) & 0x3FF
    return bytes(out)


def lzss_encode_literal(data):
    """Valid input for Lzss_Decode: every byte a literal (flag byte 0xff before each group of 8). No
    compression (12.5 % larger), which the game's decoder reads like any other stream."""
    out = bytearray()
    for i in range(0, len(data), 8):
        out.append(0xFF)
        out += data[i:i + 8]
    return bytes(out)


def encrypt(plain, name):
    """Build a sadk container for `plain` under file name `name` (the key depends on it)."""
    key = file_key(name)
    payload = bytearray(lzss_encode_literal(plain))
    xor_scramble(payload, key)
    header = struct.pack("<I4s3I", VERSION, MAGIC, zlib.crc32(plain), zlib.crc32(key), len(plain))
    return header + bytes(payload)


def is_encrypted(head):
    return len(head) >= 8 and struct.unpack_from("<I", head)[0] == VERSION and head[4:8] == MAGIC


def decrypt(blob, name):
    """Decrypt one container; raises ValueError naming the failed check (as gDecryptData logs it)."""
    if not is_encrypted(blob) or len(blob) < 20:
        raise ValueError("not a sadk container")
    data_crc, key_crc, plain_size = struct.unpack_from("<3I", blob, 8)
    key = file_key(name)
    if zlib.crc32(key) != key_crc:
        raise ValueError("pw crc mismatch")
    payload = bytearray(blob[20:])
    xor_scramble(payload, key)
    plain = lzss_decode(payload)
    if len(plain) != plain_size:
        raise ValueError(f"datasize mismatch {plain_size} != {len(plain)}")
    if zlib.crc32(plain) != data_crc:
        raise ValueError("data crc mismatch")
    return plain


def _decrypt_one(job):
    src, dst, name = job
    with open(src, "rb") as fh:
        blob = fh.read()
    if not is_encrypted(blob):
        return "plain", src
    try:
        out = decrypt(blob, name)
    except ValueError as e:
        return "failed", f"{src}: {e}"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(out)
    return "ok", src


def decrypt_tree(src_root, dst_root):
    from multiprocessing import Pool
    jobs = [(os.path.join(d, f), os.path.join(dst_root, os.path.relpath(os.path.join(d, f), src_root)), f)
            for d, _, files in os.walk(src_root) for f in sorted(files)]
    counts = {"ok": 0, "failed": 0, "plain": 0}
    with Pool() as pool:
        for status, what in pool.imap_unordered(_decrypt_one, jobs, chunksize=4):
            counts[status] += 1
            if status == "failed":
                print("FAILED", what)
    print(f"decrypted {counts['ok']}, failed {counts['failed']}, skipped {counts['plain']} plain files")
    return counts["failed"] == 0


def main(argv):
    if len(argv) >= 3 and argv[0] == "decrypt":
        return 0 if decrypt_tree(argv[1], argv[2]) else 1
    if len(argv) == 3 and argv[0] == "encrypt":
        with open(argv[1], "rb") as fh:
            blob = encrypt(fh.read(), os.path.basename(argv[2]))
        assert decrypt(blob, os.path.basename(argv[2])) == open(argv[1], "rb").read()
        with open(argv[2], "wb") as fh:
            fh.write(blob)
        return 0
    if len(argv) >= 2 and argv[0] == "file":
        with open(argv[1], "rb") as fh:
            out = decrypt(fh.read(), os.path.basename(argv[1]))
        if len(argv) >= 3:
            with open(argv[2], "wb") as fh:
                fh.write(out)
        else:
            sys.stdout.buffer.write(out)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
