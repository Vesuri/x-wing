#!/usr/bin/env python3
"""Name X-Wing's Microsoft C run-time routines by signature from Secret Weapons of the Luftwaffe.

Input: SWOTL's annotations/runtime.csv at the commit pinned in manifest/references.tsv
(read with git from the SWOTL checkout, --swotl or $SWOTL_REPO) and its original
SWOTL.EXE (its ref/, pinned in manifest/donor-binaries.sha256). Each named SWOTL routine
gives a signature: its instructions from the entry to the first return or unconditional
jump (at most 48), each as mnemonic and operand shape, with immediates, displacements and
branch targets left out. A routine of at least MIN_INSNS instructions is named in X-Wing
where exactly one static instruction start of the swept modules (tmp/sweep/*.cls) begins
the same sequence. Writes annotations/runtime.csv (evidence: the SWOTL routine and the
signature length); prints the matched, ambiguous and unmatched counts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import capstone
from capstone import x86

import xwing_model as M

MIN_INSNS = 6
MAX_INSNS = 48
SWEPT = [M.ROOT, 'FRONTEND.OVL', 'FLIGHT.OVL']
PIN = M.REPO / 'manifest/donor-binaries.sha256'


def pinned_commit(project: str) -> str:
    with (M.REPO / 'manifest/references.tsv').open() as f:
        return next(r['commit'] for r in csv.DictReader(f, delimiter='\t') if r['project'] == project)


def shape(i) -> tuple:
    out = [i.mnemonic]
    for op in i.operands:
        if op.type == x86.X86_OP_REG:
            out.append(i.reg_name(op.reg))
        elif op.type == x86.X86_OP_IMM:
            out.append('imm')
        elif op.type == x86.X86_OP_MEM:
            m = op.mem
            out.append(('mem', op.size, i.reg_name(m.segment) if m.segment else '',
                        i.reg_name(m.base) if m.base else '', i.reg_name(m.index) if m.index else ''))
    return tuple(out)


def signature(md, data: bytes, off: int) -> tuple:
    sig = []
    for i in md.disasm(data[off:off + MAX_INSNS * 8], 0):
        sig.append(shape(i))
        g = set(i.groups)
        if capstone.CS_GRP_RET in g or capstone.CS_GRP_IRET in g or \
                i.mnemonic in ('jmp', 'ljmp') or len(sig) >= MAX_INSNS:
            break
    return tuple(sig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--swotl', type=Path, default=os.environ.get('SWOTL_REPO'),
                    help='Secret Weapons of the Luftwaffe checkout (default $SWOTL_REPO)')
    args = ap.parse_args()
    if not args.swotl:
        print('runtime names: give --swotl or set SWOTL_REPO', file=sys.stderr)
        return 1
    exe = args.swotl / 'ref/SWOTL.EXE'
    want = dict(reversed(l.split()) for l in PIN.read_text().splitlines())['SWOTL.EXE']
    if hashlib.sha256(exe.read_bytes()).hexdigest() != want:
        print(f'runtime names: {exe} differs from its pin', file=sys.stderr)
        return 1
    commit = pinned_commit('Secret Weapons of Luftwaffe')
    text = subprocess.run(['git', '-C', str(args.swotl), 'show', f'{commit}:annotations/runtime.csv'],
                          capture_output=True, text=True, check=True).stdout
    donors = list(csv.DictReader(io.StringIO(text)))
    swotl, _, _ = M.mz(exe)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    md.detail = True
    mods = M.load_modules()
    index: dict[tuple, list[tuple[str, int, bool]]] = defaultdict(list)
    for f in SWEPT:
        cls = (M.REPO / f'tmp/sweep/{f}.cls').read_bytes()
        for off, c in enumerate(cls):
            if c in (1, 3):
                index[signature(md, mods[f].data, off)[:MIN_INSNS]].append((f, off, c == 3))
    rows, ambiguous, unmatched = [], [], []
    for d in donors:
        sig = signature(md, swotl, int(d['offset'], 16))
        if len(sig) < MIN_INSNS:
            unmatched.append(d['name'])
            continue
        hits = [(f, off, x) for f, off, x in index.get(sig[:MIN_INSNS], [])
                if signature(md, mods[f].data, off) == sig]
        if len(hits) == 1:
            f, off, x = hits[0]
            rows.append([f, f'0x{off:05x}', '-', d['name'], d['class'], int(x),
                         f"signature of SWOTL.EXE+{int(d['offset'], 16):05X} ({len(sig)} instructions)"])
        elif hits:
            ambiguous.append(f"{d['name']} ({len(hits)})")
        else:
            unmatched.append(d['name'])
    rows.sort()
    with (M.REPO / 'annotations/runtime.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['module', 'offset', 'seg_ip', 'name', 'class', 'executed', 'evidence'])
        w.writerows(rows)
    print(f'runtime names: {len(donors)} SWOTL routines; named {len(rows)}, ambiguous '
          f'{len(ambiguous)}, unmatched {len(unmatched)}')
    if ambiguous:
        print('ambiguous: ' + ', '.join(ambiguous))
    return 0


if __name__ == '__main__':
    sys.exit(main())
