#!/usr/bin/env python3
"""P2 census of the swept code and the trace corpus, with counts (docs/external-surface.md).

Sections, as markdown on stdout:
- opcodes: instruction starts per module (static, executed), the 80186+ opcodes, and the
  translator fit: every static start decoded by translator/decode.py (Secret Weapons of
  the Luftwaffe's decoder, copied unchanged), its rejections counted by reason;
- EMS: INT 67h functions per milestone (svc events), with the map call (AH=44h) count;
- self-modifying code: tmp/sweep/code-writes.csv rows of class self-modified;
- indirect transfers: tmp/sweep/indirect.csv, switch tables, far pointers in the root's data
  that relocate into the overlay area;
- hooked vectors: INT 21h AH=25h by vector, hardware interrupt handlers, mouse callbacks
  (INT 33h AX=000Ch/0014h);
- ports by device class, including the classes never touched;
- the music driver interface: traced transfers from the game into the driver and back,
  apart from interrupt entry and return;
- VGA: modes set, palette writes, sequencer and CRTC writes (chain-4, page flips), the
  A000h pages used.
Run tools/sweep.py and tools/code_writes.py first. Exit 1 if an input is missing.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import capstone

import xwing_model as M

sys.path.insert(0, str(M.REPO))
from translator.decode import DecodeError, decode  # noqa: E402

SWEEP = M.REPO / 'tmp/sweep'
CACHE = M.REPO / 'tmp/census'
FILES = [M.ROOT, 'FRONTEND.OVL', 'FLIGHT.OVL', 'ADLIB.IMS']
DRIVER = 'ADLIB.IMS'
OPCODES_186 = {0x60: 'pusha', 0x61: 'popa', 0x62: 'bound', 0x68: 'push imm16', 0x69: 'imul imm16',
               0x6A: 'push imm8', 0x6B: 'imul imm8', 0x6C: 'insb', 0x6D: 'insw', 0x6E: 'outsb',
               0x6F: 'outsw', 0xC0: 'shift r/m8, imm8', 0xC1: 'shift r/m16, imm8', 0xC8: 'enter',
               0xC9: 'leave'}
PORT_CLASSES = [
    ('DMA controller', lambda p: p < 0x20 or 0x80 <= p < 0xA0 or 0xC0 <= p < 0xE0),
    ('PIC', lambda p: p in (0x20, 0x21, 0xA0, 0xA1)),
    ('PIT', lambda p: 0x40 <= p <= 0x43),
    ('keyboard controller, speaker', lambda p: p in (0x60, 0x61, 0x64)),
    ('game port', lambda p: p == 0x201),
    ('Sound Blaster', lambda p: 0x220 <= p <= 0x22F),
    ('MPU-401', lambda p: p in (0x330, 0x331)),
    ('AdLib', lambda p: p in (0x388, 0x389)),
    ('VGA', lambda p: 0x3C0 <= p <= 0x3DF),
]


def svc_census(trace: Path) -> list[list[str]]:
    """(module, offset, vector, ax, count) of a trace's svc events, cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f'{trace.parent.name}.svc.csv'
    src = M.events_path(trace)
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        tmp = out.with_suffix('.part')
        subprocess.run(
            f"gzip -dc '{src}' | awk -F, '$2==\"svc\"{{split($5,a,\" \"); "
            f"c[$3\",\"$4\",\"a[1]\",\"substr(a[2],4)]++}} END{{for(k in c) print k\",\"c[k]}}' > '{tmp}'",
            shell=True, check=True)
        tmp.rename(out)
    return [line.split(',') for line in out.read_text().splitlines()]


def opcodes(mods) -> None:
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    print('## Opcodes\n')
    print('| Module | Starts (static) | Executed | Mnemonics | 80186+ starts (executed) | '
          'Rejected by the decoder (executed) |\n|---|---|---|---|---|---|')
    ops186: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    reasons: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in FILES:
        cls = (SWEEP / f'{f}.cls').read_bytes()
        data = mods[f].data
        n = ex = n186 = x186 = rej = xrej = 0
        mn = set()
        for off, c in enumerate(cls):
            if c not in (1, 3):
                continue
            n += 1
            ex += c == 3
            i = next(md.disasm(data[off:off + 16], 0), None)
            if i is not None:
                mn.add(i.mnemonic)
            k = off
            while data[k] in (0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3):
                k += 1
            if data[k] in OPCODES_186 or data[k] == 0x0F:
                n186 += 1
                x186 += c == 3
                r = ops186[(f, data[k])]
                r[0] += 1
                r[1] += c == 3
            try:
                decode(data[off:off + 16], 0)
            except DecodeError as e:
                rej += 1
                xrej += c == 3
                r = reasons[f'{f}: {e}']
                r[0] += 1
                r[1] += c == 3
        print(f'| {f} | {n} | {ex} | {len(mn)} | {n186} ({x186}) | {rej} ({xrej}) |')
    print('\n| Module | Opcode | Instruction | Static starts | Executed |\n|---|---|---|---|---|')
    for (f, op), (s, x) in sorted(ops186.items()):
        print(f'| {f} | {op:02X}h | {OPCODES_186.get(op, "0Fh escape")} | {s} | {x} |')
    print('\nDecoder rejections by reason (static, executed): ' +
          (', '.join(f'{k} {s} ({x})' for k, (s, x) in sorted(reasons.items())) or 'none') + '.\n')


