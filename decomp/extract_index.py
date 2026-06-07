#!/usr/bin/env python3
"""
extract_index.py — build navigation indexes from a Ghidra "Export as C/C++" dump.

The SADK.exe / tincat3.dll exports are unlabeled (only auto-generated FUN_/DAT_
names), so the way in is the decompiler's regular formatting plus the inlined
string literals. This script parses that formatting and emits, next to each .c:

  <stem>_functions.tsv   addr  c_line  n_lines  n_strings  signature
  <stem>_strings.tsv     c_line  func_addr  func_line  string
  <stem>_strings_uniq.txt   sorted unique string literals (the program's vocabulary)

Function boundaries rely on Ghidra's layout: a signature at column 0, then a line
that is exactly "{" at column 0, indented body, and a line that is exactly "}" at
column 0 (nested braces are always indented, so the col-0 "}" is the function end).

Usage:
  python extract_index.py decomp/sadk/SADK.exe.c decomp/tincat/tincat3.dll.c
"""
import re, sys, os

SIG_NAME   = re.compile(r'([A-Za-z_]\w*)\s*\(')          # last ident before '(' = name
ADDR_IN    = re.compile(r'(?:thunk_)?(?:FUN|LAB)_([0-9a-fA-F]{6,16})')
STR_LIT    = re.compile(r'"((?:[^"\\]|\\.)*)"')
COMMENTish = ('//', '/*', '*')


def is_sig_candidate(line: str) -> bool:
    if not line or line[0].isspace():
        return False
    s = line.lstrip()
    if s.startswith(COMMENTish) or s[0] in '{}#':
        return False
    return True


def func_name_and_addr(sig: str):
    # name = identifier immediately preceding the parameter '('
    name, addr = '', ''
    depth = 0
    # find the '(' that opens the param list: first top-level '('
    paren = sig.find('(')
    if paren != -1:
        head = sig[:paren]
        m = None
        for m in re.finditer(r'[A-Za-z_]\w*', head):
            pass
        if m:
            name = m.group(0)
    a = ADDR_IN.search(name or sig)
    if a:
        addr = a.group(1).lower().rjust(8, '0')
    return name, addr


def parse(path: str):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.read().split('\n')
    funcs, strings = [], []
    i, n = 0, len(lines)
    while i < n:
        if lines[i].rstrip() == '{':
            # walk back over blanks/comments to collect the signature
            j = i - 1
            sig_parts = []
            while j >= 0:
                ln = lines[j]
                if ln.strip() == '' or ln.lstrip().startswith(COMMENTish):
                    if sig_parts:      # blank/comment above a started sig => stop
                        break
                    j -= 1
                    continue
                if is_sig_candidate(ln):
                    sig_parts.insert(0, ln.strip())
                    if '(' in ln:      # got the param list, signature complete
                        break
                    j -= 1
                else:
                    break
            if not sig_parts or '(' not in ' '.join(sig_parts):
                i += 1
                continue
            sig = ' '.join(sig_parts)
            sig_line = j + 1                       # 1-based line of signature start
            # find function close: next col-0 "}"
            k = i + 1
            while k < n and lines[k].rstrip() != '}':
                k += 1
            body = '\n'.join(lines[i:k + 1])
            name, addr = func_name_and_addr(sig)
            lits = STR_LIT.findall(body)
            funcs.append((addr, sig_line, k - i + 1, len(lits), sig))
            for off, s in enumerate(lits):
                # locate the line of this literal for a precise jump
                strings.append((addr, sig_line, s))
            i = k + 1
        else:
            i += 1
    return funcs, strings


def main(paths):
    for path in paths:
        stem = path[:-2] if path.endswith('.c') else path
        funcs, strings = parse(path)

        with open(stem + '_functions.tsv', 'w', encoding='utf-8') as f:
            f.write('addr\tc_line\tn_lines\tn_strings\tsignature\n')
            for a, ln, nl, ns, sig in funcs:
                f.write(f'{a}\t{ln}\t{nl}\t{ns}\t{sig}\n')

        with open(stem + '_strings.tsv', 'w', encoding='utf-8') as f:
            f.write('func_addr\tfunc_line\tstring\n')
            for a, ln, s in strings:
                s = s.replace('\t', '\\t').replace('\n', '\\n')
                f.write(f'{a}\t{ln}\t{s}\n')

        uniq = sorted({s for _, _, s in strings})
        with open(stem + '_strings_uniq.txt', 'w', encoding='utf-8') as f:
            for s in uniq:
                f.write(s.replace('\t', '\\t').replace('\n', '\\n') + '\n')

        named = sum(1 for a, *_ in funcs if a)
        print(f'{os.path.basename(path)}: {len(funcs)} functions '
              f'({named} with FUN_/LAB_ address), '
              f'{len(strings)} string refs, {len(uniq)} unique strings')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
