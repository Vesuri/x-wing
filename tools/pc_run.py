#!/usr/bin/env python3
"""Run the original under the instrumented DOSBox-X, headless, from a fresh installation.

Copied from Secret Weapons of the Luftwaffe's tools/pc_run.py (commit pinned in
manifest/references.tsv) and adapted. The run directory ref/dosbox/runs/<name> must be
new. It holds c/XWING (a fresh copy of the verified installation configured for AdLib),
trace/ (hook outputs), dosbox-x.log, stdout.txt and result.txt.

The machine is reference/dosbox-x.conf: a 386 at 30,000 cycles/ms with AdLib only, no
Sound Blaster. The tracer arms at XWING.EXE's MZ entry and sets the BIOS tick count
(XWING_BIOS_TICKS, default 0) and the DOS date (1993-02-01), so the DOS clock does not
come from the host.

Exit status: 0 success (the --exit-after snapshot was reached), 2 time limit, 3 guest
fault, 4 emulator failure. A time limit is never success.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dos_reference import fresh_game, new_run
from dosbox_x import DOSBOX, verify as verify_emulator
from extract_original_data import ROOT

CONF = ROOT / 'reference/dosbox-x.conf'
LAUNCH = ['c:', 'cd \\xwing', 'xwing']

EXIT_SUCCESS, EXIT_LIMIT, EXIT_FAULT, EXIT_EMULATOR = 0, 2, 3, 4


def classify(run: Path, returncode: int) -> tuple[int, str]:
    trace = run / 'trace'
    exit_file = trace / 'exit.txt'
    if exit_file.exists():
        return EXIT_SUCCESS, exit_file.read_text().strip()
    events = trace / 'events.csv'
    if events.exists():
        for line in events.read_text(errors='replace').splitlines():
            if ',fault,' in line:
                return EXIT_FAULT, f'guest fault: {line}'
    if not (trace / 'summary.txt').exists():
        return EXIT_EMULATOR, f'emulator exited {returncode} without trace output'
    return EXIT_LIMIT, 'time limit'


def kill(run: Path) -> None:
    """DOSBox-X ignores SIGTERM; the shared helper checks the pid's identity and kills it."""
    subprocess.run(['/bin/bash', '-c',
                    '. amiga/env.sh; . "$FSUAE_COMMON"; fsuae_kill_recorded "$1" dosbox-x',
                    'pc_run', str(run / 'dosbox-x.pid')], cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('--time-limit', type=int, default=60, help='emulated seconds')
    parser.add_argument('--deadline', type=int, default=0,
                        help='host seconds before the recorded pid is killed (default: 3x limit + 60)')
    parser.add_argument('--snapshots', default='', help='name@MODULE+HEX[#N],...')
    parser.add_argument('--exit-after', default='', help='snapshot name that ends the run')
    parser.add_argument('--keys', default='',
                        help='MODULE+HEX[#N]=key/mx+N/my-N/mb0..7,... (mouse actions are immediate)')
    parser.add_argument('--key-hold', type=int, default=None)
    parser.add_argument('--bios-ticks', type=int, default=0)
    parser.add_argument('--services', action='store_true',
                        help='log every software INT from module code with entry/return registers')
    parser.add_argument('--joystick', action='store_true',
                        help='enable deterministic joystick inputs and record exact gameport accesses')
    parser.add_argument('--opl', action='store_true',
                        help='log every AdLib register write with emulated ms (trace/opl.csv)')
    parser.add_argument('--probes', default='',
                        help='MODULE+HEX:N=name,...: log entry ms and N far-call stack words')
    parser.add_argument('--polls', type=Path,
                        help='translator poll points: hardware interrupts only there, logged')
    parser.add_argument('--set', action='append', default=[], help='extra DOSBox-X setting')
    args = parser.parse_args()

    verify_emulator()
    run = new_run('pc', args.name)
    fresh_game(run, configured=True)
    (run / 'trace').mkdir()
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy',
               XWING_TRACE='1', XWING_TRACE_DIR=str(run / 'trace'),
               XWING_FIXED_FILE_CLOCK='1', XWING_BIOS_TICKS=str(args.bios_ticks),
               XWING_SNAPSHOTS=args.snapshots, XWING_EXIT_AFTER=args.exit_after,
               XWING_KEYS=args.keys)
    for var in ('XWING_JOYSTICK', 'XWING_SERVICES', 'XWING_OPL', 'XWING_PROBES', 'XWING_POLLS',
                'XWING_KEY_HOLD', 'XWING_REP_CHUNKS', 'XWING_SCRIPT'):
        env.pop(var, None)
    if args.joystick:
        env['XWING_JOYSTICK'] = '1'
    if args.services:
        env['XWING_SERVICES'] = '1'
    if args.opl:
        env['XWING_OPL'] = '1'
    if args.probes:
        env['XWING_PROBES'] = args.probes
    if args.polls:
        env['XWING_POLLS'] = str(args.polls.resolve())
    if args.key_hold is not None:
        env['XWING_KEY_HOLD'] = str(args.key_hold)
    command = [str(DOSBOX), '-conf', str(CONF), '-nogui', '-nomenu', '-silent', '-fastlaunch',
               '-time-limit', str(args.time_limit),
               '-set', f'log logfile={run / "dosbox-x.log"}',
               '-set', f'dosbox captures={run / "capture"}']
    for setting in args.set:
        command += ['-set', setting]
    command += ['-c', f'mount c "{run / "c"}"']
    for line in LAUNCH:
        command += ['-c', line]
    command += ['-c', 'exit']
    (run / 'clock-inputs.json').write_text(json.dumps({
        'host_file_clock': '1993-02-01T12:00:00', 'basis': 'local calendar',
        'dos_date': '1993-02-01', 'bios_ticks': args.bios_ticks}, indent=2) + '\n')
    deadline = args.deadline or args.time_limit * 3 + 60
    with open(run / 'stdout.txt', 'w') as out:
        proc = subprocess.Popen(command, cwd=run, env=env, stdout=out, stderr=subprocess.STDOUT)
        (run / 'dosbox-x.pid').write_text(f'{proc.pid}\n')
        try:
            returncode = proc.wait(timeout=deadline)
        except BaseException:
            kill(run)
            proc.wait()
            returncode = -1
    status, reason = classify(run, returncode)
    if returncode == -1 and status != EXIT_SUCCESS:
        status, reason = EXIT_EMULATOR, f'host deadline {deadline}s'
    (run / 'result.txt').write_text(f'{status} {reason}\n')
    print(f'{args.name}: {reason}')
    return status


if __name__ == '__main__':
    sys.exit(main())
