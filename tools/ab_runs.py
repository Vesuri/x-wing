#!/usr/bin/env python3
"""Paired frames-fixture runs of frozen build arms (docs/perf-method.md).

  ab_runs.py freeze ARM
  ab_runs.py film SESSION ARM... [--runs 3] [--no-profile]

Adapted from Secret Weapons of the Luftwaffe's tools/ab_runs.py (manifest/references.tsv):
SWOTL's bench, frames and flyby fixtures become X-Wing's one frames fixture
(tools/perf_film.py, the combat film), and the meter runs in each arm's own checkout
(tools/cost_meter.py --out, then --compare), since its image is built from the arm's
translator.

freeze  copies amiga/out/XWing.exe and XWing.elf (the non-release image: make amiga)
        into ARM/ with the commit and the tree state. Build each arm's commit, then
        freeze it; never measure a live build directory.
film    runs the arms interleaved (run 1 of every arm, then run 2, ...) into
        SESSION/<arm>/film-<n>/, never overwriting a run, and writes
        SESSION/film-summary.json: per arm the frame-interval medians and their range.
        The first run records the instruments' fingerprints (SESSION/tools.json); every
        later run checks them, so one session never mixes tool versions.
Claims: a frame-time gain only when the arms' ranges of run medians do not overlap.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARE = Path(os.environ.get("AMIGA_SHARE") or Path.home() / ".local/share/amiga")
FILES = (SHARE / "env.sh", SHARE / "fsuae_common.sh", ROOT / "amiga/debug.sh",
         ROOT / "amiga/perf_film.gdb", ROOT / "tools/perf_film.py", ROOT / "tools/profile_report.py",
         ROOT / "manifest/perf-tools.sha256")


def fingerprints():
    paths = [Path(shutil.which(t) or t) for t in ("fs-uae", "m68k-amiga-elf-gdb")] + list(FILES)
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        sys.exit(f"measurement tools missing: {missing} (source amiga/env.sh)")
    return {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def check_tools(session):
    path = session / "tools.json"
    now = fingerprints()
    if not path.exists():
        session.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(now, indent=2) + "\n")
    elif json.loads(path.read_text()) != now:
        sys.exit("measurement tools changed during the session; keep its results, start a new session")


def freeze(arm):
    arm = Path(arm)
    if arm.exists():
        sys.exit(f"{arm} exists; freeze into a new directory")
    arm.mkdir(parents=True)
    for name in ("XWing.exe", "XWing.elf"):
        shutil.copy2(ROOT / "amiga/out" / name, arm / name)
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout
    head, dirty = git("rev-parse", "HEAD").strip(), bool(git("status", "--porcelain").strip())
    sums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(arm.glob("XWing.*"))}
    (arm / "arm.json").write_text(json.dumps(dict(head=head, dirty=dirty, sha256=sums), indent=2) + "\n")
    print(f"froze {arm} at {head}{' (dirty tree)' if dirty else ''}")


def film(session, arms, runs, profile):
    session = Path(session)
    summary = {}
    for n in range(1, runs + 1):
        for arm in arms:
            arm = Path(arm)
            check_tools(session)
            out = session / arm.name / f"film-{n}"
            if out.exists():
                sys.exit(f"{out} already measured; never overwrite a measurement")
            cmd = [sys.executable, str(ROOT / "tools/perf_film.py"), str(out), "--exe", str(arm / "XWing.exe"),
                   "--elf", str(arm / "XWing.elf")] + ([] if profile else ["--no-profile"])
            r = subprocess.run(cmd, capture_output=True, text=True)
            print(r.stdout.strip() or r.stderr.strip()[-500:], flush=True)
            if r.returncode:
                sys.exit(f"film run {out} failed")
            res = json.loads((out / "frames.json").read_text())
            summary.setdefault(arm.name, []).append(res["median_ms"])
    out = {a: {"medians_ms": m, "range_ms": [min(m), max(m)], "median_ms": statistics.median(m)}
           for a, m in summary.items()}
    (session / "film-summary.json").write_text(json.dumps(out, indent=1) + "\n")
    for a, s in out.items():
        print(f"{a}: run medians {s['medians_ms']} ms, range {s['range_ms'][0]}-{s['range_ms'][1]} ms")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("arm")
    m = sub.add_parser("film")
    m.add_argument("session")
    m.add_argument("arms", nargs="+")
    m.add_argument("--runs", type=int, default=3)
    m.add_argument("--no-profile", action="store_true")
    args = ap.parse_args()
    if args.cmd == "freeze":
        freeze(args.arm)
    else:
        film(args.session, args.arms, args.runs, not args.no_profile)


if __name__ == "__main__":
    main()
