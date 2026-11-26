#!/usr/bin/env python3
"""The generated code's cycles by role, from a cost meter result (docs/perf-method.md).

  overhead_census.py METER.json [--top N] [--role ROLE] [--match REGEX ...] [--json OUT]

Input: a tools/cost_meter.py result (`instruction_counts`: every executed generated 68k
instruction with its label, offset, mnemonic, operands and executions; `labels`: each
label's model cycles, bytes, reads, writes and taken transfers). Each instruction gets
one role from the shapes the translator emits (translator/lower.py):

- address: the reversed guest address built in d7 for a `(...,d7.w)` operand or `lea`
  (`move.w #$7fff,d7` / `move.w REG,d7` / `eori.w` / `sub.w` / `add.w` / `addq`/`subq`
  on d7, and a wrap check `cmp.w #n,d7` with its branch between them);
- ems check: the EMS guard's `cmpi.w #$d001,SEG(a6)` and its branch, the CCR saved
  around it, and the out-of-line `_ex` path (the inline cache hit and the miss call);
  before a video store through ES, the guard's `cmpi.w #$9001,5(a6)` and its branch;
- video check / video mark: lower.vram_segment's test of the segment against the
  frame, and the mark's setup and call when the window meets it; behind the ES guard
  (lower.ems_guard's marks), its out-of-line `cmpi.w #$afa0,5(a6)` and branch, and the
  mark from `move.w 5(a6),d7; sub.w #$a000,d7` to its call;
- return check: `cmp #ip,d7` / `cmp.l #cs:ip,d7` and its branch to a mismatch stub;
- flags: reads and writes of the guest flag bytes (G_FL..G_TF) and CCR moves that are
  not an EMS guard's;
- poll (sync only): `tst.b G_IRQ(a6)` and its branch, which the production image does
  not have (cost_meter.py counts them apart: `polls`);
- work: everything else, the guest's own operations.

Cycles: each label's exact model cycles are shared among its instructions in proportion
to the cost model's weights (tools/cost_model.json) applied to each instruction's own
features: one instruction, its bytes (from the offsets, the last from the label's bytes),
a read for a memory source operand, a write for a memory destination, and its taken
transfers (`taken_counts`). Per role the totals are therefore DERIVED, not measured;
per label they equal the meter's.

--match REGEX (repeatable): also the executions and cycles of the generated
instructions whose `mnemonic operands` text matches, each with the instruction
that follows it (`+next`, e.g. a test's branch), for pricing a lowering's piece.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUEST = re.compile(r"^(R|FE|FLT|AD|AW)_[0-9A-F]{5}")
FLAG_SLOTS = {"10(a6)", "11(a6)", "12(a6)", "13(a6)", "14(a6)", "15(a6)"}
SEG_SLOTS = {"1(a6)", "3(a6)", "5(a6)"}
D001 = "#-12287"            # $d001 as the disassembler prints the word
VRAM_LO = "#-28671"         # $a000-$0fff, lower.vram_segment; $9001, lower.ems_guard
VRAM_HI = "#-20576"         # $afa0, lower.ems_guard
A000 = "#-24576"            # $a000
BRANCH = re.compile(r"^b(?!tst|chg|clr|set)[a-z]{2,3}(\.[bsw])?$")
D7_WRITERS = ("move.w", "move.l", "moveq", "sub.w", "add.w", "eori.w", "addq.w", "subq.w",
              "addq.l", "subq.l", "neg.w", "ext.l", "addi.w", "subi.w")


def dest(operands: str) -> str:
    depth, last = 0, -1
    for i, ch in enumerate(operands):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            last = i
    return operands[last + 1:] if last >= 0 else operands


def source(operands: str) -> str:
    d = dest(operands)
    return operands[:len(operands) - len(d) - 1] if len(d) < len(operands) else ""


def is_mem(o: str) -> bool:
    return bool(o) and ("(" in o or re.match(r"^[0-9a-f]+ <", o) is not None)


def classify(rows: list[list]) -> list[str]:
    """Roles for one label's instructions, in offset order."""
    roles = ["work"] * len(rows)
    ops = [r[2] for r in rows]
    opr = [r[3] for r in rows]
    for k in range(len(rows)):
        if ops[k] == "tst.b" and opr[k] == "9(a6)":
            roles[k] = "poll (sync only)"
            if k + 1 < len(rows) and BRANCH.match(ops[k + 1]):
                roles[k + 1] = "poll (sync only)"
        elif ops[k] == "cmpi.w" and opr[k].startswith((D001 + ",", VRAM_LO + ",")) and \
                dest(opr[k]) in SEG_SLOTS:
            roles[k] = "ems check"
            if k + 1 < len(rows) and BRANCH.match(ops[k + 1]):
                roles[k + 1] = "ems check"
            if k and ops[k - 1] == "move.w" and opr[k - 1] == "ccr,-(sp)":
                roles[k - 1] = "ems check"
        elif ops[k] == "sub.w" and opr[k] == VRAM_LO + ",d7" and k and \
                ops[k - 1] == "move.w" and source(opr[k - 1]) in SEG_SLOTS:
            roles[k - 1] = roles[k] = "video check"
            j = k + 1
            for _ in range(2):          # cmp.w #$1f9e,d7; bhi.s skip
                if j < len(rows):
                    roles[j] = "video check"
                    j += 1
            # the mark's setup up to its call, when the window met the frame (the skip
            # jumps past it: the next executed row is then the guest's own work)
            if j < len(rows) and not (ops[j] == "sub.w" and opr[j] == "#4095,d7"):
                continue
            while j < len(rows):
                roles[j] = "video mark"
                if ops[j] == "jsr":
                    break
                j += 1
        elif ops[k] == "cmpi.w" and opr[k] == VRAM_HI + ",5(a6)":
            roles[k] = "video check"
            if k + 1 < len(rows) and BRANCH.match(ops[k + 1]):
                roles[k + 1] = "video check"
        elif ops[k] == "sub.w" and opr[k] == A000 + ",d7" and k and \
                ops[k - 1] == "move.w" and source(opr[k - 1]) == "5(a6)":
            j = k - 1
            while j < len(rows):
                roles[j] = "video mark"
                if ops[j] == "jsr":
                    break
                j += 1
        elif ops[k] == "jsr" and "rt_vram_mark" in opr[k] and roles[k] == "work":
            roles[k] = "video mark"
    for k in range(len(rows)):
        if roles[k] != "work":
            continue
        if ops[k].startswith("cmp") and dest(opr[k]) == "d7" and source(opr[k]).startswith("#") and \
                k + 1 < len(rows) and BRANCH.match(ops[k + 1]) and \
                ("_rm" in opr[k + 1] or "mismatch" in opr[k + 1]):
            roles[k] = roles[k + 1] = "return check"
        elif any(s in opr[k] for s in FLAG_SLOTS) or "ccr" in opr[k] or "rt_flags" in opr[k]:
            roles[k] = "flags"
    for k in range(len(rows)):          # address chains ending in a (...,d7.w) use
        if roles[k] != "work" or "d7.w)" not in opr[k]:
            continue
        j = k - 1
        while j >= 0 and roles[j] == "work":
            if ops[j] in D7_WRITERS and dest(opr[j]) == "d7":
                roles[j] = "address"
            elif ops[j].startswith("cmp") and dest(opr[j]) == "d7" and j + 1 < k and \
                    BRANCH.match(ops[j + 1]):
                roles[j] = roles[j + 1] = "address"
            elif roles[j] == "work":
                break
            j -= 1
    return roles


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("meter", type=Path)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--role", help="also list the guest routines' labels of this role")
    ap.add_argument("--match", action="append", default=[], type=re.compile)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    d = json.loads(args.meter.read_text())
    c = json.loads((ROOT / "tools/cost_model.json").read_text())["coef"]
    W = {"insn": c["insns"], "byte": c["bytes"], "read": c["reads"], "write": c["writes"],
         "taken": c["taken"]}
    taken = {(r[0], r[1]): r[4] for r in d["taken_counts"]}
    by_label: dict[str, list] = defaultdict(list)
    for r in d["instruction_counts"]:
        if GUEST.match(r[0]):
            by_label[r[0]].append(r)
    cycles, execs = Counter(), Counter()
    per_label_role: dict[str, Counter] = defaultdict(Counter)
    matched, matched_x, matched_next = Counter(), Counter(), Counter()
    total_cycles = 0.0
    for lab, rows in by_label.items():
        rows.sort(key=lambda r: r[1])
        meta = d["labels"].get(lab)
        if not meta or not meta["execs"]:
            continue
        roles = classify(rows)
        size_total = meta["bytes"] / meta["execs"]
        est = []
        for k, r in enumerate(rows):
            nxt = rows[k + 1][1] if k + 1 < len(rows) else size_total
            size = max(2, nxt - r[1])
            s, t = source(r[3]), dest(r[3])
            reads = int(is_mem(s) and not s.startswith("#")) + \
                int(is_mem(t) and not r[2].startswith(("move", "lea", "clr", "pea")) and
                    not r[2].startswith("j") and not BRANCH.match(r[2]))
            writes = int(is_mem(t) and not r[2].startswith(("cmp", "tst", "lea", "pea")) and
                         not r[2].startswith("j") and not BRANCH.match(r[2]))
            if r[2] in ("jsr", "bsr") or (r[2] == "move.l" and t.startswith("-(sp)")) or \
                    (r[2] == "move.w" and t.startswith("-(sp)")):
                writes = max(writes, 1)
            if r[2] == "rts" or s.startswith("(sp)+"):
                reads = max(reads, 1)
            tk = taken.get((lab, r[1]), 0)
            est.append(r[4] * (W["insn"] + size * W["byte"] + reads * W["read"] +
                               writes * W["write"]) + tk * W["taken"])
        scale = meta["cycles"] / sum(est) if sum(est) else 0.0
        for k, r in enumerate(rows):
            for pat in args.match:
                if pat.search(f"{r[2]} {r[3]}"):
                    matched[pat.pattern] += est[k] * scale
                    matched_x[pat.pattern] += r[4]
                    if k + 1 < len(rows):
                        matched_next[pat.pattern] += est[k + 1] * scale
        for r, role, e in zip(rows, roles, est):
            c = e * scale
            cycles[role] += c
            execs[role] += r[4]
            per_label_role[lab][role] += c
        total_cycles += meta["cycles"]
    gen = d["classes"]["generated"]["cycles"]
    allc = sum(v["cycles"] for v in d["classes"].values())
    print(f"{args.meter.name}: {d['guest_instructions']:,} guest instructions, generated "
          f"{gen:,.0f} of {allc:,.0f} model cycles ({gen / allc:.1%})")
    print(f"labels covered: {total_cycles:,.0f} cycles ({total_cycles / gen:.1%} of generated)")
    print(f"{'role':18} {'68k execs':>12} {'model cycles':>14} {'of generated':>12} {'per guest insn':>14}")
    for role, c in cycles.most_common():
        print(f"{role:18} {execs[role]:>12,} {c:>14,.0f} {c / gen:>12.1%} "
              f"{c / d['guest_instructions']:>14.2f}")
    for pat in args.match:
        p = pat.pattern
        print(f"match {p!r}: {matched_x[p]:,} execs, {matched[p]:,.0f} cycles ({matched[p] / gen:.2%}); "
              f"+next {matched[p] + matched_next[p]:,.0f} ({(matched[p] + matched_next[p]) / gen:.2%})")
    if args.role:
        tops = sorted(per_label_role.items(), key=lambda kv: -kv[1][args.role])[:args.top]
        print(f"\nlabels by {args.role}:")
        for lab, c in tops:
            print(f"  {lab:24} {c[args.role]:>12,.0f}  ({c[args.role] / gen:.2%})")
    if args.json:
        args.json.write_text(json.dumps({"cycles": cycles, "execs": execs,
                                         "generated": gen, "all": allc}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
