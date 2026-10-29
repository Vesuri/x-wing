#!/usr/bin/env python3
"""Install and run the original DOS floppy release under the scripted DOSBox-X.

disks      verify the pinned 7z and extract its five 1.44 MB images into tmp/dos/disks
install    run the original INSTALL.EXE with the five images in A:, verify C:\\XWING and
           keep it as tmp/dos/installed/XWING
reference  run XWING.EXE from fresh copies of the installation: to the pinned intro
           frames, through the copy-protection check, and a wrong-answer control
play       open a DOSBox-X window on a fresh copy of the installation

Runs never reuse a directory: each gets ref/dosbox/runs/<name>. Inputs are driven by the
patched DOSBox-X's script (tools/patches), triggered by guest state in emulated time.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from extract_original_data import ROOT, hashes, install as keep_output, pins, sha256

ARCHIVE_NAME = 'tmp/originals/000110_x-wing.7z'
DISKS = ROOT / 'tmp/dos/disks'
INSTALLED = ROOT / 'tmp/dos/installed'
RUNS = ROOT / 'ref/dosbox/runs'
SOURCE = Path(os.environ.get('XWING_DOSBOX_X_SRC', Path.home() / '.local/src/xwing-dosbox-x'))
COMMIT = '4f19017c5f565dc40d01fede0f1382892e7243d7'
DOSBOX = SOURCE / 'src/dosbox-x'
IMAGES = [f'disk{n}.img' for n in range(1, 6)]
# A 386 at a fixed 30,000 cycles/ms; the installer rates it FAST. Turbo removes the
# real-time throttle only: emulated time per instruction is unchanged.
MACHINE = ['cpu core=normal', 'cpu cputype=386', 'cpu cycles=fixed 30000', 'dosbox memsize=16',
           'dosbox quit warning=false', 'sdl output=surface', 'mixer nosound=true']
# The copy-protection question depends on the DOS clock, which otherwise starts at the host
# time. DOS sets the RTC too; both then advance in emulated time.
CLOCK = ['date 02-01-1993', 'time 12:00:00']
GAME = ['c:', 'cd \\xwing', 'xwing']
# Reference scenarios: script and the VGA dumps it writes, pinned as <scenario>/<dump>.
SCENARIOS = {'intro': ('intro.script', ['logo.vga', 'title.vga', 'crawl.vga']),
             'security': ('security.script', ['question.vga', 'answered.vga']),
             'control': ('security-control.script', ['question.vga', 'answered.vga'])}


def verify_emulator():
    head = subprocess.run(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], capture_output=True,
                          text=True).stdout.strip()
    if head != COMMIT:
        raise ValueError('DOSBOX-X / SOURCE IS NOT THE PINNED TAG; run make dos-emulator')
    for patch in (ROOT / 'tools/patches/ORDER').read_text().split():
        check = subprocess.run(['git', '-C', str(SOURCE), 'apply', '-R', '--check',
                                str(ROOT / 'tools/patches' / patch)], capture_output=True)
        if check.returncode:
            raise ValueError(f'DOSBOX-X / {patch} NOT APPLIED; run make dos-emulator')
    newest = max(p.stat().st_mtime for p in (SOURCE / 'src/misc/xwing_script.cpp',
                                            SOURCE / 'src/hardware/pic.cpp'))
    if not DOSBOX.is_file() or DOSBOX.stat().st_mtime < newest:
        raise ValueError('DOSBOX-X / BINARY MISSING OR OLDER THAN ITS SOURCE; run make dos-emulator')


def verify_disks():
    expected = pins(ROOT / 'manifest/dos-disks.sha256')
    actual = {name: sha256(DISKS / name) for name in IMAGES if (DISKS / name).is_file()}
    if actual != expected:
        raise ValueError('DISKS / SHA-256 OR FILE SET MISMATCH; run make dos-disks')


def extract_disks():
    if sha256(ROOT / ARCHIVE_NAME) != pins(ROOT / 'manifest/originals.sha256')[ARCHIVE_NAME]:
        raise ValueError('ARCHIVE / SHA-256 MISMATCH: ' + ARCHIVE_NAME)
    scratch = Path(tempfile.mkdtemp(prefix='disks-', dir=ROOT / 'tmp'))
    try:
        subprocess.run(['7zz', 'x', '-y', f'-o{scratch}', str(ROOT / ARCHIVE_NAME)], check=True,
                       stdout=subprocess.DEVNULL)
        output = scratch / '000110_x-wing'
        names = sorted(p.name for p in output.iterdir())
        if names != IMAGES:
            raise ValueError('ARCHIVE / UNEXPECTED MEMBERS: ' + ', '.join(names))
        actual = {name: sha256(output / name) for name in IMAGES}
        if actual != pins(ROOT / 'manifest/dos-disks.sha256'):
            raise ValueError('DISKS / SHA-256 MISMATCH')
        for path in output.iterdir():
            path.chmod(0o444)
        keep_output(output, DISKS)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    verify_disks()
    print(f'DISKS PASS: {len(IMAGES)} images verified in', DISKS.relative_to(ROOT))


def verify_installed(directory):
    actual = hashes(directory)
    expected = pins(ROOT / 'manifest/dos-installed.sha256')
    if actual != expected:
        changed = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k))
        raise ValueError('INSTALLED / SHA-256 OR FILE SET MISMATCH: ' + ', '.join(changed[:20]))
    return actual


def new_run(kind, name):
    name = name or f'{kind}-' + time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in name):
        raise ValueError('RUN / INVALID NAME')
    run = RUNS / name
    if run.exists():
        raise ValueError('RUN / ALREADY EXISTS; choose a new run name')
    (run / 'c').mkdir(parents=True)
    (run / 'capture').mkdir()
    return run


def dosbox(run, script, commands, limit_ms, deadline, headless=True):
    """Run the emulator until the script's DONE; anything else is a named failure."""
    settings = list(MACHINE)
    if headless:
        settings += ['cpu turbo=true']
    else:
        settings = [s for s in settings if s != 'mixer nosound=true']
    args = [str(DOSBOX), '-defaultconf', '-nomenu', '-fastlaunch', '-set', f'log logfile={run / "dosbox.log"}',
            '-set', f'dosbox captures={run / "capture"}']
    if headless:
        args += ['-nogui', '-time-limit', str(limit_ms // 1000)]
    for setting in settings:
        args += ['-set', setting]
    args += ['-c', f'mount c "{run / "c"}"']
    for command in commands:
        args += ['-c', command]
    env = dict(os.environ)
    if script:
        env.update(XWING_SCRIPT=str(script), XWING_SCRIPT_LOG=str(run / 'script.log'),
                   XWING_SCREEN_LOG=str(run / 'screen.log'))
    if headless:
        env.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
    pidfile = run / 'dosbox-x.pid'
    with (run / 'session.log').open('wb') as output:
        process = subprocess.Popen(args, cwd=run, env=env, stdout=output, stderr=subprocess.STDOUT)
        pidfile.write_text(str(process.pid) + '\n')
        if not headless:
            return process
        try:
            process.wait(timeout=deadline)
        except BaseException:
            # DOSBox-X ignores SIGTERM. The shared helper checks the pid's identity and kills it.
            subprocess.run(['/bin/bash', '-c', '. amiga/env.sh; . "$FSUAE_COMMON"; fsuae_kill_recorded "$1" dosbox-x',
                            'reference', str(pidfile)], cwd=ROOT, check=True)
            process.wait()
            raise ValueError(f'RUN / HOST DEADLINE {deadline}s; see {run.relative_to(ROOT)}')
    log = (run / 'script.log').read_text() if (run / 'script.log').exists() else ''
    lines = log.splitlines()
    if not lines or lines[-1].split('\t')[1:] != ['DONE'] or '\tFAIL\t' in log:
        last = next((l for l in reversed(lines) if '\tBEGIN\t' in l), 'no step started')
        raise ValueError(f'RUN / SCRIPT NOT DONE (waiting at: {last.split(chr(9), 2)[-1]}); '
                         f'see {run.relative_to(ROOT)}')
    return int(lines[-1].split('\t')[0])


def install_game(name, print_manifest):
    verify_emulator()
    verify_disks()
    run = new_run('install', name)
    disks = ' '.join(f'"{DISKS / image}"' for image in IMAGES)
    done = dosbox(run, ROOT / 'tools/dos/install.script',
                  [f'imgmount a {disks} -t floppy', 'a:', 'install.exe'], 1_200_000, 900)
    output = run / 'c/XWING'
    if print_manifest:
        for name, digest in hashes(output).items():
            print(digest + '  ' + name)
        return
    result = verify_installed(output)
    staged = Path(tempfile.mkdtemp(prefix='installed-', dir=ROOT / 'tmp'))
    shutil.copytree(output, staged / 'XWING', copy_function=shutil.copy2)
    keep_output(staged, INSTALLED)
    verify_installed(INSTALLED / 'XWING')
    print(f'INSTALL PASS: original INSTALL.EXE finished at {done} ms emulated; '
          f'{len(result)} files verified in', INSTALLED.relative_to(ROOT))


def fresh_game(run):
    verify_installed(INSTALLED / 'XWING')
    shutil.copytree(INSTALLED / 'XWING', run / 'c/XWING', copy_function=shutil.copy2)


def reference(name, print_manifest):
    from vga_dump import frame, parse
    import hashlib
    verify_emulator()
    base = name or 'reference-' + time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    actual, runs = {}, []
    for scenario, (script, dumps) in SCENARIOS.items():
        run = new_run('reference', f'{base}-{scenario}')
        fresh_game(run)
        dosbox(run, ROOT / 'tools/dos' / script, CLOCK + GAME, 120_000, 300)
        runs.append(run)
        for dump in dumps:
            pixels, palette = frame(*parse((run / dump).read_bytes()))
            actual[f'{scenario}/{dump}'] = hashlib.sha256(pixels + palette).hexdigest()
    if print_manifest:
        for dump, digest in actual.items():
            print(digest + '  ' + dump)
        return
    where = ', '.join(str(run.relative_to(ROOT)) for run in runs)
    if actual['control/question.vga'] != actual['security/question.vga']:
        raise ValueError(f'REFERENCE / CONTROL ASKED A DIFFERENT QUESTION; see {where}')
    if actual['control/answered.vga'] == actual['security/answered.vga']:
        raise ValueError(f'REFERENCE / WRONG ANSWER ACCEPTED; see {where}')
    if actual != pins(ROOT / 'manifest/dos-reference.sha256'):
        changed = sorted(k for k in actual if actual[k] != pins(ROOT / 'manifest/dos-reference.sha256').get(k))
        raise ValueError(f'REFERENCE / FRAME MISMATCH: {", ".join(changed)}; see {where}')
    print('REFERENCE PASS: intro frames, copy-protection question and registration screen match;',
          'the wrong-answer control keeps the dialog; runs in', where)


def play(name):
    verify_emulator()
    run = new_run('play', name)
    fresh_game(run)
    process = dosbox(run, None, GAME, 0, 0, headless=False)
    print(f'PLAY: DOSBox-X pid {process.pid} on a fresh copy in', run.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('command', choices=['disks', 'install', 'reference', 'play'])
    parser.add_argument('--name', help='run directory name under ref/dosbox/runs')
    parser.add_argument('--print-manifest', action='store_true',
                        help='print the output hashes instead of verifying them')
    args = parser.parse_args()
    if args.command == 'disks':
        extract_disks()
    elif args.command == 'install':
        install_game(args.name, args.print_manifest)
    elif args.command == 'reference':
        reference(args.name, args.print_manifest)
    else:
        play(args.name)


if __name__ == '__main__':
    main()
