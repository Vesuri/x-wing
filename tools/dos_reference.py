#!/usr/bin/env python3
"""Install and run the original DOS floppy release under the scripted DOSBox-X.

disks      verify the pinned 7z and extract its five 1.44 MB images into tmp/dos/disks
install    run the original INSTALL.EXE with the five images in A:, verify C:\\XWING and
           keep it as tmp/dos/installed/XWING
configure  run the installed INSTALL.EXE on the AdLib-only reference machine to select AdLib,
           verify the tree and keep it as tmp/dos/configured/XWING
play       open a DOSBox-X window on a fresh copy of the installation, as a period 386 that
           answers the copy protection and then leaves the keyboard to the player

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

from dosbox_x import DOSBOX, verify as verify_emulator
from extract_original_data import ROOT, hashes, install as keep_output, pins, sha256

ARCHIVE_NAME = 'tmp/originals/000110_x-wing.7z'
DISKS = ROOT / 'tmp/dos/disks'
INSTALLED = ROOT / 'tmp/dos/installed'
CONFIGURED = ROOT / 'tmp/dos/configured'
# P10: the installation configured for "SoundBlaster" (tools/dos/configure-sb.script)
CONFIGURED_SB = ROOT / 'tmp/dos/configured-sb'
RUNS = ROOT / 'ref/dosbox/runs'
IMAGES = [f'disk{n}.img' for n in range(1, 6)]
# A 386 at a fixed 30,000 cycles/ms; the installer rates it FAST. Turbo removes the
# real-time throttle only: emulated time per instruction is unchanged.
MACHINE = ['cpu core=normal', 'cpu cputype=386', 'cpu cycles=fixed 30000', 'dosbox memsize=16',
           'dosbox quit warning=false', 'sdl output=surface', 'mixer nosound=true']
# The reference machine with AdLib only (reference/dosbox-x.conf), on which the installer
# detects AdLib and the game selects ADLIB.IMS.
ADLIB_MACHINE = MACHINE + ['sblaster sbtype=none', 'sblaster oplmode=opl2']
# P10's Sound Blaster reference machine (reference/dosbox-x-sb.conf): a Sound Blaster 2.0
# at 220h, IRQ 7, DMA 1, its OPL2 the AdLib reference's.
SB_MACHINE = MACHINE + ['sblaster sbtype=sb2', 'sblaster sbbase=220', 'sblaster irq=7',
                        'sblaster dma=1', 'sblaster oplmode=opl2']
# A 386DX-class machine of 1993 for play: 8,000 cycles/ms, 4 MB, Sound Blaster Pro 2.
PLAY_MACHINE = ['cpu core=normal', 'cpu cputype=386', 'cpu cycles=fixed 8000', 'dosbox memsize=4',
                'dosbox quit warning=false', 'sdl output=surface', 'sblaster sbtype=sbpro2']
# For play: the copy-protection question depends on the CPU speed and the DOS clock, which
# otherwise starts at the host time. DOS sets the RTC too; both then advance in emulated time.
# The reference runs (tools/pc_run.py) pin the BIOS tick count instead.
CLOCK = ['date 02-01-1993', 'time 12:00:00']
GAME = ['c:', 'cd \\xwing', 'xwing']

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


def verify_installed(directory, configured=False):
    """configured: False (installed only), True (AdLib) or 'sb' (Sound Blaster)."""
    actual = hashes(directory)
    expected = pins(ROOT / 'manifest/dos-installed.sha256')
    if configured:
        expected.update(pins(ROOT / ('manifest/dos-configured-sb.sha256' if configured == 'sb'
                                     else 'manifest/dos-configured.sha256')))
    if actual != expected:
        changed = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k))
        what = 'CONFIGURED' if configured else 'INSTALLED'
        raise ValueError(f'{what} / SHA-256 OR FILE SET MISMATCH: ' + ', '.join(changed[:20]))
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


def dosbox(run, script, commands, limit_ms, deadline, headless=True, machine=MACHINE):
    """Run the emulator until the script's DONE; anything else is a named failure."""
    settings = list(machine)
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


def configure_game(name, print_manifest, sound='adlib'):
    """sound: 'adlib' (the AdLib reference) or 'sb' (P10's Sound Blaster reference)."""
    sb = sound == 'sb'
    verify_emulator()
    run = new_run('configure', name)
    fresh_game(run)
    dosbox(run, ROOT / ('tools/dos/configure-sb.script' if sb else 'tools/dos/configure.script'),
           GAME[:2] + ['install'], 120_000, 300, machine=SB_MACHINE if sb else ADLIB_MACHINE)
    output = run / 'c/XWING'
    if print_manifest:
        installed = pins(ROOT / 'manifest/dos-installed.sha256')
        for name, digest in hashes(output).items():
            if installed.get(name) != digest:
                print(digest + '  ' + name)
        return
    kind = 'sb' if sb else True
    result = verify_installed(output, configured=kind)
    target = CONFIGURED_SB if sb else CONFIGURED
    staged = Path(tempfile.mkdtemp(prefix='configured-', dir=ROOT / 'tmp'))
    shutil.copytree(output, staged / 'XWING', copy_function=shutil.copy2)
    keep_output(staged, target)
    verify_installed(target / 'XWING', configured=kind)
    print(f'CONFIGURE PASS: {"SoundBlaster" if sb else "AdLib"} selected; {len(result)} files verified in',
          target.relative_to(ROOT))


def fresh_game(run, configured=False):
    """configured: False, True (AdLib) or 'sb' (Sound Blaster), as verify_installed."""
    source = (CONFIGURED_SB if configured == 'sb' else CONFIGURED if configured else INSTALLED) / 'XWING'
    verify_installed(source, configured)
    shutil.copytree(source, run / 'c/XWING', copy_function=shutil.copy2)


def play(name):
    verify_emulator()
    run = new_run('play', name)
    fresh_game(run)
    process = dosbox(run, ROOT / 'tools/dos/play.script', CLOCK + GAME, 0, 0, headless=False,
                     machine=PLAY_MACHINE)
    print(f'PLAY: DOSBox-X pid {process.pid} on a fresh copy in', run.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('command', choices=['disks', 'install', 'configure', 'configure-sb', 'play'])
    parser.add_argument('--name', help='run directory name under ref/dosbox/runs')
    parser.add_argument('--print-manifest', action='store_true',
                        help='print the output hashes instead of verifying them')
    args = parser.parse_args()
    if args.command == 'disks':
        extract_disks()
    elif args.command == 'install':
        install_game(args.name, args.print_manifest)
    elif args.command == 'configure':
        configure_game(args.name, args.print_manifest)
    elif args.command == 'configure-sb':
        configure_game(args.name, args.print_manifest, 'sb')
    else:
        play(args.name)


if __name__ == '__main__':
    main()
