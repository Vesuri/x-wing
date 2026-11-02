#!/usr/bin/env python3
"""Run the milestones of reference/milestones.csv and check their signals and pins.

Copied from Secret Weapons of the Luftwaffe's tools/reference.py (commit pinned in
manifest/references.tsv) and adapted. Each milestone is one tools/pc_run.py run with
--services, named <base>-<milestone> under ref/dosbox/runs. Its keys are those of the
milestone named in `after` (recursively) followed by its own. Keys and snapshot triggers
are MODULE+HEX[#N] visit counts; the aliases `menu` (FRONTEND.OVL+1808E, the frontend's
mouse poll, INT 33h AX=3) and `frame` (FLIGHT.OVL+1B7D2, the flight's once-per-frame mouse
poll) stand for those sites. Snapshots (space-separated, taken in order after the key
script) are named <milestone>-0, -1, ...; the run ends at the last.

Checks per milestone:
- the run reached its last snapshot (exit status 0);
- the listed modules are resident and the BIOS video mode is as listed at the last;
- consecutive snapshots differ in RAM and VRAM (the scene advances);
- every snapshot passes the gate 1 image proof (tools/load_image.py);
- `frame`: =NAME or !=NAME: the last snapshot's 320x200 frame and DAC equal (or differ
  from) those of milestone NAME, which must run in the same invocation; =NAME@x0 y0 x1 y1
  leaves that rectangle out (a text field whose cursor blinks);
- every software interrupt raised by module code has an svc event, and all but those
  still pending at the end have their svc_ret;
- the last snapshot's RAM, VRAM (graphics modes only: a text screen holds DOSBox-X's own
  messages, which name the host run directory) and DAC, and each file in `files` as the game left it in
  C:\\XWING, equal their pins in manifest/milestones.sha256 (`--print-manifest` prints
  them instead). Equal pins in separate runs prove the runs repeat byte-exactly.

The instruction count is reported only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import xwing_model as M

REPO = Path(__file__).resolve().parent.parent
TABLE = REPO / 'reference/milestones.csv'
PINS = REPO / 'manifest/milestones.sha256'
SITES = {'menu': 'FRONTEND.OVL+1808e', 'frame': 'FLIGHT.OVL+1b7d2'}
PENDING_MAX = 4


def site(token: str) -> str:
    for alias, target in SITES.items():
        if token == alias or token.startswith(alias + '#'):
            return target + token[len(alias):]
    return token


def keys(rows: dict[str, dict], name: str) -> list[str]:
    m = rows[name]
    before = keys(rows, m['after']) if m['after'] else []
    own = []
    for token in m['keys'].split():
        trigger, key = token.rsplit('=', 1)
        own.append(f'{site(trigger)}={key}')
    return before + own


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frame(snapshot: Path, mask: tuple[int, int, int, int] | None = None) -> bytes:
    """Chain-4 320x200 pixels plus DAC; pixels inside mask (x0, y0, x1, y1) read as 0."""
    planes = (snapshot / 'vram.bin').read_bytes()
    pixels = bytearray(planes[((a & ~3) << 2) | (a & 3)] for a in range(64000))
    if mask:
        x0, y0, x1, y1 = mask
        for y in range(y0, y1):
            pixels[y * 320 + x0:y * 320 + x1] = bytes(x1 - x0)
    return bytes(pixels) + (snapshot / 'dac.bin').read_bytes()


def service_balance(trace: Path) -> tuple[int, int]:
    counts = subprocess.run(
        f'gzip -dc "{M.events_path(trace)}" | cut -d, -f2 | grep -E "^svc(_ret)?$" | sort | uniq -c',
        shell=True, capture_output=True, text=True, check=True).stdout.split()
    got = dict(zip(counts[1::2], map(int, counts[0::2])))
    return got.get('svc', 0), got.get('svc_ret', 0)


def run(base: str, rows: dict[str, dict], name: str) -> tuple[list[str], dict[str, str], Path]:
    m = rows[name]
    triggers = [site(t) for t in m['snapshots'].split()]
    names = [f'{name}-{i}' for i in range(len(triggers))]
    run_name = f'{base}-{name}'
    cmd = [sys.executable, str(REPO / 'tools/pc_run.py'), run_name, '--services',
           '--time-limit', m['time_limit'],
           '--snapshots', ','.join(f'{n}@{t}' for n, t in zip(names, triggers)),
           '--exit-after', names[-1], '--keys', ','.join(keys(rows, name))]
    trace = REPO / 'ref/dosbox/runs' / run_name / 'trace'
    status = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT).returncode
    if status != 0:
        return [f'run status {status}'], {}, trace
    snaps = [trace / f'snap-{n}' for n in names]
    problems = []
    last = snaps[-1]
    resident = {r[2] for r in M.residency(last / 'residency.csv')}
    missing = set(m['resident'].split()) - resident
    if missing:
        problems.append(f"not resident: {' '.join(sorted(missing))}")
    regs = dict(kv.split('=') for kv in (last / 'regs.txt').read_text().split())
    if m['vga_mode'] and int(regs['vga_mode'], 16) != int(m['vga_mode'], 16):
        problems.append(f"vga mode {regs['vga_mode']}")
    for a, b in zip(snaps, snaps[1:]):
        for part in ('ram.bin', 'vram.bin'):
            if (a / part).read_bytes() == (b / part).read_bytes():
                problems.append(f'{b.name} {part} did not advance')
    for s in snaps:
        if subprocess.run([sys.executable, str(REPO / 'tools/load_image.py'), str(s)],
                          stdout=subprocess.DEVNULL).returncode:
            problems.append(f'{s.name} image proof')
    svc, ret = service_balance(trace)
    if (not svc and int(regs['icount']) > 1) or not 0 <= svc - ret <= PENDING_MAX:
        problems.append(f'services: {svc} svc, {ret} svc_ret')
    actual = {f'{name}/ram': sha((last / 'ram.bin').read_bytes())}
    if int(regs['vga_mode'], 16) != 3:  # text screens hold DOSBox-X's messages with host paths
        actual[f'{name}/vram'] = sha((last / 'vram.bin').read_bytes())
    actual[f'{name}/dac'] = sha((last / 'dac.bin').read_bytes())
    for f in m['files'].split():
        path = trace.parent / 'c/XWING' / f
        actual[f'{name}/{f}'] = sha(path.read_bytes()) if path.exists() else 'missing'
    print(f"{name:22} icount={regs['icount']} svc={svc}", flush=True)
    return problems, actual, last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('only', nargs='*', help='milestones to run (default: all)')
    ap.add_argument('--name', help='run name base (default: ms-<time>-<id>)')
    ap.add_argument('--jobs', type=int, default=6)
    ap.add_argument('--print-manifest', action='store_true')
    args = ap.parse_args()
    with TABLE.open() as f:
        rows = {r['name']: r for r in csv.DictReader(f)}
    names = args.only or list(rows)
    base = args.name or 'ms-' + time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    with ThreadPoolExecutor(args.jobs) as ex:
        results = dict(zip(names, ex.map(lambda n: run(base, rows, n), names)))
    pins = {}
    if PINS.exists():
        for line in PINS.read_text().splitlines():
            digest, key = line.split(None, 1)
            pins[key] = digest
    failed = False
    lines = []
    for name in names:
        problems, actual, last = results[name]
        ref = rows[name]['frame']
        if ref and actual:
            other, _, rect = ref.lstrip('!=').partition('@')
            mask = tuple(int(v) for v in rect.split()) if rect else None
            if other not in results or not results[other][1]:
                problems.append(f'frame: {other} not run')
            else:
                same = frame(last, mask) == frame(results[other][2], mask)
                if same != (not ref.startswith('!')):
                    problems.append(f"frame {'equals' if same else 'differs from'} {other}")
        for key, digest in actual.items():
            lines.append(f'{digest}  {key}')
            if not args.print_manifest and pins.get(key) != digest:
                problems.append(f'{key.split("/", 1)[1]} differs from its pin')
        failed |= bool(problems)
        print(f"{name:22} {'FAIL ' + '; '.join(problems) if problems else 'ok'}", flush=True)
    if args.print_manifest:
        print('\n'.join(lines))
    print(f"MILESTONES {'FAIL' if failed else 'PASS'}: {len(names)} in ref/dosbox/runs/{base}-*")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
