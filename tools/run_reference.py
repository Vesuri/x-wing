#!/usr/bin/env python3
"""Boot a fresh System 7.5.5 Quadra 700 under headless MAME and launch the demo."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from extract_original_data import ROOT, pins
from prepare_reference import prepare

MACHINE = ['macqd700', '-ramsize', '8M']   # 20M and above hang in the MAME 0.289 ROM boot


def run(name=None, deadline=900):
    mame = Path(shutil.which(os.environ.get('MAME', 'mame')) or '')
    if not mame.is_file():
        raise ValueError('REFERENCE / MAME NOT FOUND')
    with mame.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != pins(ROOT/'manifest/reference-tools.sha256')['mame']:
            raise ValueError('REFERENCE / MAME HASH MISMATCH')
    name = name or time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in name):
        raise ValueError('REFERENCE / INVALID RUN NAME')
    destination = ROOT/'ref/mame/runs'/name
    prepare(destination)
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', XWING_REFERENCE_RUN=str(destination.relative_to(ROOT)))
    args = [str(mame), *MACHINE, '-noreadconfig', '-hard', str(destination/'volume.hd'),
            '-rompath', 'ref/mame/roms', '-nvram_directory', str(destination/'nvram'),
            '-cfg_directory', str(destination/'cfg'), '-snapshot_directory', str(destination/'snap'),
            '-state_directory', str(destination/'states'), '-video', 'none', '-sound', 'none',
            '-window', '-nothrottle', '-skip_gameinfo', '-nosamples', '-autoboot_delay', '0',
            '-autoboot_script', 'tools/mac_reference.lua', '-seconds_to_run', '600']
    pidfile = destination/'mame.pid'
    with (destination/'session.log').open('wb') as output:
        process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        pidfile.write_text(str(process.pid) + '\n')
        try:
            result = process.wait(timeout=deadline)
        except BaseException:
            # Use the shared identity-checked helper; never kill by process name.
            subprocess.run(['/bin/bash', '-c', '. amiga/env.sh; . "$FSUAE_COMMON"; fsuae_kill_recorded "$1" mame',
                            'reference', str(pidfile)], cwd=ROOT, check=True)
            process.wait()
            raise
    log = (destination/'session.log').read_text(errors='replace')
    if result or 'FAIL REFERENCE' in log or 'REF ERROR' in log or log.count('REFERENCE_RUNNING X-Wing\n') != 1:
        raise ValueError(f'REFERENCE / NOT RUNNING (exit {result}); see {destination.relative_to(ROOT)}/session.log')
    shots = sorted((destination/'snap').rglob('*.png'))
    print(f'REFERENCE PASS: X-Wing frontmost for 12 checks; {len(shots)} snapshots in',
          (destination/'snap').relative_to(ROOT))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name')
    parser.add_argument('--deadline', type=int, default=900, help='host deadline in seconds')
    args = parser.parse_args()
    run(args.name, args.deadline)
