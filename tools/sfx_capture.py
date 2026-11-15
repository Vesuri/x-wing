#!/usr/bin/env python3
"""Each iMUSE sound's AdLib writes, alone, from the original music driver.

The original ADLIB.IMS runs under Unicorn x86 from a memory image with the driver
initialised and its sound table holding the music and SFXADL.LFD's effects (default: the
m13-mission-flight reference snapshot). Per id, from that image: stop all (command 0Bh),
start (08h) and set its group (10h, as FLIGHT.OVL+18A3C), then the driver's INT 08h
handler at its PIT rate until status (0Dh) reads 0 or 8 s. The request queue is emptied
first and, before each tick, the
handler's game-timer accumulator (DS:0678) cleared and its BIOS countdown (CS:0910)
reloaded, so only driver code runs: no game callback, no BIOS chain; each call on the
runtime's private stack. Code outside the
driver or a write outside its memory and the call stack stops the tool. Per id:
tmp/sound/sfx/ID.csv (opl_render's format: the chip reset, then the driver's OPL shadow
after the stop, then the writes) and a row of tmp/sound/sfx-capture.csv: writes, ticks
to the sound's end, seconds. All of them in tmp/sound/sfx-writes.csv, tools/fm_effect_check's
input: the start registers ("# opl", the same for every id), "# loop ID" for each that
never ends, then tick,id,reg,value rows.

    tools/sfx_capture.py [--snapshot DIR] [ID ...]

tests/host_run.py --sfx-capture runs it (capture()) from the port's guest RAM at the
capture's hook and compares.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import uc as U  # noqa: E402

RUNS = REPO / "ref/dosbox/runs"
OUT = REPO / "tmp/sound"
ENTRY, TIMER = 0x0000, 0x0A1B       # ADLIB.IMS load-image offsets (docs/external-surface.md)
DATA_PARA = 0x4D0                   # the driver's DS, paragraphs from its code (ADLIB.IMS+00BEF)
DRIVER_BYTES = 0x7760               # its image and minimum allocation (MZ header: 5378h + 23Eh paragraphs)
SOUNDS = 0x6E2                      # DS: far pointer to the game's sound table, id * 4
SHADOW = 0x342                      # DS: the driver's OPL register shadow (ADLIB.IMS+04BD2)
TIMER_ACC, BIOS_COUNT = 0x678, 0x910    # DS word: game-timer accumulator; CS byte: BIOS chain countdown
DS_SLOT = 0x911                     # CS word: the handler's DS
QUEUE_HEAD, QUEUE_TAIL = 0xEBE, 0x12C0  # DS words: the request queue's read and write index (+02B7D)
FIRST_EFFECT = 4                    # ids from 4 are effects (FLIGHT.OVL+18A55)
STACK_SS, STACK_SP = 0xB000, 0x8000  # runtime.h RT_IRQ_SS:RT_IRQ_SP
STOP_ALL, START, STATUS, GROUP = 0x0B, 0x08, 0x0D, 0x10
TICK_HZ = 1193182 / 0x1000          # PIT channel 0 divisor 1000h
TICKS_MAX = 2330                    # 8 s (src/runtime/sfx.c)
RET_SEG = 0x0050                    # a free BIOS-data paragraph: the far return


def find_snapshot(path: str | None) -> Path:
    if path:
        return Path(path)
    for d in sorted(RUNS.glob("*-m13-mission-flight/trace/snap-m13-mission-flight-0")):
        if (d / "ram.bin").exists():
            return d
    raise SystemExit("no m13-mission-flight snapshot under ref/dosbox/runs: make dos-reference")


def snapshot_image(snap: Path) -> tuple[bytes, int, int, int]:
    """A reference snapshot's RAM, the driver's code segment, DS and ES."""
    regs = {}
    for line in (snap / "regs.txt").read_text().split("\n"):
        for kv in line.split():
            k, _, v = kv.partition("=")
            if k in U.X86:
                regs[k] = int(v, 16)
    for r in csv.reader((snap / "residency.csv").open()):
        if r[2] == "ADLIB.IMS":
            seg = int(r[0], 16) - int(r[3], 16) // 16
            return (snap / "ram.bin").read_bytes(), seg, regs["ds"], regs["es"]
    raise SystemExit(f"{snap}: ADLIB.IMS not resident")


def driver_segment(ram: bytes) -> int:
    """The driver's code segment from IVT 08h (its INT 08h handler)."""
    off, seg = struct.unpack_from("<HH", ram, 8 * 4)
    if off != TIMER or struct.unpack_from("<H", ram, seg * 16 + DS_SLOT)[0] != seg + DATA_PARA:
        raise SystemExit(f"IVT 08h {seg:04x}:{off:04x} is not the music driver's handler")
    return seg


