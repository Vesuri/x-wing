#!/usr/bin/env python3
"""Stores to the VGA frame on the host run to a milestone (annotations/vram-ds.csv's
input, the owner decision "Video stores through DS" in docs/design.md).

Shaped as tools/ems_frame_profile.py. Runs tests/host_run.py's lockstep check with
a memory hook on the 64,000-byte frame (A0000h-AF9FFh, reversed guest RAM) and
reports generated code's stores there by the segment registers whose window holds
the byte (DS, ES, SS), the stores DS addresses by instruction label,
and every write of a value whose window meets the frame (9001h-AF9Fh, as
translator/lower.py vram_segment) into the state block's DS slot, by the label
that wrote it (generated code: a DS load; runtime: a service or return).

usage: tools/vram_ds_profile.py [--milestone m01-logo] [--bypass] [--resume] [--timeout s] [--top 40]
"""
import argparse
import bisect
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import host_run as H  # noqa: E402

FRAME, FRAME_END = 0xA0000, 0xA0000 + 64000
WINDOW = (0x9001, 0xAF9F)       # segments whose 64 KiB window meets the frame


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", default="m01-logo")
    ap.add_argument("--bypass", action="store_true")
    ap.add_argument("--resume", action="store_true", help="from the milestone's save (host_run --resume)")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    stats = dict(seg=Counter(), ds_label=Counter(), ds_load=Counter(), other=Counter())
    original_run = H.Host.run

    def run(self, script, timeout):
        names = sorted((a, n) for n, a in self.syms.items() if isinstance(a, int))
        addrs = [a for a, _ in names]
        tags = tuple(f"{t}_" for t in H.emit.TAG.values())
        lo, hi = H.TOP - (FRAME_END - 1), H.TOP - FRAME

        def where(pc):
            k = bisect.bisect_right(addrs, pc) - 1
            return names[k][1] if k >= 0 else "?"

        @H.U.MEM_CB
        def store(h, access, addr, size, value, user):
            name = where(self.r("pc"))
            if not name.startswith(tags):
                stats["other"]["runtime frame stores"] += 1
                return True
            lin = H.TOP - addr - size + 1           # lowest guest byte written
            st = self.mem(H.STATE, 6)
            segs = {"ds": int.from_bytes(st[0:2], "big"), "ss": int.from_bytes(st[2:4], "big"),
                    "es": int.from_bytes(st[4:6], "big")}
            hits = sorted(s for s, v in segs.items() if v * 16 <= lin < v * 16 + 0x10000)
            stats["seg"][" ".join(hits) or "none"] += 1
            if "ds" in hits:
                stats["ds_label"][(name, " ".join(hits))] += 1
            return True

        self.e.hook_range(H.U.HOOK_MEM_WRITE, store, lo, hi)

        @H.U.MEM_CB
        def ds_write(h, access, addr, size, value, user):
            if addr == H.STATE and size >= 2:
                v = (value >> (8 * (size - 2))) & 0xFFFF
                if WINDOW[0] <= v <= WINDOW[1]:
                    stats["ds_load"][(where(self.r("pc")), f"{v:04x}")] += 1
            return True

        self.e.hook_range(H.U.HOOK_MEM_WRITE, ds_write, H.STATE, H.STATE + 1)
        return original_run(self, script, timeout)

    H.Host.run = run
    problems = H.check(args.milestone, args.timeout, None, None, bypass=args.bypass, resume=args.resume)
    print(f"lockstep: {'ok' if not problems else problems[:3]}")
    print("generated frame stores by the segments whose window holds the byte:")
    for k, n in stats["seg"].most_common():
        print(f"  {n:10} {k}")
    print("runtime:", dict(stats["other"]))
    print("frame stores DS addresses (with the other segments that do), by label:")
    for (lab, k), n in stats["ds_label"].most_common(args.top * 4):
        print(f"  {n:10} {lab:24} {k}")
    print("DS slot writes of a frame-window value, by label and value:")
    for (lab, v), n in stats["ds_load"].most_common(args.top * 4):
        print(f"  {n:10} {lab:24} {v}")


if __name__ == "__main__":
    main()
