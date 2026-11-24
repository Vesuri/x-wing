"""Exact original REP decoder slices, used only by diagnostic replay builds.

Copied from Secret Weapons of the Luftwaffe's tests/rep_replay.py (commit pinned in
manifest/references.tsv) and adapted: no compute objects or joystick wrapper. DOSBox-X
restarts a REP instruction when its cycle slice ends (dosbox-x-xwing-rep-chunks.patch,
trace/rep.csv), so an interrupt taken inside one lands at a slice boundary; the host
replays those boundaries at the REP's poll point (tests/host_run.py)."""
from array import array
import csv
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translator import cfg, emit, gen

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('module', 'offset', 'service', 'hits', 'cx', 'si', 'di',
          'end_cx', 'end_si', 'end_di', 'restart')


@dataclass(frozen=True)
class Chunk:
    label: str
    service: int
    hits: int
    start: tuple
    end: tuple
    restart: bool


class Chunks:
    """The slices in packed arrays (m13 records 12 million; as Chunk objects they
    take 6 GB): a Chunk is built when read."""

    def __init__(self):
        self.names: list[str] = []
        self.ids: dict[str, int] = {}
        self.label = array('H')
        self.service = array('Q')
        self.hits = array('I')
        self.regs = array('H')       # cx si di end_cx end_si end_di per slice
        self.restart = array('B')

    def append(self, label, service, hits, start, end, restart):
        if label not in self.ids:
            self.ids[label] = len(self.names)
            self.names.append(label)
        self.label.append(self.ids[label])
        self.service.append(service)
        self.hits.append(hits)
        self.regs.extend(start + end)
        self.restart.append(restart)

    def __len__(self):
        return len(self.label)

    def __getitem__(self, i):
        if not 0 <= i < len(self.label):
            raise IndexError(i)
        r = self.regs[6 * i:6 * i + 6]
        return Chunk(self.names[self.label[i]], self.service[i], self.hits[i],
                     tuple(r[:3]), tuple(r[3:]), bool(self.restart[i]))

    def __iter__(self):
        return (self[i] for i in range(len(self)))


def read(trace, required=False):
    path = trace / 'rep.csv'
    if not path.exists():
        if required:
            raise ValueError('required REP metadata is missing')
        return Chunks()
    result = Chunks()
    labels = {}
    with path.open() as f:
        rows = csv.DictReader(f)
        if tuple(rows.fieldnames or ()) != FIELDS:
            raise ValueError('REP metadata schema differs')
        for r in rows:
            values = [int(r[k], 0) for k in FIELDS[1:]]
            off, service, hits, cx, si, di, end_cx, end_si, end_di, restart = values
            if min(values) < 0 or max(values[3:9]) > 65535 or restart not in (0, 1):
                raise ValueError(f'invalid REP metadata: {r}')
            if end_cx > cx or restart and not 0 < end_cx < cx:
                raise ValueError(f'invalid REP progress: {r}')
            key = (r['module'], off)
            if key not in labels:
                labels[key] = emit.label(r['module'], off)
            result.append(labels[key], service, hits, (cx, si, di), (end_cx, end_si, end_di),
                          bool(restart))
    # an empty file is a record: the tracer writes the header only with --rep-chunks,
    # and a run with no REP at a poll point (m00-entry) records no slice
    return result


def compact(chunks):
    """Lossless runs of adjacent identical slice steps; boundaries stay exact."""
    groups = []
    for c in chunks:
        if groups:
            a, n = groups[-1]
            delta = tuple((y - x) & 65535 for x, y in zip(a.start, a.end))
            expected = tuple((x + n * d) & 65535 for x, d in zip(a.start, delta))
            if (a.restart and c.restart and n < 65535 and a.label == c.label and
                    a.service == c.service and a.hits + n == c.hits and
                    c.start == expected and
                    tuple((y - x) & 65535 for x, y in zip(c.start, c.end)) == delta):
                groups[-1] = (a, n + 1)
                continue
        groups.append((c, 1))
    return groups