class Driver:
    """The driver in RAM image `ram` (linear, 1 MB or more), its code at `seg`; each call
    on the runtime's private stack (runtime.h RT_IRQ_SS:RT_IRQ_SP), DS and ES as given."""

    def __init__(self, ram: bytes, seg: int, ds: int, es: int):
        self.seg, self.ds, self.es = seg, ds, es
        self.ram = ram
        self.e = U.Engine(U.ARCH_X86, U.MODE_16)
        self.e.map(0, 0x110000)
        self.e.write(0, ram[:0x110000])
        self.ret = RET_SEG * 16
        self.e.write(self.ret, b"\xf4")            # hlt: the far return lands here
        self.tick_n, self.writes, self.index = 0, [], 0

        @U.OUT_CB
        def out(h, port, size, value, user):
            if port == 0x388:
                self.index = value & 0xFF
            elif port == 0x389:
                self.writes.append((self.tick_n, self.index, value & 0xFF))

        @U.IN_CB
        def inp(h, port, size, user):
            return 0

        self.e.hook(U.HOOK_INSN, out, U.X86_INS_OUT)
        self.e.hook(U.HOOK_INSN, inp, U.X86_INS_IN)
        self.stray: list[str] = []
        base, top = seg * 16, seg * 16 + DRIVER_BYTES
        stack = STACK_SS * 16 + STACK_SP

        @U.CODE_CB
        def code(h, addr, size, user):
            if not (base <= addr < top or self.ret <= addr <= self.ret + 1):
                self.stray.append(f"code at {addr:05x}")
                self.e.stop()

        @U.MEM_CB
        def write(h, access, addr, size, value, user):
            if not (base <= addr < top or stack - 0x400 <= addr < stack):
                self.stray.append(f"write {size} at {addr:05x}")
            return True

        self.e.hook(U.HOOK_CODE, code)
        self.e.hook(U.HOOK_MEM_WRITE, write)

    def sound_table(self) -> list[int]:
        """The ids whose table entry points at an iMUSE ADL sound."""
        ds = (self.seg + DATA_PARA) * 16
        off, seg = struct.unpack_from("<HH", self.ram, ds + SOUNDS)
        ids = []
        for i in range(256):
            o, s = struct.unpack_from("<HH", self.ram, seg * 16 + off + 4 * i)
            a = s * 16 + o
            if (o or s) and a + 4 <= len(self.ram) and self.ram[a:a + 4] == b"ADL ":
                ids.append(i)
        return ids

    def push(self, *words: int) -> None:
        sp = self.e.reg_read(U.X86["sp"])
        for w in words:
            sp = (sp - 2) & 0xFFFF
            self.e.write(STACK_SS * 16 + sp, struct.pack("<H", w & 0xFFFF))
        self.e.reg_write(U.X86["sp"], sp)

    def run(self, ip: int, *frame: int) -> int:
        self.e.reg_write(U.X86["ss"], STACK_SS)
        self.e.reg_write(U.X86["ds"], self.ds)
        self.e.reg_write(U.X86["es"], self.es)
        self.e.reg_write(U.X86["sp"], STACK_SP)
        self.push(*frame)
        self.e.reg_write(U.X86["cs"], self.seg)
        self.e.reg_write(U.X86["ip"], ip)
        err = self.e.start(self.seg * 16 + ip, self.ret)
        pc = self.e.reg_read(U.X86["cs"]) * 16 + self.e.reg_read(U.X86["ip"])
        if err or pc not in (self.ret, self.ret + 1):
            raise SystemExit(f"ADLIB.IMS+{ip:05X}: stopped at {pc:05x} "
                             f"({U.uc.uc_strerror(err).decode()}; {', '.join(self.stray[:4])})")
        return self.e.reg_read(U.X86["ax"])

    def command(self, *args: int) -> int:       # far C call, args pushed right to left
        return self.run(ENTRY, *reversed(args), RET_SEG, 0)

    def tick(self) -> None:                     # the interrupt frame: FLAGS, CS, IP
        ds = (self.seg + DATA_PARA) * 16
        self.e.write(ds + TIMER_ACC, b"\0\0")
        self.e.write(self.seg * 16 + BIOS_COUNT, b"\x10")
        self.run(TIMER, 0x0202, RET_SEG, 0)

    def word(self, off: int) -> int:
        return struct.unpack("<H", self.e.read((self.seg + DATA_PARA) * 16 + off, 2))[0]

    def shadow(self) -> bytes:
        return self.e.read((self.seg + DATA_PARA) * 16 + SHADOW, 256)


