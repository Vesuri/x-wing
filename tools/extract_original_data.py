#!/usr/bin/env python3
"""Extract the pinned BinHex/Compact Pro demo, preserving both forks and Finder data.

Adapted from Prince of Persia 2's extract_original_data.py at the commit in
manifest/references.tsv. Every original name holds its data fork (including
empty forks); name.rsrc holds its raw resource fork when present; name.finfo is
Alone in the Dark's 32-byte AFI1 record. Scratch lives under ignored tmp/ and is
removed on exit. A differing destination moves to .replaced/.
"""
from __future__ import annotations

import argparse
import atexit
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
from pathlib import Path, PurePosixPath
import struct
import subprocess
import tempfile

import _amigaxdev
from amigaxdev.mac.resource_fork import parse_resource_fork

ROOT = _amigaxdev.ROOT
FOLDER = 'X-Wing Demo ƒ'
APPLICATION = 'X-Wing'
ARCHIVE_NAME = 'tmp/originals/xwingdemo.sea__1.hqx'
ARCHIVE = ROOT / ARCHIVE_NAME
DESTINATION = ROOT / 'tmp/runtime-data'
FILES, DIRECTORIES = 67, 16


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pins(path):
    result = {}
    for line in path.read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name in result or len(digest) != 64:
            raise ValueError('MANIFEST / INVALID ENTRY: ' + name)
        result[name] = digest
    return result


def verify_archive(archive):
    digest = sha256(archive)
    if digest != pins(ROOT / 'manifest/originals.sha256')[ARCHIVE_NAME]:
        raise ValueError('ARCHIVE / SHA-256 MISMATCH')
    return digest


def apple_double(path):
    """Strict version of Alone in the Dark's AppleDouble resource/Finder reader."""
    raw = path.read_bytes()
    if len(raw) < 26 or raw[:8] != bytes.fromhex('0005160700020000'):
        raise ValueError('APPLEDOUBLE / HEADER: ' + str(path))
    count = struct.unpack_from('>H', raw, 24)[0]
    end = 26 + 12 * count
    if end > len(raw):
        raise ValueError('APPLEDOUBLE / TABLE')
    entries, extents = {}, []
    for i in range(count):
        kind, offset, size = struct.unpack_from('>III', raw, 26 + 12 * i)
        if kind in entries or offset < end or offset + size > len(raw):
            raise ValueError('APPLEDOUBLE / ENTRY')
        if any(offset < b and a < offset + size for a, b in extents):
            raise ValueError('APPLEDOUBLE / OVERLAP')
        extents.append((offset, offset + size))
        entries[kind] = raw[offset:offset + size]
    return entries


def mac_date(value):
    # lsar is forced to UTC; never use host filesystem birthtime/mtime.
    date = datetime.strptime(value, '%Y-%m-%d %H:%M:%S %z')
    return int((date - datetime(1904, 1, 1, tzinfo=timezone.utc)).total_seconds())


def metadata(records, finder):
    if len(finder) != 32:
        raise ValueError('METADATA / FINDER SIZE')
    first = records[0]
    for record in records:
        declared = struct.pack('>IIH', record['XADFileType'],
                               record['XADFileCreator'], record['XADFinderFlags'])
        if finder[:10] != declared:
            raise ValueError('METADATA / FINDER SOURCE DISAGREEMENT')
        for field in ('XADCreationDate', 'XADLastModificationDate'):
            if record[field] != first[field]:
                raise ValueError('METADATA / FORK DATE DISAGREEMENT')
    body = b'AFI1' + finder[:16] + struct.pack(
        '>II', mac_date(first['XADCreationDate']), mac_date(first['XADLastModificationDate']))
    checksum = 2166136261
    for byte in body:
        checksum = ((checksum ^ byte) * 16777619) & 0xffffffff
    return body + struct.pack('>I', checksum)


