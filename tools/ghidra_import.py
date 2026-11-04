#!/usr/bin/env python3
"""Headless Ghidra project with one program per code unit.

Copied from Secret Weapons of the Luftwaffe's tools/ghidra_import.py (commit pinned in
manifest/references.tsv) and adapted to X-Wing's units (tools/sweep.py): the root, each
overlay segment (`FRONTEND.OVL#3`; segments share link addresses, so each is its own
program) and ADLIB.IMS. Uses tmp/sweep from a previous tools/sweep.py. For each unit:
writes its code bytes to tmp/ghidra/<unit>.bin and an entry CSV (traced instruction
starts; functions at the MZ entry, thunk targets and resolved far-call targets), imports
it into tmp/ghidra-proj/ at its link linear address (x86 real mode, BinaryLoader), seeds
the entries (ghidra_scripts/MarkEntries.java, pre-analysis) and exports
tmp/ghidra/<unit>.txt (AmigaXDev's ExportAuditListing.java). Addresses in Ghidra are
link addresses (load segment 0). The project holds the game's code and stays in tmp/.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict

import sweep as S
import xwing_model as M

GHIDRA = os.path.join(os.environ.get('GHIDRA_HOME') or '/opt/homebrew/opt/ghidra/libexec',
                      'support/analyzeHeadless')
SCRIPT_PATH = ';'.join((str(M.REPO / 'ghidra_scripts'), os.environ.get('AMIGA_GHIDRA_SCRIPTS')
                        or os.path.expanduser('~/.local/share/amiga/ghidra_scripts')))
JAVA_HOME = os.environ.get('GHIDRA_JAVA_HOME') or \
    '/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home'
PROJECT = M.REPO / 'tmp/ghidra-proj'
OUT = M.REPO / 'tmp/ghidra'


def functions(us: dict[str, S.Unit]) -> dict[str, dict[int, str]]:
    """Unit -> {file offset: name} for function seeds."""
    out: dict[str, dict[int, str]] = defaultdict(dict)
    out[M.ROOT][M.entry()] = 'mz_entry'
    with (M.REPO / 'tmp/sweep/far-refs.csv').open() as f:
        for r in csv.DictReader(f):
            owner = r['owners'].replace(' (thunk)', '')
            if owner not in us:
                continue
            u = us[owner]
            seg, off = int(r['segment'], 16), int(r['target'], 16)
            out[owner].setdefault(u.from_link(seg * 16 + off), f'far_{seg:04X}_{off:04X}')
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('units', nargs='*', help='units to import (default: all)')
    args = ap.parse_args()
    mods = M.load_modules()
    us = S.units(mods)
    funcs = functions(us)
    OUT.mkdir(parents=True, exist_ok=True)
    PROJECT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=JAVA_HOME)
    for name in args.units or list(us):
        u = us[name]
        safe = name.replace('#', '-')
        binary = OUT / f'{safe}.bin'
        hi = M.OVL_AREA[0] if name == M.ROOT else u.hi   # root: code below the overlay area
        binary.write_bytes(mods[u.file].data[u.lo:hi])
        cls = (M.REPO / f'tmp/sweep/{u.file}.cls').read_bytes()
        entries = OUT / f'{safe}-entries.csv'
        with entries.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['linear', 'kind', 'name'])
            for off, fname in sorted(funcs[name].items()):
                if u.lo <= off < hi and cls[off] in (1, 3):
                    w.writerow([f'0x{u.to_link(off):05x}', 'func', fname])
            for off in range(u.lo, hi):
                if cls[off] == 3:
                    w.writerow([f'0x{u.to_link(off):05x}', 'code', ''])
        cmd = [GHIDRA, str(PROJECT), 'XWING', '-import', str(binary), '-overwrite',
               '-processor', 'x86:LE:16:Real Mode', '-loader', 'BinaryLoader',
               '-loader-baseAddr', f'0x{u.link_lo:x}', '-scriptPath', SCRIPT_PATH,
               '-preScript', 'MarkEntries.java', str(entries),
               '-postScript', 'ExportAuditListing.java', str(OUT / f'{safe}.txt')]
        log = OUT / f'{safe}.log'
        with log.open('w') as fh:
            status = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
        head = (OUT / f'{safe}.txt').read_text().splitlines()[0] if (OUT / f'{safe}.txt').exists() else '-'
        print(f'{name:16} {"ok" if status == 0 else f"FAIL {status} (see {log})"}  {head}', flush=True)
        if status:
            return status
    return 0


if __name__ == '__main__':
    sys.exit(main())
