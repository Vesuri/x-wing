#!/usr/bin/env python3
"""EMS frame accesses on the host run to a milestone (open-work 2's input).

Copied from Wing Commander 2's tools/ems_frame_profile.py and trimmed. Runs
tests/host_run.py's lockstep check with a memory hook on the frame (E0000h-EFFFFh,
reversed guest RAM) and reports, for generated code and the runtime separately:
accesses and bytes, the segment register behind each generated access (DS, ES or SS,
whichever addresses the frame), accesses straddling a 16 KB page, the hottest code
labels, generated accesses that run on a store page (rt_ems_es's displacement), and
the EMS model's own page copies by the entry that caused them.

usage: tools/ems_frame_profile.py [--milestone m01-logo] [--bypass] [--timeout s] [--top 25]
"""
import argparse
import bisect
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import host_run as H  # noqa: E402

FRAME, FRAME_END = 0xE0000, 0xF0000
PAGE = 0x4000
STORE_PAGES = 0x40     # runtime.h RT_EMS_STORE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", default="m01-logo")
    ap.add_argument("--bypass", action="store_true")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    stats = dict(gen=Counter(), rt=Counter(), seg=Counter(), label=Counter(), rt_label=Counter(),
                 straddle=Counter(), model=Counter(), entries=Counter())
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
        def hook(h, access, addr, size, value, user):
            name = where(self.r("pc"))
            if name == "copy":
                return True
            lin = H.TOP - addr - size + 1           # lowest guest byte touched
            kind = "gen" if name.startswith(tags) else "rt"
            stats[kind]["accesses"] += 1
            stats[kind]["bytes"] += size
            if (lin - FRAME) // PAGE != (lin + size - 1 - FRAME) // PAGE:
                stats["straddle"][kind] += 1
            if kind == "gen":
                st = self.mem(H.STATE, 6)
                segs = {"ds": int.from_bytes(st[0:2], "big"), "ss": int.from_bytes(st[2:4], "big"),
                        "es": int.from_bytes(st[4:6], "big")}
                hits = sorted(f"{s}={v:04x}" for s, v in segs.items()
                              if v * 16 <= lin < v * 16 + 0x10000)
                stats["seg"][" ".join(hits) or "none"] += 1
                stats["label"][name] += 1
            else:
                stats["rt_label"][name] += 1
            return True

        self.e.hook_range(H.U.HOOK_MEM_READ | H.U.HOOK_MEM_WRITE, hook, lo, hi)

        cause = ["?"]
        entries = {self.syms[n]: n for n in ("rt_ems_es", "rt_ems_seg", "rt_int67", "rt_int_c",
                                             "rt_ems_touch", "rt_ems_sync", "rt_irq0_take")
                   if n in self.syms}

        @H.U.CODE_CB
        def entry(h, addr, size, user):
            n = entries[addr]
            stats["entries"][n] += 1
            if n == "rt_ems_touch" and cause[0] != "?":
                return None         # inside one of the others
            cause[0] = n
            return None

        for a in entries:
            self.e.hook_range(H.U.HOOK_CODE, entry, a, a)
        store_lo, store_hi = H.STATE + 16, H.STATE + 16 + STORE_PAGES * PAGE - 1

        @H.U.MEM_CB
        def copied(h, access, addr, size, value, user):
            if where(self.r("pc")) == "copy":
                into = "store" if store_lo <= addr <= store_hi else "frame"
                stats["model"][f"{cause[0]} -> {into}"] += size
            return True

        self.e.hook_range(H.U.HOOK_MEM_WRITE, copied, lo, store_hi)

        @H.U.MEM_CB
        def in_store(h, access, addr, size, value, user):
            if where(self.r("pc")).startswith(tags):     # generated code on a store page
                stats["gen"]["store accesses"] += 1
                stats["gen"]["store bytes"] += size
            return True

        self.e.hook_range(H.U.HOOK_MEM_READ | H.U.HOOK_MEM_WRITE, in_store, store_lo, store_hi)
        return original_run(self, script, timeout)

    H.Host.run = run
    problems = H.check(args.milestone, args.timeout, None, None, bypass=args.bypass)
    print(f"lockstep: {'ok' if not problems else problems[:3]}")
    for kind in ("gen", "rt"):
        c = stats[kind]
        print(f"{kind}: {c['accesses']} frame accesses, {c['bytes']} bytes, "
              f"{stats['straddle'][kind]} straddle a 16 KB page")
    print(f"gen: {stats['gen']['store accesses']} accesses on store pages (no copy), "
          f"{stats['gen']['store bytes']} bytes")
    print("runtime entries:", dict(stats["entries"]))
    print("EMS model copies (bytes written, by cause):", dict(stats["model"]),
          "total", sum(stats["model"].values()))
    print("generated accesses by the segment that addresses the frame:")
    for k, n in stats["seg"].most_common(args.top):
        print(f"  {n:10} {k}")
    print("hottest generated labels:")
    for k, n in stats["label"].most_common(args.top):
        print(f"  {n:10} {k}")
    print("hottest runtime functions:")
    for k, n in stats["rt_label"].most_common(args.top):
        print(f"  {n:10} {k}")


if __name__ == "__main__":
    main()
