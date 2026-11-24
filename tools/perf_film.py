#!/usr/bin/env python3
"""P8 frames fixture: the combat film (m17) or the intro's Star Destroyer scene on an
Amiga image (docs/perf-method.md).

  perf_film.py OUT [--scene film|intro] [--exe amiga/out/XWing.exe]
               [--elf amiga/out/XWing.elf] [--frames N] [--no-profile] [--cpu 68030]

The non-release image runs from a Shell under amiga/debug.sh with a KEYS script
(src/platform/amiga/amiga_platform.c): through the intro, registers the pilot LUKE,
opens the film room from the concourse, loads COMBAT.CLP (manifest/films.sha256,
placed beside the installation as reference/seeds.csv places it) and plays it; the
three O keys track Red 3, as m17. Keys up to the film's start wait for fields (the
start is host-timed I/O); from P on they wait for published frames (`fN`, the
guest's plat_present calls), so the window starts at the same point of the film in
every build. amiga/perf_film.gdb takes the field at each of the next FRAMES visits
to the flight's frame label from the script's mark, then a 100-field profile, which
tools/profile_report.py reports and which is then deleted.

--scene intro: no keys; the intro plays by itself. The mark is the 100th published frame
(plat_present call) after the Star Destroyer scene's load, the first frame interval over
60 fields after the 1250th frame, in the scene's slowest stretch. The scene's first frame
moves by a few frames from run to run (the 1300th or the 1302nd in two runs of one image,
MEASURED: the field of every plat_present call), so the mark counts from the load, not
from the start. The frames are the next FRAMES plat_present calls (default 30).

Output OUT/: gdb.log, fixture.gdb, frames.json (fields per frame, the frame-interval
median and spread in ms), profile.txt. Emulated fields, never wall time; the 68030
model: the shared cycle-exact preset a1200-030 (50 MHz 68030, data cache, 2 MB Chip,
8 MB Fast) without its MMU (--uae_mmu_model=0), unless --cpu says otherwise.
"""
import argparse
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import seeds  # noqa: E402

# Fields: the intro, the title, registration (LUKE), the concourse (the pointer onto the
# pilot's door), Down Right Enter to the film room, Up Enter in "Load Mission Film".
# Published frames: P plays; O O O track Red 3; the mark starts the window.
KEYS = ("1300:enter,1700:enter,2100:enter,2500:l,2520:u,2540:k,2560:e,2650:enter,"
        "2950:mx-40,2951:my-40,2960:lmb,3600:down,3700:right,3800:enter,5000:up,5100:enter,"
        "5500:p,f60:o,f5:o,f5:o,f10:shot")

# Per scene: the KEYS script, the milestone whose seed files are placed, the frame
# label (one visit per frame), the default frame count, the name printed and, for a
# window gdb finds itself, the commands that replace the wait for the KEYS mark.
SCENES = {
    "film": dict(keys=KEYS, seeds="m17-combat-film", label="FLT_1B7D2", frames=60, name="combat film"),
    "intro": dict(keys="", seeds=None, label="plat_present", frames=30,
                  name="intro's Star Destroyer scene", mark="""\
break plat_present
set $prev = amiga_frames
while amiga_presents < 1250 || amiga_frames - $prev <= 60
  set $prev = amiga_frames
  continue
end
printf "SCENE_LOAD presents %u field %u\\n", amiga_presents, amiga_frames
set $n = 0
while $n < 100
  continue
  set $n = $n + 1
end
delete $bpnum
"""),
}


