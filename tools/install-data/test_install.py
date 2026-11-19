#!/usr/bin/env python3
"""XWingInstallData on the host: exact files, sources, refusals, cleanup, cancel.

    python3 tools/install-data/test_install.py build/install-data/XWingInstallData

Inputs are local, never shipped: the five floppy images (XWING_IMAGES, default
tmp/dos/disks, pinned in manifest/dos-disks.sha256). Oracle: the directory the
original INSTALL.EXE installed and configured in DOSBox-X (XWING_REFERENCE,
default tmp/dos/configured/XWING), pinned in manifest/dos-installed.sha256 and
manifest/dos-configured.sha256. Adapted from Secret Weapons of the Luftwaffe's.
"""
import hashlib
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGES = Path(os.environ.get('XWING_IMAGES', ROOT / 'tmp/dos/disks'))
REFERENCE = Path(os.environ.get('XWING_REFERENCE', ROOT / 'tmp/dos/configured/XWING'))
PINS = [ROOT / 'manifest/dos-installed.sha256', ROOT / 'manifest/dos-configured.sha256']
COPIED = ('INSTALL.EXE', 'DETECT.EXE', 'READ.ME')
FILES = 284


def tree(base):
    return {p.relative_to(base).as_posix().upper(): p for p in base.rglob('*') if p.is_file()}


def fat12_file(image, name):
    """A file of a FAT12 image, read independently of the helper."""
    b = image.read_bytes()
    le = lambda o, n=2: int.from_bytes(b[o:o + n], 'little')
    bps, spc, reserved, fats, roots, spf = le(11), b[13], le(14), b[16], le(17), le(22)
    fat, root = reserved * bps, (reserved + fats * spf) * bps
    data = root + roots * 32
    stem, _, ext = name.partition('.')
    want = (stem.ljust(8) + ext.ljust(3)).encode()
    for e in range(root, root + roots * 32, 32):
        if b[e:e + 11] == want:
            size, c, out = le(e + 28, 4), le(e + 26), bytearray()
            while 2 <= c < 0xff8:
                out += b[data + (c - 2) * spc * bps:data + (c - 1) * spc * bps]
                v = le(fat + c + c // 2)
                c = v >> 4 if c & 1 else v & 0xfff
            return bytes(out[:size])
    raise SystemExit(f'{name} not in {image}')


def main():
    binary = Path(sys.argv[1]).resolve()
    images = [IMAGES / f'disk{n}.img' for n in range(1, 6)]
    pins = {}
    for pin in PINS:
        for line in pin.read_text().splitlines():
            digest, name = line.split(maxsplit=1)
            pins[name.upper()] = digest
    expected = tree(REFERENCE)
    assert expected.keys() == pins.keys() and len(pins) == FILES, sorted(expected.keys() ^ pins.keys())[:10]
    for k, p in expected.items():
        assert hashlib.sha256(p.read_bytes()).hexdigest() == pins[k], k
    (ROOT / 'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='xwing-install-', dir=ROOT / 'tmp') as td:
        base = Path(td)

        def run(source, dest, good):
            r = subprocess.run([binary, source, dest], capture_output=True, text=True)
            assert (r.returncode == 0) == good, f'{source} -> {dest}\n{r.stdout}{r.stderr}'
            if not good:
                assert 'existing installations were not changed' in r.stdout or 'Destination exists' in r.stdout, r.stdout
            return r.stdout

        def drawer(name, files):
            d = base / name
            d.mkdir()
            for target, data in files.items():
                (d / target).write_bytes(data)
            return d

        def verify(dest):
            got = tree(dest)
            assert got.keys() == expected.keys(), sorted(got.keys() ^ expected.keys())[:10]
            for k, p in expected.items():
                assert got[k].read_bytes() == p.read_bytes(), k

        disks = [i.read_bytes() for i in images]
        source = drawer('images', {f'disk{n}.img': d for n, d in enumerate(disks, 1)})
        assert f'Installed {FILES}' in run(source, base / 'a', True)
        verify(base / 'a')
        volumes = [fat12_file(i, f'XWING.00{n}') for n, i in enumerate(images, 1)]
        loose = {f'XWING.00{n}': v for n, v in enumerate(volumes, 1)}
        loose.update({name: fat12_file(images[0], name) for name in COPIED})
        files = drawer('files', loose)
        run(files, base / 'b', True)
        verify(base / 'b')
        # An existing destination is refused and left as it was.
        keep = base / 'a/XWING.EXE'
        stamp = keep.stat().st_mtime_ns
        assert 'Destination exists' in run(source, base / 'a', False)
        assert keep.stat().st_mtime_ns == stamp
        # Missing, truncated or damaged volumes or disk 1 files create nothing.
        flipped = bytearray(volumes[2])
        flipped[700000] ^= 1
        without = lambda name: {k: v for k, v in loose.items() if k != name}
        swapped = {f'disk{n}.img': d for n, d in enumerate(disks, 1)}
        swapped['disk2.img'], swapped['disk3.img'] = disks[2], disks[1]
        for index, bad in enumerate((
                without('XWING.005'),
                dict(loose, **{'XWING.004': volumes[3][:-1]}),
                dict(loose, **{'XWING.003': bytes(flipped)}),
                without('DETECT.EXE'),
                dict(loose, **{'READ.ME': loose['READ.ME'][:-1] + b'!'}),
                swapped,
                dict(swapped, **{'disk1.img': disks[0][:4096]}))):
            dest = base / f'bad-{index}'
            run(drawer(f'badsrc-{index}', bad), dest, False)
            assert not dest.exists(), dest
        # Cancel (Ctrl-C on the Amiga) removes what the run created.
        dest = base / 'cancelled'
        proc = subprocess.Popen([binary, source, dest], stdout=subprocess.PIPE, text=True)
        while 'Extracting' not in proc.stdout.readline():
            pass
        proc.send_signal(signal.SIGTERM)
        out = proc.communicate(timeout=60)[0]
        assert proc.returncode == 20 and 'cancelled' in out, out
        assert not dest.exists()
    print(f'PASS: {FILES} files equal the DOS install and configuration from images and loose '
          'files; refusal, damaged/missing disks and files, cancel cleanup')


if __name__ == '__main__':
    main()
