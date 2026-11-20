"""Static model of X-Wing's files: root, overlay segments, music drivers, traces.

Adapted from Secret Weapons of the Luftwaffe's tools/swotl_model.py (commit pinned in
manifest/references.tsv), file half only. The overlay manager itself is modelled in P2.

Module address = module offset (the tracer's convention):
- root: offset in XWING.EXE's MZ load image;
- overlay file (`FRONTEND.OVL`, `FLIGHT.OVL`): offset in the file;
- music driver (`*.IMS`, loaded by INT 21h AX=4B03): offset in its MZ load image.

Overlay manager (MEASURED, docs/overlay-manager.md): a descriptor table of nine-word
records at root image offset 4A5Fh (segment 0406h, offset 09FFh; the count word at 0406h:09FBh
is 27, the last record empty). Fields: link segment, file-name offset (+4061h = image
offset of the name), file position in paragraphs, a byte 0 (position high byte), a flags
byte (04h; bit 1 set while resident), memory size in paragraphs, fixup count, parent
index (FFFFh for a file's base segment), id (index + 2) and the paragraphs read. In the
file, a segment is its fixup table (count x 4 bytes: offset, link segment) followed by its
code at the next paragraph. Loading puts the code at load segment + link segment and adds
the load segment to each fixup word, as for the root (MEASURED: all 1,696 FRONTEND base
fixups in a snapshot). Thunks at root image 4D47h..56B1h, ten bytes each: `call 048Ah;
jmp far seg:off; dw index`.

Root layout (MEASURED): code below 5BA0h (link segment 05BAh); the overlay area
5BA0h..39600h is zero in the image; above it, the data segment 3960h.
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
MANAGER_SEG = 0x0406
THUNK_HANDLER_IP = 0x048A   # image 44EAh: reads the index after the thunk's far jump
MANAGER_IP = 0x017C         # image 41DCh: AX = descriptor index (FFFFh: none)
THUNKS = 0x4D47
OVL_AREA = (0x5BA0, 0x39600)  # link linear range of the overlay area
NAME_BASE = 0x4061  # file-name offset + this = image offset of the name (MEASURED)
DRIVERS = ['ADLIB.IMS', 'ADLIB_W.IMS', 'ROLAND.IMS', 'ROLAND_W.IMS', 'GMIDI.IMS', 'GMIDI_W.IMS']
OUT_OF_SCOPE = tuple(DRIVERS[1:])  # music drivers the AdLib reference never loads


@dataclass
class Segment:
    index: int                  # descriptor index (thunk and manager argument)
    file: str
    link_seg: int
    pos: int                    # file offset of the fixup table
    paras: int                  # memory size in paragraphs (eviction overlap)
    nfix: int
    parent: int                 # descriptor index, or None for a file's base segment
    read_paras: int             # paragraphs read by the manager

    @property
    def id(self) -> int:
        return self.index + OVL_FIRST_ID

    @property
    def code(self) -> int:      # file offset of the first code byte
        return self.pos + ((self.nfix * 4 + 15) & ~15)

    @property
    def end(self) -> int:       # file offset after the last code byte read
        return self.code + self.read_paras * 16

    def overlaps(self, other: 'Segment') -> bool:
        return self.link_seg < other.link_seg + other.paras and \
            other.link_seg < self.link_seg + self.paras


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
        seg, name_off, pos, _, paras, nfix, parent, oid, read = struct.unpack_from(
            '<9H', image, OVL_TABLE + 18 * i)
        if oid != OVL_FIRST_ID + i:
            raise ValueError(f'overlay record {i}: id {oid}')
        start = NAME_BASE + name_off
        name = image[start:image.index(b'\0', start)].decode('ascii')
        out.append(Segment(i, name, seg, pos * 16, paras, nfix, None if parent == 0xFFFF else parent,
                           read))
    return out


def thunks(image: bytes) -> list[tuple[int, int, int, int]]:
    """(root offset, descriptor index, target link segment, target offset) per thunk."""
    out, a = [], THUNKS
    while image[a] == 0xE8 and (a + 3 + struct.unpack_from('<h', image, a + 1)[0]) & 0xFFFF == \
            MANAGER_SEG * 16 + THUNK_HANDLER_IP and image[a + 3] == 0xEA:
        off, seg, index = struct.unpack_from('<HHH', image, a + 4)
        out.append((a, index, seg, off))
        a += 10
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


def runs(pattern: str = 'latest') -> list[Path]:
    """Traces of the runs matching a glob. 'latest' is the newest AdLib milestone set of
    tools/reference.py: the base name of the most recent `*-m00-entry` run, host
    references (`host-*`, `--polls`: m00 and m01 only) and P10's Sound Blaster sets
    (`sb*`, `--sb`) excluded. 'latest-sb' is the newest Sound Blaster set (`sb*`), 'latest+sb'
    both."""
    if pattern == 'latest+sb':  # both: the corpus of the modules both machines run
        return runs('latest') + runs('latest-sb')
    if pattern in ('latest', 'latest-sb'):
        sb = pattern == 'latest-sb'
        entries = sorted((p for p in RUNS.glob('*-m00-entry')
                          if (p.name.startswith('sb') if sb else
                              not p.name.startswith(('host-', 'sb')))),
                         key=lambda p: p.stat().st_mtime)
        if not entries:
            return []
        pattern = entries[-1].name[:-len('m00-entry')] + '*'
    return sorted(p / 'trace' for p in RUNS.glob(pattern) if (p / 'trace/summary.txt').exists())


def executed(traces: list[Path]) -> dict[str, set[int]]:
    """Union of executed instruction starts per module."""
    out: dict[str, set[int]] = {}
    for t in traces:
        for f in t.glob('executed-*.bin'):
            name = f.name[len('executed-'):-len('.bin')]
            out.setdefault(name, set()).update(i for i, b in enumerate(f.read_bytes()) if b)
    return out


def edges(traces: list[Path]) -> set[tuple[str, int, str, int]]:
    out = set()
    for t in traces:
        with (t / 'edges.csv').open() as f:
            for r in csv.DictReader(f):
                out.add((r['from_module'], int(r['from_offset'], 16),
                         r['to_module'], int(r['to_offset'], 16)))
    return out


def csv_rows(traces: list[Path], name: str) -> list[dict]:
    rows = []
    for t in traces:
        p = t / name
        if p.exists():
            with p.open() as f:
                for r in csv.DictReader(f):
                    r['_run'] = t.parent.name
                    rows.append(r)
    return rows


def residency(path: Path) -> list[tuple[int, int, str, int]]:
    """(first linear, end linear, module, module offset of first) rows."""
    with path.open() as f:
        return [(int(r['first_para'], 16) * 16, (int(r['last_para'], 16) + 1) * 16, r['module'],
                 int(r['module_offset'], 16)) for r in csv.DictReader(f)]


def locate(rows: list[tuple[int, int, str, int]], linear: int) -> tuple[str, int] | None:
    for lo, hi, mod, off in rows:
        if lo <= linear < hi:
            return mod, off + linear - lo
    return None


FILL_WRITER = 'XWING.EXE+0454E'  # the manager's zero fill after the read size (image 4529h)


def fill_ranges(load: int) -> list[tuple[int, int]]:
    """Linear ranges the manager zero-fills: each segment's memory beyond its read size."""
    return [((load + s.link_seg + s.read_paras) * 16, (load + s.link_seg + s.paras) * 16)
            for s in segments(mz(REF / ROOT)[0]) if s.paras > s.read_paras]


