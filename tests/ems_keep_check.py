#!/usr/bin/env python3
"""Controls for translator/emit.py check_ems_keep: the annotated keep rows of
annotations/ems-ds.csv pass, and a row breaking each condition is refused for
that condition (no RETF, outside one guard range, a DS write, a caller outside
guarded code, a dispatch row). Exit 0 only if every case behaves."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from translator import emit  # noqa: E402
from translator.lower import LowerError  # noqa: E402


def main() -> int:
    p = emit.Program()
    kind, rows, dispatch = p.ems_kind, dict(p.ems_keep), set(p.dispatch)
    helper = {("FRONTEND.OVL", 0x1746a): 0x17442}          # 1B36:0202-022A
    cases = [  # name, keep rows, call site made unlisted, extra dispatch row, expected refusal
        ("annotated rows", rows, None, None, None),
        ("no RETF", {("FRONTEND.OVL", 0x17469): 0x17442}, None, None, "last is no RETF"),
        ("outside a guard range", {("FLIGHT.OVL", 0x1ab4a): 0x1ab4b}, None, None, "not inside one guard range"),
        ("writes DS", {("FRONTEND.OVL", 0x1746a): 0x1724c}, None, None, "writes DS"),
        ("caller outside", helper, ("FRONTEND.OVL", 0x17388), None, "outside guarded code"),
        ("dispatch row", helper, None, ("FRONTEND.OVL", 0x17442), "dispatch row"),
    ]
    bad = 0
    for name, keep, unlisted, row, want in cases:
        p.ems_keep = keep
        p.ems_kind = (lambda m, o, u=unlisted: None if (m, o) == u else kind(m, o))
        p.dispatch = dispatch | ({row} if row else set())
        try:
            p.check_ems_keep()
            got = None
        except LowerError as e:
            got = str(e)
        ok = got is None if want is None else got is not None and want in got
        bad += not ok
        print(f"{'ok' if ok else 'FAIL':5} {name}: {got or 'accepted'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