def capture(ram: bytes, seg: int, ds: int, es: int, sid: int,
            limit: int = TICKS_MAX) -> tuple[bytes, list, int]:
    """One id as src/runtime/sfx.c captures it: (the OPL shadow after the stop, the
    writes as (tick, reg, value), the tick status read 0, 0 if not within `limit`)."""
    d = Driver(ram, seg, ds, es)
    tail = struct.pack("<H", d.word(QUEUE_TAIL))
    d.e.write((seg + DATA_PARA) * 16 + QUEUE_HEAD, tail)    # no queued request runs
    d.command(STOP_ALL)
    opl0 = d.shadow()
    d.writes.clear()
    d.command(START, sid)
    d.command(GROUP, sid, 1)
    end = 0
    for t in range(1, limit + 1):
        d.tick_n = t
        d.tick()
        if d.command(STATUS, sid) == 0:
            end = t
            break
    if d.stray:
        raise SystemExit(f"id {sid}: outside the driver: {', '.join(d.stray[:8])}")
    return opl0, d.writes, end


def effect_ids(ram: bytes, seg: int, ds: int, es: int) -> list[int]:
    return [i for i in Driver(ram, seg, ds, es).sound_table() if i >= FIRST_EFFECT]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ids", nargs="*", type=int)
    ap.add_argument("--snapshot")
    args = ap.parse_args()
    ram, seg, ds, es = snapshot_image(find_snapshot(args.snapshot))
    ids = args.ids or effect_ids(ram, seg, ds, es)
    (OUT / "sfx").mkdir(parents=True, exist_ok=True)
    rows, start, log = [], None, []
    for sid in ids:
        opl0, writes, end = capture(ram, seg, ds, es, sid)
        if start not in (None, opl0):
            raise SystemExit(f"id {sid}: start registers differ from the first id's")
        start = opl0
        log += [f"# loop {sid}\n"] if not end else []
        log += [f"{t},{sid},0x{r:02x},0x{v:02x}\n" for t, r, v in writes]
        with (OUT / f"sfx/{sid}.csv").open("w") as f:
            f.write("ms,reg,value\n")
            f.writelines(f"0.000000,0x{r:02x},0x{v:02x}\n" for r, v in enumerate(opl0) if r and v)
            f.writelines(f"{1000 * t / TICK_HZ:.6f},0x{r:02x},0x{v:02x}\n" for t, r, v in writes)
        rows.append((sid, len(writes), end, f"{end / TICK_HZ:.3f}"))
        print(f"{sid:3} writes {len(writes):5}  ticks {end:5}  {end / TICK_HZ:6.3f} s"
              f"{'' if end else '  (no end: a loop)'}", flush=True)
    with (OUT / "sfx-capture.csv").open("w") as f:
        f.write("id,writes,ticks,seconds\n")
        f.writelines(",".join(map(str, r)) + "\n" for r in rows)
    with (OUT / "sfx-writes.csv").open("w") as f:
        f.write(f"# opl {start.hex() if start else ''}\n")
        f.writelines(log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
