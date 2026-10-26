#!/usr/bin/env python3
"""Install the verified demo folder on a fresh HFS volume, adapted from Prince of Persia 2."""
import argparse
from pathlib import Path
import struct
import subprocess

from extract_original_data import DESTINATION, FOLDER, scratch_directory, verify_output


def crc16(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xffff
    return crc


def macbinary(source):
    data = source.read_bytes()
    fork = Path(str(source) + '.rsrc')
    resource = fork.read_bytes() if fork.exists() else b''
    info = Path(str(source) + '.finfo').read_bytes()
    name = source.name.encode('mac_roman')
    header = bytearray(128)
    header[1] = len(name)
    header[2:2+len(name)] = name
    header[65:73] = info[4:12]
    header[73] = info[12]
    header[75:81] = info[14:20]
    header[101] = info[13]
    struct.pack_into('>II', header, 83, len(data), len(resource))
    header[91:99] = info[20:28]
    header[122] = header[123] = 129
    struct.pack_into('>H', header, 124, crc16(header[:124]))
    pad = lambda b: b + bytes(-len(b) % 128)
    return bytes(header) + pad(data) + pad(resource), data, resource


def hfs(*args):
    # hfsutils takes HFS names as raw Mac Roman bytes.
    return subprocess.check_output([a if isinstance(a, bytes) else str(a).encode('mac_roman')
                                    for a in args], stderr=subprocess.STDOUT).decode('mac_roman')


def hfs_path(parent, relative):
    return parent + ':' + relative.replace('/', ':')


def install(volume):
    verified = verify_output(DESTINATION)
    scratch = scratch_directory()
    hfs('hmount', str(volume))
    try:
        parent = ':Desktop Folder' if 'Desktop Folder' in hfs('hls', '-1a', ':').splitlines() else ''
        if FOLDER in hfs('hls', '-1a', parent + ':').splitlines():
            raise ValueError('REFERENCE / GAME FOLDER ALREADY EXISTS')
        directories = sorted(p.relative_to(DESTINATION).as_posix()
                             for p in DESTINATION.rglob('*') if p.is_dir())
        for relative in directories:
            hfs('hmkdir', hfs_path(parent, relative))
        sources = sorted(p for p in (q.relative_to(DESTINATION).as_posix()
                                     for q in DESTINATION.rglob('*.finfo')))
        for i, finfo in enumerate(sources):
            relative = finfo[:-6]
            blob, data, resource = macbinary(DESTINATION / relative)
            (scratch / (str(i) + '.bin')).write_bytes(blob)
            target = hfs_path(parent, relative)
            hfs('hcopy', '-m', scratch / (str(i) + '.bin'), target)
            # MacBinary round-trip independently checks both fork lengths and bytes.
            check = scratch / (str(i) + '-roundtrip.bin')
            hfs('hcopy', '-m', target, check)
            raw = check.read_bytes()
            # hcopy clears only Finder's initialized bit so the new folder lays out icons.
            expected = bytearray(blob[:128]); expected[73] &= 0xfe
            fields = list(range(65, 81)) + [101] + list(range(91, 99))
            if any(raw[j] != expected[j] for j in fields):
                raise ValueError('REFERENCE / INSTALLED METADATA MISMATCH: ' + relative)
            data_size, resource_size = struct.unpack_from('>II', raw, 83)
            resource_start = 128 + ((data_size + 127) // 128) * 128
            if (raw[128:128+data_size] != data or
                    raw[resource_start:resource_start+resource_size] != resource):
                raise ValueError('REFERENCE / INSTALLED FORK MISMATCH: ' + relative)
        print(f'INSTALL PASS: {len(directories)} folders, {len(sources)} files; '
              'both forks and Finder metadata verified')
    finally:
        hfs('humount')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('volume', type=Path)
    install(parser.parse_args().volume)
