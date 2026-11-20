"""Recursive descent over the in-scope modules with the translator's own decoder.

Copied from Secret Weapons of the Luftwaffe's translator/cfg.py (commit pinned in
manifest/references.tsv) and adapted to X-Wing's overlay manager
(docs/overlay-manager.md; the same unit and resolution rules as tools/sweep.py).

Seeds (all from annotations/ and the images, no traces): MZ entry, the manager's thunks,
`entries.csv`, `runtime.csv`, `code-pointers.csv` (far functions), the switch and traced
targets of `indirect.csv`. Follows
fall-through and direct near/far transfers; a call listed in `noreturn.csv` has no
fall-through; a near RET listed in `ret-jumps.csv` continues at its target. Code is split into segment ranges: the root
(without the overlay area), each overlay segment (its code bytes in its file, at its
link segment) and the music driver (its own link space). A thunk (`call 048Ah; jmp far;
dw index`) names its target segment by the descriptor index after the far jump. Any
other far target resolves to the range itself, else its parent chain (the manager keeps
parents resident), else the root; more than one candidate is an error. CS follows
control flow: a far transfer sets it, fall-through and near transfers keep it. An entry
seeded without a CS takes the base whose lowest far entry is the highest at or below it
(a far function's CS is its entry rounded down to a paragraph, so the bytes just below
an entry still belong to the previous base); bases grow to a fixpoint. Self-modified
regions are not decoded statically: flow into one is recorded as an entry of the region
(D16). Overlaps, flow outside a range, undecodable bytes, a start reached with two CS
values and ambiguous far targets raise CfgError (all of them, after the fixpoint).

Units are per file (`insns`, `cs` keyed by file offset); `ranges` holds the segment
ranges of the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import image
from .decode import DecodeError, Far, Insn, Rel, decode

M = image.M
DRIVER = image.DRIVER


class CfgError(Exception):
    pass


@dataclass
class Range:
    name: str                   # root, `FRONTEND.OVL#3`, driver
    file: str
    lo: int                     # file offsets of the code bytes
    hi: int
    link_lo: int                # link linear address of lo
    parents: list[str] = field(default_factory=list)
    holes: list[tuple[int, int]] = field(default_factory=list)

    def to_link(self, off: int) -> int:
        return self.link_lo + off - self.lo

    def from_link(self, linear: int) -> int:
        return linear - self.link_lo + self.lo

    def has_link(self, linear: int) -> bool:
        return self.link_lo <= linear < self.link_lo + self.hi - self.lo and \
            not any(a <= linear < b for a, b in self.holes)

    def has(self, off: int) -> bool:
        return self.lo <= off < self.hi and self.has_link(self.to_link(off))


@dataclass
class Unit:
    name: str
    module: M.Module
    ranges: list[Range]
    bases: dict[str, dict[int, int]]                           # range -> CS -> lowest entry linear
    insns: dict[int, Insn] = field(default_factory=dict)
    cs: dict[int, int] = field(default_factory=dict)           # offset -> CS link paragraph
    manager_calls: dict[int, str] = field(default_factory=dict)  # thunk far jump -> segment range
    smc_entries: dict[int, str] = field(default_factory=dict)  # region entry -> reason
    far_targets: dict[int, tuple[str, int]] = field(default_factory=dict)  # site -> (module, offset)
    seeds: dict[int, str] = field(default_factory=dict)

    def range_at(self, off: int) -> Range:
        for r in self.ranges:
            if r.has(off):
                return r
        raise CfgError(f"{self.name}+{off:05X}: outside every code range")

    def segment(self, off: int) -> int:
        """CS of an entry seeded without one (module docstring)."""
        r = self.range_at(off)
        linear = r.to_link(off)
        return max((start, b) for b, start in self.bases[r.name].items() if start <= linear)[1]

    def ip_of(self, off: int) -> int:
        seg = self.cs[off] if off in self.cs else self.segment(off)
        return self.range_at(off).to_link(off) - seg * 16

    def off_of(self, seg: int, ip: int, at: int) -> int:
        """File offset of seg:ip as reached from the range holding offset `at`."""
        return self.range_at(at).from_link(seg * 16 + ip)


def ranges(mods: dict[str, M.Module]) -> dict[str, Range]:
    root = mods[M.ROOT]
    out = {M.ROOT: Range(M.ROOT, M.ROOT, 0, len(root.data), 0, holes=[M.OVL_AREA])}
    segs = M.segments(root.data)
    names = {s.index: f"{s.file}#{s.index}" for s in segs}
    for s in segs:
        chain, p = [], s.parent
        while p is not None:
            chain.append(names[p])
            p = segs[p].parent
        out[names[s.index]] = Range(names[s.index], s.file, s.code, min(s.end, len(mods[s.file].data)),
                                    s.link_seg * 16, chain)
    out[DRIVER] = Range(DRIVER, DRIVER, 0, len(mods[DRIVER].data), 0)
    return out


def seeds(mods: dict[str, M.Module]) -> list[tuple[str, int, str, int | None]]:
    out = [(M.ROOT, M.entry(), "MZ entry", None)]
    out += [(M.ROOT, at, "thunk", M.MANAGER_SEG) for at, _, _, _ in M.thunks(mods[M.ROOT].data)]
    for r in image.rows("entries.csv"):
        out.append((r["module"], int(r["offset"], 16), r["reason"], None))
    for r in image.rows("runtime.csv"):
        out.append((r["module"], int(r["offset"], 16), f"runtime {r['name']}", None))
    for r in image.rows("code-pointers.csv"):   # far functions (tools/sweep.py)
        mod, off = r["target"].split("+")
        if r["kind"] == "pointer":                # a far pointer constant: its CS
            out.append((mod, int(off, 16), f"far pointer {r['module']}+{r['offset']}",
                        int(r["segment"], 16)))
        else:                                     # after a RETF: the sweep's module segment
            out.append((mod, int(off, 16), f"after retf {r['module']}+{r['offset']}",
                        int(r["segment"], 16) if r["segment"] else None))
    for r in image.rows("indirect.csv"):
        site = f"{r['module']}+{r['offset']}"
        for col in ("switch_targets", "traced_targets"):
            for t in r[col].split():
                if t == "(isr)":
                    continue
                mod, off = t.split("+")
                out.append((mod, int(off, 16), f"{col[:-8]} {site}", None))
    return [s for s in out if s[0] in image.SCOPE]


class _Descent:
    def __init__(self, mods, rs: dict[str, Range], bases):
        self.mods, self.rs = mods, rs
        self.units = {n: Unit(n, mods[n], [r for r in rs.values() if r.file == n], bases)
                      for n in image.SCOPE}
        self.thunk_jumps = {a + 3: index for a, index, _, _ in M.thunks(mods[M.ROOT].data)}
        self.index_range = {int(n.split("#")[1]): n for n in rs if "#" in n}
        self.smc = image.smc_regions()
        self.noreturn = {(r["module"], int(r["offset"], 16)) for r in image.rows("noreturn.csv")}
        self.ret_jumps = ret_jumps()
        self.fixups = {n: set(mods[n].fixups) for n in image.SCOPE}
        self.far_entries: dict[str, dict[int, int]] = {n: {} for n in rs}
        self.work: list[tuple[str, int, str, int | None]] = []
        self.body: dict[str, dict[int, int]] = {n: {} for n in image.SCOPE}  # byte -> start
        self.errors: list[str] = []

    def seed(self, mod, off, why, cs=None):
        if mod in self.units:
            self.work.append((mod, off, why, cs))
            self.units[mod].seeds.setdefault(off, why)

    def in_smc(self, mod, off):
        return any(lo <= off <= hi for lo, hi in self.smc.get(mod, ()))

    def add_base(self, r: Range, seg: int, linear: int):
        e = self.far_entries[r.name]
        e[seg] = min(e.get(seg, linear), linear)

    def resolve(self, r: Range, linear: int) -> list[str]:
        if r.file == DRIVER:
            return [r.name] if r.has_link(linear) else []
        for n in [r.name] + r.parents + [M.ROOT]:
            if self.rs[n].has_link(linear):
                return [n]
        if r.name == M.ROOT:
            return [n for n, v in self.rs.items() if v.file != DRIVER and v.has_link(linear)]
        return []

    def far(self, mod, r: Range, at, f: Far, index):
        linear = f.seg * 16 + f.off
        if index is not None:
            t = self.rs[self.index_range[index]]
            if not t.has_link(linear):
                raise CfgError(f"{mod}+{at:05X}: thunk target outside {t.name}")
            self.units[mod].manager_calls[at] = t.name
            owners = [t.name]
        else:
            if at + 3 not in self.fixups[mod]:
                # the segment word (9A/EA ptr16:16, at +3) is not relocated: an
                # absolute address outside the program (XWING.EXE+0431F's 0000:0000
                # placeholder, never executed); no target, lowered as its named stop
                return
            owners = self.resolve(r, linear)
        if len(owners) > 1:
            raise CfgError(f"{mod}+{at:05X}: far target {f} ambiguous: {owners}")
        if not owners:
            raise CfgError(f"{mod}+{at:05X}: far target {f} outside code")
        t = self.rs[owners[0]]
        self.add_base(t, f.seg, linear)
        self.seed(t.file, t.from_link(linear), f"far {mod}+{at:05X}", f.seg)
        self.units[mod].far_targets[at] = (t.file, t.from_link(linear))

    def run(self):
        while self.work:
            try:
                self.flow(*self.work.pop())
            except CfgError as e:
                self.errors.append(str(e))

    def flow(self, mod, off, why, cs):
        u = self.units[mod]
        data = u.module.data
        try:
            r = u.range_at(off)
        except CfgError:
            raise CfgError(f"{mod}+{off:05X}: flow outside code ({why})") from None
        while True:
            if not r.has(off):
                raise CfgError(f"{mod}+{off:05X}: flow past the end of {r.name} ({why})")
            if off in u.insns:
                if cs is not None and u.cs[off] != cs:
                    raise CfgError(f"{mod}+{off:05X}: reached with CS {cs:04X} and {u.cs[off]:04X} ({why})")
                return
            if self.in_smc(mod, off):
                u.smc_entries.setdefault(off, why)
                return
            if off in self.body[mod]:
                raise CfgError(f"{mod}+{off:05X}: start inside {mod}+{self.body[mod][off]:05X} ({why})")
            seg = cs = u.segment(off) if cs is None else cs
            ip = r.to_link(off) - seg * 16
            if not 0 <= ip < 0x10000:
                raise CfgError(f"{mod}+{off:05X}: outside CS {seg:04X} ({why})")
            try:
                n = decode(data, ip, off)
            except DecodeError as e:
                raise CfgError(f"{mod}+{off:05X}: {e} ({why})") from None
            for k in range(off + 1, off + n.size):
                if k in u.insns or k in self.body[mod]:
                    raise CfgError(f"{mod}+{off:05X}: overlaps {mod}+{k:05X} ({why})")
                self.body[mod][k] = off
            u.insns[off], u.cs[off] = n, seg
            why = f"{mod}+{off:05X}"
            if (mod, off) in self.ret_jumps:
                if n.op != "ret" or n.operands:
                    raise CfgError(f"{mod}+{off:05X}: ret-jumps.csv names no plain near RET ({n})")
                self.seed(mod, self.ret_jumps[(mod, off)], why, seg)
                return
            if n.op in ("ret", "retf", "iret", "hlt"):
                return
            if n.op in ("callf", "jmpf") and isinstance(n.operands[0], Far):
                index = self.thunk_jumps.get(off) if mod == M.ROOT and n.op == "jmpf" else None
                self.far(mod, r, off, n.operands[0], index)
                if n.op == "jmpf":
                    return
            elif n.operands and isinstance(n.operands[0], Rel):
                self.seed(mod, r.from_link(seg * 16 + n.operands[0].target), why, seg)
                if n.op == "jmp":
                    return
            elif n.op in ("jmp", "jmpf"):
                return
            if (mod, off) in self.noreturn:
                if n.op not in ("call", "callf"):
                    raise CfgError(f"{mod}+{off:05X}: noreturn.csv names no call ({n})")
                return
            off += n.size


def ret_jumps() -> dict[tuple[str, int], int]:
    """ret-jumps.csv: near RETs that pop a continuation the routine pushed
    itself (module offset of the RET -> module offset of the target)."""
    return {(r["module"], int(r["offset"], 16)): int(r["target"], 16)
            for r in image.rows("ret-jumps.csv")}


def build(mods: dict[str, M.Module] | None = None) -> dict[str, Unit]:
    mods = mods or image.load()
    rs = ranges(mods)
    bases = {n: {r.link_lo >> 4: r.link_lo} for n, r in rs.items()}
    bases[M.ROOT][M.mz(M.REF / M.ROOT)[2][0]] = M.entry()  # MZ entry CS (the manager segment)
    start = seeds(mods)
    while True:
        d = _Descent(mods, rs, bases)
        for s in start:
            d.seed(*s)
            if s[2].startswith("far pointer") and s[0] in d.units:  # a far entry: its CS is a base
                r = d.units[s[0]].range_at(s[1])
                d.add_base(r, s[3], r.to_link(s[1]))
        d.run()
        grown = {n: {b: min(bases[n].get(b, s), s) for b, s in {**d.far_entries[n], **bases[n]}.items()}
                 for n in bases}
        if grown == bases:
            if d.errors:  # only the fixpoint pass knows every code segment
                raise CfgError("\n".join(sorted(set(d.errors))))
            return d.units
        bases = grown
