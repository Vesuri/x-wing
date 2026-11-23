#!/usr/bin/env python3
"""Audit the exact minimal LHA release, its checksums and its members.

    python3 tools/check_release.py dist/X-Wing-$(cat VERSION).lha [--exe amiga/out/XWing-release.exe]

Copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and
adapted. Every member is decoded independently with Lhasa (`lha pq`) and must
equal its build output. No member may equal an original (package_release.py's
lists) or hold any 64-byte block of the configured DOS install
(tmp/dos/configured-sb/XWING, every file: the release's Sound Blaster configuration) or of the five archive volumes
(tmp/dos/disks images), forward or byte-reversed (guest RAM order).
"""
import argparse
import hashlib
import os
import struct
import subprocess
from pathlib import Path
from package_release import ORIGINAL_HASHES, PREFIX, ROOT, crc16, members

DATE = '22.11.2026'
STAMP = (((2026 - 1980) << 9) | (11 << 5) | 22) << 16
INSTALL = Path(os.environ.get('XWING_REFERENCE', ROOT / 'tmp/dos/configured-sb/XWING'))
IMAGES = Path(os.environ.get('XWING_IMAGES', ROOT / 'tmp/dos/disks'))
SIZE = 64


def original_blocks():
    out, files = set(), sorted(p for p in INSTALL.rglob('*') if p.is_file())
    files += sorted(IMAGES.glob('disk[1-5].img'))
    assert len(files) == 289, f'expected the 284 installed files and 5 images, found {len(files)}'
    for p in files:
        d = p.read_bytes()
        for a in range(0, len(d) - SIZE + 1, SIZE):
            b = d[a:a + SIZE]
            if len(set(b)) > 8:
                out.update((b, b[::-1]))
    assert len(out) > 100000, 'original blocks missing'
    return out


def contains_block(data, blocks):
    # Any aligned original block occurs whole in data, so slide by one over data.
    return any(data[i:i + SIZE] in blocks for i in range(len(data) - SIZE + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--exe', type=Path, default=ROOT / 'amiga/out/XWing-release.exe')
    args = parser.parse_args()
    expected = members(args.exe)
    raw = args.archive.read_bytes()
    pos, payloads = 0, {}
    while pos < len(raw) and raw[pos]:
        size = raw[pos]
        header = raw[pos + 2:pos + 2 + size]
        assert len(header) == size and sum(header) & 255 == raw[pos + 1], 'bad header checksum'
        assert header[:5] == b'-lh5-' and header[18] == 0, 'expected level-zero LH5'
        packed, unpacked = struct.unpack_from('<II', header, 5)
        assert struct.unpack_from('<I', header, 13)[0] == STAMP, 'wrong release date'
        n = header[19]
        assert size == 22 + n
        archive_name = header[20:20 + n].decode('ascii').replace('\\', '/')
        if archive_name == PREFIX + '.info':
            name = '@drawer'
        else:
            assert archive_name.startswith(PREFIX + '/'), 'wrong installation drawer'
            name = archive_name[len(PREFIX) + 1:]
        assert name in set(expected) | {'@drawer'} and name not in payloads, 'unexpected or duplicate file: ' + name
        pos += size + 2
        assert len(raw[pos:pos + packed]) == packed, 'truncated payload'
        data = subprocess.run(['lha', 'pq', str(args.archive.resolve()), archive_name],
                              check=True, capture_output=True).stdout
        assert len(data) == unpacked and crc16(data) == struct.unpack_from('<H', header, 20 + n)[0], 'bad payload CRC'
        payloads[name] = data
        pos += packed
    assert raw[pos:] == b'\0' and set(payloads) == set(expected) | {'@drawer'}, 'wrong archive contents'
    for name, data in expected.items():
        assert payloads[name] == data, 'member differs from build output: ' + name
    blocks = original_blocks()
    for name, data in payloads.items():
        assert hashlib.sha256(data).hexdigest() not in ORIGINAL_HASHES, 'original file: ' + name
        assert not contains_block(data, blocks), 'original bytes in ' + name
    for name in ('X-Wing', 'X-Wing.slave', 'X-WingInstallData'):
        assert payloads[name][:4] == b'\0\0\3\xf3', 'not an Amiga HUNK executable: ' + name
    for name, kind in (('X-Wing.inf', 4), ('ReadMe.info', 4), ('Install.info', 4), ('@drawer', 2)):
        assert payloads[name][:4] == b'\xe3\x10\0\1' and payloads[name][48] == kind, 'bad icon: ' + name
    version = (ROOT / 'VERSION').read_text().strip().encode()
    for name in ('X-Wing', 'X-Wing.slave', 'X-WingInstallData'):
        assert b'$VER: ' + name.encode() + b' ' + version + b' (' + DATE.encode() + b')' in payloads[name], 'version: ' + name
    assert b'$VER: Install ' + version + b' (' + DATE.encode() + b')' in payloads['Install']
    assert b'version ' + version + b' (' + DATE.encode() + b'):' in payloads['ReadMe']
    for heading in (b'EARLY ALPHA', b'not\n optimized', b'What to expect:', b'Requirements:', b'Starting:', b'Installation:', b'Playing:',
                    b'History:', b'Contact:', b'Credits:', b'https://github.com/Vesuri/x-wing'):
        assert heading in payloads['ReadMe'], heading
    # WHDLoadSlave header, whdload.i: flags +14, BaseMem +16, keyexit +31, ExpMem +32.
    slave = payloads['X-Wing.slave']
    signature = b'\x70\xff\x4e\x75WHDLOADS'
    assert slave.count(signature) == 1, 'ambiguous WHDLoad header'
    header = slave.index(signature)
    flags = struct.unpack_from('>H', slave, header + 14)[0]
    assert flags & 0x32 == 0x32, 'slave must set NoError, Req68020 and ReqAGA'
    assert struct.unpack_from('>I', slave, header + 16)[0] == 0x200000, 'expected 2 MiB Chip'
    assert struct.unpack_from('>I', slave, header + 32)[0] == 0x880000, 'expected 8 MiB game plus 512 KiB Kickstart'
    assert slave[header + 31] == 0x5f, 'Help must be the quit key'
    assert b'APPNAME=X-Wing\0' in payloads['Install.info']
    assert not any(n.lower().endswith(('.plt', '.cfg', '.dat', '.img', '.ima', '.exe', '.ovl', '.lfd', '.xid'))
                   for n in payloads)
    print(f'PASS: {len(payloads)} allowlisted LH5 members; independent decompression, CRCs, '
          'build identity, no original files or blocks, versions, slave header and icons')


if __name__ == '__main__':
    main()
