"""The patched DOSBox-X reference emulator: location and verification.

The tree is $XWING_DOSBOX_X_SRC (default ~/.local/src/xwing-dosbox-x), built by
tools/build_dosbox_x.sh. verify() requires HEAD at the pinned tag, every file the patch
series touches equal to tools/patches/ORDER applied to that tag, no other tracked file
changed (generated *.in files aside), and a binary newer than every patched file.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get('XWING_DOSBOX_X_SRC', Path.home() / '.local/src/xwing-dosbox-x'))
COMMIT = '4f19017c5f565dc40d01fede0f1382892e7243d7'
DOSBOX = SOURCE / 'src/dosbox-x'
PATCHES = ROOT / 'tools/patches'


def git(*args, env=None, check=True):
    return subprocess.run(['git', '-C', str(SOURCE), *args], capture_output=True, text=True,
                          env=env, check=check).stdout


def expected_tree():
    """Tree id of the pinned tag with the patch series applied, built in a scratch index."""
    with tempfile.TemporaryDirectory() as scratch:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(scratch) / 'index'))
        git('read-tree', COMMIT, env=env)
        for patch in (PATCHES / 'ORDER').read_text().split():
            result = subprocess.run(['git', '-C', str(SOURCE), 'apply', '--cached',
                                     str(PATCHES / patch)], capture_output=True, text=True, env=env)
            if result.returncode:
                raise ValueError(f'DOSBOX-X / {patch} DOES NOT APPLY IN ORDER: {result.stderr.strip()}')
        return git('write-tree', env=env).strip()


def verify():
    if git('rev-parse', 'HEAD').strip() != COMMIT:
        raise ValueError('DOSBOX-X / SOURCE IS NOT THE PINNED TAG; run make dos-emulator')
    tree = expected_tree()
    touched = git('diff', '--name-only', COMMIT, tree).split()
    for path in touched:
        want = git('rev-parse', f'{tree}:{path}').strip()
        have = git('hash-object', '--no-filters', path).strip() if (SOURCE / path).is_file() else ''
        if have != want:
            raise ValueError(f'DOSBOX-X / {path} DIFFERS FROM THE PATCH SERIES; run make dos-emulator')
    stray = [p for p in git('diff', '--name-only', COMMIT).split()
             if p not in touched and not p.endswith('.in')]
    if stray:
        raise ValueError('DOSBOX-X / UNEXPECTED CHANGES: ' + ', '.join(stray[:10]))
    newest = max((SOURCE / p).stat().st_mtime for p in touched)
    if not DOSBOX.is_file() or DOSBOX.stat().st_mtime < newest:
        raise ValueError('DOSBOX-X / BINARY MISSING OR OLDER THAN ITS SOURCE; run make dos-emulator')