def check_emulator() -> str:
    """The FS-UAE build every P8 figure comes from (manifest/perf-tools.sha256, relative
    to ~/.local/share/amiga): the fs-uae on PATH must be it."""
    import hashlib
    share = Path(os.environ.get("AMIGA_SHARE") or Path.home() / ".local/share/amiga")
    digest, name = (ROOT / "manifest/perf-tools.sha256").read_text().split()
    found = shutil.which(os.environ.get("FSUAE") or "fs-uae")
    if not found or Path(found).resolve() != (share / name).resolve():
        sys.exit(f"fs-uae on PATH is {found}, not {share / name} (source amiga/env.sh)")
    if hashlib.sha256(Path(found).read_bytes()).hexdigest() != digest:
        sys.exit(f"{found} differs from manifest/perf-tools.sha256")
    return digest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--exe", type=Path, default=ROOT / "amiga/out/XWing.exe")
    ap.add_argument("--elf", type=Path, default=ROOT / "amiga/out/XWing.elf")
    ap.add_argument("--scene", choices=SCENES, default="film")
    ap.add_argument("--frames", type=int)
    ap.add_argument("--cpu", default="68030")
    ap.add_argument("--no-profile", action="store_true")
    ap.add_argument("--keep-capture", action="store_true",
                    help="keep the capture (for tools/cost_meter.py --calibrate; 0.4 GB)")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()
    scene = SCENES[args.scene]
    args.frames = args.frames or scene["frames"]
    emulator = check_emulator()
    out = args.out.resolve()
    if (out / "gdb.log").exists():
        sys.exit(f"{out} already measured; never overwrite a measurement")
    seed, run = out / "seed", out / "run"
    for d in (seed, run):
        d.mkdir(parents=True, exist_ok=True)
    if scene["seeds"]:
        seeds.place(seeds.files(scene["seeds"]), seed)
    capture = out / "profile.bin"
    text = (ROOT / "amiga/perf_film.gdb").read_text().replace("@FRAMES@", str(args.frames))
    text = text.replace("@LABEL@", scene["label"])
    if "mark" in scene:
        wait = "break amiga_script_mark\ncontinue\ndelete $bpnum\n"
        assert text.count(wait) == 1
        text = text.replace(wait, scene["mark"])
    text = text.replace("@OUT@", os.path.relpath(capture, ROOT / "amiga"))
    if args.no_profile:
        text = text.replace(f'monitor profile 100 "" "{os.path.relpath(capture, ROOT / "amiga")}"\n', "")
    (out / "fixture.gdb").write_text(text)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, DEBUG_PORT=str(port), FSUAE_PORT_PINNED="1", FSUAE_CLAIM_STRICT="1",
               AMIGA_CPU=args.cpu, XWING_ELF=str(args.elf.resolve()), XWING_ARGS=f"KEYS={scene['keys']}" if scene["keys"] else "",
               XWING_SEED_DIR=str(seed), FSUAE_RUN=os.path.relpath(run, ROOT / "amiga"),
               # FS-UAE's profiler records no instruction on the 68030 MMU core
               # (AmigaXDev docs/reference/measurement-method.md); the game uses no MMU
               EXTRA_ARGS="--uae_mmu_model=0")
    if args.cpu == "68030":
        # the shared cycle-exact preset (AmigaXDev docs/reference/headless-fsuae.md):
        # without one FS-UAE's 68030 is not cycle-exact and its profiler records nothing
        env["AMIGA_SETUP"] = "a1200-030"
    for k in ("CPU", "FAST_KB", "FAST_MEMORY"):
        env.pop(k, None)
    with (out / "gdb.log").open("w") as log:
        r = subprocess.run([str(ROOT / "amiga/debug.sh"), "", str(out / "fixture.gdb"),
                            str(args.exe.resolve())], env=env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=args.timeout, cwd=ROOT / "amiga")
    lines = (out / "gdb.log").read_text().splitlines()
    shutil.rmtree(run, ignore_errors=True)
    if r.returncode or "XWING_PERF_OK" not in lines:
        print("\n".join(lines[-15:]))
        sys.exit(f"perf_film: no window (exit {r.returncode}); see {out / 'gdb.log'}")
    fields = [int(x.split()[-1]) for x in lines if x.startswith("FRAME ")]
    mark = next(int(x.split()[2]) for x in lines if x.startswith("WINDOW_MARK "))
    iv = [b - a for a, b in zip(fields, fields[1:])]
    res = {"scene": args.scene, "exe": str(args.exe), "cpu": args.cpu, "fs-uae": emulator, "frames": args.frames, "mark_field": mark,
           "fields": fields, "intervals": iv, "median_ms": statistics.median(iv) * 20,
           "mean_ms": round(sum(iv) / len(iv) * 20, 1), "min_ms": min(iv) * 20, "max_ms": max(iv) * 20,
           "window_fields": fields[-1] - fields[0]}
    (out / "frames.json").write_text(json.dumps(res, indent=1) + "\n")
    print(f"{scene['name']}, {len(iv)} frame intervals from the mark: median {res['median_ms']} ms, "
          f"mean {res['mean_ms']} ms, {res['min_ms']}-{res['max_ms']} ms, "
          f"{res['window_fields']} fields")
    if capture.exists():
        rep = subprocess.run([sys.executable, str(ROOT / "tools/profile_report.py"), str(capture),
                              str(args.elf), "--objdump", "m68k-amiga-elf-objdump",
                              "--count", scene["label"]], capture_output=True, text=True)
        (out / "profile.txt").write_text(rep.stdout + rep.stderr)
        if rep.returncode:
            print(rep.stderr[-2000:])
            sys.exit("profile_report failed (capture kept)")
        if not args.keep_capture:
            capture.unlink()
        print(f"profile: {out / 'profile.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
