#!/usr/bin/env python3
"""Rebuild root, overlay and driver images from the files and compare with a snapshot.

Copied from Secret Weapons of the Luftwaffe's tools/load_image.py (commit pinned in
manifest/references.tsv) and adapted to X-Wing's loader model (tools/xwing_model.py):
- root: MZ load image at the load segment, each relocation word += load segment;
- overlay file: the module offset is the file offset; code bytes of every segment have
  their fixup words += load segment; other bytes (fixup tables) are raw file bytes;
- music driver: MZ load image with each relocation word += the relocation segment of
  its INT 21h AX=4B03 load (exec_overlay event).

Every snapshot residency row is compared with the rebuilt bytes; bytes of a row past the
end of the module's file or load image are counted as beyond. A differing byte must
have a CPU writer since its load (snapshot writes.csv) or be the byte the last traced DOS
read put there (reads.bin); written bytes are split into executed instruction bytes
(trace bitmap + Capstone length: self-modifying code, listed by writer) and data. Exit 1
if any byte differs without a writer, or a resident module has no model.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import capstone

import xwing_model as M


def dos_reads(trace: Path, until: int) -> dict[int, int]:
    """Linear address -> byte from the last traced DOS read before `until`."""
    payload = (trace / 'reads.bin').read_bytes()
    out = {}
    for row in M.events(trace, ('read',)):
        if int(row[0]) > until:
            break
        name, *kv = row[4].split()
        kv = dict(x.split('=') for x in kv)
        lin, got, offset = int(kv['linear'], 16), int(kv['got']), int(kv['data'])
        data = payload[offset:offset + got]
        if len(data) != got:
            raise ValueError(f'{trace}: {name} read: expected {got} bytes, got {len(data)}')
        for k, byte in enumerate(data):
            out[lin + k] = byte
    return out


def driver_relocations(trace: Path, until: int) -> dict[str, int]:
    out = {}
    for row in M.events(trace, ('exec_overlay',)):
        if int(row[0]) > until:
            break
        name, *kv = row[4].split()
        out[name] = int(dict(x.split('=') for x in kv)['reloc'], 16)
    return out


def code_bytes(image: bytes, bitmap: bytes) -> set[int]:
    """Module offsets covered by executed instructions (lengths from Capstone)."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    cover = set()
    for off, hit in enumerate(bitmap):
        if hit and off < len(image):
            insn = next(md.disasm(bytes(image[off:off + 16]), 0), None)
            cover.update(range(off, off + (insn.size if insn else 1)))
    return cover


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('snapshot', type=Path, help='ref/dosbox/runs/<run>/trace/snap-<name>')
    ap.add_argument('--ref', type=Path, default=M.REF)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    snap, trace = args.snapshot, args.snapshot.parent
    regs = dict(kv.split('=') for kv in (snap / 'regs.txt').read_text().split())
    load, until = int(regs['load_seg'], 16), int(regs['icount'])
    ram = (snap / 'ram.bin').read_bytes()
    mods = M.load_modules(args.ref)
    reloc = driver_relocations(trace, until)
    images = {}
    for name, m in mods.items():
        if name in M.DRIVERS:
            if name in reloc:
                images[name] = M.relocated(m, reloc[name])
        else:
            images[name] = M.relocated(m, load)
    read = dos_reads(trace, until)
    writer = {}
    with (snap / 'writes.csv').open() as f:
        for r in csv.DictReader(f):
            w = f"{r['writer_module']}+{int(r['writer_offset'], 16):05X}"
            for a in range(int(r['first_linear'], 16), int(r['last_linear'], 16) + 1):
                writer[a] = w
    cover = {}
    smc = Counter()
    failed = False
    print(f'load segment {load:04X}')
    print(f"{'module':12} {'linear':>13} {'bytes':>7} {'same':>7} {'code-wr':>7} "
          f"{'data-wr':>7} {'beyond':>6} {'unexpl':>6}")
    with (snap / 'residency.csv').open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        mod = r['module']
        lo, hi = int(r['first_para'], 16) * 16, (int(r['last_para'], 16) + 1) * 16
        if mod not in images:
            print(f'{mod:12} {lo:06X}-{hi:06X} no loader model')
            failed = True
            continue
        img = images[mod]
        moff = int(r['module_offset'], 16)
        if mod not in cover:
            bm = trace / f'executed-{mod}.bin'
            cover[mod] = code_bytes(img, bm.read_bytes() if bm.exists() else b'')
        same = code_wr = data_wr = beyond = 0
        bad = []
        for k in range(hi - lo):
            off = moff + k
            if not 0 <= off < len(img):
                beyond += 1  # past the end of the file or load image: the loader wrote nothing
                continue
            if img[off] == ram[lo + k]:
                same += 1
            elif lo + k not in writer:
                if read.get(lo + k) == ram[lo + k]:
                    data_wr += 1
                else:
                    bad.append(off)
            elif off in cover[mod]:
                code_wr += 1
                smc[(mod, writer[lo + k])] += 1
            else:
                data_wr += 1
        failed |= bool(bad)
        print(f'{mod:12} {lo:06X}-{hi:06X} {hi - lo:7} {same:7} {code_wr:7} {data_wr:7} {beyond:6} {len(bad):6}')
        if args.verbose and bad:
            print('  unexplained at', ' '.join(f'{o:05X}' for o in bad[:32]))
    for (mod, w), n in sorted(smc.items()):
        print(f'self-modified {mod} executed bytes: {n:5} by {w}')
    print('gate: FAIL' if failed else
          'gate: every byte matches the file + loader model or has a CPU writer')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