def cpu_writes(traces: list[Path], skip: tuple[str, ...] = ()) -> dict[str, dict[int, set[str]]]:
    """Module offset -> writer sites, from snapshot writes.csv (last writer since load,
    mapped by the snapshot's residency) and code-writes.csv (writes into executed
    paragraphs, with their target module and offset at the time of the write). Writers
    in `skip` are left out."""
    out: dict[str, dict[int, set[str]]] = {}

    def add(rows, lo, hi, writer):
        if writer in skip:
            return
        for a in range(lo, hi + 1):
            hit = locate(rows, a)
            if hit:
                out.setdefault(hit[0], {}).setdefault(hit[1], set()).add(writer)

    for t in traces:
        for snap in t.glob('snap-*'):
            rows = residency(snap / 'residency.csv')
            if (snap / 'writes.csv').exists():
                with (snap / 'writes.csv').open() as f:
                    for r in csv.DictReader(f):
                        add(rows, int(r['first_linear'], 16), int(r['last_linear'], 16),
                            f"{r['writer_module']}+{int(r['writer_offset'], 16):05X}")
        with (t / 'code-writes.csv').open() as f:
            for r in csv.DictReader(f):
                writer = f"{r['writer_module']}+{int(r['writer_offset'], 16):05X}"
                if writer in skip or r['target_module'] == '-':
                    continue
                off = int(r['target_offset'], 16)
                for k in range(int(r['width'])):
                    out.setdefault(r['target_module'], {}).setdefault(off + k, set()).add(writer)
    return out


def writes_by(traces: list[Path], writer: str) -> list[tuple[Path, int, int]]:
    """(trace, load segment, linear) of every byte a writer wrote (both write logs)."""
    out = []
    for t in traces:
        load = int(dict(l.split('=') for l in (t / 'summary.txt').read_text().split())['load_seg'], 16)
        mod, off = writer.split('+')
        for snap in t.glob('snap-*'):
            if (snap / 'writes.csv').exists():
                with (snap / 'writes.csv').open() as f:
                    for r in csv.DictReader(f):
                        if r['writer_module'] == mod and int(r['writer_offset'], 16) == int(off, 16):
                            out += [(t, load, a) for a in range(int(r['first_linear'], 16),
                                                                int(r['last_linear'], 16) + 1)]
        with (t / 'code-writes.csv').open() as f:
            for r in csv.DictReader(f):
                if r['writer_module'] == mod and int(r['writer_offset'], 16) == int(off, 16):
                    a = int(r['target_linear'], 16)
                    out += [(t, load, a + k) for k in range(int(r['width']))]
    return out
