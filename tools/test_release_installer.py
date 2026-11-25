#!/usr/bin/env python3
"""Run release/Install in real Installer 43 under FS-UAE with scripted answers.

    python3 tools/test_release_installer.py [mode ...] [--archive LHA] [--keep DIR]

Copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and
adapted: five floppies, no sound choice. The installation files are the
package members (tools/package_release.py from the current build), or with
--archive those decoded from a release archive. --keep copies the last mode's
installed X-Wing drawer to DIR (it holds game data: local only).

Modes: fresh (images), files (XWING.001-005 and disk 1's files), keep (Use
existing), replace (images over a damaged install), upgrade (beside 0.1's XWing
drawer, AdLib setup: a new X-Wing drawer from the images, the old pilots and films
copied), remove, bad-disks (Replace with a corrupted image). X-WingInstallData runs on the emulated
68020; installed game files must equal the configured DOS install, pilots
must survive Keep and Replace, and a refused source must leave the install as
it was. Inputs are local: the floppy images and the configured DOS install
(as tools/install-data/test_install.py), Installer 43, WHDLoad, Kickstart 3.1,
the Workbench floppy. Each emulator is stopped by its own PID.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/install-data'))
from test_install import COPIED, FILES, IMAGES, REFERENCE, fat12_file  # noqa: E402
from test_install import tree as host_tree  # noqa: E402
from package_release import PREFIX, members  # noqa: E402

AMIGA = Path.home() / '.local/share/amiga'
WORKBENCH = Path(os.environ.get('WORKBENCH_ADF', AMIGA / 'Workbenchv2.04rev37.67Workbench.adf'))
INSTALLER = Path(os.environ.get('INSTALLER43', AMIGA / 'Installer43/Installer'))
SETPATCH = Path(os.environ.get('SETPATCH', AMIGA / 'SetPatch'))
WHDLOAD = Path(os.environ.get('WHDLOAD', AMIGA / 'WHDLoad')) / 'C/WHDLoad'
KICK = Path(os.environ.get('KICKSTART_A1200', AMIGA / 'Kickstarts/kick40068.A1200'))
SCRIPT = os.environ.get('INSTALL_SCRIPT')  # sabotage override of the package's Install
PACKAGE = {}
MODES = ('fresh', 'files', 'keep', 'replace', 'upgrade', 'remove', 'bad-disks')
# 0.1's AdLib setup of the same files (manifest/dos-configured.sha256)
ADLIB_SETUP = Path(os.environ.get('XWING_ADLIB_REFERENCE', ROOT / 'tmp/dos/configured/XWING'))
PILOT = b'pilot written by the game'
FILM = b'film recorded by the game'
DAMAGED = 'VGA.PAC'


def tree(base):
    # FS-UAE keeps Amiga protection bits and dates in .uaem sidecar files.
    return {k: p for k, p in host_tree(base).items() if not k.endswith('.UAEM')}


def replace_form(text, start, replacement):
    a = text.index(start)
    depth, quoted, i = 0, False, a
    while i < len(text):
        c = text[i]
        if quoted and c == '\\':
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        elif not quoted:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return text[:a] + replacement + text[i + 1:]
        i += 1
    raise ValueError('unbalanced Installer form: ' + start)


def mark(name, then=''):
    return f'((textfile (dest "DH2:{name}") (append "yes")) {then})'


def script(mode):
    s = (Path(SCRIPT).read_bytes() if SCRIPT else PACKAGE['Install']).decode('latin-1')
    s = replace_form(s, '(welcome)', '(if 0 (welcome))')
    s = replace_form(s, '(set #source', '(set #source "DH0:")')
    s = s.replace('SYS:Utilities/MultiView', 'Execute DH0:multiview').replace('SYS:Utilities/More', 'Execute DH0:more')
    s = replace_form(s, '(set #parent', mark('parent-asked', '(set #parent "DH2:out")'))
    s = replace_form(s, '(set #remove-existing', mark('remove-asked', f'(set #remove-existing {int(mode == "remove")})'))
    s = replace_form(s, '(set #install-data\n', mark('reuse-asked', f'(set #install-data {int(mode in ("replace", "bad-disks"))})'))
    s = replace_form(s, '(message ("X-Wing 0.1 is installed', mark('upgrade-told'))
    disks = 'DH2:files' if mode == 'files' else 'DH2:disks'
    s = replace_form(s, '(set #disks', mark('disks-asked', f'(set #disks "{disks}")'))
    s = replace_form(s, '(abort "The X-Wing disks', mark('disks-refused', '(exit (quiet))'))
    s = replace_form(s, '(exit)', '(exit (quiet))')
    return s.encode('latin-1')


def fixture(mode, base):
    boot, out = base / 'boot', base / 'out'
    for p in (boot / 's', boot / 'env', boot / 'devs/Kickstarts', out, base / 'state'):
        p.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(INSTALLER, boot / 'Installer')
    shutil.copyfile(WHDLOAD, boot / 'WHDLoad')
    for name, data in PACKAGE.items():
        (boot / name).write_bytes(data)
    (boot / 'Install').write_bytes(script(mode))
    (boot / 'devs/Kickstarts/kick40068.A1200').touch()
    (boot / 'devs/Kickstarts/kick40068.A1200.RTB').touch()
    for viewer, rc in (('multiview', 20 if mode == 'fresh' else 0), ('more', 0)):
        (boot / viewer).write_text(f'.key FILE/A\nEcho "<FILE>" >DH2:{viewer}-readme\nQuit {rc}\n')
    (boot / 'env/WHDLInstPath').write_text('DH2:previous parent')
    images = [IMAGES / f'disk{n}.img' for n in range(1, 6)]
    (base / 'disks').mkdir()
    for n, image in enumerate(images, 1):
        data = bytearray(image.read_bytes())
        if mode == 'bad-disks' and n == 3:
            data[900000] ^= 1
        (base / f'disks/disk{n}.img').write_bytes(data)
    if mode == 'files':
        (base / 'files').mkdir()
        for n, image in enumerate(images, 1):
            (base / f'files/XWING.00{n}').write_bytes(fat12_file(image, f'XWING.00{n}'))
        for name in COPIED:
            (base / 'files' / name).write_bytes(fat12_file(images[0], name))
    data = out / ('XWing/data' if mode == 'upgrade' else 'X-Wing/data')
    if mode in ('keep', 'replace', 'upgrade', 'remove', 'bad-disks'):
        data.mkdir(parents=True)
        for name, path in REFERENCE_FILES.items():
            (data / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, data / name)
        if mode == 'upgrade':
            for name in ('LANDRU.CFG', 'OPTIONS.CFG'):
                shutil.copyfile(ADLIB_SETUP / name, data / name)
        (data / 'PILOT.PLT').write_bytes(PILOT)
        if mode == 'upgrade':
            (data / 'BATTLE.CLP').write_bytes(FILM)
        if mode in ('keep', 'replace'):
            (data / DAMAGED).write_bytes(b'damaged')
        (data.parent / 'old-marker').touch()
    (out / 'unrelated').write_text('keep')
    (boot / 'c').mkdir(exist_ok=True)
    shutil.copyfile(SETPATCH, boot / 'c/SetPatch')
    (boot / 's/startup-sequence').write_text(
        'DH0:c/SetPatch QUIET\nCD DH0:\nStack 16384\nDF0:C/Assign C: DF0:C\nDF0:C/Assign LIBS: DF0:Libs\n'
        'DF0:C/Assign DEVS: DH0:devs\nDF0:C/Assign ENV: RAM:\nDF0:C/Assign ENVARC: DH0:env\n'
        'Copy ENVARC:WHDLInstPath ENV:WHDLInstPath\nDF0:C/Assign T: RAM:\nPath DH0: ADD\nC:LoadWB\n'
        'Installer SCRIPT DH0:Install APPNAME X-Wing MINUSER NOVICE DEFUSER NOVICE '
        'LOGFILE DH2:installer.log NOPRETEND >DH2:console.log\nEcho done >DH2:finished\n')


def emulate(base, seconds):
    with (base / 'emulator.log').open('w') as log:
        emu = subprocess.Popen([os.environ.get('FSUAE', 'fs-uae'), '--amiga_model=A1200', '--cpu=68020',
            '--uae_cpu_model=68020', '--jit_compiler=0', '--chip_memory=2048', '--fast_memory=8192',
            '--kickstart_file=' + str(KICK), '--hard_drive_0=' + str(base / 'boot'), '--hard_drive_0_priority=10',
            '--hard_drive_2=' + str(base), '--floppy_drive_0=' + str(WORKBENCH), '--audio_driver=dummy',
            '--warp_mode=1', '--fullscreen=0', '--automatic_input_grab=0',
            '--base_dir=' + str(base / 'fsuae'), '--state_dir=' + str(base / 'state')],
            stdout=log, stderr=log, env=dict(os.environ, SDL_AUDIODRIVER='dummy'))
        try:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline and not (base / 'finished').exists():
                if emu.poll() is not None:
                    raise SystemExit(f'FAIL: emulator exited ({base})')
                time.sleep(.25)
            time.sleep(1)
        finally:
            emu.terminate()
            try:
                emu.wait(timeout=5)
            except subprocess.TimeoutExpired:
                emu.kill()
                emu.wait()
    assert (base / 'finished').exists(), f'Installer did not finish: {base}'


def check(mode, base):
    asked = lambda name: (base / name).exists()
    dest = base / 'out/X-Wing'
    data = dest / 'data'
    assert (base / 'multiview-readme').read_text().strip() == 'DH0:ReadMe'
    assert asked('more-readme') == (mode == 'fresh')
    assert (base / 'boot/env/WHDLInstPath').read_text().strip() == 'DH2:out'
    assert (base / 'out/unrelated').read_text() == 'keep'
    assert not (dest / 'InstallStaging').exists(), 'staging drawer left behind'
    existing = mode not in ('fresh', 'files', 'upgrade')
    assert asked('remove-asked') == existing
    assert asked('reuse-asked') == (mode in ('keep', 'replace', 'bad-disks'))
    assert asked('upgrade-told') == (mode == 'upgrade')
    if mode == 'bad-disks':
        # Refused before anything was copied: the earlier install is unchanged.
        assert asked('disks-refused')
        assert not (data / 'X-Wing').exists() and not (dest / 'X-Wing.slave').exists()
        files = {k: p for k, p in tree(data).items() if k != 'PILOT.PLT'}
        assert files.keys() == REFERENCE_FILES.keys()
        assert (data / 'PILOT.PLT').read_bytes() == PILOT
        return
    assert asked('disks-asked') == (mode in ('fresh', 'files', 'replace', 'upgrade', 'remove'))
    files = tree(data)
    assert files.pop('X-WING') and (data / 'X-Wing').read_bytes() == PACKAGE['X-Wing']
    kept = mode in ('keep', 'replace')
    pilot = files.pop('PILOT.PLT', None)
    assert (pilot is not None) == (kept or mode == 'upgrade'), 'PILOT.PLT'
    if mode == 'upgrade':
        # Copied from 0.1's drawer, which is left as it was.
        assert pilot.read_bytes() == PILOT and files.pop('BATTLE.CLP').read_bytes() == FILM
        old = base / 'out/XWing'
        assert (old / 'old-marker').exists() and (old / 'data/PILOT.PLT').read_bytes() == PILOT
        assert (old / 'data/LANDRU.CFG').read_bytes() == (ADLIB_SETUP / 'LANDRU.CFG').read_bytes()
    assert files.keys() == REFERENCE_FILES.keys(), sorted(files.keys() ^ REFERENCE_FILES.keys())[:8]
    for name, path in REFERENCE_FILES.items():
        expected = b'damaged' if mode == 'keep' and name == DAMAGED else path.read_bytes()
        assert files[name].read_bytes() == expected, name
    assert (dest / 'X-Wing.slave').read_bytes() == PACKAGE['X-Wing.slave']
    assert (dest / 'ReadMe').exists() and (dest / 'ReadMe.info').exists()
    assert (dest / 'old-marker').exists() == kept
    # X-Wing.info starts the program directly, X-Wing (WHDLoad).info through the slave;
    # both are the package's game icon (a project icon, do_Type 4) with a 16 KiB stack.
    direct, whdload = (dest / 'X-Wing.info').read_bytes(), (dest / 'X-Wing (WHDLoad).info').read_bytes()
    for icon in (direct, whdload):
        assert icon[:4] == b'\xe3\x10\0\1' and icon[48] == 4 and icon[74:78] == (16384).to_bytes(4, 'big')
    assert b'data/X-Wing\0' in direct and b'WHDLoad' not in direct and b'Slave' not in direct
    assert b'WHDLoad\0' in whdload
    whdload = whdload.lower()
    assert b'slave=x-wing.slave\0' in whdload and b'preload\0' in whdload


REFERENCE_FILES = {}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('modes', nargs='*', default=MODES)
    p.add_argument('--archive', type=Path)
    p.add_argument('--keep', type=Path)
    args = p.parse_args()
    assert set(args.modes) <= set(MODES), args.modes
    if args.archive:
        names = subprocess.run(['lha', 'lq', str(args.archive)], check=True, capture_output=True, text=True).stdout
        for line in names.splitlines():
            m = re.search(r' \d\d:\d\d (.+)$', line)  # lha lq: ... Nov 19 00:00 NAME
            name = m[1] if m else ''
            if name.startswith(PREFIX + '/'):
                PACKAGE[name[len(PREFIX) + 1:]] = subprocess.run(['lha', 'pq', str(args.archive), name],
                                                                 check=True, capture_output=True).stdout
        assert {'Install', 'X-Wing', 'X-Wing.slave', 'X-WingInstallData'} <= PACKAGE.keys(), sorted(PACKAGE)
    else:
        PACKAGE.update(members(ROOT / 'amiga/out/XWing-release.exe'))
    REFERENCE_FILES.update(host_tree(REFERENCE))
    assert len(REFERENCE_FILES) == FILES, len(REFERENCE_FILES)
    (ROOT / 'tmp').mkdir(exist_ok=True)
    for mode in args.modes:
        base = Path(tempfile.mkdtemp(prefix=f'installer-{mode}-', dir=ROOT / 'tmp'))
        print(base, flush=True)
        fixture(mode, base)
        emulate(base, 1800)
        check(mode, base)
        print(f'PASS: Installer {mode}', flush=True)
        if args.keep and mode == args.modes[-1]:
            shutil.rmtree(args.keep, ignore_errors=True)
            shutil.copytree(base / 'out/X-Wing', args.keep, ignore=shutil.ignore_patterns('*.uaem'))
            shutil.copyfile(base / 'out/X-Wing.info', args.keep.with_name(args.keep.name + '.info'))
            print('Installed drawer:', args.keep)
        shutil.rmtree(base)


if __name__ == '__main__':
    main()
