#!/usr/bin/env python3
"""P9 save and exit scenario (docs/release.md, gate 8): a pilot saved and the game left
by its own exit on the Amiga.

  test_save_exit.py OUT [--exe amiga/out/XWing.exe] [--elf amiga/out/XWing.elf] [--cpu 68030]

The non-release image (KEYS is not in the release image) runs from a Shell under
amiga/debug.sh on the configured DOS install, with a KEYS script
(src/platform/amiga/amiga_platform.c) that follows tools/perf_film.py's route through
the intro and registration (the pilot LUKE) to the concourse, where the click onto the
pilot's door saves the pilot as at m06, then leaves as m16 does: Esc, the pointer
+86,+59 and a click on the exit. amiga/save_exit.gdb needs, in order, m16's milestone
point (the exit's INT 21h, XWING.EXE+1660), plat_exit with the game's exit code, the
reference's 3 (AX 4C03h at m16, MEASURED), and the program's return of 0 to the Shell; a runtime stop, an earlier exit or a return
before plat_exit fails. The LUKE.PLT the run wrote must equal the reference's at m06
(manifest/milestones.sha256, m06-concourse-pilot-saved/LUKE.PLT); the configured
install must hold no LUKE.PLT, so the file is the run's.

Output OUT/: gdb.log, result.json. The run directory is deleted afterwards. The
68030 model: the shared preset a1200-030 (2 MB Chip, 8 MB Fast) unless --cpu says
otherwise.
"""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "tmp/dos/configured/XWING"
# tools/perf_film.py's route to the concourse's click (m06), then m16's keys
KEYS = ("1300:enter,1700:enter,2100:enter,2500:l,2520:u,2540:k,2560:e,2650:enter,"
        "2950:mx-40,2951:my-40,2960:lmb,3600:esc,3700:mx+86,3701:my+59,3760:lmb")
PILOT = "LUKE.PLT"
EXIT_CODE = 3   # the reference at m16: AX 4C03h at the INT 21h (MEASURED)


def pinned(name: str) -> str:
    for line in (ROOT / "manifest/milestones.sha256").read_text().splitlines():
        digest, path = line.split()
        if path == name:
            return digest
    sys.exit(f"{name} is not pinned in manifest/milestones.sha256")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--exe", type=Path, default=ROOT / "amiga/out/XWing.exe")
    ap.add_argument("--elf", type=Path, default=ROOT / "amiga/out/XWing.elf")
    ap.add_argument("--cpu", default="68030")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    want = pinned(f"m06-concourse-pilot-saved/{PILOT}")
    if (GAME / PILOT).exists():
        sys.exit(f"{GAME / PILOT} exists: the run's pilot would not be its own")
    out = args.out.resolve()
    if (out / "gdb.log").exists():
        sys.exit(f"{out} already holds a run; never overwrite one")
    run = out / "run"
    run.mkdir(parents=True, exist_ok=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, DEBUG_PORT=str(port), FSUAE_PORT_PINNED="1", FSUAE_CLAIM_STRICT="1",
               AMIGA_CPU=args.cpu, XWING_ELF=str(args.elf.resolve()), XWING_ARGS=f"KEYS={KEYS}",
               FSUAE_RUN=os.path.relpath(run, ROOT / "amiga"), XWING_GAME_DIR=str(GAME))
    if args.cpu == "68030":
        env["AMIGA_SETUP"] = "a1200-030"
    for k in ("CPU", "FAST_KB", "FAST_MEMORY"):
        env.pop(k, None)
    with (out / "gdb.log").open("w") as log:
        r = subprocess.run([str(ROOT / "amiga/debug.sh"), "", str(ROOT / "amiga/save_exit.gdb"),
                            str(args.exe.resolve())], env=env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=args.timeout, cwd=ROOT / "amiga")
    lines = (out / "gdb.log").read_text().splitlines()
    saved = run / "dh1" / PILOT
    got = hashlib.sha256(saved.read_bytes()).hexdigest() if saved.exists() else "missing"
    shutil.rmtree(run, ignore_errors=True)
    signals = [x for x in lines if x.startswith("XWING_")]
    res = {"exe": str(args.exe), "cpu": args.cpu, "signals": signals, "pilot": got, "pilot_reference": want}
    (out / "result.json").write_text(json.dumps(res, indent=1) + "\n")
    names = [x.split()[0] for x in signals]
    problems = []
    if r.returncode:
        problems.append(f"debug.sh exit {r.returncode}")
    if names != ["XWING_EXIT_POINT", "XWING_EXIT_CODE", "XWING_PROGRAM_RETURNED"]:
        problems.append(f"signals {signals}")
    elif signals[1] != f"XWING_EXIT_CODE {EXIT_CODE}" or signals[2] != "XWING_PROGRAM_RETURNED 0":
        problems.append(f"exit {signals[1:]}")
    if got != want:
        problems.append(f"{PILOT} {got}, the reference's {want}")
    if problems:
        print("\n".join(lines[-15:]))
        sys.exit("FAIL: " + "; ".join(problems))
    print(f"save and exit: {signals[0]}, exit code {EXIT_CODE} as the reference, returned 0; {PILOT} equals the reference's (m06)")
    print("XWING_SAVE_EXIT_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
