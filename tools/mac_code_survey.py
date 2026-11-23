#!/usr/bin/env python3
"""P8 step 4: survey the Macintosh demo's 68k code for counterparts of DOS routines.

Reads the demo's resource fork (tmp/runtime-data, `make extract-original-data`) and the
translator's flight IR (build/gen/FLIGHT.OVL.ir), and writes tmp/p8/mac/survey.txt.
Nothing it writes is committed: it prints counts, offsets and scores only.

The Mac side: every CODE segment walked by recursive descent (AmigaXDev's
`amigaxdev.mac.m68k_sweep.walk`) from its jump-table entries and its LINK A6 sites, with
the walk's coverage reported. A function starts at a root or at a BSR target and runs to
the next start. For each function: instructions, FPU instructions, 68020-only
instructions, multiplies, divides, A-line traps, and its tokens: the displacements it
uses off an address register other than A5, A6 and A7 (structure fields) and its
immediates.

The DOS side: a function of FLIGHT.OVL starts at a CALL or CALLF target, or at a profiled
entry given with --hot, and runs to the next start. Its tokens are its [reg+disp]
displacements off BX, SI and DI and its immediates.

The match: IDF-weighted Jaccard similarity of token sets. The control is the best score
the same DOS function reaches against the Mac functions with each token replaced by a
random Mac token of about the same rarity (within 25 places in document-frequency order;
--seeds runs); a match counts as found only if its score clears every control score.

Usage: tools/mac_code_survey.py [--hot FLIGHT.OVL+22541,...] [--top 3] [--seeds 20]
"""
import argparse, math, os, random, re, struct, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.environ.get("AMIGA_PYLIB",
                                  str(Path.home() / ".local/share/amiga/pylib")))
from amigaxdev.mac.resource_fork import read_resource_fork    # noqa: E402
from amigaxdev.mac import m68k_sweep as S                     # noqa: E402

RSRC = Path("tmp/runtime-data/X-Wing Demo ƒ/X-Wing.rsrc")
IR = Path("build/gen/FLIGHT.OVL.ir")
FPU = re.compile(r"^f[a-z]")


def num(s):
    s = s.lstrip("#")
    neg = s.startswith("-")
    s = s.lstrip("-")
    v = int(s[1:], 16) if s.startswith("$") else int(s, 16) if s.startswith("0x") else int(s)
    return -v if neg else v


# ------------------------------------------------------------------ Mac side

MAC_DISP = re.compile(r"(-?\$[0-9a-f]+)\((a[0-4])[,)]")
MAC_IMM = re.compile(r"#(-?\$[0-9a-f]+|-?\d+)")


def mac_functions():
    res = read_resource_fork(RSRC)
    code = {r.rid: (r.name, r.body) for r in res if r.kind == b"CODE"}
    entries, _, _ = S.jump_table(code[0][1])
    per = defaultdict(set)
    for seg, off in entries:
        per[seg].add(off)
    funcs, coverage = [], []
    global fpu_forms
    fpu_forms = Counter()
    for seg in sorted(code):
        if seg == 0:
            continue
        name, body = code[seg]
        c = body[4:]
        roots = set(per[seg])
        roots |= {o for o in range(0, len(c) - 1, 2) if c[o:o + 2] == b"\x4e\x56"}
        _, seen, blind = S.walk(c, sorted(roots), name)
        # starts: roots that the walk reached, and BSR targets
        starts = {r for r in roots if r in seen}
        insns = {}
        pc_list = sorted(o for o in seen if o % 2 == 0)
        inside = set()                       # extension words of a decoded instruction
        for pc in pc_list:
            if pc in insns or pc in inside:
                continue
            w = struct.unpack_from(">H", c, pc)[0]
            if 0xA000 <= w <= 0xAFFF:
                insns[pc] = ("_trap", f"{w:04x}", 2)
                continue
            i = next(iter(S.md40.disasm(c[pc:pc + 16], pc, count=1)), None)
            if i is None or i.size == 0 or any(pc + k not in seen for k in range(i.size)):
                continue
            insns[pc] = (i.mnemonic, i.op_str, i.size)
            inside.update(range(pc + 2, pc + i.size, 2))
            m = i.mnemonic.split(".")[0]
            if m == "bsr":
                t = S.target_of(i)
                if t is not None:
                    starts.add(t)
        coverage.append((seg, name, len(c), len(seen), blind, len(roots)))
        st = sorted(starts)
        for k, s in enumerate(st):
            e = st[k + 1] if k + 1 < len(st) else len(c)
            f = dict(seg=seg, seg_name=name, off=s, size=e - s, n=0, fpu=0, c020=0,
                     mul=0, div=0, traps=0, shifts=0, tokens=Counter())
            for pc in range(s, e, 2):
                if pc not in insns:
                    continue
                mn, ops, _ = insns[pc]
                f["n"] += 1
                if mn == "_trap":
                    f["traps"] += 1
                    continue
                m = mn.split(".")[0]
                if FPU.match(m):
                    f["fpu"] += 1
                    fpu_forms[(seg, mn)] += 1
                if m in ("muls", "mulu"):
                    f["mul"] += 1
                if m in ("divs", "divu", "divsl", "divul"):
                    f["div"] += 1
                if m in ("asr", "asl", "lsr", "lsl"):
                    f["shifts"] += 1
                if mn in S.NOT_68000 or m in ("extb", "bfextu", "bfexts", "bfins") or \
                        mn in ("muls.l", "mulu.l", "divs.l", "divu.l"):
                    f["c020"] += 1
                for d, _ in MAC_DISP.findall(ops):
                    v = num(d)
                    if 0 < v < 0x400:
                        f["tokens"]["d%x" % v] += 1
                for v in MAC_IMM.findall(ops):
                    v = num(v)
                    if m in ("moveq", "addq", "subq") and -8 <= v <= 8:
                        continue
                    f["tokens"]["i%x" % (v & 0xffff)] += 1
            if f["n"]:
                funcs.append(f)
    return funcs, coverage


