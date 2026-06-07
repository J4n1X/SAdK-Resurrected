#!/usr/bin/env python3
"""
SaDK Capture Analyzer
Reads a binary capture file produced by lobby_proxy.py and performs deep analysis.

Usage:
  python analyze_capture.py sadk_captures/conn_2_<timestamp>.bin
  python analyze_capture.py sadk_captures/conn_2_<timestamp>.bin --key Siedler
"""

import sys
import struct
import argparse
import os

# ── TinCat_Scramble (from Ghidra decompile of 0x10007d70) ──────────────────

def tincat_encrypt(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    out  = bytearray(data)
    prev = 0x3F
    klen = len(key)
    for i in range(len(out)):
        raw    = out[i]
        mixed  = (raw + i + prev) & 0xFF
        out[i] = key[i % klen] ^ mixed
        prev   = raw
    return bytes(out)

def tincat_decrypt(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    out  = bytearray(data)
    prev = 0x3F
    klen = len(key)
    for i in range(len(out)):
        mixed  = key[i % klen] ^ out[i]
        plain  = (mixed - i - prev) & 0xFF
        out[i] = plain
        prev   = plain
    return bytes(out)

# ── Helpers ──────────────────────────────────────────────────────────────────

def hex_dump(data: bytes, indent="  ", width=16) -> str:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{i:04x}  {h:<{width*3}}  |{a}|")
    return "\n".join(lines)

def find_strings(data: bytes, min_len=4) -> list:
    results, cur, start = [], [], None
    for i, b in enumerate(data):
        if 32 <= b < 127:
            if start is None:
                start = i
            cur.append(chr(b))
        else:
            if cur and len(cur) >= min_len:
                results.append((start, "".join(cur)))
            cur, start = [], None
    if cur and len(cur) >= min_len:
        results.append((start, "".join(cur)))
    return results

def find_bytes(haystack: bytes, needle: bytes) -> list:
    pos, hits = 0, []
    while True:
        idx = haystack.find(needle, pos)
        if idx == -1:
            break
        hits.append(idx)
        pos = idx + 1
    return hits

MSG_NAMES = {
    1:"Simple", 2:"ChatMessage", 3:"PrivateChatMessage", 4:"RequestLogin",
    5:"UserJoinedChannel", 6:"UserLeftChannel", 7:"ChannelInfo", 42:"Result",
    71:"RequestCreateAccount", 105:"RequestMOTD", 106:"MOTD",
    107:"RegObserverGlobalChat", 183:"CheckLevel", 188:"CheckVersion",
    201:"StartAuthenticateSession", 202:"AckAuthenticateSession",
    203:"SelfRegistration", 204:"AuthenticateUser", 207:"SessionKey",
    211:"StartValidateTokenSession", 212:"AckValidateTokenSession",
    213:"SendToken", 214:"ValidateToken",
}

def try_decode_msg(data: bytes, label="") -> list:
    hits = []
    for off in range(min(40, len(data) - 2)):
        t = struct.unpack_from("<H", data, off)[0]
        if t in MSG_NAMES:
            hits.append(f"  [{label}+{off}] TYPE {t} = {MSG_NAMES[t]}")
    return hits

# ── Parse binary capture file ─────────────────────────────────────────────

def parse_capture(path: str):
    """
    File format written by lobby_proxy.py:
        [HH:MM:SS.mmm] <direction> <N> bytes\n
        <N raw bytes>
        \n
    Repeated for each chunk.
    """
    chunks = []
    with open(path, "rb") as f:
        raw = f.read()

    pos = 0
    while pos < len(raw):
        # Find next marker line
        nl = raw.find(b"\n", pos)
        if nl == -1:
            break
        line = raw[pos:nl].decode("ascii", errors="replace").strip()
        pos = nl + 1

        # Parse header line: "[HH:MM:SS.mmm] c2s 80 bytes"
        if not line.startswith("["):
            continue
        parts = line.split()
        if len(parts) < 4 or parts[3] != "bytes":
            continue
        try:
            n = int(parts[2])
            direction = parts[1]
        except Exception:
            continue

        data = raw[pos:pos+n]
        pos += n
        if pos < len(raw) and raw[pos:pos+1] == b"\n":
            pos += 1

        chunks.append((direction, data, line))

    return chunks

# ── Main analysis ─────────────────────────────────────────────────────────

def analyze(path: str, serial: str = None, extra_keys: list = None):
    print(f"\n{'='*70}")
    print(f"SaDK Capture Analyzer")
    print(f"File: {path}")
    print(f"{'='*70}\n")

    chunks = parse_capture(path)
    if not chunks:
        print("No chunks found. File may be empty or wrong format.")
        return

    print(f"Total chunks in capture: {len(chunks)}\n")

    # All keys to try for decryption
    keys_to_try = []
    if serial:
        keys_to_try.append(serial.encode())
    if extra_keys:
        keys_to_try.extend(k.encode() for k in extra_keys)
    keys_to_try += [b"TinCat", b"Funatics", b"SADK", b"sadk", b"Siedler", b"siedler"]

    for chunk_idx, (direction, data, header) in enumerate(chunks):
        arrow = "CLIENT ──► SERVER" if direction == "c2s" else "SERVER ──► CLIENT"
        print(f"\n{'─'*70}")
        print(f"Chunk #{chunk_idx+1}  {arrow}  {len(data)} bytes")
        print(f"  ({header})")
        print()

        # Raw hex dump
        print(f"  HEX DUMP:")
        print(hex_dump(data))

        # Strings in raw data
        strs = find_strings(data, min_len=4)
        if strs:
            print(f"\n  STRINGS IN RAW DATA:")
            for off, s in strs:
                print(f"    offset {off:4d} (0x{off:02x}): {s!r}")

        # TinCat magic detection
        MAGIC = b'\xef\xfb\xba\xda'
        magic_hits = find_bytes(data, MAGIC)
        if magic_hits:
            print(f"\n  TinCat magic 0xEFFBBADA at offsets: {magic_hits}")
            # Hypothesis: second magic instance marks end of header
            if len(magic_hits) >= 2:
                header_end = magic_hits[1]
                print(f"  → Header likely ends at offset {header_end} (second magic)")
                payload = data[header_end+4:]
                print(f"  → Payload after second magic ({len(payload)} bytes):")
                print(hex_dump(payload, indent="    "))
                inner_strs = find_strings(payload, min_len=3)
                if inner_strs:
                    print(f"  → Payload strings:")
                    for off, s in inner_strs:
                        print(f"      +{off}: {s!r}")
                inner_msgs = try_decode_msg(payload, "payload")
                for m in inner_msgs:
                    print(m)

        # Try extracting length field (big-endian uint32 at offset 16)
        if len(data) >= 20:
            be_len = struct.unpack_from(">I", data, 16)[0]
            if 4 <= be_len <= len(data):
                payload_off = len(data) - be_len
                print(f"\n  Length field at offset 16 (BE) = {be_len}")
                print(f"  → Suggests payload at offset {payload_off}:")
                inner_msgs = try_decode_msg(data[payload_off:], f"@{payload_off}")
                for m in inner_msgs:
                    print(m)

        # Try msgdef decoding at each possible header size
        print(f"\n  MSGDEF TYPE SCAN (scanning first 40 bytes for known types):")
        msgs = try_decode_msg(data)
        if msgs:
            for m in msgs:
                print(m)
        else:
            print("    No known msgdef type found in raw packet")

        # Scramble decrypt attempts
        print(f"\n  SCRAMBLE DECRYPT ATTEMPTS:")
        for key in keys_to_try:
            dec = tincat_decrypt(data, key)
            strs_dec = find_strings(dec, min_len=4)
            msgs_dec = try_decode_msg(dec)
            if strs_dec or msgs_dec:
                print(f"  key={key!r}:")
                if msgs_dec:
                    for m in msgs_dec:
                        print(f"    {m.strip()}")
                if strs_dec:
                    for off, s in strs_dec:
                        print(f"    dec+{off}: {s!r}")
                # Show decrypted hex for first 64 bytes
                print(f"    Decrypted hex (first 64 bytes):")
                print(hex_dump(dec[:64], indent="      "))

    # Cross-chunk analysis: show the full raw byte stream
    print(f"\n{'='*70}")
    print("FULL BYTE STREAM SUMMARY")
    print(f"{'='*70}")
    all_data = b"".join(d for _, d, _ in chunks)
    print(f"Total bytes across all chunks: {len(all_data)}")
    all_strs = find_strings(all_data, min_len=4)
    if all_strs:
        print("All strings in full stream:")
        for off, s in all_strs:
            print(f"  offset {off:4d} (0x{off:03x}): {s!r}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SaDK binary capture analyzer")
    parser.add_argument("file", help="Path to .bin capture file")
    parser.add_argument("--serial", "--key", help="Serial number / CD key used during login")
    parser.add_argument("--extra-keys", nargs="*", help="Additional keys to try for scramble decryption")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        sys.exit(1)

    analyze(args.file, serial=args.serial, extra_keys=args.extra_keys)
