#!/usr/bin/env python3
"""Instruction and short-block differential of the 68020 lowering (gate 4):
original bytes in Unicorn x86-16 vs the generated 68020 code in Unicorn 68020.

Same corpora and states as tests/x86_diff.py (forms, space, boundary, blocks).
Each case is lowered in test mode (every transfer leaves through a stub that
reports CS:IP; flags live at the end of the case), assembled with vasm in
batches and run on the 68020 core over the same guest RAM (reversed below a6
as the register contract maps it, SP/BP mirrored; translator/lower.py; guest
registers enter with upper words 0, FFFFh or random). Compared: registers
(low words), segment registers, CS:IP, defined
flags (undefined ones masked by the IR), FLAGS bits 12-14, every written byte,
the OUT sequence and the raised interrupt/fault. Checked on the 68k side alone:
the poll-point contract of runtime.h (G_IRQ never set without rt_irq_pending;
once IF is set, a pending interrupt re-arms G_IRQ).

Shared by both sides: the case bytes and state; the 68k side never sees the
x86 results or the IR (the IR only supplies the undefined-flag mask).

--record PATH saves each case's x86 side (IR mask or skip, Unicorn result);
--replay PATH reuses it for a case whose state and bytes match, under the
same sources and Unicorn, and runs any other case live (m68k_sabotage sets
REPLAY: the plants reuse make test's boundary run).
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import os
import pickle
import random
import subprocess
import sys
import tempfile
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uc as U  # noqa: E402
import x86_diff as X  # noqa: E402
from translator import flags as F, region  # noqa: E402
from translator.decode import DecodeError, decode  # noqa: E402
from translator.interp import State, UndefinedFlag, step  # noqa: E402
from translator.ir import FLAG_BIT, FLAGS, STATUS  # noqa: E402
from translator.lower import Ctx, LowerError, es_access, hx  # noqa: E402
from translator.support import HELPERS, equates  # noqa: E402

VASM = Path(os.environ.get("VASM") or Path.home() / ".local/vasmm68k_mot")
GUEST_LO = 0x100000         # lowest host byte of guest RAM
TOP = GUEST_LO + X.RAM + 0x10000 - 1    # a6: guest linear L at TOP - L
STATE = TOP + 1             # state block page
CODE = 0x400000
STUB = 0x300000
STACK = 0x380000
PENDING = STATE + 0x800     # rt_irq_pending
# ems.c rt_ems_cache_es/ds (segment, lowest offset; end; base), set per case
CACHE = {"es": STATE + 0x810, "ds": STATE + 0x81C}
EMS_CACHE = ("empty", "hit", "end", "low", "segment")   # the cases' cache states, cycling
STUBS = ("T_JUMP", "T_CALL", "T_JUMPF", "T_CALLF", "T_INT", "T_FAULT", "T_HALT", "T_END",
         "rt_in8", "rt_in16", "rt_out8", "rt_out16", "T_RET", "T_TRAP", "rt_ems_es", "rt_ems_seg",
         "rt_ems_ds", "rt_ems_ds_leave", "rt_ems_es_miss", "rt_ems_ds_miss", "rt_vram_ds")
STUB_AT = {n: STUB + 4 * k for k, n in enumerate(STUBS)}
REGS = ("ax", "bx", "cx", "dx", "sp", "bp", "si", "di")
MIRROR = {"sp": 0x7FFF, "bp": 0x7FFF}   # held as offset ^ 7FFFh
M68 = {"ax": "d0", "cx": "d1", "dx": "d2", "bx": "d3", "sp": "d4", "bp": "d5", "si": "a4",
       "di": "a5"}
BATCH = 1500
# EMS model (lower.py ems_guard, putseg): the edges of the guard's D001h compare,
# and of the VGA frame's window at a DS load (9001h-AF9Fh, rt_vram_ds, D9)
EMS_EDGES = (0xD000, 0xD001, 0xDFFF, 0xE000, 0xEFFF, 0xF000, 0xFFFF, 0x9000, 0x9001, 0xAF9F, 0xAFA0)
REPLAY: Path | None = None   # set by m68k_sabotage


ASM_DEFS = ("-DXWING_SYNC=1",)   # the sync build: poll checks host runs deliver at (irq-plan I8)


def assemble(src: str, out: Path) -> bytes:
    s = out.with_suffix(".s")
    s.write_text(src)
    r = subprocess.run([str(VASM), "-quiet", "-m68020", *ASM_DEFS, "-Fbin", "-o", str(out), str(s)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"vasm failed:\n{r.stdout}{r.stderr}"[:4000])
    return out.read_bytes()


def ccr_image(flags: dict) -> int:
    return flags["CF"] | flags["OF"] << 1 | flags["ZF"] << 2 | flags["SF"] << 3


def lower_case(insns, cs: int, tag: str, end_ip: int, **extra) -> tuple[list[str], Counter]:
    """Test-mode 68k text for a straight-line run of decoded instructions
    (`extra`: Ctx fields every instruction gets)."""
    lives = F.seq_lives(insns)
    stats = Counter()

    def ctx_for(k):
        return Ctx(cs=hx(cs), label=f"{tag}_{k}", **extra)

    lines, cold = [f"{tag}:"], []
    for k, lw in enumerate(F.plan(insns, lives, set(), ctx_for)):
        lines.append(f"{tag}_{k}:")
        lines.extend(lw.out)
        cold += lw.cold
        stats.update(lw.stats)
    lines += [f"{tag}_end:", f"\tmove.l #{hx(end_ip)},d7", "\tjmp T_END"]
    return lines + cold, stats


def lower_region_case(insns, cs: int, tag: str, end_ip: int):
    """R6: the run behind a region guard, as a guarded copy (direct [bp+d]) with
    the exact lowering as its fallback; None where no region applies."""
    rng = region.bp_range(insns)
    if rng is None or any(region.writes_bp(i) for i in insns):
        return None
    lives = F.seq_lives(insns)
    stats = Counter()
    lines, cold = [f"{tag}:"] + region.guard(rng, f"{tag}_x"), []
    for k, lw in enumerate(F.plan(insns, lives, set(),
                                  lambda k: Ctx(cs=hx(cs), label=f"{tag}_{k}", bp_direct=True))):
        lines.append(f"{tag}_{k}:")
        lines.extend(lw.out)
        cold += lw.cold
        stats.update(lw.stats)
    lines += [f"{tag}_end:", f"\tmove.l #{hx(end_ip)},d7", "\tjmp T_END"] + cold
    exact, _ = lower_case(insns, cs, f"{tag}_x", end_ip)
    stats["region case"] += 1
    return lines + exact, stats


def carries_in_place(i) -> bool:
    """adc/sbb of a constant address and an immediate (lower.carry_in_place, the
    driver's Ctx.atomic_carry)."""
    return i.op in ("adc", "sbb") and len(i.operands) == 2 and \
        type(i.operands[0]).__name__ == "Mem" and i.operands[0].base is None and \
        i.operands[0].index is None and type(i.operands[1]).__name__ == "Imm"


def loads_segment(i) -> bool:
    """mov/pop to ES, DS or SS, les, lds (lower.putseg)."""
    o = i.operands[0] if i.operands else None
    return i.op in ("les", "lds") or i.op in ("mov", "pop") and getattr(o, "name", None) in \
        ("es", "ds", "ss")


def ems_es(i) -> bool:
    """The instruction accesses memory through ES (lower.py ems_guard)."""
    if i.op in ("lea", "nop"):
        return False
    return i.op in ("movs", "cmps", "stos", "scas") or \
        i.op in ("lods", "xlat") and i.seg == "es" or any(
        getattr(o, "seg", None) == "es" and hasattr(o, "disp") for o in i.operands)


def ems_ds(i) -> bool:
    """The instruction accesses memory through DS (ems_guard in listed code)."""
    if i.op in ("lea", "nop"):
        return False
    return (i.op in ("movs", "cmps", "lods", "xlat") and (i.seg or "ds") == "ds") or any(
        getattr(o, "seg", None) == "ds" and hasattr(o, "disp") for o in i.operands)


EMS_EXITS = ("retf", "iret", "int", "into", "callf", "jmpf")   # lower.py


def ems_case(i) -> bool:
    return ems_es(i) or loads_segment(i) and getattr(i.operands[0], "name", None) in ("ds", "ss") \
        or i.op == "lds"


def ems_ds_case(i) -> bool:
    return ems_ds(i) or i.op in EMS_EXITS or i.op == "lds" or \
        loads_segment(i) and getattr(i.operands[0], "name", None) == "ds"


def ems_index(i, seg: str) -> list[str]:
    """A string's operands through `seg` (lower.py ems_guard): SI in its segment, ES:DI."""
    return [r for r, on in (("si", i.op in ("movs", "cmps", "lods") and (i.seg or "ds") == seg),
                            ("di", seg == "es" and i.op in ("movs", "cmps", "stos", "scas"))) if on]


def ems_want(i, seg: str, regs: dict, flags: dict) -> tuple[int, int | None]:
    """The guard's (d6 bytes, d7 offset or None: not compared) for its access
    through `seg`: from the lowest of a string's operands in it (ES:DI, [SI] in
    its segment), its size times CX (REP; CX 0: one) plus the distance between
    the two, or 0 with DF set (the whole window); one element through one
    operand (no REP): its own bytes; xlat's byte at BX+AL; else the operand."""
    idx = ems_index(i, seg)
    if idx and not i.rep and len(idx) == 1:
        return i.width // 8, regs[idx[0]]
    if idx:
        if flags.get("DF"):
            return 0, None
        n = (regs["cx"] or 1) if i.rep else 1
        lo = min(regs[r] for r in idx)
        return max(regs[r] for r in idx) - lo + i.width // 8 * n, lo
    if i.op == "xlat":
        return 1, (regs["bx"] + (regs["ax"] & 0xFF)) & 0xFFFF
    m = next(o for o in i.operands if getattr(o, "seg", None) == seg and hasattr(o, "disp"))
    return max(1, m.width // 8), (m.disp + sum(regs[r] for r in (m.base, m.index) if r)) & 0xFFFF


def ems_diffs(i, regs: dict, flags: dict, out: dict, calls: list, stop, ds_mode: bool,
              hit: set = frozenset()) -> list[str]:
    """The guards' runtime calls (copied from Wing Commander 2, the string range
    and the listed-code DS mode X-Wing's): rt_ems_es before an ES access iff ES
    >= D001h, with the access's offset and size, but for a segment in `hit`
    (the one-entry cache covers the access: no call, the cached base); in
    listed code (ds_mode)
    rt_ems_ds the same for DS, no rt_ems_seg at a DS load, and rt_ems_ds_leave
    before an exit iff DS >= D001h; elsewhere rt_ems_seg after a DS or SS load
    iff the value loaded is D001h or above."""
    diffs = []
    by = {n: [c for c in calls if c[0] == n] for n in ("rt_ems_es", "rt_ems_ds", "rt_ems_seg",
                                                        "rt_ems_ds_leave", "rt_vram_ds")}
    for seg, n, has in (("es", "rt_ems_es", ems_es(i)), ("ds", "rt_ems_ds", ds_mode and ems_ds(i))):
        got = by[n]
        if not has:
            if got:
                diffs.append(f"{n} called without a {seg} access")
            continue
        want = regs[seg] >= 0xD001 and seg not in hit
        if want != bool(got):
            diffs.append(f"{n} {'missing' if want else 'called'} at {seg}={regs[seg]:04x}")
        elif got:
            _, d6, d7, es, ds = got[0]
            wd6, wd7 = ems_want(i, seg, regs, flags)
            v = es if seg == "es" else ds
            if d6 != wd6 or wd7 is not None and (d7 & 0xFFFF) != wd7 or v != regs[seg]:
                diffs.append(f"{n} d6={d6:x} d7={d7 & 0xFFFF:04x} {seg}={v:04x}, "
                             f"want d6={wd6:x} d7={wd7 if wd7 is None else f'{wd7:04x}'}")
    leave = ds_mode and i.op in EMS_EXITS and regs["ds"] >= 0xD001
    if leave != bool(by["rt_ems_ds_leave"]):
        diffs.append(f"rt_ems_ds_leave {'missing' if leave else 'called'} at ds={regs['ds']:04x}")
    loaded = [s for s in ("ds", "ss") if (i.op == "lds" and s == "ds") or
              (loads_segment(i) and getattr(i.operands[0], "name", None) == s)]
    seg_calls = by["rt_ems_seg"]
    want = any(out[s] >= 0xD001 and stop not in ("T_FAULT", "T_INT") and not (ds_mode and s == "ds")
               for s in loaded)
    if want != bool(seg_calls):
        diffs.append(f"rt_ems_seg {'missing' if want else 'called'} at "
                     + " ".join(f"{s}={out[s]:04x}" for s in loaded))
    # D9: a DS load whose window meets the VGA frame marks it all (rt_vram_ds)
    want = "ds" in loaded and 0x9001 <= out["ds"] <= 0xAF9F and stop not in ("T_FAULT", "T_INT")
    if want != bool(by["rt_vram_ds"]):
        diffs.append(f"rt_vram_ds {'missing' if want else 'called'} at ds={out['ds']:04x}")
    return diffs


def irq_diffs(f: dict, irq: int, pending: int) -> list[str]:
    """runtime.h: G_IRQ only with rt_irq_pending; with IF set, pending means G_IRQ."""
    if irq and not pending:
        return [f"G_IRQ {irq} without rt_irq_pending"]
    if f["IF"] and pending and not irq:
        return ["IF set, G_IRQ not re-armed"]
    return []


class M68k:
    """Unicorn 68020 with guest RAM, state block, stubs and native stack."""

    def __init__(self, background: bytes, stubs: dict[str, int] | None = None,
                 compute_services=frozenset()):
        assert len(background) == X.RAM
        self.bg = background
        self.stub_at = stubs or STUB_AT
        e = self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(STATE, 0x1000)
        e.map(GUEST_LO, TOP + 1 - GUEST_LO)
        self.gwrite(0, background)
        e.map(STUB, 0x1000)
        e.write(STUB, b"\x4a\xfc\x4e\x75" * len(self.stub_at))  # illegal; rts
        e.map(STACK - 0x10000, 0x20000)
        e.map(CODE, 0x800000)
        self.writes: set[int] = set()
        self.outs: list = []
        self.stop: str | None = None
        self.irq_rng = random.Random(1)
        self.upper_rng = random.Random(4)   # guest registers' upper words (speed-plan R4)
        # rt_irq called at a poll point: None stops there (a block exit); a
        # list records (d6, d7) and returns, G_IRQ and rt_irq_pending cleared
        # (an interrupt taken) or, with irq_keep, left set (the bench watch).
        self.irq_calls: list | None = None
        self.budget = 4_000_000     # 68k instructions per case (m68k_blocks: more per REP)
        self.irq_keep = False
        self.ems_calls: list = []   # (stub, d6, d7, G_ES, G_DS) of the EMS entries
        self.cache = bytes(24)       # CACHE's contents for the next run

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            if GUEST_LO <= addr <= TOP:
                self.writes.update(range(TOP - addr - size + 1, TOP - addr + 1))
            return True

        by_addr = {a: n for n, a in self.stub_at.items()}
        self.extra_stops: dict[int, str] = {}
        self.inside: set[int] = set()
        self.entry: int | None = None

        @U.CODE_CB
        def code(h, addr, size, user):
            n = by_addr.get(addr)
            if addr == self.entry:
                self.entry = None  # the case starts here; a later visit is a back edge
                return
            if n is None:
                n = self.extra_stops.get(addr)
                if n is None or addr in self.inside:
                    return
            if n == "rt_irq" and self.irq_calls is not None:
                self.irq_calls.append((self.r("d6"), self.r("d7")))
                if not self.irq_keep:
                    self.e.write(STATE + 8, b"\0")
                    self.e.write(PENDING, b"\0")
                self.e.reg_write(U.M68K["pc"], addr + 2)
            elif n in ("rt_in8", "rt_in16"):
                port = self.r("d7") & 0xFFFF
                w = 8 if n == "rt_in8" else 16
                v = X.port_value(port, w // 8)
                d6 = self.r("d6")
                self.e.reg_write(U.M68K["d6"], d6 & ~(0xFF if w == 8 else 0xFFFF) | v)
                self.e.reg_write(U.M68K["pc"], addr + 2)
            elif n in ("rt_ems_es", "rt_ems_seg", "rt_ems_ds", "rt_ems_ds_leave", "rt_ems_es_miss",
                       "rt_ems_ds_miss", "rt_vram_ds"):
                st = self.e.read(STATE, 16)
                es, ds = int.from_bytes(st[4:6], "big"), int.from_bytes(st[0:2], "big")
                self.ems_calls.append((n.removesuffix("_miss"), self.r("d6"), self.r("d7"), es, ds))
                if n.endswith("_miss"):     # the runtime's base: plain, as below the frame
                    a, v = ("a1", es) if n == "rt_ems_es_miss" else ("a3", ds)
                    self.e.reg_write(U.M68K[a], TOP - v * 16 - 0x7FFF)
                if n in ("rt_ems_es", "rt_ems_ds", "rt_ems_es_miss", "rt_ems_ds_miss"):
                    # rt_entry.s EMS_GUARD keeps no CCR ("the callers keep d6, d7 and
                    # the CCR"): X N Z V C come back inverted, so a caller that needs
                    # them and did not save them shows
                    self.e.reg_write(U.M68K["sr"], self.r("sr") ^ 0x1F)
                self.e.reg_write(U.M68K["pc"], addr + 2)
            elif n in ("rt_out8", "rt_out16"):
                w = 8 if n == "rt_out8" else 16
                self.outs.append((self.r("d7") & 0xFFFF, w, self.r("d6") & ((1 << w) - 1)))
                self.e.reg_write(U.M68K["pc"], addr + 2)
            elif n in compute_services:  # d7=0: exact fallback, as x86
                self.e.reg_write(U.M68K['d7'], 0)
                self.e.reg_write(U.M68K['pc'], addr + 2)
            elif n in ("rt_vram_mark", "rt_vram_mark_short"):  # D9 changed rows: no guest state (d6, d7, a0
                self.e.reg_write(U.M68K["pc"], addr + 2)   # scratch); host_run checks it
            elif n.startswith("rt_hle_"):  # EQ: the guest code runs (as x86)
                self.e.reg_write(U.M68K["sr"], self.r("sr") | 4)
                self.e.reg_write(U.M68K["pc"], addr + 2)
            else:
                self.stop = n
                U.uc.uc_emu_stop(h)

        e.hook(U.HOOK_MEM_WRITE, write)
        e.hook(U.HOOK_CODE, code)

    def r(self, name: str) -> int:
        return self.e.reg_read(U.M68K[name])

    def gread(self, a: int, n: int) -> bytes:
        """Guest bytes a..a+n-1 in guest order."""
        return self.e.read(TOP - a - n + 1, n)[::-1]

    def gwrite(self, a: int, data: bytes) -> None:
        self.e.write(TOP - a - len(data) + 1, bytes(data)[::-1])

    def load(self, image: bytes) -> None:
        self.e.write(CODE, image)
        self.e.flush()

    def run(self, entry: int, case, rng, skip_entry: bool = True, init: dict | None = None,
            irq: bool = True, posted: bool = False):
        """irq: rt_irq_pending mostly set, G_IRQ as rt_irq leaves it (IF ? pending : 0);
        otherwise both clear (code with poll points), or with `posted` both set (an
        interrupt posted before a poll point)."""
        regs, flags, flagsx, ip, patches = case
        e = self.e
        for a, data in patches:
            self.gwrite(a, data)
        for r in REGS:   # upper words undefined (R4): 0, FFFFh or random
            hi = (0, 0xFFFF, self.upper_rng.randrange(1, 0xFFFF))[self.upper_rng.randrange(3)]
            e.reg_write(U.M68K[M68[r]], hi << 16 | regs[r] ^ MIRROR.get(r, 0))
        for s, a in (("es", "a1"), ("ss", "a2"), ("ds", "a3")):
            e.reg_write(U.M68K[a], TOP - regs[s] * 16 - 0x7FFF)
        e.reg_write(U.M68K["a6"], TOP)
        for j in ("d6", "d7", "a0"):
            e.reg_write(U.M68K[j], rng.randrange(1 << 32))
        for j, v in (init or {}).items():
            e.reg_write(U.M68K[j], v)
        st = bytearray(16)
        st[16 - 2:16] = bytes([rng.randrange(256) & 0xE0, ccr_image(flags) | rng.randrange(2) << 4])
        st[16 - 3] = 0 if flags["PF"] else 1
        st[16 - 4] = flags["AF"] << 4 | rng.randrange(16) & 0xEF
        st[16 - 5], st[16 - 6], st[16 - 7] = flags["DF"], flags["IF"], flags["TF"]
        st[16 - 10:16 - 8] = flagsx.to_bytes(2, "big")
        for s, at in (("es", 12), ("ss", 14), ("ds", 16)):
            st[16 - at:16 - at + 2] = regs[s].to_bytes(2, "big")
        pending = int(irq and self.irq_rng.randrange(4) != 0)
        st[16 - 8] = pending & flags["IF"]
        if posted:
            pending = st[16 - 8] = 1
        e.write(PENDING, bytes([pending]))
        e.write(CACHE["es"], self.cache)
        self.cache = bytes(24)
        e.write(STATE, bytes(st))
        sp = STACK - 0x100
        e.write(sp, self.stub_at["T_RET"].to_bytes(4, "big"))
        e.reg_write(U.M68K["sr"], 0)  # user mode first: a7 is then the USP
        e.reg_write(U.M68K["a7"], sp)
        self.writes, self.outs, self.stop = set(), [], None
        self.ems_calls = []
        self.entry = entry if skip_entry else None
        err = e.start(entry, 0xFFFFFFFF, self.budget)
        out = {r: (self.r(M68[r]) ^ MIRROR.get(r, 0)) & 0xFFFF for r in REGS}
        st = e.read(STATE, 16)
        for s, at in (("es", 12), ("ss", 14), ("ds", 16)):
            out[s] = int.from_bytes(st[16 - at:16 - at + 2], "big")
        fl = st[16 - 1]
        f = {"CF": fl & 1, "OF": fl >> 1 & 1, "ZF": fl >> 2 & 1, "SF": fl >> 3 & 1,
             "PF": int(bin(st[16 - 3]).count("1") % 2 == 0), "AF": st[16 - 4] >> 4 & 1,
             "DF": st[16 - 5], "IF": st[16 - 6], "TF": st[16 - 7]}
        fx = int.from_bytes(st[16 - 10:16 - 8], "big")
        d6, d7 = self.r("d6") & 0xFFFF, self.r("d7") & 0xFFFF
        info = {"stop": self.stop, "err": err, "d6": d6, "d7": d7, "d6.l": self.r("d6"),
                "d7.l": self.r("d7"),
                "irq": irq_diffs(f, st[16 - 8], e.read(PENDING, 1)[0]),
                "a7": self.r("a7"), "segbase": {a: self.r(a) for a in ("a1", "a2", "a3")},
                "ems": list(self.ems_calls)}
        mem = {a: self.gread(a, 1)[0] for a in sorted(self.writes)}
        return out, f, fx, mem, list(self.outs), set(self.writes), info

    def restore(self, addrs) -> None:
        for a, b in X.spans(addrs):
            self.gwrite(a, self.bg[a:b])


def sources_key() -> str:
    """What a recorded x86 side depends on: the test and translator sources, Unicorn."""
    h = hashlib.sha256()
    root = Path(__file__).resolve().parent.parent
    for f in sorted([*root.glob("tests/*.py"), *root.glob("translator/*.py")]):
        h.update(f.name.encode() + f.read_bytes())
    st = os.stat(U.LIB)
    h.update(f"{U.LIB} {st.st_size} {st.st_mtime_ns}".encode())
    return h.hexdigest()


def runs(mem: dict) -> list:
    """{address: byte} as [(first address, bytes)] (a REP store writes 64 KiB)."""
    out = []
    for a in sorted(mem):
        if out and out[-1][0] + len(out[-1][1]) == a:
            out[-1][1].append(mem[a])
        else:
            out.append((a, bytearray([mem[a]])))
    return [(a, bytes(d)) for a, d in out]


def unruns(rs: list) -> dict:
    return {a + k: v for a, d in rs for k, v in enumerate(d)}


class Harness(X.Harness):
    recording = False   # --record
    keep_failing = True     # keep the source and image of a batch with mismatches
    dirs: list = []         # batch directories made by this process

    def __init__(self, seed: int):
        super().__init__(seed)
        self.m = M68k(self.bg)
        self.pending: list = []
        self.stats = Counter()
        self.lowered = Counter()
        self.tmp = Path(tempfile.mkdtemp(prefix="m68k-diff-"))
        Harness.dirs.append(self.tmp)
        self.nbatch = 0
        self.seed = seed
        self.record: list | None = [] if self.recording else None   # [(case key, x86 side)]
        self.replay: list = []
        self.replayed = self.ncases = 0
        if REPLAY and REPLAY.exists():
            key, rec = pickle.loads(zlib.decompress(REPLAY.read_bytes()))
            if key == sources_key():
                self.replay = rec

    def save(self, path: Path) -> None:
        part = path.with_name(path.name + ".part")
        part.write_bytes(zlib.compress(pickle.dumps((sources_key(), self.record), 5), 1))
        part.replace(path)

    def case(self, code: bytes, label: str, n: int = 1, overrides=None, block=False):
        regs, flags, flagsx, ip = self.state(overrides)
        cs = regs["cs"]
        patches = []
        sp_lin = regs["ss"] * 16 + regs["sp"]
        stack = bytearray(self.rng.randrange(256) for _ in range(8))
        for k in (1, 3, 5, 7):
            stack[k] &= 0xFE
        patches.append((sp_lin, bytes(stack)))
        for a, data in (overrides or {}).get("mem", []):
            patches.append((a(regs) if callable(a) else a, data))
        patches.append((cs * 16 + ip, code))
        case = (regs, flags, flagsx, ip, patches)
        key = hashlib.blake2b(repr((self.seed, n, sorted(regs.items()), sorted(flags.items()),
                                    flagsx, ip, patches)).encode(), digest_size=16).digest()
        k, self.ncases = self.ncases, self.ncases + 1
        if k < len(self.replay) and self.replay[k][0] == key:
            side = self.replay[k][1]
            self.replayed += 1
        else:
            side = self.x86_side(code, n, case)
        if self.record is not None:
            self.record.append((key, side))
        if side[0] == "undefined":
            self.undefined[side[1]] += 1
            return
        if side[0] == "skipped":
            self.skipped[side[1]] += 1
            return
        _, undef, (err, out, fl, mem, ints, outs) = side
        oracle = (err, out, fl, unruns(mem), ints, outs)
        # decode the whole run statically (the 68k side runs what the bytes say)
        insns, k, at = [], 0, ip
        while len(insns) < n:
            i = decode(code, at, k)
            insns.append(i)
            k += i.size
            at = i.next_ip
        tag = f"c{len(self.pending)}"
        try:
            text, st = lower_case(insns, cs, tag, insns[-1].next_ip)
        except LowerError as e:
            self.bad.append(f"{label} {code.hex()}: lowering: {e}")
            return
        self.lowered.update(st)
        self.pending.append((label, code, case, undef, oracle, text, regs, flags, insns[-1].op))
        guarded = lower_region_case(insns, cs, f"c{len(self.pending)}", insns[-1].next_ip)
        if guarded:     # the same case through a region guard (speed-plan R6)
            self.lowered.update(guarded[1])
            self.pending.append((label + " bp-region", code, case, undef, oracle, guarded[0],
                                 regs, flags, insns[-1].op))
        if any(map(loads_segment, insns)):   # segment loads compared first (R30)
            tag = f"c{len(self.pending)}"
            try:
                text, st = lower_case(insns, cs, tag, insns[-1].next_ip, seg_repeat=True)
            except LowerError as e:
                self.bad.append(f"{label} seg-repeat {code.hex()}: lowering: {e}")
                return
            self.lowered.update(st)
            self.pending.append((label + " seg-repeat", code, case, undef, oracle, text,
                                 regs, flags, insns[-1].op))
        if any(map(carries_in_place, insns)):   # the driver's one-instruction form
            tag = f"c{len(self.pending)}"
            try:
                text, st = lower_case(insns, cs, tag, insns[-1].next_ip, atomic_carry=True)
            except LowerError as e:
                self.bad.append(f"{label} atomic-carry {code.hex()}: lowering: {e}")
                return
            self.lowered.update(st)
            self.pending.append((label + " atomic-carry", code, case, undef, oracle, text,
                                 regs, flags, insns[-1].op))
        if label.startswith("b:ems-hold:"):     # lower.ems_held over the block
            tag = f"c{len(self.pending)}"
            try:
                text, st = lower_case(insns, cs, tag, insns[-1].next_ip, ems=True)
            except LowerError as e:
                self.bad.append(f"{label} emshold {code.hex()}: lowering: {e}")
                return
            self.lowered.update(st)
            self.pending.append((label + " emshold", code, case, undef, oracle, text,
                                 regs, flags, insns[-1].op))
        if n == 1 and ems_case(insns[0]):
            self.ems_variant(code, label, insns, case, overrides)
        if n == 1 and ems_ds_case(insns[0]):
            self.ems_variant(code, label, insns, case, overrides, ds=True)
        if len(self.pending) >= BATCH:
            self.flush()

    def ems_variant(self, code, label, insns, case, overrides, ds: bool = False) -> None:
        """EMS model (copied from Wing Commander 2): the case lowered with its
        guards (Ctx.ems), ES (or the value a DS/SS load takes from a register)
        set to one of the guard's edges, cycling; compare() checks the semantics
        and the runtime calls. The x86 side runs live (not in the recording).
        `ds`: as listed code (Ctx.ems_ds), DS at the edge for a DS access or an
        exit (X-Wing's)."""
        regs, flags, flagsx, ip, patches = case
        i = insns[0]
        edge = EMS_EDGES[self.lowered["ems case"] % len(EMS_EDGES)]
        src = i.operands[1] if len(i.operands) > 1 else None
        if ds and (ems_ds(i) or i.op in EMS_EXITS):
            regs2 = dict(regs, ds=edge)
        elif ems_es(i):
            regs2 = dict(regs, es=edge)
        elif i.op == "mov" and getattr(src, "name", None) in REGS:
            regs2 = dict(regs, **{src.name: edge})
        else:
            regs2 = dict(regs)
        if regs2 != regs:
            patches = patches[:1] + [(a(regs2) if callable(a) else a, d)
                                     for a, d in (overrides or {}).get("mem", [])] + \
                [(regs2["cs"] * 16 + ip, code)]
        case2 = (regs2, flags, flagsx, ip, patches)
        side = self.x86_side(code, 1, case2)
        if side[0] != "ok":
            return
        _, undef, (err, out, fl, mem, ints, outs) = side
        tag = f"c{len(self.pending)}"
        try:
            text, st = lower_case(insns, regs2["cs"], tag, insns[-1].next_ip, ems=True, ems_ds=ds)
        except LowerError as e:
            self.bad.append(f"{label} ems {code.hex()}: lowering: {e}")
            return
        self.lowered.update(st)
        self.lowered["ems case"] += 1
        self.pending.append((label + (" emsds" if ds else " ems"), code, case2, undef, (err, out, fl, unruns(mem), ints, outs),
                             text, regs2, flags, insns[-1].op))

    def x86_side(self, code: bytes, n: int, case) -> tuple:
        """("undefined", why) | ("skipped", why) | ("ok", undefined flags, Unicorn result)."""
        regs, flags, flagsx, ip, patches = case
        cs = regs["cs"]
        # IR side: only the undefined-flag mask (and decode).
        s = State(dict(regs, flagsx=flagsx), dict(flags), self.mem, ip)
        s.port_in = lambda port, w: X.port_value(port, w // 8)
        for a, data in patches:
            self.mem[a:a + len(data)] = data
        insns = []
        try:
            for _ in range(n):
                ex, insn = step(s)
                insns.append(insn)
                if ex.kind in ("int", "fault", "trap"):
                    break
        except (UndefinedFlag, DecodeError) as e:
            self.reset(patches, s.writes, set())
            return ("undefined", type(e).__name__)
        undef = set(s.undef)
        self.reset(patches, s.writes, set())
        err, out, fl, umem, ints, outs, uwrites = self.oracle.run(case, n)
        code_span = set(range(cs * 16 + ip, cs * 16 + ip + len(code)))
        why = None
        if code_span & uwrites:
            why = "writes its own code"
        elif X.restarted(cs * 16 + ip, len(code), s.writes, ip, out, ints):
            why = "oracle: store into its code's page restarts it"
        elif n == 1 and (dev := X.oracle_deviation(code, regs)):
            why = f"oracle: {dev}"
        if why:
            self.oracle.restore(uwrites | {a for a, d in patches for a in range(a, a + len(d))})
            return ("skipped", why)
        mem = {a: umem.get(a, self.oracle.e.read(a, 1)[0]) for a in set(umem) | uwrites}
        self.oracle.restore(uwrites | set(umem) | {a for a, d in patches
                                                   for a in range(a, a + len(d))})
        return ("ok", undef, (err, out, fl, runs(mem), ints, outs))

    def flush(self) -> None:
        if not self.pending:
            return
        src = [equates()]
        src += [f"{n}\tequ\t${a:x}" for n, a in STUB_AT.items()]
        src.append(f"rt_irq_pending\tequ\t${PENDING:x}")
        src += [f"rt_ems_cache_{s}\tequ\t${a:x}" for s, a in CACHE.items()]
        src.append(f"\torg\t${CODE:x}")
        src.append("table:")
        src += [f"\tdc.l\tc{k}" for k in range(len(self.pending))]
        for p in self.pending:
            src += p[5]
        src.append(HELPERS)
        self.nbatch += 1
        out = self.tmp / f"batch{self.nbatch}.bin"
        image = assemble("\n".join(src) + "\n", out)
        self.m.load(image)
        bad = len(self.bad)
        for k, (label, code, case, undef, oracle, text, regs, flags, last) in enumerate(self.pending):
            entry = int.from_bytes(image[4 * k:4 * k + 4], "big")
            self.compare(label, code, case, undef, oracle, entry, regs, flags, last)
        self.pending = []
        if len(self.bad) == bad or not self.keep_failing:
            out.unlink()
            out.with_suffix(".s").unlink()

    @staticmethod
    def tidy() -> None:
        """Remove the batch directories that keep no failing batch."""
        for d in Harness.dirs:
            with contextlib.suppress(OSError):
                d.rmdir()
        Harness.dirs.clear()

    def ems_hold_diffs(self, code: bytes, case, calls: list) -> list[str]:
        """lower.ems_held: every access through ES at D001h or above (the IR run
        of the block gives ES and the offset) has its rt_ems_es call, in order,
        or is within the last call's bytes at the same ES value (the guard's
        result, a1, held); nothing else calls the EMS model here."""
        regs, flags, flagsx, ip, patches = case
        s = State(dict(regs, flagsx=flagsx), dict(flags), self.mem, ip)
        for a, data in patches:
            self.mem[a:a + len(data)] = data
        need = []
        try:
            while s.ip < ip + len(code) - 1:    # the PUSHF that ends the block aside
                i = decode(bytes(self.mem[regs["cs"] * 16 + s.ip:][:16]), s.ip, 0)
                a = es_access(i)
                if a is not None and s.regs["es"] >= 0xD001:
                    off = (a[2] + sum(s.regs[r] for r in a[:2] if r)) & 0xFFFF
                    need.append((s.regs["es"], off, a[3], str(i)))
                step(s)
        finally:
            self.reset(patches, s.writes, set())
        diffs, held, got = [], None, [c for c in calls if c[0] == "rt_ems_es"]
        if len(got) != len(calls):
            diffs.append(f"other EMS calls {[c[0] for c in calls]}")
        for es, off, n, text in need:
            if got and (got[0][3], got[0][2] & 0xFFFF, got[0][1]) == (es, off, n):
                held = (es, off, n)
                got.pop(0)
            elif not (held and held[0] == es and held[1] <= off and off + n <= held[1] + held[2]):
                diffs.append(f"{text} at es={es:04x} offset {off:04x}: neither guarded nor held")
        if got:
            diffs.append(f"rt_ems_es calls beyond the accesses: {got}")
        return diffs

    def ems_cache(self, i, regs: dict, flags: dict) -> set:
        """The guard caches for an EMS case (EMS_CACHE, cycling): empty, covering
        the access exactly with the plain base (lower.py ems_guard's inline hit:
        no runtime call), or missing it by its last byte, its first byte or the
        segment, with another base (a wrong hit shows in the base). One string
        element through one operand checks it inline too; other strings call
        the runtime, which checks the cache itself (host_run ems_guard_problems).
        Returns the segments expected to hit."""
        state = EMS_CACHE[self.lowered["ems cache"] % len(EMS_CACHE)]
        self.lowered["ems cache"] += 1
        cache, hit = bytearray(24), set()
        for k, seg in enumerate(("es", "ds")):
            idx = ems_index(i, seg)
            if state == "empty" or (idx and (i.rep or len(idx) != 1)) or \
                    not (ems_es(i) if seg == "es" else ems_ds(i)):
                continue
            n, lo = ems_want(i, seg, regs, flags)
            plain = TOP - regs[seg] * 16 - 0x7FFF
            v, low, end, base = regs[seg], lo, lo + n, plain
            if state == "end":
                end -= 1
            elif state == "low":
                low += 1
            elif state == "segment":
                v = (v + 1) & 0xFFFF
            if state == "hit":
                hit.add(seg)
            else:
                base += 0x10
            if low > 0xFFFF:
                continue
            cache[12 * k:12 * k + 12] = (v.to_bytes(2, "big") + low.to_bytes(2, "big") + end.to_bytes(4, "big")
                                         + base.to_bytes(4, "big"))
        self.m.cache = bytes(cache)
        return hit

    def compare(self, label, code, case, undef, oracle, entry, regs, flags, last) -> None:
        err, out, fl, umem, ints, outs = oracle
        hit = set()
        if label.endswith((" ems", " emsds")):
            hit = self.ems_cache(decode(code, case[3], 0), regs, flags)
        mo, mf, mfx, mmem, mouts, mwrites, info = self.m.run(entry, case, self.rng)
        diffs = []
        if err:
            diffs.append(f"unicorn x86 error {err}")
        if info["err"]:
            diffs.append(f"unicorn 68k error {info['err']} stop={info['stop']}")
        diffs += info["irq"]
        stop = info["stop"]
        if "trap" in out or stop == "T_TRAP":
            # TF set by POPF/IRET: a stop at that instruction, nothing else compared
            if stop != "T_TRAP" or info["d7"] != out.get("trap"):
                diffs.append(f"exit {stop} ip={info['d7']:04x} want T_TRAP at {out.get('trap')}")
            self.count[label] += 1
            if diffs:
                self.bad.append(f"{label} {code.hex()}: {'; '.join(diffs)}")
            self.m.restore(set(mwrites) | {a for p, d in case[4] for a in range(p, p + len(d))})
            return
        exc = ints[0] if ints else None
        if exc is not None and exc in X.EXCEPTIONS:
            want = "T_FAULT"
        elif exc is not None:
            want = "T_INT"
        else:
            want = None
        if want and stop != want:
            diffs.append(f"exit {stop} want {want}")
        if want and info["d6"] != exc:
            diffs.append(f"vector 68k={info['d6']} x86={exc}")
        if not want and stop in ("T_INT", "T_FAULT", None):
            diffs.append(f"exit {stop} without x86 interrupt")
        for r in REGS:
            if mo[r] != out[r]:
                diffs.append(f"{r} 68k={mo[r]:04x} x86={out[r]:04x}")
        for sname, a in (("es", "a1"), ("ss", "a2"), ("ds", "a3")):
            if mo[sname] != out[sname]:
                diffs.append(f"{sname} 68k={mo[sname]:04x} x86={out[sname]:04x}")
            if info["segbase"][a] != TOP - out[sname] * 16 - 0x7FFF:
                diffs.append(f"{sname} base {info['segbase'][a]:x}")
        # CS:IP
        far = stop in ("T_JUMPF", "T_CALLF") or stop == "T_RET" and last in ("retf", "iret")
        mcs = info["d6"] if far else regs["cs"]
        if stop == "T_RET" and last in ("retf", "iret"):
            mcs = info["d7.l"] >> 16
        mip = info["d7"]
        if mip != out["ip"]:
            diffs.append(f"ip 68k={mip:04x} x86={out['ip']:04x} ({stop})")
        if mcs != out["cs"]:
            diffs.append(f"cs 68k={mcs:04x} x86={out['cs']:04x}")
        for f in FLAGS:
            if f not in undef and mf[f] != fl >> FLAG_BIT[f] & 1:
                diffs.append(f"{f} 68k={mf[f]} x86={fl >> FLAG_BIT[f] & 1}")
        if (mfx >> 12) & 7 != (fl >> 12) & 7:
            diffs.append(f"flags[14:12] 68k={mfx >> 12 & 7} x86={fl >> 12 & 7}")
        for a in sorted(set(umem) | mwrites):
            x = umem.get(a, self.bg[a] if a not in {p for p, d in case[4] for p in range(p, p + len(d))}
                         else None)
            m = mmem.get(a)
            if m is None:
                m = self.m.gread(a, 1)[0]
            if x is None:
                x = next(d[a - p] for p, d in case[4] if p <= a < p + len(d))
            if m != x:
                diffs.append(f"mem {a:05x} 68k={m:02x} x86={x:02x}")
                break
        if mouts != outs:
            diffs.append(f"out 68k={mouts} x86={outs}")
        if stop in (None,) and not info["err"]:
            diffs.append("no exit (instruction limit)")
        if label.endswith(" emshold"):
            diffs += self.ems_hold_diffs(code, case, info["ems"])
        elif label.endswith((" ems", " emsds")):
            diffs += ems_diffs(decode(code, case[3], 0), regs, flags, out, info["ems"], stop,
                               label.endswith(" emsds"), hit)
        elif info["ems"]:
            diffs.append(f"EMS runtime calls without the model: {info['ems']}")
        self.count[label] += 1
        if diffs:
            st = " ".join(f"{k}={v:04x}" for k, v in regs.items())
            fs = "".join(f for f in FLAGS if flags[f])
            self.bad.append(f"{label} {code.hex()} ip={case[3]:04x} [{st} {fs}]: "
                            f"{'; '.join(diffs[:6])}")
        touched = set(mwrites) | {a for p, d in case[4] for a in range(p, p + len(d))}
        self.m.restore(touched)


atexit.register(Harness.tidy)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    record = None
    if "--record" in argv:
        k = argv.index("--record")
        record = Path(argv[k + 1])
        del argv[k:k + 2]
    if "--replay" in argv:
        global REPLAY
        k = argv.index("--replay")
        REPLAY = Path(argv[k + 1])
        del argv[k:k + 2]
    Harness.recording = record is not None
    h = X.run(argv, harness=Harness)
    h.flush()
    if record:
        h.save(record)
    total = sum(h.count.values())
    groups = Counter()
    for k, v in h.count.items():
        groups[k.split(":")[0]] += v
    print("cases", total, dict(groups), "batches", h.nbatch)
    if h.skipped:
        print("not compared:", dict(h.skipped))
    if h.undefined:
        print("skipped (IR reads undefined flag / undecodable):", dict(h.undefined))
    print("lowering counters:", dict(h.lowered))
    for b in h.bad[:40]:
        print(b)
    print(f"{len(h.bad)} mismatches")
    return 1 if h.bad or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