def unpack(archive, scratch):
    verify_archive(archive)
    env = dict(os.environ, TZ='UTC')
    listing = json.loads(subprocess.check_output(['lsar', '-j', str(archive)], env=env))
    if listing['lsarFormatName'] != 'BinHex':
        raise ValueError('ARCHIVE / EXPECTED BINHEX')
    groups, directories = {}, set()
    for entry in listing['lsarContents']:
        name = PurePosixPath(entry['XADFileName'])
        if name.is_absolute() or '..' in name.parts or name.parts[0] != FOLDER:
            raise ValueError('ARCHIVE / UNEXPECTED PATH')
        name.as_posix().encode('mac_roman')  # every name must be an HFS name
        if any(len(part.encode('mac_roman')) > 31 for part in name.parts):
            raise ValueError('ARCHIVE / NAME TOO LONG')
        if entry.get('XADIsDirectory'):
            directories.add(name.as_posix())
            continue
        groups.setdefault(name.as_posix(), []).append(entry)
    if (len(groups), len(directories)) != (FILES, DIRECTORIES):
        raise ValueError('ARCHIVE / FILE OR DIRECTORY COUNT')
    if FOLDER + '/' + APPLICATION not in groups:
        raise ValueError('ARCHIVE / APPLICATION MISSING')
    if any(str(PurePosixPath(p).parent) not in directories for p in groups):
        raise ValueError('ARCHIVE / UNLISTED PARENT DIRECTORY')
    subprocess.run(['unar', '-q', '-k', 'visible', '-o', str(scratch / 'unpacked'),
                    str(archive.resolve())], check=True, env=env)
    output = scratch / 'runtime-data'
    output.mkdir()
    for relative in sorted(directories):
        (output / relative).mkdir(parents=True, exist_ok=True)
    for relative, records in sorted(groups.items()):
        source = scratch / 'unpacked' / relative
        if source.is_symlink():
            raise ValueError('EXTRACT / SYMLINK: ' + relative)
        sizes = {}
        for record in records:
            resource = bool(record.get('XADIsResourceFork'))
            if resource in sizes:
                raise ValueError('EXTRACT / DUPLICATE FORK: ' + relative)
            sizes[resource] = record['XADFileSize']
        companion = Path(str(source) + '.rsrc')
        if companion.exists():
            entries = apple_double(companion)
            finder = entries.get(9, b'')
            resource = entries.get(2, b'')
        else:
            # unar writes FinderInfo as an xattr for data-only files on macOS.
            finder = bytes.fromhex(subprocess.check_output(
                ['xattr', '-px', 'com.apple.FinderInfo', str(source)], text=True))
            resource = b''
        data = source.read_bytes() if source.is_file() else b''
        if len(data) != sizes.get(False, 0) or len(resource) != sizes.get(True, 0):
            raise ValueError('EXTRACT / FORK SIZE: ' + relative)
        if resource:
            parse_resource_fork(resource, relative)
        target = output / relative
        target.write_bytes(data)
        if resource:
            Path(str(target) + '.rsrc').write_bytes(resource)
        Path(str(target) + '.finfo').write_bytes(metadata(records, finder))
    return output, groups, directories


def hashes(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('OUTPUT / SYMLINK: ' + str(path))
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = sha256(path)
    return result


def manifest_name(name):
    # Keep the manifest one line per file: escape the control characters in names.
    return name.encode('unicode_escape').decode('ascii')


def verify_output(directory):
    actual = {manifest_name(k): v for k, v in hashes(directory).items()}
    expected = pins(ROOT / 'manifest/runtime-data.sha256')
    if actual != expected:
        changed = sorted(k for k in actual.keys() | expected.keys()
                         if actual.get(k) != expected.get(k))
        raise ValueError('OUTPUT / SHA-256 OR FILE SET MISMATCH: ' + ', '.join(changed))
    return actual


def scratch_directory():
    (ROOT / 'tmp').mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='extract-', dir=ROOT / 'tmp'))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    return directory


def install(output, destination):
    # Keep the entire previous tree, including saves and unexpected files.
    if destination.is_symlink():
        raise ValueError('DESTINATION / SYMLINK')
    if destination.exists():
        if destination.is_dir() and hashes(destination) == hashes(output):
            return
        backup = ROOT / '.replaced'
        backup.mkdir(exist_ok=True)
        holder = Path(tempfile.mkdtemp(prefix='runtime-data-', dir=backup))
        destination.rename(holder / destination.name)
        print('Previous output retained at', (holder / destination.name).relative_to(ROOT))
    destination.parent.mkdir(parents=True, exist_ok=True)
    output.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--print-manifest', action='store_true',
                        help='print the output hashes instead of verifying them')
    args = parser.parse_args()
    output, groups, _ = unpack(ARCHIVE, scratch_directory())
    if args.print_manifest:
        for name, digest in hashes(output).items():
            print(digest + '  ' + manifest_name(name))
        return
    result = verify_output(output)
    install(output, DESTINATION)
    verify_output(DESTINATION)
    print(f'EXTRACT PASS: {len(groups)} original files; {len(result)} fork/metadata files verified')


if __name__ == '__main__':
    main()
