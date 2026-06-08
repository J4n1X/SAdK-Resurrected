"""
Decode the P2P game-join capture (capture_scoped.json, a tshark -T json export of the
joiner→host TinCat/Net-Driver conversation on port 5478).

READ-ONLY analysis tool. Reassembles the TCP stream and decodes the TinCat framing
(identical to the lobby: magic 0xDABAFBEF + src + dst + type + arg + len + crc32) plus
the game-session body message magics (0x0061 user-list, 0x0063, 0x27d9 game-logon).

Usage:  python tools/decode_game_join.py [capture_scoped.json]
"""
import json, struct, sys

sys.stdout.reconfigure(encoding="utf-8")
PATH = sys.argv[1] if len(sys.argv) > 1 else "capture_scoped.json"

MAGIC = 0xDABAFBEF
SPECIAL = {0xEFFFFFEE: "CLIENT/unassigned", 0xEFFFFFCC: "SERVER"}
TYPES = {2: "DATA", 3: "HANDSHAKE", 5: "HANDSHAKE_ACK", 11: "PING"}


def load_stream(path):
    data = json.load(open(path, encoding="utf-8"))
    seen, rows = set(), []
    for entry in data:
        L = entry["_source"]["layers"]
        ip, tcp = L.get("ip", {}), L.get("tcp", {})
        ph = tcp.get("tcp.payload", "")
        payload = bytes.fromhex(ph.replace(":", "")) if ph else b""
        if not payload:
            continue
        seq = int(tcp.get("tcp.seq", "0"))
        src, sport = ip.get("ip.src"), tcp.get("tcp.srcport")
        key = (src, sport, seq, len(payload))
        if key in seen:           # dedupe the doubled capture
            continue
        seen.add(key)
        t = float(L.get("frame", {}).get("frame.time_relative", "0"))
        rows.append((t, src, sport, ip.get("ip.dst"), tcp.get("tcp.dstport"), payload))
    rows.sort(key=lambda r: r[0])
    return rows


def idname(v):
    return SPECIAL.get(v, f"id={v}")


def decode_tincat(buf, indent="    "):
    """Decode a TinCat frame (or several concatenated) from a body buffer."""
    out, off = [], 0
    while off + 28 <= len(buf):
        magic, frm, to, typ, arg, plen, crc = struct.unpack_from("<IIIIIII", buf, off)
        if magic != MAGIC:
            break
        body = buf[off + 28: off + 28 + plen]
        argrepr = f"0x{arg:08x}" + (f' ="{struct.pack("<I", arg).decode("latin1")}"'
                                    if all(32 <= b < 127 for b in struct.pack("<I", arg)) else "")
        out.append(f"{indent}TinCat {idname(frm)}→{idname(to)} type={typ}({TYPES.get(typ,'?')}) "
                   f"arg={argrepr} len={plen} crc={crc:08x}")
        if body:
            out.append(f"{indent}  body[{len(body)}]: {body[:48].hex()}")
        off += 28 + plen
    return out, off


def main():
    rows = load_stream(PATH)
    if not rows:
        print("No payload packets found."); return
    joiner = (rows[0][1], rows[0][2])
    print(f"Game-join capture: {PATH}")
    print(f"Joiner {joiner[0]}:{joiner[1]}  →  Host {rows[0][3]}:{rows[0][4]}\n")
    for t, src, sport, dst, dport, payload in rows:
        d = ">>>" if (src, sport) == joiner else "<<<"
        head = struct.unpack_from("<I", payload, 0)[0] if len(payload) >= 4 else 0
        if head == MAGIC and len(payload) >= 28:
            magic, frm, to, typ, arg, plen, crc = struct.unpack_from("<IIIIIII", payload)
            tag = TYPES.get(typ, f"type{typ}")
            print(f"[{t:8.4f}] {d} {len(payload):>4}B  TinCat {idname(frm)}→{idname(to)} "
                  f"{tag} arg=0x{arg:08x} len={plen} crc={crc:08x}")
            body = payload[28:]
            if body:
                print(f"            body: {body[:64].hex()}")
        else:
            bmagic = struct.unpack_from("<H", payload, 0)[0] if len(payload) >= 2 else 0
            print(f"[{t:8.4f}] {d} {len(payload):>4}B  BODY magic=0x{bmagic:04x}")
            for o in range(0, min(len(payload), 112), 16):
                chunk = payload[o:o + 16]
                asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"            {o:04x}  {' '.join(f'{b:02x}' for b in chunk):<47}  |{asc}|")


if __name__ == "__main__":
    main()
