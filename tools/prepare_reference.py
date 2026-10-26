#!/usr/bin/env python3
"""Build a fresh, verified System 7.5.5 volume with the demo installed, never reusing a run."""
import argparse
import hashlib
from pathlib import Path
import zipfile

from extract_original_data import ROOT, pins, verify_output, DESTINATION
from install_reference_volume import install

SYSTEM = 'ref/mame/dl/755_2GB_drive.zip'


def verify_inputs():
    for name, digest in pins(ROOT/'manifest/reference-inputs.sha256').items():
        with (ROOT/name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('REFERENCE / INPUT HASH MISMATCH: ' + name)
    verify_output(DESTINATION)


def sparse_copy(source, destination):
    """Preserve every disk byte while leaving all-zero blocks unallocated."""
    while block := source.read(1024*1024):
        if block == bytes(len(block)):
            destination.seek(len(block), 1)
        else:
            destination.write(block)
    destination.truncate()  # A trailing hole must still have its logical size.


def prepare(destination):
    destination = destination.absolute()
    if destination.resolve() != destination or not destination.is_relative_to(ROOT/'ref/mame/runs'):
        raise ValueError('REFERENCE / RUN MUST BE UNDER ref/mame/runs WITHOUT SYMLINKS')
    if destination.exists():
        raise ValueError('REFERENCE / RUN ALREADY EXISTS; choose a new run name')
    verify_inputs()
    destination.mkdir(parents=True)
    for name in ('cfg', 'nvram', 'snap'):
        (destination/name).mkdir()
    volume = destination/'volume.hd'
    with zipfile.ZipFile(ROOT/SYSTEM) as archive:
        if archive.namelist() != ['755_2GB_drive.dsk']:
            raise ValueError('REFERENCE / SYSTEM ARCHIVE MEMBERS')
        with archive.open('755_2GB_drive.dsk') as source, volume.open('wb') as output:
            sparse_copy(source, output)
    install(volume)
    print('PREPARE PASS:', destination.relative_to(ROOT))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    prepare(parser.parse_args().destination)
