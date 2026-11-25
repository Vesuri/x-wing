#!/usr/bin/env python3
"""Create the minimal deterministic Amiga LHA distribution (LH5).

    python3 tools/package_release.py amiga/out/XWing-release.exe dist

Copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and
adapted. The members are an explicit allowlist; none may equal an original:
the hashes of release/originals.sha256 (the archive volumes) and of every
manifest that pins original material.
"""
import argparse
from pathlib import Path
import _amigaxdev  # noqa: F401  (verifies amigaxdev/release.py, manifest/mac-helpers.sha256)
from amigaxdev import release
from amigaxdev.release import crc16  # noqa: F401  (check_release.py imports it from here)

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_LISTS = ['release/originals.sha256'] + [f'manifest/{n}.sha256' for n in (
    'originals', 'dos-disks', 'dos-installed', 'dos-configured', 'reference-inputs',
    'runtime-data', 'films', 'donor-binaries')]
ORIGINAL_HASHES = {line.split()[0] for name in ORIGINAL_LISTS
                   for line in (ROOT / name).read_text().splitlines() if line.strip()}
PREFIX = 'X-Wing Install'
STAMP = release.dos_stamp(2026, 11, 25)
ICONS = ROOT / 'release/icons'


def installer_icon(game=False):
    # X-Wing.inf is distributed as is; Installer copies it to both game icons and configures them.
    return release.installer_icon(ICONS, 'X-Wing', game=game)


def members(executable):
    return {
        'X-Wing': executable.read_bytes(),
        'X-Wing.slave': (ROOT / 'build/whdload/XWing.slave').read_bytes(),
        'X-Wing.inf': installer_icon(game=True),
        'X-WingInstallData': (ROOT / 'build/install-data/XWingInstallData.exe').read_bytes(),
        'Install': (ROOT / 'release/Install').read_bytes(),
        'Install.info': installer_icon(),
        'ReadMe': (ROOT / 'release/ReadMe').read_bytes(),
        'ReadMe.info': release.template_icon(ICONS, 'readme.info.b64'),
        'LICENSE.LGPL.txt': (ROOT / 'tools/install-data/COPYING.LIB').read_bytes(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('executable', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    files = members(args.executable)
    release.refuse_originals(files, ORIGINAL_HASHES)
    archive = release.write(args.output_directory / f'X-Wing-{version}.lha',
                            release.archive(PREFIX, files, release.template_icon(ICONS, 'drawer.info.b64'), STAMP),
                            refuse_overwrite=True)
    print(f'{archive}: {len(files)} drawer contents plus drawer icon, {archive.stat().st_size} bytes')


if __name__ == '__main__':
    main()