# ------------------------------------------------------------------ DOS side

DOS_LINE = re.compile(r"^FLIGHT\.OVL\+([0-9A-F]+) ([0-9A-F]+):([0-9A-F]+) [0-9a-f]+ +(\S+)\s*(.*)$")
DOS_DISP = re.compile(r"\[(?:bx|si|di)(?:\+(?:si|di))?\+(0x[0-9a-f]+)\]")
DOS_IMM = re.compile(r"(?:^|, )(0x[0-9a-f]+|\d+)$")


def dos_functions(hot):
    ins, link = [], {}
    for line in IR.open():
        m = DOS_LINE.match(line)
        if m:
            off = int(m.group(1), 16)
            link[(int(m.group(2), 16), int(m.group(3), 16))] = off
            ins.append((off, int(m.group(2), 16), m.group(4), m.group(5).strip()))
    ins.sort()
    starts = set(hot)
    for off, seg, mn, ops in ins:
        if mn == "call":
            t = re.match(r"0x([0-9a-f]+)$", ops)
            if t and (seg, int(t.group(1), 16)) in link:
                starts.add(link[(seg, int(t.group(1), 16))])
        elif mn == "callf":
            t = re.match(r"0x([0-9a-f]+):0x([0-9a-f]+)$", ops)
            if t and (int(t.group(1), 16), int(t.group(2), 16)) in link:
                starts.add(link[(int(t.group(1), 16), int(t.group(2), 16))])
    st = sorted(starts)
    funcs, k = {}, 0
    for j, s in enumerate(st):
        e = st[j + 1] if j + 1 < len(st) else 1 << 30
        f = dict(off=s, size=0, n=0, mul=0, div=0, shifts=0, tokens=Counter())
        while k < len(ins) and ins[k][0] < s:
            k += 1
        while k < len(ins) and ins[k][0] < e:
            off, seg, mn, ops = ins[k]
            f["n"] += 1
            f["size"] = off - s
            if mn in ("mul", "imul"):
                f["mul"] += 1
            if mn in ("div", "idiv"):
                f["div"] += 1
            if mn in ("shl", "shr", "sar", "sal"):
                f["shifts"] += 1
            for d in DOS_DISP.findall(ops):
                v = int(d, 16)
                if 0 < v < 0x400:
                    f["tokens"]["d%x" % v] += 1
            im = DOS_IMM.search(ops)
            if im and "[" not in ops.split(",")[-1] and mn not in ("call", "callf", "jmp") \
                    and not mn.startswith("j") and mn not in ("loop", "int", "ret", "retf"):
                v = num(im.group(1)) & 0xffff
                if not (mn in ("add", "sub", "inc", "dec") and v <= 8) and \
                        not (mn in ("shl", "shr", "sar", "rcl", "rcr", "rol", "ror") and v <= 8):
                    f["tokens"]["i%x" % v] += 1
            k += 1
        funcs[s] = f
    return funcs


