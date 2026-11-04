#!/usr/bin/env python3
"""Check the overlay manager model (docs/overlay-manager.md) against every traced run.

Adapted from Secret Weapons of the Luftwaffe's tools/plink_check.py (commit pinned in
manifest/references.tsv): the PLINK model is replaced by X-Wing's manager.

Model: a call of the manager (root image 41DCh, AX = descriptor index; tracer event
`ovl_call`) makes the segment resident. If it is not resident, every resident segment
whose memory range overlaps it stops being resident, its code is read from its file
position to load segment + link segment, and its fixup table is read and applied. Then
the manager calls itself for the parent, if any, resident or not. Calls come from thunks
(`ovl_thunk`, which name the index) or from that parent recursion.

Checks per trace:
- every `ovl_call` follows its thunk or its child's call;
- its resident bit equals the model's;
- the `.OVL` reads between two calls are exactly the predicted code and fixup reads;
- the thunk's caller is resident when its call chain ends (the far return lands in the
  code that called);
- at each snapshot, every resident segment's code is mapped at its predicted address
  (snapshot residency.csv).
Exit 1 on any violation. `--sabotage` breaks one model rule (no-evict: overlapping
segments stay resident; no-parent: no parent call; position: code read one paragraph
later) and must then fail: the control that the checks can see each rule.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import xwing_model as M

FIXUP_READER = '0x04392'    # root image 4392h: the fixup-table read into the manager's buffer


def kv(detail: str) -> tuple[str, dict[str, str]]:
    head, *rest = detail.split()
    return head, dict(x.split('=', 1) for x in rest if '=' in x)


def expected_reads(s: M.Segment, load: int) -> list[tuple[str, int, int | None, int]]:
    """(file, file position, linear or None for the fixup buffer, bytes): the code, then the
    fixup table."""
    out = [(s.file, s.code, (load + s.link_seg) * 16, s.read_paras * 16)]
    if s.nfix:
        out.append((s.file, s.pos, None, s.nfix * 4))
    return out


def merged(rows: list[tuple[str, int, int | None, int]]) -> list[tuple[str, int, int | None, int]]:
    """Contiguous reads joined: the manager splits the code at up to 0F80h paragraphs and the
    fixups at 58h entries, and a read past the end of the file returns fewer bytes."""
    out: list[tuple[str, int, int | None, int]] = []
    for f, pos, lin, n in rows:
        if out and out[-1][0] == f and out[-1][1] + out[-1][3] == pos and \
                (lin is None) == (out[-1][2] is None) and \
                (lin is None or out[-1][2] + out[-1][3] == lin):
            out[-1] = (f, out[-1][1], out[-1][2], out[-1][3] + n)
        else:
            out.append((f, pos, lin, n))
    return out


def same_reads(got, want, size) -> bool:
    """Equal after merging; a read may end at the end of the file (size)."""
    g, w = merged(got), merged(want)
    if len(g) != len(w):
        return False
    for (f, p, l, n), (wf, wp, wl, wn) in zip(g, w):
        if (f, p, l) != (wf, wp, wl) or not (n == wn or (n < wn and p + n == size[f])):
            return False
    return True


def check(trace: Path, segs: list[M.Segment], sabotage: str = '') -> tuple[list[str], dict[str, int]]:
    by_index = {s.index: s for s in segs}
    load = None
    resident: set[int] = set()
    bad: list[str] = []
    stats = {'calls': 0, 'loads': 0, 'thunks': 0, 'resident_calls': 0, 'snapshots': 0}
    expect_call: int | None = None      # index the next ovl_call must have
    reads: list[tuple[str, int, int | None, int]] = []
    want: list = []
    caller: tuple[str, int, str] | None = None
    size = {s.file: (M.REF / s.file).stat().st_size for s in segs}

    def where(row):
        return f'{trace.parent.name} @{row[0]}'

    def settle(row):
        nonlocal reads, want
        if want or reads:
            if not same_reads(reads, want, size):
                bad.append(f'{where(row)}: reads {reads[:4]}..., model {want[:4]}...')
        reads, want = [], []

    def caller_intact(row):
        nonlocal caller
        if caller is None:
            return
        mod, off, thunk = caller
        if mod.endswith('.OVL'):
            seg = next((s for s in segs if s.file == mod and s.code <= off < s.end), None)
            if seg is None or seg.index not in resident:
                bad.append(f'{where(row)}: caller {mod}+{off:05X} of thunk {thunk} not resident')
        caller = None

    for row in M.events(trace, ('arm', 'ovl_thunk', 'ovl_call', 'read', 'snapshot')):
        kind = row[1]
        if kind == 'arm':
            load = int(kv('x ' + row[4])[1]['load_seg'], 16)
            continue
        if kind == 'read':
            name, a = kv(row[4])
            if not name.endswith('.OVL'):
                continue
            lin, pos, got = int(a['linear'], 16), int(a['pos'], 16), int(a['got'])
            if row[3] == FIXUP_READER:
                reads.append((name, pos, None, got))
            else:
                reads.append((name, pos, lin, got))
            continue
        if kind == 'snapshot':
            stats['snapshots'] += 1
            snap = trace / f'snap-{row[4]}'
            rows = M.residency(snap / 'residency.csv')
            for i in resident:
                s = by_index[i]
                linear = (load + s.link_seg) * 16
                hit = next(((m, o + linear - lo) for lo, hi, m, o in rows if lo <= linear < hi), None)
                if hit != (s.file, s.code):
                    bad.append(f'{where(row)}: segment {i} at {linear:05X} is {hit}, model '
                               f'{s.file}+{s.code:05X}')
            continue
        name, a = kv('x ' + row[4])
        if kind == 'ovl_thunk':
            settle(row)
            caller_intact(row)
            if expect_call is not None:
                bad.append(f'{where(row)}: thunk while the call of {expect_call} is pending')
            stats['thunks'] += 1
            expect_call = int(a['index'])
            mod, off = a['caller'].split('+')
            caller = (mod, int(off, 16), a['thunk'])
            continue
        # ovl_call
        settle(row)
        index = int(a['index'])
        stats['calls'] += 1
        if expect_call != index:
            bad.append(f'{where(row)}: call of {index}, expected {expect_call}')
        s = by_index[index]
        was = index in resident
        if int(a['resident']) != was:
            bad.append(f'{where(row)}: resident bit {a["resident"]} for {index}, model {int(was)}')
        if was:
            stats['resident_calls'] += 1
        else:
            for r in [r for r in resident if by_index[r].overlaps(s)]:
                if sabotage != 'no-evict':
                    resident.discard(r)
            resident.add(index)
            stats['loads'] += 1
            want = expected_reads(s, load)
            if sabotage == 'position':
                f, pos, lin, n = want[0]
                want[0] = (f, pos + 16, lin, n)
        expect_call = None if sabotage == 'no-parent' else s.parent
    final = ['end', '', '', '', '']
    settle(final)
    if expect_call is not None:
        bad.append(f'{trace.parent.name}: call of {expect_call} pending at the end')
    caller_intact(final)
    return bad, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', default='latest', help="ref/dosbox/runs glob, or 'latest' (newest milestone set)")
    ap.add_argument('--sabotage', choices=('no-evict', 'no-parent', 'position'), default='')
    args = ap.parse_args()
    segs = M.segments(M.load_modules()[M.ROOT].data)
    total = {}
    bad_all = []
    traces = M.runs(args.runs)
    for t in traces:
        bad, stats = check(t, segs, args.sabotage)
        bad_all += bad
        for k, v in stats.items():
            total[k] = total.get(k, 0) + v
        print(f"{t.parent.name:40} " + ' '.join(f'{k}={v}' for k, v in stats.items()) +
              (f'  FAIL {len(bad)}' if bad else ''), flush=True)
    for b in bad_all[:40]:
        print(b)
    print(f"overlay manager: {len(traces)} traces, " + ', '.join(f'{k} {v}' for k, v in total.items()) +
          f", model violations {len(bad_all)}")
    if not total.get('calls'):
        print('overlay manager: FAIL no ovl_call events (tracer without the overlay patch?)')
        return 1
    return 1 if bad_all else 0


if __name__ == '__main__':
    sys.exit(main())
