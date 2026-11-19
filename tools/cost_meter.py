#!/usr/bin/env python3
"""Deterministic cost meter (docs/perf-method.md): the per-step acceptance of P8.

  cost_meter.py [MILESTONE] [--no-resume] [--out JSON]
  cost_meter.py --compare A.json B.json
  cost_meter.py --calibrate CAPTURE ELF [--write]
  cost_meter.py --plant-check BASE_JSON

Copied from Secret Weapons of the Luftwaffe's tools/cost_meter.py
(manifest/references.tsv) and adapted: the run is tests/host_run.py's lockstep check
of the milestone (--bypass, and --resume from its save at the flight's start where it
has one), and any lockstep problem refuses the result. Its window is the milestone's
first snapshot trigger to its last (reference/milestones.csv; m12-training-flight:
the 50 frames after frame 300 of the training flight). A C block hook
(tests/host_meter.c) counts executions of every translated block and every taken
transfer (and its target: `targets`); blocks expand to executed 68k instructions over
the disassembly of the image that ran: the host image with tests/rep_replay.py's
diagnostic REP hooks, whose REP lowering differs from the production image's only
at the REP instructions an interrupt split in the reference. Features per
instruction: encoded bytes and taken transfers, each split by whether the
instruction lies in a loop of <= 256 bytes whose closing branch is taken
in this workload (the 68020 i-cache); data reads; data writes; mul/div.
Unsigned register long arithmetic has a separately probed total cost. Model cycles =
the features weighted by tools/cost_model.json. Exact and layout-blind: the
same build gives the same numbers, and moving code changes nothing.
The image is the sync image: interrupt poll tests (`tst.b G_IRQ(a6)` and its bne),
which production does not have, are counted per class: visits, taken branches and
their model cycles.

Calibrate: fit the weights (non-negative least squares) on an FS-UAE capture
(tools/profile_report.py format) of the Amiga ELF of the same build: per-PC
cycles against per-PC executions times features, taken counts from the
capture's PC sequence. Compare: per class and per x86 form. Plant check: NOPs (flag-neutral) at one
generated label must add exactly their instructions and bytes per execution, and
their cost.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TOOLS))
import lowering_cost as L  # noqa: E402
import profile_report as P  # noqa: E402

MODEL = TOOLS / "cost_model.json"
# The shared toolchain, as amiga/env.sh.
CROSS = str(Path(os.environ.get("AMIGA_TOOLCHAIN") or Path.home() / ".local/opt") / "bin/m68k-amiga-elf-")
VASM = os.environ.get("VASM") or str(Path.home() / ".local/vasmm68k_mot")
OBJDUMP = CROSS + "objdump"
FEATURES = ("insns", "bytes", "loop_bytes", "reads", "writes", "taken", "loop_taken", "muldiv", "long_arith")
LOOP = 256      # 68020 instruction cache
G_IRQ = int(re.search(r"^G_IRQ\s+equ\s+(\d+)", (REPO / "src/runtime/rt_entry.s").read_text(), re.M).group(1))
POLL_TEST = ("tst.b", f"{G_IRQ}(a6)")

# --- static features ---------------------------------------------------------

REG = re.compile(r"^(%?[ad][0-7]|sp|fp|pc|ccr|sr|usp|vbr|(?:[ad][0-7]|fp|sp)[/-].*)$")
ABS = re.compile(r"^[0-9a-f]+( <[^>]*>)?$")
BRANCH = re.compile(r"^(b(ra|hi|ls|cc|cs|ne|eq|vc|vs|pl|mi|ge|lt|gt|le|hs|lo)|db\w+)(\.[swl])?$")
CC = ("t", "f", "hi", "ls", "cc", "cs", "ne", "eq", "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le")
READ_ONLY = ("cmp", "cmpa", "cmpi", "tst", "btst", "chk", "chk2", "cmp2", "bftst", "bfextu",
             "bfexts", "bfffo", "mulu", "muls", "divu", "divs", "divul", "divsl")


def split_args(args: str) -> list[str]:
    """Top-level comma split (indexed modes contain commas); symbol notes dropped."""
    out, depth, cur = [], 0, ""
    for ch in re.sub(r" <[^>]*>", "", args):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def is_mem(operand: str) -> bool:
    if operand.startswith("#") or REG.match(operand):
        return False
    return "(" in operand or bool(ABS.match(operand))


def reglist_size(operand: str) -> int:
    operand = operand.replace("fp", "a6").replace("sp", "a7")
    n = 0
    for part in operand.split("/"):
        if "-" in part:
            a, b = part.split("-")
            n += int(b[1]) - int(a[1]) + 1 + (8 if a[0] != b[0] else 0)
        else:
            n += 1
    return n


def accesses(op: str, args: str) -> tuple[int, int, int]:
    """(data reads, data writes, mul/div) of one 68k instruction."""
    base = op.split(".")[0]
    if base in ("rts", "rtd"):
        return 1, 0, 0
    if base == "rtr":
        return 2, 0, 0
    if base in ("jsr", "bsr"):
        return 0, 1, 0
    if base in ("jmp", "nop", ".short", ".word", ".long") or BRANCH.match(op) or base.startswith("trap"):
        return 0, 0, 0
    if base == "link":
        return 0, 1, 0
    if base == "unlk":
        return 1, 0, 0
    ops = split_args(args)
    muldiv = int(base in ("mulu", "muls", "divu", "divs", "divul", "divsl"))
    if base == "movem":
        n = reglist_size(ops[0] if REG.match(ops[0]) else ops[1])
        return (0, n, 0) if REG.match(ops[0]) else (n, 0, 0)
    if base == "cmpm":
        return 2, 0, 0
    if base in ("addx", "subx", "abcd", "sbcd") and ops and is_mem(ops[0]):
        return 2, 1, 0
    if base in ("bfextu", "bfexts", "bfffo"):
        # objdump: source,offset,width,destination (unlike BFINS).
        ops = [ops[0], ops[-1]]
    elif base.startswith("bf"):   # offset and width follow the operands
        ops = ops[:-2]
    if base == "pea":
        return 0, 1, 0
    if base == "lea":
        return 0, 0, 0
    mem = [is_mem(o) for o in ops]
    if not any(mem):
        return 0, 0, muldiv
    if base in ("move", "movea", "movep", "move16", "moves"):
        return int(mem[0]), int(len(mem) > 1 and mem[-1]), 0
    if base == "clr" or base in tuple("s" + c for c in CC):
        return 0, int(mem[-1]), 0
    if base in READ_ONLY or base.startswith("cmp"):
        return sum(mem), 0, muldiv
    if base.startswith("bf"):     # bfins, bfset, bfclr, bfchg: read-modify-write
        return 1, 1, 0
    # ALU: a memory source is read; a memory destination is read and written
    reads = sum(mem[:-1]) + int(mem[-1])
    return reads, int(mem[-1]), muldiv


class Program:
    """The disassembly and symbols of one ELF: per-PC static features and the
    class of every PC (generated guest code, cell walk, runtime, platform)."""

    def __init__(self, elf: Path, objdump: str = OBJDUMP, platform_objs: tuple = ()):
        out = subprocess.run([objdump, "-d", "--insn-width=32", str(elf)],
                             capture_output=True, text=True, check=True).stdout
        self.init(out, P.symbols(objdump, str(elf)), self.object_symbols(objdump, platform_objs))

    @staticmethod
    def object_symbols(objdump: str, objs) -> set[str]:
        names = set()
        for o in objs:
            if Path(o).exists():
                out = subprocess.run([objdump, "-t", str(o)], capture_output=True, text=True,
                                     check=True).stdout
                names.update(p.split()[-1] for p in out.splitlines()
                             if len(p.split()) >= 5 and p.split()[-3] == ".text")
        return names

    def init(self, dis: str, syms: list, platform: set[str]):
        mn, sizes = L.parse_disassembly(dis)
        self.addrs = np.array(sorted(mn), dtype=np.int64)
        self.size = {a: sizes[a] for a in mn}
        self.mn = mn
        self.syms = syms
        self.sym_addr = [a for a, _ in syms]
        self.by_name = {n: a for a, n in syms}
        feats = {}
        for a, (op, arg) in mn.items():
            r, w, m = accesses(op, arg)
            # Only the unsigned register forms covered by the standalone probe.
            # Signed, immediate and memory forms retain the general model.
            long_arith = int(op in ("mulu.l", "divu.l", "divul.l") and
                             bool(re.fullmatch(r"d[0-7],d[0-7](?:[:,]d[0-7])?", arg)))
            feats[a] = [1, sizes[a], 0, r, w, 0, 0, m, long_arith]
        self.feat = feats
        self.cls = {}
        for a in mn:
            self.cls[a] = self.classify(a, platform)
        # Interrupt poll tests (irq-plan I1): `tst.b G_IRQ(a6)` and the bne
        # after it (emit.poll).
        self.polls = set()
        for i in range(len(self.addrs) - 1):
            a, b = int(self.addrs[i]), int(self.addrs[i + 1])
            if mn[a] == POLL_TEST and mn[b][0].startswith("bne"):
                self.polls.update((a, b))

    def set_loops(self, taken):
        """Reclassify bytes for this workload; cold back branches give no discount.

        This is a workload-level cache approximation, not a cache simulator.
        Recompute from neutral features so reusing a Program cannot retain loops
        observed in a different workload.
        """
        for f in self.feat.values():
            f[1], f[2] = f[1] + f[2], 0
        for a, (op, arg) in self.mn.items():
            if not BRANCH.match(op) or taken.get(a, 0) <= 0:
                continue
            target = self.branch_target(a)
            if target is not None and target <= a and a + self.size[a] - target <= LOOP:
                i = bisect.bisect_left(self.addrs, target)
                while i < len(self.addrs) and self.addrs[i] <= a:
                    f = self.feat[int(self.addrs[i])]
                    f[2], f[1] = f[1] + f[2], 0
                    i += 1

    def branch_target(self, pc):
        op, arg = self.mn[pc]
        t = re.match(r"^(?:d[0-7],)?([0-9a-f]+) <", arg)
        return int(t.group(1), 16) if BRANCH.match(op) and t else None

    def symbol(self, pc: int) -> str:
        i = bisect.bisect_right(self.sym_addr, pc) - 1
        return self.syms[i][1] if i >= 0 else "?"

    def classify(self, pc: int, platform: set[str]) -> str:
        name = self.symbol(pc)
        if name.endswith("_walk") or "_walk_" in name:
            return "walk"
        if P.GUEST.match(name) or P.TRAMPOLINE.match(name):
            return "generated"
        if name in platform:
            return "platform"
        return "runtime"


def cost_features(feat):
    """Pricing features, separate from raw instruction/byte/access counters.

    The probe fits the whole unsigned register long-arithmetic instruction,
    including its fetch cost; do not also charge generic bytes or mul/div.
    """
    priced = list(feat)
    if priced[8]:
        priced[0] = priced[1] = priced[2] = priced[7] = 0
    return priced


def model_cycles(feat, n, taken, coef) -> float:
    priced = cost_features(feat)
    return n * sum(coef[k] * priced[i] for i, k in enumerate(FEATURES) if "taken" not in k) + \
        coef["loop_taken" if feat[2] else "taken"] * taken


def load_model() -> dict:
    return json.loads(MODEL.read_text())["coef"]


# --- the run -------------------------------------------------------------------

def hook_library():
    """The block hook (tests/host_meter.c), built into tmp on first use."""
    import ctypes
    import hashlib
    src = REPO / "tests/host_meter.c"
    out = REPO / "tmp/host-meter" / (hashlib.sha256(src.read_bytes()).hexdigest()[:16] + ".so")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".{os.getpid()}.so")
        subprocess.run(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
                        str(src), "-o", str(tmp)], check=True)
        tmp.rename(out)
    return ctypes.CDLL(str(out))


def run(milestone: str, timeout: int, elf: Path | None = None, resume: bool = True):
    """The host lockstep check of the milestone (tests/host_run.py check, --bypass,
    and --resume for a milestone with a resume point), with a block hook counting from
    its first snapshot trigger to its last. Block counts {(addr, size): n}, taken counts
    {block: n}, taken transfers {(block, target): n} (meta["into"]) and the ELF that ran
    (the host image with the diagnostic REP hooks of tests/rep_replay.py). Any lockstep
    problem refuses the run."""
    import ctypes
    import host_resume
    import host_run as H
    lib = hook_library()
    lib.meter_reset()
    on = ctypes.c_uint8.in_dll(lib, "meter_on")
    window = {}

    class MeterHost(H.Host):
        @property
        def step(self):
            return self._step

        @step.setter
        def step(self, value):
            self._step = value
            if "open" in window:
                on.value = int(window["open"] <= value < window["close"])

        def run(self, script, timeout):
            window["open"] = len(script["keys"]) + 1        # past the first snapshot trigger
            window["close"] = len(script["keys"]) + len(script["snapshots"])
            window["host"] = self
            self.e.hook_range(8, lib.meter_block, 0x10000, self.code[1])   # UC_HOOK_BLOCK
            return super().run(script, timeout)

    # The resume's harness fingerprint (host_resume.HARNESS) reads Host.run by name:
    # it stays the unpatched harness's, so the meter and the gates share their saves.
    original, harness = H.Host, H.harness_hash
    pinned = harness()
    H.Host, H.harness_hash = MeterHost, lambda: pinned
    t0 = time.time()
    try:
        problems = H.check(milestone, timeout, None, None, elf=elf, bypass=True,
                           resume=resume and milestone in host_resume.POINTS)
    finally:
        H.Host, H.harness_hash = original, harness
    h = window["host"]
    meta = {"milestone": milestone, "stopped_at": h.stopped_at, "seconds": round(time.time() - t0),
            "label": h.stopped_at, "elf": str(Path(h.elf).relative_to(REPO))}
    if problems or ctypes.c_uint32.in_dll(lib, "meter_lost").value:
        raise SystemExit(f"meter run failed: {problems[:5] or 'a hook table filled up'}")
    n = 1 << 20
    view = lambda name, ty, k: (ty * k).from_address(ctypes.addressof(ty.in_dll(lib, name)))
    addr, size = view("blk_addr", ctypes.c_uint32, n), view("blk_size", ctypes.c_uint32, n)
    cnt, tak = view("blk_n", ctypes.c_uint64, n), view("blk_taken", ctypes.c_uint64, n)
    blocks, taken, into = Counter(), Counter(), Counter()
    slot = {}
    for i in range(n):
        if size[i]:
            slot[i] = (addr[i], size[i])
            if cnt[i]:
                blocks[slot[i]] = cnt[i]
            if tak[i]:
                taken[slot[i]] = tak[i]
    m = 1 << 21
    ef, et, en = view("edge_from", ctypes.c_uint32, m), view("edge_to", ctypes.c_uint32, m), \
        view("edge_n", ctypes.c_uint64, m)
    for i in range(m):
        if en[i]:
            into[(slot[ef[i]], slot[et[i]][0])] = en[i]
    if not blocks:
        raise SystemExit("meter run failed: no block ran in the window")
    meta["into"] = into
    return blocks, taken, meta, Path(h.elf)


def expand(prog: Program, blocks: Counter, taken_blocks: Counter):
    """Per-PC executions and taken transfers from block counts."""
    n, taken = Counter(), Counter()
    for (addr, size), k in blocks.items():
        i = bisect.bisect_left(prog.addrs, addr)
        end = addr + size
        last = None
        while i < len(prog.addrs) and prog.addrs[i] < end:
            pc = int(prog.addrs[i])
            n[pc] += k
            last = pc
            i += 1
        if last is None:
            raise ValueError(f"block {addr:x}+{size} outside the disassembly")
    for (addr, size), k in taken_blocks.items():
        i = bisect.bisect_left(prog.addrs, addr + size) - 1
        taken[int(prog.addrs[i])] += k
    return n, taken


def targets(prog: Program, into: Counter) -> dict:
    """Taken transfers into generated code from outside a cached loop, per
    target as "LABEL+offset" (tools/align_targets.py, speed-plan R8)."""
    out = Counter()
    for ((addr, size), dst), k in into.items():
        i = bisect.bisect_left(prog.addrs, addr + size) - 1
        if prog.feat[int(prog.addrs[i])][2] or prog.cls.get(dst) not in ("generated", "walk"):
            continue
        lab = prog.symbol(dst)
        out[f"{lab}+{dst - prog.by_name[lab]}"] += k
    return dict(out)


def instruction_counts(prog: Program, n: Counter) -> list:
    """Exact executed generated instructions, relocatable by symbol and offset.
    Keep the decoded instruction so target-profile mapping can fail on stale code."""
    rows = []
    for pc, count in sorted(n.items()):
        if count and prog.cls.get(pc) in ("generated", "walk"):
            lab = prog.symbol(pc)
            op, arg = prog.mn[pc]
            rows.append((lab, pc - prog.by_name[lab], op, arg, count))
    return rows


def taken_counts(prog: Program, taken: Counter) -> list:
    """Taken transfers per generated instruction, as instruction_counts
    (tools/outline_sites.py, speed-plan R27)."""
    return [(prog.symbol(pc), pc - prog.by_name[prog.symbol(pc)], *prog.mn[pc], k)
            for pc, k in sorted(taken.items()) if k and prog.cls.get(pc) in ("generated", "walk")]


def poll_counts(prog: Program, n: Counter, taken: Counter, coef: dict) -> dict:
    """Per class: poll test visits, taken branches (deliveries) and the model
    cycles of both instructions. Call after set_loops."""
    polls = defaultdict(lambda: Counter())
    for pc in prog.polls:
        if n.get(pc):
            c = polls[prog.cls[pc]]
            c["cycles"] += model_cycles(prog.feat[pc], n[pc], taken[pc], coef)
            if prog.mn[pc] == POLL_TEST:
                c["tests"] += n[pc]
            else:
                c["taken"] += taken[pc]
    return {k: dict(v) for k, v in polls.items()}


def report(prog: Program, n: Counter, taken: Counter, coef: dict, gen: Path) -> dict:
    prog.set_loops(taken)
    text, _ = L.static_counts(gen)
    classes = defaultdict(lambda: Counter())
    labels = defaultdict(lambda: Counter())
    ops = defaultdict(lambda: Counter())
    runtime = Counter()
    for pc, k in n.items():
        f = prog.feat[pc]
        c = classes[prog.cls[pc]]
        cyc = model_cycles(f, k, taken[pc], coef)
        c["cycles"] += cyc
        for i, name in enumerate(FEATURES):
            c[name] += (taken[pc] if (name == "loop_taken") == bool(f[2]) else 0) \
                if "taken" in name else f[i] * k
        if prog.cls[pc] in ("generated", "walk"):
            op = prog.mn[pc][0] + (" #8" if prog.mn[pc][1].startswith("#8,") else "")
            ops[op]["execs"] += k
            ops[op]["cycles"] += cyc
            ops[op]["bytes"] += (f[1] + f[2]) * k
            lab = prog.symbol(pc)
            labels[lab]["cycles"] += cyc
            labels[lab]["bytes"] += (f[1] + f[2]) * k
            labels[lab]["reads"] += f[3] * k
            labels[lab]["writes"] += f[4] * k
            labels[lab]["taken"] += taken[pc]
            if pc == prog.by_name.get(lab):
                labels[lab]["execs"] += k
        elif prog.cls[pc] == "runtime":     # per runtime symbol (natives, helpers)
            runtime[prog.symbol(pc)] += cyc
    forms = defaultdict(lambda: Counter())
    for lab, c in labels.items():
        t = text.get(lab)
        form = L.form(t) if t else ("walk" if "walk" in lab else "?")
        forms[form]["cycles"] += c["cycles"]
        forms[form]["execs"] += c["execs"]
        forms[form]["bytes"] += c["bytes"]
    guest = sum(c["execs"] for lab, c in labels.items() if lab in text)
    return {"classes": {k: dict(v) for k, v in classes.items()},
            "labels": {k: dict(v) for k, v in labels.items()},
            "runtime": dict(runtime),
            "forms": {k: dict(v) for k, v in forms.items()},
            "ops": {k: dict(v) for k, v in ops.items()},
            "polls": poll_counts(prog, n, taken, coef),
            "guest_instructions": guest,
            "instruction_counts": instruction_counts(prog, n),
            "taken_counts": taken_counts(prog, taken)}


def static_size(prog: Program) -> dict:
    out = Counter()
    for a, s in prog.size.items():
        out[prog.cls[a]] += s
    return dict(out)


def summary(res: dict) -> str:
    cl = res["classes"]
    tot = sum(c["cycles"] for c in cl.values())
    g = res["guest_instructions"]
    gen = cl.get("generated", {}).get("cycles", 0) + cl.get("walk", {}).get("cycles", 0)
    lines = [f"{res['meta']['milestone']}: model cycles {tot:,.0f}; generated+walk {gen:,.0f} "
             f"({gen / max(g, 1):.3f} per guest instruction, {g:,} guest instructions)"]
    for k in ("generated", "walk", "runtime", "platform"):
        c = cl.get(k, {})
        if c:
            lines.append(f"  {k:9} cycles {c['cycles']:>14,.0f}  insns {c['insns']:>12,}  bytes "
                         f"{c['bytes'] + c['loop_bytes']:>13,} (loop {c['loop_bytes']:,})  reads "
                         f"{c['reads']:>11,}  writes {c['writes']:>11,}  taken {c['taken']:>11,}")
    for k, c in sorted(res.get("polls", {}).items()):
        lines.append(f"  poll tests ({k}): {c['tests']:,} visits, {c['taken']:,} taken, model cycles "
                     f"{c['cycles']:,.0f} ({100 * c['cycles'] / tot:.2f}% of the total)")
    lines.append("  static bytes: " + ", ".join(f"{k} {v:,}" for k, v in sorted(res["static"].items())))
    return "\n".join(lines)


def compare(a: dict, b: dict, top: int = 25) -> str:
    def tot(r, keys=("generated", "walk", "runtime")):
        return sum(r["classes"].get(k, {}).get("cycles", 0) for k in keys)
    out = []
    ta, tb = tot(a), tot(b)
    out.append(f"model cycles (generated+walk+runtime) {ta:,.0f} -> {tb:,.0f}: "
               f"{tb - ta:+,.0f} ({100 * (tb - ta) / ta:+.4f}%)")
    for k in ("generated", "walk", "runtime"):
        ca, cb = a["classes"].get(k, {}), b["classes"].get(k, {})
        d = {f: cb.get(f, 0) - ca.get(f, 0) for f in ("cycles", "bytes", "loop_bytes", "reads",
                                                         "writes", "taken", "insns")}
        out.append(f"  {k:9} " + "  ".join(f"{f} {v:+,.0f}" for f, v in d.items()))
    sa, sb = a["static"], b["static"]
    out.append("  static bytes " + ", ".join(f"{k} {sb.get(k, 0) - sa.get(k, 0):+,}"
                                              for k in sorted(set(sa) | set(sb))))
    if a["guest_instructions"] != b["guest_instructions"]:
        out.append(f"  WARNING guest instructions {a['guest_instructions']:,} vs "
                   f"{b['guest_instructions']:,}: not the same guest work")
    fa, fb = a["forms"], b["forms"]
    deltas = sorted(((fb.get(f, {}).get("cycles", 0) - fa.get(f, {}).get("cycles", 0), f)
                     for f in set(fa) | set(fb)), key=lambda x: abs(x[0]), reverse=True)
    out.append(f"  x86 forms by |delta cycles| (top {top}):")
    for d, f in deltas[:top]:
        out.append(f"    {d:+14,.0f}  {f}")
    return "\n".join(out)


# --- the doubling plant -------------------------------------------------------

def plant(gen: Path, label: str, nops: int) -> None:
    """`nops` flag-neutral NOPs at the start of a generated guest label, in place."""
    for s in gen.glob("*.s"):
        text = s.read_text()
        head = re.search(rf"^{re.escape(label)}:[^\n]*\n", text, flags=re.M)
        if head:
            s.write_text(text[:head.end()] + "\tnop\n" * nops + text[head.end():])
            return
    raise SystemExit(f"plant: no label {label} in {gen}")


def plant_check(base_json: Path, objdump: str, label: str, nops: int) -> int:
    """`nops` NOPs (2 bytes, no flags) at the start of one generated guest label in the
    image the base ran: the meter must see exactly `nops` more instructions and 2*`nops`
    more bytes per execution of the label, and the model move by their cost, in a run
    whose lockstep check passes. The label should first run after the milestone's save,
    so the planted image may resume."""
    import shutil
    base = json.loads(base_json.read_text())
    ran = REPO / base["meta"]["elf"]
    work = REPO / "tmp/meter-plant"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(ran.parent / "gen", work / "gen")
    plant(work / "gen", label, nops)
    subprocess.run([VASM, "-quiet", "-m68020", "-Felf", "-x", "-nowarn=62", "-DXWING_SYNC=1",
                    "-o", str(work / "program.o"), "program.s"], cwd=work / "gen", check=True)
    # tests/rep_replay.py host_image's link, with the planted program
    host = REPO / "build/host"
    objs = [host / (c.stem + ".o") for c in sorted((REPO / "src/runtime").glob("*.c"))]
    objs += [host / o for o in ("host_s.o", "host.o", "rt_entry.o")]
    objs += [work / "program.o", ran.parent / "rep.o"]
    elf = work / "xwing.elf"
    subprocess.run([CROSS + "ld", "-Ttext=0x10000", "-e", "_start", f"-Map={work / 'xwing.map'}",
                    "-o", str(elf)] + [str(o) for o in objs], check=True)
    prog = Program(elf, objdump, (host / "host.o", host / "host_s.o"))
    blocks, taken_blocks, meta, _ = run(base["meta"]["milestone"], 40000, elf)
    meta.pop("into")
    n, taken = expand(prog, blocks, taken_blocks)
    coef = load_model()
    res = report(prog, n, taken, coef, work / "gen")
    execs = base["labels"].get(label, {}).get("execs", 0)
    g = lambda r, f: sum(r["classes"].get(k, {}).get(f, 0) for k in ("generated", "walk"))
    nop = lambda r, f: r["ops"].get("nop", {}).get(f, 0)
    d_insns = g(res, "insns") - g(base, "insns")
    d_nops, d_bytes, d_cyc = (nop(res, f) - nop(base, f) for f in ("execs", "bytes", "cycles"))
    d_label = res["labels"].get(label, {}).get("cycles", 0) - base["labels"].get(label, {}).get("cycles", 0)
    want = nops * execs
    lo, hi = (want * (coef["insns"] + 2 * coef[k]) for k in sorted(
        ("bytes", "loop_bytes"), key=lambda k: coef[k]))
    ok = execs > 0 and d_insns == want and d_nops == want and d_bytes == 2 * want and \
        lo <= d_cyc <= hi and d_label >= d_cyc
    total = lambda r: sum(c.get("cycles", 0) for c in r["classes"].values())
    print(f"plant: {nops} NOPs at {label}, executed {execs:,} times; instructions {d_insns:+,} "
          f"(want {want:+,}), NOP bytes {d_bytes:+,} (want {2 * want:+,}), their model cycles "
          f"{d_cyc:+,.0f} (want {lo:,.0f}..{hi:,.0f}), the label's {d_label:+,.0f}; window "
          f"{total(base):,.0f} -> {total(res):,.0f}: {'ok' if ok else 'FAIL'}")
    shutil.rmtree(work)
    return 0 if ok else 1


# --- calibration -----------------------------------------------------------------

def capture_counts(prog: Program, capture: Path):
    """Per-PC cycles, executions and taken transfers of an FS-UAE capture."""
    prof = P.decode(capture)
    addrs = prog.addrs
    sizes = np.array([prog.size[int(a)] for a in addrs], dtype=np.int64)
    cyc, cnt, tak = (np.zeros(len(addrs)) for _ in range(3))
    branch_targets = np.array([t if (t := prog.branch_target(int(a))) is not None else -1
                               for a in addrs], dtype=np.int64)
    previous = None
    for _, _, pcs, cost in prof["fields"]:
        idx = np.searchsorted(addrs, pcs)
        idx = np.clip(idx, 0, len(addrs) - 1)
        ok = addrs[idx] == pcs
        np.add.at(cyc, idx[ok], cost[ok])
        np.add.at(cnt, idx[ok], 1)
        # Fields split a continuous PC stream. A direct branch is taken only
        # when its decoded target follows it, not when an interrupt intervenes.
        seq = np.concatenate(([previous], pcs)) if previous is not None else pcs
        ix = np.clip(np.searchsorted(addrs, seq), 0, len(addrs) - 1)
        valid = addrs[ix] == seq
        src, dst = ix[:-1], seq[1:]
        fall = seq[:-1] + sizes[src]
        bt = branch_targets[src]
        t = valid[:-1] & valid[1:] & (dst != fall) & ((bt < 0) | (dst == bt))
        np.add.at(tak, src[t], 1)
        if len(pcs):
            previous = pcs[-1]
    return cyc, cnt, tak, len(prof["fields"])


def fit(X: np.ndarray, y: np.ndarray, names: list[str]) -> dict:
    """Least squares with non-negative weights (drop a negative weight, refit)."""
    keep = list(range(X.shape[1]))
    while True:
        w, *_ = np.linalg.lstsq(X[:, keep], y, rcond=None)
        if (w >= 0).all():
            break
        keep.pop(int(np.argmin(w)))
    coef = {n: 0.0 for n in names}
    for k, v in zip(keep, w):
        coef[names[k]] = float(v)
    return coef


def calibrate(capture: Path, elf: Path, objdump: str, write: bool) -> None:
    prog = Program(elf, objdump)
    cyc, cnt, tak, fields = capture_counts(prog, capture)
    prog.set_loops(dict(zip(prog.addrs.tolist(), tak)))
    rows, y = [], []
    for i, a in enumerate(prog.addrs.tolist()):
        if cnt[i] and prog.cls[a] in ("generated", "walk"):
            f = prog.feat[a]
            row = [cnt[i] * value for value in cost_features(f)]
            row[5], row[6] = (0, tak[i]) if f[2] else (tak[i], 0)
            rows.append(row)
            y.append(cyc[i])
    X, y = np.array(rows), np.array(y)
    coef = fit(X, y, list(FEATURES))
    # An absent instruction class supplies no calibration evidence. Preserve
    # its standalone coefficient instead of replacing it with a fitted zero.
    if not X[:, FEATURES.index("long_arith")].any():
        coef["long_arith"] = load_model()["long_arith"]
    w = np.array([coef[k] for k in FEATURES])
    pred = X @ w
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    total, model = y.sum(), pred.sum()
    print(f"capture {capture.name}: {fields} fields, {len(y):,} generated PCs, "
          f"{int(cnt.sum()):,} executions")
    print("weights: " + ", ".join(f"{k} {v:.3f}" for k, v in coef.items()))
    print(f"R^2 {r2:.3f}; generated code measured {total:,.0f}, model {model:,.0f} "
          f"({100 * (model - total) / total:+.2f}%)")
    for cls in ("runtime",):
        m = sum(model_cycles(prog.feat[a], cnt[i], tak[i], coef)
                for i, a in enumerate(prog.addrs.tolist()) if cnt[i] and prog.cls[a] == cls)
        t = sum(cyc[i] for i, a in enumerate(prog.addrs.tolist()) if cnt[i] and prog.cls[a] == cls)
        print(f"{cls} (not fitted): measured {t:,.0f}, model {m:,.0f}")
    if write:
        metadata = json.loads(MODEL.read_text())
        if X[:, FEATURES.index("long_arith")].any():
            metadata.pop("long_arithmetic_probe", None)
        MODEL.write_text(json.dumps({**metadata, "coef": coef, "r2": round(float(r2), 4),
                                     "capture": {"fields": fields, "pcs": len(y),
                                                 "measured": int(total), "model": int(model)}},
                                    indent=1) + "\n")
        print(f"wrote {MODEL.relative_to(REPO)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("milestone", nargs="?", default="m12-training-flight")
    ap.add_argument("--no-resume", action="store_true", help="run from boot, not from a save")
    ap.add_argument("--out", type=Path, help="write the full result as JSON")
    ap.add_argument("--timeout", type=int, default=40000)
    ap.add_argument("--objdump", default=OBJDUMP)
    ap.add_argument("--calibrate", nargs=2, type=Path, metavar=("CAPTURE", "ELF"))
    ap.add_argument("--write", action="store_true", help="with --calibrate: write cost_model.json")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"))
    ap.add_argument("--plant-check", type=Path, metavar="BASE_JSON",
                    help="meter the base's image with --nops NOPs at --label against BASE_JSON")
    ap.add_argument("--label", default="FLT_22E3E", help="with --plant-check: the planted label")
    ap.add_argument("--nops", type=int, default=8, help="with --plant-check: NOPs planted")
    args = ap.parse_args(argv)
    if args.compare:
        a, b = (json.loads(p.read_text()) for p in args.compare)
        print(compare(a, b))
        return 0
    if args.plant_check:
        return plant_check(args.plant_check, args.objdump, args.label, args.nops)
    if args.calibrate:
        calibrate(*args.calibrate, args.objdump, args.write)
        return 0
    host = REPO / "build/host"
    blocks, taken_blocks, meta, elf = run(args.milestone, args.timeout, resume=not args.no_resume)
    prog = Program(elf, args.objdump, (host / "host.o", host / "host_s.o"))
    n, taken = expand(prog, blocks, taken_blocks)
    res = report(prog, n, taken, load_model(), elf.parent / "gen")
    res["targets"] = targets(prog, meta.pop("into"))
    res["meta"] = meta
    res["static"] = static_size(prog)
    print(summary(res))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
