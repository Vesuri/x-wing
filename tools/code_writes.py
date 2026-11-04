#!/usr/bin/env python3
"""Classify every CPU write into a module image (D16 evidence).

Copied from Secret Weapons of the Luftwaffe's tools/code_writes.py (commit pinned in
manifest/references.tsv) and adapted: X-Wing's overlay manager applies the fixups.
Writes come from the trace corpus (snapshot writes.csv + code-writes.csv,
xwing_model.cpu_writes); byte classes from tools/sweep.py (tmp/sweep/*.cls).
Classes per written byte:
  relocation     the overlay manager's fixup add (root +043AD), checked by linear address:
                 each byte must be in a fixup word of a segment (load segment + its link
                 segment). The tracer maps whole paragraphs read, so the last, partly read
                 paragraph of a segment keeps its previous owner.
  fill           the manager's zero fill (root +0454E) of a segment's memory beyond its
                 read size; checked by linear address (the paragraphs' module mapping is
                 that of their previous owner), not attributed to a module
  dos            DOS/BIOS service (writer in the F000 callback area)
  self-modified  byte inside annotations/self-modifying.csv
  data           byte outside any decoded instruction (code-segment data)
A write into decoded code outside the annotated regions fails.
Output: tmp/sweep/code-writes.csv (module, class, writer, first, last,
bytes; runs of consecutive offsets) and a summary. Exit 1 if a relocation
write is not on a fixup word, a writer is unknown, or code is written
outside the annotated regions.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import defaultdict

import xwing_model as M
from sweep import smc_regions

FIXUP_WRITER = "XWING.EXE+043AD"  # the manager's fixup add (root image 43ADh)
CLASS_OF = {0: "data", 1: "static-code", 2: "static-code", 3: "self-modified", 4: "self-modified",
            5: "data"}


def fixup_words(data: bytes, s: M.Segment) -> list[tuple[int, int]]:
    """(link segment, offset) of a segment's fixup words."""
    return [struct.unpack_from("<HH", data, s.pos + 4 * k)[::-1] for k in range(s.nfix)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', default='latest', help="ref/dosbox/runs glob for the trace corpus, or 'latest' (newest milestone set)")
    args = ap.parse_args()
    mods = M.load_modules()
    traces = M.runs(args.runs)
    writes = M.cpu_writes(traces, skip=(M.FILL_WRITER, FIXUP_WRITER))
    smc = smc_regions()
    bad = []
    runs: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for mod, offs in writes.items():
        if not (M.REPO / f"tmp/sweep/{mod}.cls").exists():
            continue
        m = mods[mod]
        cls = (M.REPO / f"tmp/sweep/{mod}.cls").read_bytes()
        fix = {b for f in m.fixups for b in (f, f + 1)}
        for off, writers in offs.items():
            for w in writers:
                if w == FIXUP_WRITER:
                    kind = "relocation"
                    if off not in fix:
                        bad.append(f"{mod}+{off:05X}: fixup applier off a fixup word")
                elif w.startswith("-+F"):
                    kind = "dos"
                elif w.startswith("-"):
                    kind = "unknown"
                    bad.append(f"{mod}+{off:05X}: writer {w} outside any module")
                elif any(lo <= off <= hi for lo, hi in smc.get(mod, ())):
                    kind = "self-modified"
                else:
                    kind = CLASS_OF[cls[off]] if off < len(cls) else "data"
                    if kind != "data":
                        bad.append(f"{mod}+{off:05X}: {w} writes code outside "
                                   "annotations/self-modifying.csv")
                runs[(mod, kind, w)].append(off)
    words: dict[int, set[int]] = {}
    relocs = M.writes_by(traces, FIXUP_WRITER)
    for t, load, a in relocs:
        if load not in words:
            words[load] = {(load + fseg) * 16 + off + k for s in M.segments(mods[M.ROOT].data)
                           for fseg, off in fixup_words(mods[s.file].data, s) for k in (0, 1)}
        if a not in words[load]:
            bad.append(f"{t.parent.name}: fixup applier at {a:05X}, not a segment fixup word")
    print(f"{'(linear)':13} {'relocation':13} {len(relocs):6}  {FIXUP_WRITER}")
    fills = M.writes_by(traces, M.FILL_WRITER)
    ranges = {}
    for t, load, a in fills:
        r = ranges.setdefault(load, M.fill_ranges(load))
        if not any(lo <= a < hi for lo, hi in r):
            bad.append(f"{t.parent.name}: fill at {a:05X} outside every segment's fill range")
    print(f"{'(linear)':13} {'fill':13} {len(fills):6}  {M.FILL_WRITER}")
    rows = []
    for (mod, kind, w), offs in sorted(runs.items()):
        offs.sort()
        start = prev = offs[0]
        for o in offs[1:] + [None]:
            if o is not None and o == prev + 1:
                prev = o
                continue
            rows.append([mod, kind, w, f"0x{start:05x}", f"0x{prev:05x}", prev - start + 1])
            if o is not None:
                start = prev = o
    with (M.REPO / "tmp/sweep/code-writes.csv").open("w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["module", "class", "writer", "first", "last", "bytes"])
        cw.writerows(rows)
    total = defaultdict(int)
    writers = defaultdict(set)
    for mod, kind, w, _, _, n in rows:
        total[(mod, kind)] += n
        writers[(mod, kind)].add(w)
    for (mod, kind), n in sorted(total.items()):
        ws = sorted(writers[(mod, kind)])
        shown = " ".join(ws[:6]) + (f" (+{len(ws) - 6})" if len(ws) > 6 else "")
        print(f"{mod:13} {kind:13} {n:6}  {shown}")
    for b in bad[:20]:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
