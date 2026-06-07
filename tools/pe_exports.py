r"""
pe_exports.py -- minimal PE32 export-table parser (no deps, never executes the DLL).

Used to map the SAdK protector's baked WinXP kernel32 address 0x7C81320C
(RVA 0x1320C, base 0x7C800000) to a function NAME, and to build the XP-RVA ->
current-address shim. Parses raw PE bytes only.
"""
import struct, sys

def parse_exports(path):
    data = open(path, "rb").read()
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[e_lfanew:e_lfanew+4] == b"PE\0\0", "not a PE"
    coff = e_lfanew + 4
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    size_opt     = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    assert magic == 0x10B, f"not PE32 (magic={magic:#x})"
    image_base = struct.unpack_from("<I", data, opt + 0x1C)[0]
    dd = opt + 0x60                                   # DataDirectory[] for PE32
    exp_va, exp_size = struct.unpack_from("<II", data, dd)   # [0] = export table

    sec_off = opt + size_opt
    sections = []
    for i in range(num_sections):
        so = sec_off + i * 40
        vsize, va, raw_size, raw_off = struct.unpack_from("<IIII", data, so + 8)
        sections.append((va, vsize, raw_off, raw_size))

    def rva2off(rva):
        for va, vsize, raw_off, raw_size in sections:
            if va <= rva < va + max(vsize, raw_size):
                return raw_off + (rva - va)
        return None

    eoff = rva2off(exp_va)
    base_ord = struct.unpack_from("<I", data, eoff + 0x10)[0]
    nfunc    = struct.unpack_from("<I", data, eoff + 0x14)[0]
    nname    = struct.unpack_from("<I", data, eoff + 0x18)[0]
    eat_rva  = struct.unpack_from("<I", data, eoff + 0x1C)[0]
    nam_rva  = struct.unpack_from("<I", data, eoff + 0x20)[0]
    ord_rva  = struct.unpack_from("<I", data, eoff + 0x24)[0]
    eat_off, nam_off, ord_off = rva2off(eat_rva), rva2off(nam_rva), rva2off(ord_rva)

    eat = [struct.unpack_from("<I", data, eat_off + 4*i)[0] for i in range(nfunc)]
    exports, forwarders = {}, {}
    for i in range(nname):
        nrva = struct.unpack_from("<I", data, nam_off + 4*i)[0]
        no = rva2off(nrva); end = data.index(b"\0", no)
        nm = data[no:end].decode("latin1")
        oidx = struct.unpack_from("<H", data, ord_off + 2*i)[0]
        frva = eat[oidx]
        if exp_va <= frva < exp_va + exp_size:        # forwarder
            fo = rva2off(frva); fend = data.index(b"\0", fo)
            forwarders[nm] = data[fo:fend].decode("latin1")
        else:
            exports[nm] = frva
    return dict(exports=exports, forwarders=forwarders, nfunc=nfunc, nname=nname,
                image_base=image_base)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else r"<path-to-xp_kernel32.dll>"
    target = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x1320C
    r = parse_exports(path)
    exp, fwd = r["exports"], r["forwarders"]
    print(f"file              : {path}")
    print(f"image_base        : {r['image_base']:#010x}")
    print(f"named exports     : {len(exp)}  forwarders: {len(fwd)}  nfunc: {r['nfunc']}  nname: {r['nname']}")
    print(f"target RVA        : {target:#x}   (abs @0x7C800000 = {0x7C800000+target:#010x})")
    exact = [n for n, rva in exp.items() if rva == target]
    print(f"EXACT export @ RVA {target:#x}: {exact}")
    fexact = [n for n, s in fwd.items()
              if False]  # forwarders have export-dir RVAs, not code RVAs; skip
    below = sorted([(rva, n) for n, rva in exp.items() if rva <= target])
    above = sorted([(rva, n) for n, rva in exp.items() if rva >  target])
    print("nearest <= target :", [(hex(rva), n) for rva, n in below[-4:]])
    print("nearest >  target :", [(hex(rva), n) for rva, n in above[:4]])
    print("in [0x13000,0x13400]:",
          sorted([(hex(rva), n) for n, rva in exp.items() if 0x13000 <= rva < 0x13400]))