def ems(traces) -> None:
    print('## EMS (INT 67h) per milestone\n')
    rows = {}
    with ThreadPoolExecutor(8) as ex:
        for t, svc in zip(traces, ex.map(svc_census, traces)):
            c = Counter()
            for mod, off, vec, ax, n in svc:
                if vec == '67':
                    c[ax[:2].upper()] += int(n)
            rows[t.parent.name] = c
    funcs = sorted({k for c in rows.values() for k in c})
    print('| Run | ' + ' | '.join(f'AH={f}h' for f in funcs) + ' |\n|---|' + '---|' * len(funcs))
    for name, c in rows.items():
        print(f'| {name} | ' + ' | '.join(str(c.get(f, 0)) for f in funcs) + ' |')
    print()
    return rows


def smc() -> None:
    print('## Self-modifying code\n')
    rows = list(csv.DictReader((SWEEP / 'code-writes.csv').open()))
    sm = [r for r in rows if r['class'] == 'self-modified']
    by = defaultdict(lambda: [0, set()])
    for r in sm:
        k = (r['module'], r['writer'])
        by[k][0] += int(r['bytes'])
        by[k][1].add(r['first'])
    print('| Module | Writer | Bytes | Runs |\n|---|---|---|---|')
    for (m, w), (n, runs) in sorted(by.items()):
        print(f'| {m} | {w} | {n} | {len(runs)} |')
    print(f'\nWrites into decoded code: {sum(int(r["bytes"]) for r in sm)} bytes by {len(by)} '
          'writers (classes from tools/code_writes.py).\n')


def indirect(mods) -> None:
    print('## Indirect transfers\n')
    rows = list(csv.DictReader((SWEEP / 'indirect.csv').open()))
    by = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        v = by[r['module']]
        v[0] += 1
        v[1] += r['executed'] == '1'
        v[2] += bool(r['switch_targets'])
        v[3] += bool(r['traced_targets'])
    print('| Module | Sites | Executed | Switch tables | With traced targets |\n|---|---|---|---|---|')
    for m, (n, x, s, t) in sorted(by.items()):
        print(f'| {m} | {n} | {x} | {s} | {t} |')
    root = mods[M.ROOT]
    lo, hi = M.OVL_AREA
    ptr = Counter()
    for fx in root.fixups:
        if fx >= hi and fx >= 2:
            seg = int.from_bytes(root.data[fx:fx + 2], 'little')
            ptr['overlay area' if lo <= seg * 16 < hi else 'root' if seg * 16 < lo else 'data'] += 1
    print(f"\nRoot data relocations (segment words above the overlay area): "
          f"{sum(ptr.values())}, of which into the overlay area {ptr['overlay area']}, root code "
          f"{ptr['root']}, data {ptr['data']}: far pointers whose module depends on the resident "
          "base segment.\n")


def vectors(traces, svcs) -> None:
    print('## Hooked vectors\n')
    set_vec = Counter()
    mouse = Counter()
    for svc in svcs:
        for mod, off, vec, ax, n in svc:
            if vec == '21' and ax[:2].lower() == '25':
                set_vec[(ax[2:].upper(), f'{mod}+{int(off, 16):05X}')] += int(n)
            if vec == '33' and ax.lower() in ('000c', '0014', '0018'):
                mouse[(ax, mod)] += int(n)
    print('| Vector | Set by (×count) |\n|---|---|')
    by = defaultdict(list)
    for (v, site), n in sorted(set_vec.items()):
        by[v].append(f'{site}×{n}')
    for v, sites in sorted(by.items()):
        print(f'| {v}h | {", ".join(sites)} |')
    hw = defaultdict(Counter)
    for r in M.csv_rows(traces, 'interrupts.csv'):
        if r['type'] == '0':
            hw[r['vector']][f"{r['target_module']}+{int(r['target_offset'], 16):05X}"] += int(r['count'])
    print('\n| Hardware vector | Handler (×count) |\n|---|---|')
    for v, c in sorted(hw.items()):
        print(f'| {int(v, 16):02X}h | {", ".join(f"{k}×{n}" for k, n in sorted(c.items()))} |')
    print(f'\nMouse event handlers (INT 33h AX=000Ch/0014h/0018h): '
          f'{sum(mouse.values()) or "none"}.\n')


