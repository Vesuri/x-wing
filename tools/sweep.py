#!/usr/bin/env python3
"""Recursive-descent sweep of the root, every overlay segment and the music driver.

Copied from Secret Weapons of the Luftwaffe's tools/sweep.py (commit pinned in
manifest/references.tsv) and adapted to X-Wing's overlay manager (tools/xwing_model.py,
docs/overlay-manager.md).

Units: the root (link range 0..end of image, without the overlay area), each of the 26
overlay segments (its code bytes in its file, at its link segment) and `ADLIB.IMS` (its
own link space). Seeds: the MZ entry, every thunk, every traced instruction start
(union of the trace corpus), traced indirect targets. Follows fall-through, near and far
direct jumps and calls; stops at returns, indirect jumps and the calls listed in
annotations/noreturn.csv; never sweeps linearly. A far
target resolves to the unit itself, else its parent chain (the manager keeps parents
resident), else the root; a thunk's far jump resolves through its descriptor index. Root
far references into the overlay area are listed, not followed. CS is kept along a flow
and passed to near and far targets; a unit's CS values (bases) grow to a fixpoint.

Outputs in tmp/sweep/: <file>.cls (byte per file offset: 0 unknown, 1 instruction start,
2 instruction body, 3 executed start, 4 executed body, 5 switch table), coverage.csv,
conflicts.csv, far-refs.csv, indirect.csv (every static indirect jump/call site:
executed, MS C switch-table targets, traced targets; "(isr)" marks a target that is also
a hardware interrupt entry). With --annotations, the indirect sites are also written to
annotations/indirect.csv.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass, field

import capstone
from capstone import x86

import xwing_model as M

OUT = M.REPO / 'tmp/sweep'
UNKNOWN, START, BODY, TABLE = 0, 1, 2, 5
DRIVER = 'ADLIB.IMS'
FILES = [M.ROOT, 'FRONTEND.OVL', 'FLIGHT.OVL', DRIVER]


@dataclass
class Unit:
    name: str                   # root, `FRONTEND.OVL#3`, driver
    file: str
    lo: int                     # file offsets of the code bytes
    hi: int
    link_lo: int                # link linear address of lo
    parents: list[str] = field(default_factory=list)
    holes: list[tuple[int, int]] = field(default_factory=list)  # link ranges not in the unit

    def to_link(self, off: int) -> int:
        return self.link_lo + off - self.lo

    def from_link(self, linear: int) -> int:
        return linear - self.link_lo + self.lo

    def has_link(self, linear: int) -> bool:
        return self.link_lo <= linear < self.link_lo + self.hi - self.lo and \
            not any(a <= linear < b for a, b in self.holes)

    def has(self, off: int) -> bool:
        return self.lo <= off < self.hi


def units(mods: dict[str, M.Module]) -> dict[str, Unit]:
    root = mods[M.ROOT]
    out = {M.ROOT: Unit(M.ROOT, M.ROOT, 0, len(root.data), 0, holes=[M.OVL_AREA])}
    segs = M.segments(root.data)
    names = {s.index: f'{s.file}#{s.index}' for s in segs}
    for s in segs:
        chain, p = [], s.parent
        while p is not None:
            chain.append(names[p])
            p = segs[p].parent
        size = len(mods[s.file].data)
        out[names[s.index]] = Unit(names[s.index], s.file, s.code, min(s.end, size),
                                   s.link_seg * 16, chain)
    if DRIVER in mods:
        out[DRIVER] = Unit(DRIVER, DRIVER, 0, len(mods[DRIVER].data), 0)
    return out


def unit_at(us: dict[str, Unit], file: str, off: int) -> Unit | None:
    return next((u for u in us.values() if u.file == file and u.has(off)), None)


def smc_regions() -> dict[str, list[tuple[int, int]]]:
    """annotations/self-modifying.csv: file ranges whose code is rewritten at run time."""
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with (M.REPO / 'annotations/self-modifying.csv').open() as f:
        for r in csv.DictReader(f):
            out[r['module']].append((int(r['first'], 16), int(r['last'], 16)))
    return out


def dispatch_tables() -> dict[tuple[str, int], int]:
    """annotations/tables.csv: indirect sites whose word table length is shown by evidence
    other than an MS C bounds check -> entry count."""
    with (M.REPO / 'annotations/tables.csv').open() as f:
        return {(r['module'], int(r['site'], 16)): int(r['entries']) for r in csv.DictReader(f)}


def data_tables() -> dict[tuple[str, int], tuple[str, int, int]]:
    """annotations/data-tables.csv: indirect near call/jmp sites whose target is read from
    a word table in a data segment -> (table module, table module offset, entries). The
    words are read from the module file; the rows' evidence shows the bound and that the
    table is not written."""
    with (M.REPO / 'annotations/data-tables.csv').open() as f:
        return {(r['module'], int(r['site'], 16)):
                (r['table'].split('+')[0], int(r['table'].split('+')[1], 16), int(r['entries']))
                for r in csv.DictReader(f)}


# A far function pointer built in registers (MS C: mov ax,offset; mov dx,seg; push dx;
# push ax): two moves of an immediate, the second's a relocated segment, the target the
# start of a function (enter, or push bp; mov bp,sp).
PROLOGUES = (b'\xc8', b'\x55\x8b\xec')


class Sweep:
    def __init__(self, mods: dict[str, M.Module], us: dict[str, Unit], bases: dict[str, dict[int, int]],
                 thunk_jumps: dict[int, int]):
        self.mods, self.us, self.bases = mods, us, bases
        self.thunk_jumps = thunk_jumps          # root offset of a thunk's far jump -> index
        self.segs: dict[str, dict[int, int]] = {n: {} for n in us}  # CS -> lowest entry linear
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
        self.md.detail = True
        self.cls = {f: bytearray(len(mods[f].data)) for f in FILES if f in mods}
        self.insn: dict[str, dict[int, object]] = {f: {} for f in self.cls}
        self.work: list[tuple[str, int, str, int | None]] = []
        self.conflicts: list[tuple[str, int, str]] = []
        self.far_refs: list[tuple[str, int, int, int, str]] = []
        self.indirect: dict[tuple[str, int], str] = {}
        self.tables: dict[tuple[str, int], list[int]] = {}
        self.switch_sites: list[tuple[Unit, int, int, object]] = []
        self.smc = smc_regions()
        with (M.REPO / 'annotations/noreturn.csv').open() as f:
            self.noreturn = {(r['module'], int(r['offset'], 16)) for r in csv.DictReader(f)}
        self.smc_conflicts = 0
        self.curated = dispatch_tables()
        self.data_tables = data_tables()
        self.code_ptrs: set[tuple[str, int, str, int, int]] = set()  # load site -> target, CS
        self.retf_funcs: set[tuple[str, int]] = set()            # far functions after a RETF
        self.index_unit = {int(n.split('#')[1]): n for n in us if '#' in n}
        self.fixups = {f: set(mods[f].fixups) for f in self.cls}
        self.fixups = {f: set(mods[f].fixups) for f in self.cls}

    def in_smc(self, file: str, off: int) -> bool:
        return any(lo <= off <= hi for lo, hi in self.smc.get(file, ()))

    def conflict(self, file: str, off: int, why: str) -> None:
        """Static bytes of self-modified code differ from what runs: not a conflict."""
        if self.in_smc(file, off):
            self.smc_conflicts += 1
        else:
            self.conflicts.append((file, off, why))

    def seed(self, unit: str, off: int, why: str, cs: int | None = None) -> None:
        self.work.append((unit, off, why, cs))

    def segment(self, u: Unit, off: int) -> int:
        """Code segment of a file offset: the known base whose lowest far entry is the
        highest at or below it. A far function's CS is its entry rounded down to a
        paragraph, so the code just below the entry still belongs to the previous base."""
        linear = u.to_link(off)
        return max(((start, b) for b, start in self.bases[u.name].items() if start <= linear))[1]

    def add_base(self, unit: str, seg: int, linear: int) -> None:
        s = self.segs[unit]
        s[seg] = min(s.get(seg, linear), linear)

    def decode(self, u: Unit, off: int, seg: int):
        ip = u.to_link(off) - seg * 16
        data = self.mods[u.file].data
        return next(self.md.disasm(data[off:off + 16], ip), None) if 0 <= ip < 0x10000 else None

    def resolve(self, u: Unit, linear: int) -> list[str]:
        """Units a far target from u can be in: u, its parents, the root (one), or the
        overlay-area candidates when the root refers into the overlay area."""
        if u.file == DRIVER:
            return [u.name] if u.has_link(linear) else []
        for n in [u.name] + u.parents + [M.ROOT]:
            if self.us[n].has_link(linear):
                return [n]
        if u.name == M.ROOT:
            return [n for n, v in self.us.items() if v.file != DRIVER and v.has_link(linear)]
        return []

    def far_target(self, u: Unit, at: int, seg: int, off: int, index: int | None = None) -> None:
        linear = seg * 16 + off
        if index is not None:   # a thunk's far jump: the descriptor names the segment
            t = self.us[self.index_unit[index]]
            if not t.has_link(linear):
                self.conflicts.append((u.file, at, f'thunk target outside {t.name}'))
            else:
                self.add_base(t.name, seg, linear)
                self.seed(t.name, t.from_link(linear), f'thunk {u.name}+{at:X}', seg)
            self.far_refs.append((u.file, at, seg, off, f'{t.name} (thunk)'))
            return
        owners = self.resolve(u, linear)
        if len(owners) == 1:
            t = self.us[owners[0]]
            self.add_base(t.name, seg, linear)
            self.seed(t.name, t.from_link(linear), f'far from {u.name}+{at:X}', seg)
        self.far_refs.append((u.file, at, seg, off, ' '.join(owners) or '-'))

    def switch(self, u: Unit, off: int, seg: int, i) -> None:
        """MS C switch: cmp ax,N; ja/jbe; add ax,ax; xchg bx,ax; jmp cs:[bx+T] (N+1 entries),
        the same without the doubling (a byte index: N/2+1 entries), or a cs: word table
        call/jmp of annotations/tables.csv (count from there)."""
        ops = i.operands
        if i.mnemonic not in ('jmp', 'call') or not ops or ops[0].type != x86.X86_OP_MEM:
            return
        if (u.file, off) in self.data_tables:
            self.data_table(u, off, seg)
            return
        mem = ops[0].mem
        if i.reg_name(mem.segment) != 'cs' or mem.index:
            return
        f = u.file
        if (f, off) in self.curated:
            n = self.curated[(f, off)]
        else:
            if i.mnemonic != 'jmp' or i.reg_name(mem.base) != 'bx':
                return
            before = [self.insn[f][k] for k in range(off - 1, max(off - 24, 0), -1) if k in self.insn[f]]
            cmp = next((r for r in before if r.mnemonic == 'cmp'
                        and len(r.operands) == 2 and r.operands[1].type == x86.X86_OP_IMM), None)
            if cmp is None:
                return
            # Doubled after the bound check (MS C: add ax,ax), the bound counts entries;
            # otherwise the index is already a byte offset (X-Wing: shr ax,3 of a multiple
            # of 16) and the bound counts bytes.
            between = [r for r in before if r.address > cmp.address]
            doubled = any(r.mnemonic in ('add', 'shl') and r.op_str in ('ax, ax', 'bx, bx', 'ax, 1', 'bx, 1')
                          for r in between)
            bound = cmp.operands[1].imm & 0xFFFF
            n = bound + 1 if doubled else bound // 2 + 1
        cls, data = self.cls[f], self.mods[f].data
        table = u.from_link(seg * 16 + (mem.disp & 0xFFFF))
        if not 0 < n <= 512 or not u.has(table) or not u.has(table + 2 * n - 1):
            self.conflicts.append((f, off, 'switch table out of range'))
            return
        targets = []
        for k in range(n):
            ip, = struct.unpack_from('<H', data, table + 2 * k)
            targets.append(u.from_link(seg * 16 + ip))
            for b in (table + 2 * k, table + 2 * k + 1):
                if cls[b] in (START, BODY):
                    self.conflicts.append((f, b, f'switch table over code ({f}+{off:X})'))
                cls[b] = TABLE
        self.tables[(f, off)] = targets
        for t in targets:
            self.seed(u.name, t, f'switch {f}+{off:X}', seg)

    def data_table(self, u: Unit, off: int, seg: int) -> None:
        tm, to, n = self.data_tables[(u.file, off)]
        data = self.mods[tm].data
        if not 0 < n <= 512 or to + 2 * n > len(data):
            self.conflicts.append((u.file, off, 'data table out of range'))
            return
        targets = []
        for k in range(n):
            ip, = struct.unpack_from('<H', data, to + 2 * k)
            t = u.from_link(seg * 16 + ip)
            if not u.has(t):
                self.conflicts.append((u.file, off, f'data table entry {k} outside {u.name}'))
                return
            targets.append(t)
        self.tables[(u.file, off)] = targets
        for t in targets:
            self.seed(u.name, t, f'switch {u.file}+{off:X}', seg)

    def code_pointers(self) -> bool:
        """Seed the far code pointers among the decoded instructions; True if any is new."""
        new = False
        for u in self.us.values():
            ins = self.insn[u.file]
            for at in [o for o in ins if u.has(o) and o - 3 in ins and ins[o].mnemonic == 'mov']:
                n = len(self.code_ptrs)
                self.code_pointer(u, at, ins[at - 3], ins[at])
                new |= len(self.code_ptrs) > n
        return new

    def after_retf(self) -> bool:
        """Seed the far functions that start right after a decoded RETF (MS C lays far
        functions out back to back): an undecoded prologue there; True if any is new."""
        new = False
        for u in self.us.values():
            cls, data = self.cls[u.file], self.mods[u.file].data
            for at, i in list(self.insn[u.file].items()):
                nxt = at + i.size
                if i.mnemonic != 'retf' or not u.has(at) or not u.has(nxt) or cls[nxt] \
                        or not any(data.startswith(p, nxt) for p in PROLOGUES):
                    continue
                if (u.file, nxt) not in self.retf_funcs:
                    self.retf_funcs.add((u.file, nxt))
                    self.seed(u.name, nxt, f'after retf {u.name}+{at:X}')
                    new = True
        return new

    def code_pointer(self, u: Unit, at: int, prev, i) -> None:
        """A far code pointer loaded by prev (offset) and i (segment, relocated)."""
        fix = self.fixups[u.file]
        if not (prev and prev.mnemonic == 'mov' and i.mnemonic == 'mov' and i.size == 3
                and len(prev.operands) == 2 and prev.operands[1].type == x86.X86_OP_IMM
                and prev.operands[0].type == x86.X86_OP_REG and prev.size == 3
                and i.operands[1].type == x86.X86_OP_IMM and (at + 1) in fix):
            return
        seg, ip = i.operands[1].imm & 0xFFFF, prev.operands[1].imm & 0xFFFF
        owners = self.resolve(u, seg * 16 + ip)
        if len(owners) != 1:
            return
        t = self.us[owners[0]]
        dst = t.from_link(seg * 16 + ip)
        if not t.has(dst) or not any(self.mods[t.file].data.startswith(p, dst) for p in PROLOGUES):
            return
        if (u.file, at - prev.size, t.file, dst, seg) in self.code_ptrs:
            return
        self.code_ptrs.add((u.file, at - prev.size, t.file, dst, seg))
        self.add_base(t.name, seg, seg * 16 + ip)
        self.seed(t.name, dst, f'far pointer {u.name}+{at - prev.size:X}', seg)

    def run(self) -> None:
        """Drain the worklist; switch dispatches resolve once their bounds check is decoded."""
        while self.work or self.switch_sites or self.code_pointers() or self.after_retf():
            while self.work:
                self.flow(*self.work.pop())
            pending, self.switch_sites = self.switch_sites, []
            for u, off, seg, i in pending:
                if (u.file, off) not in self.tables:
                    self.switch(u, off, seg, i)

    def flow(self, unit: str, off: int, why: str, cs: int | None = None) -> None:
        u = self.us[unit]
        f = u.file
        cls, data = self.cls[f], self.mods[f].data
        if not u.has(off):
            self.conflict(f, off, f'flow outside {unit} ({why})')
            return
        seg = self.segment(u, off) if cs is None else cs
        while u.has(off):
            if cls[off] == START:
                return
            if cls[off] == BODY:
                self.conflict(f, off, f'start inside instruction ({why})')
                return
            i = self.decode(u, off, seg)
            if i is None:
                self.conflict(f, off, f'undecodable ({why})')
                return
            span = range(off, min(off + i.size, u.hi))
            if any(cls[k] for k in span):
                self.conflict(f, off, f'overlaps instruction ({why})')
                return
            cls[off] = START
            for k in span[1:]:
                cls[k] = BODY
            self.insn[f][off] = i
            nxt = off + i.size
            g = set(i.groups)
            ops = i.operands
            if capstone.CS_GRP_RET in g or capstone.CS_GRP_IRET in g or i.mnemonic == 'hlt':
                return
            if i.mnemonic in ('ljmp', 'lcall') and len(ops) == 2 and ops[0].type == x86.X86_OP_IMM:
                index = self.thunk_jumps.get(off) if unit == M.ROOT and i.mnemonic == 'ljmp' else None
                self.far_target(u, off, ops[0].imm & 0xFFFF, ops[1].imm & 0xFFFF, index)
                if i.mnemonic == 'ljmp':
                    return
            elif capstone.CS_GRP_JUMP in g or capstone.CS_GRP_CALL in g or \
                    i.mnemonic in ('loop', 'loope', 'loopne', 'jcxz'):
                if ops and ops[0].type == x86.X86_OP_IMM:
                    self.seed(unit, u.from_link(seg * 16 + (ops[0].imm & 0xFFFF)), f'{unit}+{off:X}', seg)
                else:
                    self.indirect[(f, off)] = f'{i.mnemonic} {i.op_str}'
                    self.switch_sites.append((u, off, seg, i))
                if i.mnemonic in ('jmp', 'ljmp'):
                    return
            if (f, off) in self.noreturn:
                return
            off = nxt
        self.conflict(f, off, f'flow past the end of {unit} ({why})')


def residue(data: bytes, cls: bytearray, ranges: list[tuple[int, int]], fixups: set[int]) -> list[int]:
    """Unreached code-unit bytes by run: zero fill (>= 90 % zero), text, code-like (MS C
    prologue `55 8B EC` or a fixup-anchored far call `9A`), other data."""
    out = [0, 0, 0, 0]
    for lo, hi in ranges:
        off = lo
        while off < hi:
            if cls[off]:
                off += 1
                continue
            end = off
            while end < hi and not cls[end]:
                end += 1
            run = data[off:end]
            zeros = run.count(0)
            text = sum(1 for b in run if 32 <= b < 127 or b in (10, 13))
            if zeros >= 0.9 * len(run):
                out[0] += len(run)
            elif text + zeros >= 0.9 * len(run) and text >= 0.5 * len(run) and len(run) >= 4:
                out[1] += len(run)
            elif b'\x55\x8b\xec' in run or any(data[k] == 0x9A and k + 3 in fixups for k in range(off, end)):
                out[2] += len(run)
            else:
                out[3] += len(run)
            off = end
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', default='latest', help="ref/dosbox/runs glob for the trace corpus, or 'latest' (newest milestone set)")
    ap.add_argument('--annotations', action='store_true', help='write annotations/indirect.csv')
    args = ap.parse_args()
    mods = M.load_modules()
    us = units(mods)
    root = mods[M.ROOT].data
    thunk_list = M.thunks(root)
    thunk_jumps = {a + 3: index for a, index, _, _ in thunk_list}
    traces = M.runs(args.runs)
    exe = M.executed(traces)
    hw = {(r['target_module'], int(r['target_offset'], 16))
          for r in M.csv_rows(traces, 'interrupts.csv') if r['type'] == '0'}
    edge_set = M.edges(traces)
    bases = {n: {u.link_lo >> 4: u.link_lo} for n, u in us.items()}
    entry_cs = M.mz(M.REF / M.ROOT)[2][0]
    bases[M.ROOT][entry_cs] = M.entry()  # MZ entry CS
    while True:  # segment bases come from decoded far references; iterate to a fixpoint
        sw = Sweep(mods, us, bases, thunk_jumps)
        sw.seed(M.ROOT, M.entry(), 'MZ entry')
        for a, _, _, _ in thunk_list:
            sw.seed(M.ROOT, a, 'thunk', M.MANAGER_SEG)
        for f, starts in exe.items():
            for off in starts:
                u = unit_at(us, f, off)
                if u:
                    sw.seed(u.name, off, 'traced')
        sw.run()
        targets = defaultdict(set)
        for fm, fo, tm, to in edge_set:
            if (fm, fo) in sw.indirect:
                targets[(fm, fo)].add((tm, to))
        for (fm, fo), ts in targets.items():
            for tm, to in ts:
                u = unit_at(us, tm, to)
                if (tm, to) not in hw and u:
                    sw.seed(u.name, to, f'indirect {fm}+{fo:X}')
        sw.run()
        grown = {n: {b: min(bases[n].get(b, s), s) for b, s in {**sw.segs[n], **bases[n]}.items()}
                 for n in bases}
        if grown == bases:
            break
        bases = grown

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'coverage.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['module', 'code_bytes', 'static_code', 'executed_code', 'unexecuted_code',
                    'switch_tables', 'residue', 'residue_zero', 'residue_text', 'residue_codelike',
                    'residue_other', 'executed_not_code', 'smc_region', 'indirect_sites',
                    'indirect_traced'])
        for n in sw.cls:
            cls, data = sw.cls[n], mods[n].data
            ranges = [(u.lo, u.hi) for u in us.values() if u.file == n]
            if n == M.ROOT:
                ranges = [(0, M.OVL_AREA[0]), (M.OVL_AREA[1], len(data))]
            starts = exe.get(n, set())
            ex = bytearray(len(cls))
            missing = 0
            for s in starts:
                if s >= len(cls) or cls[s] != START:
                    missing += 0 if sw.in_smc(n, s) else 1
                    continue
                for k in range(s, s + sw.insn[n][s].size):
                    ex[k] = 1
            body = sum(hi - lo for lo, hi in ranges)
            code = sum(1 for c in cls if c in (START, BODY))
            tables = sum(1 for c in cls if c == TABLE)
            res = residue(data, cls, ranges, set(mods[n].fixups))
            exn = sum(ex)
            out = bytearray(c + (2 if ex[k] else 0) if c in (START, BODY) else c for k, c in enumerate(cls))
            (OUT / f'{n}.cls').write_bytes(bytes(out))
            sites = [s for s in sw.indirect if s[0] == n]
            smc = sum(hi - lo + 1 for lo, hi in sw.smc.get(n, ()))
            w.writerow([n, body, code, exn, code - exn, tables, body - code - tables, *res,
                        missing, smc, len(sites), sum(1 for s in sites if targets.get(s))])
    with (OUT / 'conflicts.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['module', 'offset', 'reason'])
        for mod, off, why in sorted(set(sw.conflicts)):
            w.writerow([mod, f'0x{off:05x}', why])
    with (OUT / 'far-refs.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['module', 'offset', 'segment', 'target', 'owners'])
        for mod, at, seg, off, owners in sorted(set(sw.far_refs)):
            w.writerow([mod, f'0x{at:05x}', f'0x{seg:04x}', f'0x{off:04x}', owners])
    rows = []
    for (mod, off), text in sorted(sw.indirect.items()):
        ts = sorted(targets.get((mod, off), ()))
        table = sw.tables.get((mod, off), [])
        rows.append([mod, f'0x{off:05x}', text, int(off in exe.get(mod, ())),
                     ' '.join(f'{mod}+0x{t:05x}' for t in sorted(set(table))),
                     ' '.join(f'{tm}+0x{to:05x}' + (' (isr)' if (tm, to) in hw else '')
                              for tm, to in ts)])
    for path in [OUT / 'indirect.csv'] + ([M.REPO / 'annotations/indirect.csv'] if args.annotations else []):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['module', 'offset', 'instruction', 'executed', 'switch_targets',
                        'traced_targets'])
            w.writerows(rows)
    for path in [OUT / 'code-pointers.csv'] + ([M.REPO / 'annotations/code-pointers.csv'] if args.annotations else []):
        with path.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['module', 'offset', 'kind', 'target', 'segment'])
            rows = [(mod, at, 'pointer', f'{tm}+0x{to:05x}', f'0x{seg:04x}')
                    for mod, at, tm, to, seg in sw.code_ptrs]
            rows += [(mod, nxt, 'after retf', f'{mod}+0x{nxt:05x}', '') for mod, nxt in sw.retf_funcs]
            for mod, at, kind, t, seg in sorted(rows):
                w.writerow([mod, f'0x{at:05x}', kind, t, seg])
    with (OUT / 'coverage.csv').open() as f:
        print(f.read(), end='')
    print(f'conflicts {len(set(sw.conflicts))} (+{sw.smc_conflicts} in self-modified regions), '
          f'far refs {len(set(sw.far_refs))}, code pointers {len(sw.code_ptrs)}, after retf {len(sw.retf_funcs)}, traces {len(traces)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
