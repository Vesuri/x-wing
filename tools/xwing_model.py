"""Static model of X-Wing's files: root, overlay segments, music drivers, traces.

Adapted from Secret Weapons of the Luftwaffe's tools/swotl_model.py (commit pinned in
manifest/references.tsv), file half only. The overlay manager itself is modelled in P2.

Module address = module offset (the tracer's convention):
- root: offset in XWING.EXE's MZ load image;
- overlay file (`FRONTEND.OVL`, `FLIGHT.OVL`): offset in the file;
- music driver (`*.IMS`, loaded by INT 21h AX=4B03): offset in its MZ load image.

Overlay segments (MEASURED, XWING.EXE image offset 4A5Fh): 26 records of nine words,
ids 2-27: link segment, file-name offset, file position in paragraphs, a word that is
0400h in every record, size in paragraphs, fixup count, parent index (FFFFh for a file's
base segment), id, and a size word equal to the size or one less. In the file, a segment is
its fixup table (count x 4 bytes: offset, link segment) followed by its code at the next
paragraph. Loading puts the code at load segment + link segment and adds the load segment
to each fixup word, as for the root (MEASURED: all 1,696 FRONTEND base fixups in a
snapshot).
"""

from __future__ import annotations

import csv
import gzip
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REF = REPO / 'tmp/dos/configured/XWING'
RUNS = REPO / 'ref/dosbox/runs'
ROOT = 'XWING.EXE'
OVL_TABLE, OVL_COUNT, OVL_FIRST_ID = 0x4A5F, 26, 2
NAME_BASE = 0x4061  # file-name offset + this = image offset of the name (MEASURED)
DRIVERS = ['ADLIB.IMS', 'ADLIB_W.IMS', 'ROLAND.IMS', 'ROLAND_W.IMS', 'GMIDI.IMS', 'GMIDI_W.IMS']


@dataclass
class Segment:
    id: int
    file: str
    link_seg: int
    pos: int                    # file offset of the fixup table
    paras: int
    nfix: int
    parent: int

    @property
    def code(self) -> int:      # file offset of the first code byte
        return self.pos + ((self.nfix * 4 + 15) & ~15)


@dataclass
class Module:
    name: str
    data: bytes                 # file bytes (root and drivers: MZ load image), unrelocated
    fixups: list[int] = field(default_factory=list)  # module offsets of segment words
    segments: list[Segment] = field(default_factory=list)


def mz(path: Path) -> tuple[bytes, list[tuple[int, int]], tuple[int, int]]:
    data = path.read_bytes()
    last, pages, nrel, hdr = struct.unpack_from('<HHHH', data, 2)
    size = pages * 512 - (512 - last if last else 0) - hdr * 16
    ip, cs = struct.unpack_from('<HH', data, 0x14)
    relo = struct.unpack_from('<H', data, 0x18)[0]
    rels = [struct.unpack_from('<HH', data, relo + 4 * i) for i in range(nrel)]
    return data[hdr * 16: hdr * 16 + size], rels, (cs, ip)


def segments(image: bytes) -> list[Segment]:
    out = []
    for i in range(OVL_COUNT):
        seg, name_off, pos, _, paras, nfix, parent, oid, _ = struct.unpack_from(
            '<9H', image, OVL_TABLE + 18 * i)
        if oid != OVL_FIRST_ID + i:
            raise ValueError(f'overlay record {i}: id {oid}')
        start = NAME_BASE + name_off
        name = image[start:image.index(b'\0', start)].decode('ascii')
        out.append(Segment(oid, name, seg, pos * 16, paras, nfix, parent))
    return out


def load_modules(ref: Path = REF) -> dict[str, Module]:
    image, rels, _ = mz(ref / ROOT)
    mods = {ROOT: Module(ROOT, image, [seg * 16 + off for off, seg in rels])}
    for s in segments(image):
        m = mods.setdefault(s.file, Module(s.file, (ref / s.file).read_bytes()))
        m.segments.append(s)
        for k in range(s.nfix):
            off, fseg = struct.unpack_from('<HH', m.data, s.pos + 4 * k)
            m.fixups.append(s.code + (fseg - s.link_seg) * 16 + off)
    for name in DRIVERS:
        if (ref / name).exists():
            data, rels, _ = mz(ref / name)
            mods[name] = Module(name, data, [seg * 16 + off for off, seg in rels])
    return mods


def relocated(m: Module, load: int) -> bytearray:
    """Module bytes with every fixup word += load (segment)."""
    out = bytearray(m.data)
    for a in m.fixups:
        struct.pack_into('<H', out, a, (struct.unpack_from('<H', out, a)[0] + load) & 0xFFFF)
    return out


def entry(ref: Path = REF) -> int:
    _, _, (cs, ip) = mz(ref / ROOT)
    return cs * 16 + ip


def events_path(trace: Path) -> Path:
    return trace / 'events.csv.gz'


def events(trace: Path, kinds: tuple[str, ...] = ()):
    """Rows of events.csv.gz as lists [icount, kind, module, offset, detail]. With `kinds`,
    lines are filtered by grep first: the log can hold tens of millions of service lines."""
    path = events_path(trace)
    if not kinds:
        with gzip.open(path, 'rt', errors='replace') as f:
            next(f)
            for line in f:
                yield line.rstrip('\n').split(',', 4)
        return
    pattern = '|'.join(f',{k},' for k in kinds)
    proc = subprocess.Popen(f'gzip -dc "{path}" | grep -E "{pattern}"', shell=True,
                            stdout=subprocess.PIPE, text=True, errors='replace')
    for line in proc.stdout:
        row = line.rstrip('\n').split(',', 4)
        if len(row) == 5 and row[1] in kinds:
            yield row
    if proc.wait() not in (0, 1):
        raise ValueError(f'{path}: cannot read')


def runs(pattern: str = 'ms-*') -> list[Path]:
    return sorted(p / 'trace' for p in RUNS.glob(pattern) if (p / 'trace/summary.txt').exists())


def executed(traces: list[Path]) -> dict[str, set[int]]:
    """Union of executed instruction starts per module."""
    out: dict[str, set[int]] = {}
    for t in traces:
        for f in t.glob('executed-*.bin'):
            name = f.name[len('executed-'):-len('.bin')]
            out.setdefault(name, set()).update(i for i, b in enumerate(f.read_bytes()) if b)
    return out


def residency(path: Path) -> list[tuple[int, int, str, int]]:
    """(first linear, end linear, module, module offset of first) rows."""
    with path.open() as f:
        return [(int(r['first_para'], 16) * 16, (int(r['last_para'], 16) + 1) * 16, r['module'],
                 int(r['module_offset'], 16)) for r in csv.DictReader(f)]