def ports(traces) -> None:
    print('## Ports by device\n')
    by = defaultdict(lambda: [0, 0, set()])
    for r in M.csv_rows(traces, 'ports.csv'):
        if r['source_module'] == '-':
            continue
        p = int(r['port'], 16)
        cls = next((n for n, f in PORT_CLASSES if f(p)), f'other {p:03X}h')
        v = by[cls]
        v[0 if r['direction'] == 'in' else 1] += int(r['count'])
        v[2].add(f'{p:03X}h')
    print('| Device | In | Out | Ports |\n|---|---|---|---|')
    for name, _ in PORT_CLASSES:
        i, o, ps = by.get(name, [0, 0, set()])
        print(f'| {name} | {i} | {o} | {" ".join(sorted(ps)) or "never touched"} |')
    for name, (i, o, ps) in sorted(by.items()):
        if not any(name == n for n, _ in PORT_CLASSES):
            print(f'| {name} | {i} | {o} | {" ".join(sorted(ps))} |')
    print()


def driver(traces) -> None:
    print('## Music driver interface\n')
    hw = {(r['target_module'], int(r['target_offset'], 16))
          for r in M.csv_rows(traces, 'interrupts.csv') if r['type'] == '0'}
    calls = defaultdict(set)
    back = defaultdict(set)
    for fm, fo, tm, to in M.edges(traces):
        if tm == DRIVER and fm not in (DRIVER, '-') and (tm, to) not in hw:
            calls[to].add(f'{fm}+{fo:05X}')
        if fm == DRIVER and tm not in (DRIVER, '-'):
            back[fo].add(tm)
    print('| Driver entry | Callers (distinct sites) |\n|---|---|')
    for to, sites in sorted(calls.items()):
        mods = Counter(s.split('+')[0] for s in sites)
        print(f'| {DRIVER}+{to:05X} | {len(sites)}: ' +
              ', '.join(f'{m} {n}' for m, n in sorted(mods.items())) + ' |')
    print('\n| Driver site | Transfers out to |\n|---|---|')
    for fo, mods in sorted(back.items()):
        print(f'| {DRIVER}+{fo:05X} | {" ".join(sorted(mods))} |')
    print()


def vga(traces, svcs) -> None:
    print('## VGA\n')
    modes, pal = Counter(), Counter()
    for svc in svcs:
        for mod, off, vec, ax, n in svc:
            if vec == '10' and ax[:2] == '00':
                modes[f'{int(ax[2:], 16):02X}h'] += int(n)
            if vec == '10' and ax.lower().startswith('10'):
                pal[f'AX={ax.upper()}h {mod}'] += int(n)
    regs = Counter()
    for r in M.csv_rows(traces, 'ports.csv'):
        if r['direction'] == 'out' and r['source_module'] != '-':
            p = int(r['port'], 16)
            if p in (0x3C4, 0x3C5, 0x3CE, 0x3CF, 0x3D4, 0x3D5, 0x3C8, 0x3C9, 0x3C0):
                regs[f'{p:03X}h'] += int(r['count'])
    pages = defaultdict(lambda: [0, 0, set()])
    for r in M.csv_rows(traces, 'vga.csv'):
        v = pages[r['source_module']]
        v[0 if r['direction'] == 'read' else 1] += int(r['count'])
        v[2].add(int(r['page'], 16))
    print(f'Modes set (INT 10h AH=00h): {", ".join(f"{k}×{n}" for k, n in sorted(modes.items()))}.')
    print(f'Palette services (INT 10h AH=10h): {", ".join(f"{k}×{n}" for k, n in sorted(pal.items())) or "none"}.')
    print('Register writes: ' + ', '.join(f'{k}×{n}' for k, n in sorted(regs.items())) + '; '
          'sequencer (3C4h/3C5h), graphics controller (3CEh/3CFh) and CRTC (3D4h/3D5h): '
          f'{sum(regs[k] for k in ("3C4h", "3C5h", "3CEh", "3CFh", "3D4h", "3D5h"))} writes.\n')
    print('| Module | Reads | Writes | Highest A000h page offset |\n|---|---|---|---|')
    for m, (rd, wr, ps) in sorted(pages.items()):
        print(f'| {m} | {rd} | {wr} | {max(ps):05X}h |')
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', default='latest', help="ref/dosbox/runs glob for the trace corpus, or 'latest' (newest milestone set)")
    args = ap.parse_args()
    for f in FILES:
        if not (SWEEP / f'{f}.cls').exists():
            print(f'census: tmp/sweep/{f}.cls missing: run tools/sweep.py', file=sys.stderr)
            return 1
    if not (SWEEP / 'code-writes.csv').exists():
        print('census: tmp/sweep/code-writes.csv missing: run tools/code_writes.py', file=sys.stderr)
        return 1
    traces = M.runs(args.runs)
    mods = M.load_modules()
    print(f'Trace corpus: {len(traces)} traces ({args.runs}).\n')
    opcodes(mods)
    ems(traces)
    svcs = [svc_census(t) for t in traces]
    smc()
    indirect(mods)
    vectors(traces, svcs)
    ports(traces)
    driver(traces)
    vga(traces, svcs)
    return 0


if __name__ == '__main__':
    sys.exit(main())
