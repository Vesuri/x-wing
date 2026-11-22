"""Module images and annotations (layout: tools/xwing_model.py).

Copied from Secret Weapons of the Luftwaffe's translator/image.py (commit pinned in
manifest/references.tsv) and adapted: X-Wing's model is tools/xwing_model.py and the
translated scope is the root, the two overlay files and one music driver, DRIVER: the
AdLib setup's ADLIB.IMS, or with XWING_DRIVER=ADLIB_W.IMS the Sound Blaster setup's (P10;
translator/driver.py).
"""

from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import xwing_model as M  # noqa: E402

ANNOTATIONS = REPO / "annotations"
DRIVERS = ("ADLIB.IMS", "ADLIB_W.IMS")   # the drivers a build may translate
DRIVER = os.environ.get("XWING_DRIVER") or DRIVERS[0]
if DRIVER not in DRIVERS:
    raise SystemExit(f"XWING_DRIVER={DRIVER}: not one of {' '.join(DRIVERS)}")
SCOPE = (M.ROOT, "FRONTEND.OVL", "FLIGHT.OVL", DRIVER)
# Map outputs (tools/sweep.py), which hold rows of every driver: no carrying over
MAPPED = ("indirect.csv", "code-pointers.csv")


def load(ref: Path = M.REF) -> dict[str, M.Module]:
    return M.load_modules(ref)


def rows(name: str) -> list[dict]:
    """An annotation file's rows for this build: a row whose `driver` column names a
    driver applies to that driver's build only, and a row of a driver's code to that
    driver's build only (ADLIB.IMS rows carry, below); in a build of another driver than
    ADLIB.IMS, a hand-written row of ADLIB.IMS code applies to the same instruction of
    DRIVER unless the file has a DRIVER row at the same offset (translator/driver.py carry)."""
    with (ANNOTATIONS / name).open() as f:
        out = [r for r in csv.DictReader(f) if r.get("driver") in (None, "", DRIVER)]
    if name in MAPPED:      # targets in the driver the build does not translate are dropped
        other = tuple(f"{d}+" for d in DRIVERS if d != DRIVER)
        for r in out:
            for col in ("switch_targets", "traced_targets"):
                if r.get(col):
                    r[col] = " ".join(x for x in r[col].split() if not x.startswith(other))
        return out
    if out and "module" in out[0]:      # another driver's own rows never apply
        out = [r for r in out if r["module"] not in DRIVERS or r["module"] in (DRIVER, DRIVERS[0])]
    if DRIVER == DRIVERS[0] or not out or "module" not in out[0]:
        return out
    from . import driver
    # the row's key column and the code offsets it names (flags.csv: a PUSHF and its POPF)
    key, cols = next((k, c) for k, c in (("offset", ("offset",)), ("first", ("first", "last")),
                                          ("save", ("save", "restore"))) if k in out[0])
    own = {r[key] for r in out if r["module"] == DRIVER}
    keep = []
    for r in out:
        if r["module"] == DRIVERS[0]:
            if r[key] in own:
                continue
            for col in cols:
                driver.carry(int(r[col], 16))
            r["module"] = DRIVER
        keep.append(r)
    return keep


def smc_regions() -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for r in rows("self-modifying.csv"):
        span = (int(r["first"], 16), int(r["last"], 16))
        if span not in out[r["module"]]:
            out[r["module"]].append(span)
    return out


def smc_forms() -> dict[tuple[str, int, int], list[str]]:
    """Cell forms (hex, `ww` = word read at run time) per self-modified region."""
    out: dict[tuple[str, int, int], list[str]] = defaultdict(list)
    for r in rows("self-modifying.csv"):
        if r["kind"] == "form":
            out[(r["module"], int(r["first"], 16), int(r["last"], 16))].append(r["form"])
    return out


def runtime_bytes(traces: list[Path]) -> dict[str, bytes]:
    """Module images as found in the first snapshot holding each self-modified region."""
    out = {}
    mods = load()
    for name, spans in smc_regions().items():
        for t in traces:
            for snap in sorted(t.glob("snap-*")):
                res = M.residency(snap / "residency.csv")
                img = bytearray(mods[name].data)
                ram = (snap / "ram.bin").read_bytes()
                covered = set()
                for lo, hi, mod, off in res:
                    if mod == name:
                        n = min(hi - lo, len(img) - off)
                        img[off:off + n] = ram[lo:lo + n]
                        covered.update(range(off, off + n))
                if all(a in covered for lo, hi in spans for a in (lo, hi)):
                    out[name] = bytes(img)
                    break
            if name in out:
                break
    return out