class Replay:
    def __init__(self, chunks):
        self.chunks = chunks
        self.labels = sorted(chunks.names if isinstance(chunks, Chunks) else
                             {c.label for c in chunks})
        self.index = 0
        self.active = False

    def checkpoint(self, point, registers, service, visits, done):
        if self.index == len(self.chunks):
            raise ValueError('unrecorded REP execution')
        c = self.chunks[self.index]
        if not 0 <= point < len(self.labels) or self.labels[point] != c.label:
            raise ValueError(f'REP point differs at slice {self.index}')
        if service != c.service or visits != c.hits + 1:
            raise ValueError(f'REP epoch/visit differs at slice {self.index}: '
                             f'{service}/{visits} != {c.service}/{c.hits + 1}')
        if not self.active:
            if registers != c.start:
                raise ValueError(f'REP entry differs at slice {self.index}: {registers} != {c.start}')
            self.active = True
        if done or c.restart and registers[0] == c.end[0]:
            if registers != c.end or bool(done) == c.restart:
                raise ValueError(f'REP end differs at slice {self.index}: {registers} != {c.end}')
            self.index += 1
            self.active = False
            return c.restart
        if registers[0] < c.end[0]:
            raise ValueError(f'REP passed recorded endpoint at slice {self.index}')
        return False

    def complete(self):
        if self.active or self.index != len(self.chunks):
            raise ValueError(f'REP slices incomplete: {self.index}/{len(self.chunks)}')


def host_image(labels):
    """Link generated diagnostic REP lowering with the unchanged host runtime."""
    objects = [ROOT / 'build/host' / (p.stem + '.o') for p in sorted((ROOT / 'src/runtime').glob('*.c'))]
    objects += [ROOT / 'build/host' / n for n in ('host_s.o', 'host.o', 'rt_entry.o')]
    inputs = [Path(__file__)] + sorted((ROOT / 'translator').glob('*.py')) + \
        sorted((ROOT / 'annotations').glob('*.csv')) + sorted((ROOT / 'build/gen').glob('*.s')) + objects
    digest = hashlib.sha256(('\n'.join(labels)).encode())
    digest.update(os.environ.get('XWING_VRAM_PLANT', '').encode())   # lower.py VRAM_PLANT
    for p in inputs:
        digest.update(p.name.encode()); digest.update(p.read_bytes())
    final = ROOT / 'tmp/rep-host' / digest.hexdigest()[:20]
    if (final / 'xwing.elf').exists():
        return final / 'xwing.elf'
    # built aside and renamed: runs sharing the labels may build the same image at once
    out = final.with_name(f'{final.name}.{os.getpid()}')
    elf = out / 'xwing.elf'
    units = cfg.build()
    nodes = {emit.label(mod, off): (mod, off) for mod, u in units.items() for off in u.insns}
    hooks = {nodes[lab]: n for n, lab in enumerate(labels)}
    for node in hooks:
        if not units[node[0]].insns[node[1]].rep:
            raise ValueError(f'REP metadata names a non-REP instruction: {node}')
    program = emit.Program(units, diagnostic_reps=hooks)
    if not set(hooks) <= program.loop_heads:
        raise ValueError('REP metadata outside the original poll set')
    gen.generate(out / 'gen', program=program)
    vasm = str(os.environ.get('VASM') or Path.home() / '.local/vasmm68k_mot')
    subprocess.run([vasm, '-quiet', '-m68020', '-Felf', '-x', '-nowarn=62', '-DXWING_SYNC=1',
                    '-o', str(out / 'program.o'), 'program.s'], cwd=out / 'gen', check=True)
    # The host hook supplies the result in the argument slot; no guest work here.
    (out / 'rep.s').write_text(' section .text,code\n xdef rt_replay_rep\nrt_replay_rep:\n rts\n')
    subprocess.run([vasm, '-quiet', '-m68020', '-Felf', '-o', str(out / 'rep.o'),
                    str(out / 'rep.s')], check=True)
    toolchain = Path(os.environ.get('AMIGA_TOOLCHAIN') or Path.home() / '.local/opt')
    subprocess.run([str(toolchain / 'bin/m68k-amiga-elf-ld'), '-Ttext=0x10000', '-e', '_start',
                    f'-Map={out / "xwing.map"}', '-o', str(elf), *(str(p) for p in objects), str(out / 'program.o'),
                    str(out / 'rep.o')], check=True)
    try:
        out.rename(final)
    except OSError:  # another run renamed its identical build first
        shutil.rmtree(out)
    return final / 'xwing.elf'