# ------------------------------------------------------------------- match

def score(a, b, idf):
    inter = sum(idf[t] for t in a.keys() & b.keys())
    union = sum(idf[t] for t in a.keys() | b.keys())
    return inter / union if union else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hot", default="")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--out", default="tmp/p8/mac/survey.txt")
    a = ap.parse_args()
    hot = [int(h.split("+")[1], 16) for h in a.hot.split(",") if h]
    mac, cov = mac_functions()
    dos = dos_functions(hot)
    df = Counter()
    for f in mac:
        df.update(f["tokens"].keys())
    for f in dos.values():
        df.update(f["tokens"].keys())
    N = len(mac) + len(dos)
    idf = defaultdict(lambda: math.log(N), {t: math.log(N / c) for t, c in df.items()})
    # the control's vocabulary in document-frequency order: a token is replaced by one of
    # about the same rarity, so the control keeps the function's IDF profile
    vocab = sorted({t for f in mac for t in f["tokens"]}, key=lambda t: (-df[t], t))
    rank = {t: k for k, t in enumerate(vocab)}
    out = []
    p = out.append
    p("## Mac CODE coverage (recursive descent from jump-table entries and LINK A6 sites)")
    for seg, name, size, seen, blind, roots in cov:
        p(f"CODE {seg} {name!r}: {size} B, roots {roots}, reached {seen} B "
          f"({100 * seen / size:.1f}%), unfollowable jumps {blind}")
    tot = Counter()
    for f in mac:
        for k in ("n", "fpu", "c020", "mul", "div", "traps"):
            tot[(f["seg"], k)] += f[k]
    p("\n## Mac functions per segment: functions, instructions, FPU, 68020-only, mul, div, traps;"
      " functions with any FPU instruction")
    for seg, name, *_ in cov:
        fs = [f for f in mac if f["seg"] == seg]
        p(f"CODE {seg} {name!r}: {len(fs)} functions, {tot[(seg, 'n')]} insns, "
          f"FPU {tot[(seg, 'fpu')]}, 68020-only {tot[(seg, 'c020')]}, mul {tot[(seg, 'mul')]}, "
          f"div {tot[(seg, 'div')]}, traps {tot[(seg, 'traps')]}; "
          f"FPU functions {sum(1 for f in fs if f['fpu'])}")
    p("FPU mnemonics per segment: " + "; ".join(
        f"{seg}:{mn} {n}" for (seg, mn), n in sorted(fpu_forms.items())))
    for seg, name, *_ in cov:
        for f in mac:
            if f["seg"] == seg and f["fpu"]:
                p(f"   FPU CODE {seg}+{f['off']:05X} {f['n']} insns, {f['fpu']} FPU")
    p("\n## DOS hot routines and their best Mac candidates (score; control max over seeds)")
    rng = random.Random(1)
    for h in hot:
        f = dos.get(h)
        if not f:
            p(f"FLIGHT.OVL+{h:05X}: not a function start")
            continue
        sc = sorted(((score(f["tokens"], m["tokens"], idf), m) for m in mac),
                    key=lambda x: -x[0])
        ctl = 0.0
        for _ in range(a.seeds):
            perm = Counter()
            for t, c in f["tokens"].items():
                r = rank.get(t, len(vocab) - 1)
                perm[vocab[min(len(vocab) - 1, max(0, r + rng.randint(-25, 25)))]] += c
            ctl = max(ctl, max(score(perm, m["tokens"], idf) for m in mac))
        p(f"FLIGHT.OVL+{h:05X}: {f['n']} insns, {f['size']} B, mul {f['mul']}, div {f['div']},"
          f" shifts {f['shifts']}, tokens {len(f['tokens'])}; control {ctl:.3f}")
        for s, m in sc[:a.top]:
            shared = sorted(f["tokens"].keys() & m["tokens"].keys(), key=lambda t: (-idf[t], t))
            p(f"   {'FOUND ' if s > ctl else '      '}{s:.3f} CODE {m['seg']}+{m['off']:05X} "
              f"{m['n']} insns, mul {m['mul']}, div {m['div']}, fpu {m['fpu']}; shared "
              f"{len(shared)}: {' '.join(shared[:12])}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
