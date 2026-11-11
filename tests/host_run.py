#!/usr/bin/env python3
"""Run the generated program with the runtime on Unicorn 68020 (gate 5):
build/host/xwing.elf from the XWING.EXE entry to a reference milestone, data
files read from the configured installation (tmp/dos/configured/XWING,
read-only). Copied from Secret Weapons of the Luftwaffe's tests/host_run.py
(manifest/references.tsv) and adapted: X-Wing's milestone table, traces and
VGA status replay; SWOTL's SPAZ, pointer, effect, joystick and stress checks
are not copied.

Checked against the newest host reference run of that milestone
(ref/dosbox/runs/host-*-<milestone>, `tools/reference.py --polls`: hardware
interrupts at the translator's poll points, the VGA status reads recorded):
- service log: every software INT the guest raises, in order, with the
  registers at entry and at return (the tracer's svc/svc_ret events), compared
  as they run; a register byte the guest loaded from dead stack may differ
  (ServiceLog; controls --dead-sabotage);
- at the milestone label: guest registers and guest RAM (COMPARE ranges);
  dead stack is masked: bytes in the DEAD_STACK window below SS:SP at the entry, at a
  service call or hardware interrupt (at an IRQ0 delivery to the guest handler, its
  frame and proved stack depth) that the guest did not write afterwards (DOSBox-X's own code
  and the interrupt frame's FLAGS word leave other values there, open-work 24),
  and the FLAGS images of annotations/flags.csv PUSHFs until rewritten; a byte whose
  last write stored a value generated code read from dead stack since the last
  service event may differ (Host.dead_stored, owner decision 2026-11-10);
- every machine byte outside COMPARE (and the IRQ0 handler's private stack)
  that generated code read holds the reference value.
Every read of port 3DAh answers the reference's next recorded value
(trace/retrace.csv) in the same service-event interval, and all are used.
DOSBox-X restarts a REP at the end of its cycle slice, so an interrupt can land
inside one: a diagnostic image with REP hooks (rep_replay.py) replays the
reference's slices (trace/rep.csv) at each REP poll point, and all are used.
With --amiga DIR, the same checks run on the A1200 model's capture
(amiga/milestone.gdb.in: regs.txt, state.bin, ram.bin, dac.bin), masked by
this host run's dead-stack set, and the shown frame (plane0-7.bin, bytes per
row in regs.txt, colours.bin = LoadRGB32 table) decodes to the reference
framebuffer and DAC. --label prints a milestone's label for the fixture.
Exit 1 on any difference, a runtime stop or the time limit.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import gzip
import csv
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import uc as U  # noqa: E402
import rep_replay  # noqa: E402
import irq_monitor  # noqa: E402
from translator import emit, image  # noqa: E402
import reference as R  # noqa: E402  tools/reference.py: the milestone table's sites and keys

REPO = image.REPO
ELF = REPO / "build/host/xwing.elf"
MEM = 0x01000000          # flat map: code, data, stack, guest RAM
STACK_TOP = 0x00FF0000
BLOCK = 0x00400000        # src/platform/host/host.c HOST_BLOCK
GUEST_BYTES = 0x110000
TOP = BLOCK + GUEST_BYTES - 1   # rt_guest: guest linear L at TOP - L (reversed)
STATE = TOP + 1           # state block (translator/lower.py STATE_EQU)
G_IRQ = TOP + 9
# Key names of the reference key script (tracer KeyByName): scan << 8 | ASCII
# as the BIOS INT 09h handler stores them.
KEYS = {"enter": 0x1C0D, "esc": 0x011B, "space": 0x3920, "tab": 0x0F09, "backspace": 0x0E08,
        "up": 0x4800, "down": 0x5000, "left": 0x4B00, "right": 0x4D00,
        **{f"f{k}": (0x3A + k) << 8 for k in range(1, 11)},
        **{c: s << 8 | ord(c) for c, s in zip("qwertyuiopasdfghjklzxcvbnm",
                                             list(range(0x10, 0x1A)) + list(range(0x1E, 0x27))
                                             + list(range(0x2C, 0x33)))},
        **{str(k): (k + 1) << 8 | ord(str(k)) for k in range(1, 10)}, "0": 0x0B30,
        "minus": 0x0C2D, "equals": 0x0D3D}
GREY = {KEYS[k] for k in ("up", "down", "left", "right")}  # E0-prefixed (DOSBox KBD_up..)
# Modifier bits belong to scripted input, above the base BIOS key word.
KEY_MODIFIERS = {"shift": 1 << 16, "ctrl": 1 << 17, "alt": 1 << 18}


def key_code(name: str) -> int:
    parts = name.split("+")
    modifiers = 0
    for part in parts[:-1]:
        bit = KEY_MODIFIERS.get(part, 0)
        if not bit or modifiers & bit:
            raise ValueError(f"invalid key chord: {name}")
        modifiers |= bit
    if parts[-1] not in KEYS:
        raise ValueError(f"unknown key: {name}")
    return modifiers | KEYS[parts[-1]]


def key_events(key: int) -> tuple[int, ...]:
    if key & ~0x7ffff:
        raise ValueError(f"invalid scripted key: {key:x}")
    base = key & 0xffff
    scan = base >> 8
    modifiers = tuple(scan for bit, scan in ((1 << 16, 0x2a),
                      (1 << 17, 0x1d), (1 << 18, 0x38)) if key & bit)
    body = (0xe0, scan, 0xe0, scan | 0x80) if base in GREY else (scan, scan | 0x80)
    return modifiers + body + tuple(scan | 0x80 for scan in reversed(modifiers))


KEY_HOLD = 600_000  # tracer: x86 instructions from key down to key up
# Compared guest RAM: the DOS arena from the environment MCB to the top of
# conventional memory; below it are IVT/BIOS/DOS internals the runtime models
# only through services, above it video and BIOS ROM.
COMPARE = [(0x07C90, 0xA0000)]
# Chained mode 13h: guest A0000h+a is DOSBox-X vram[((a & ~3) << 2) | (a & 3)]
# (tools/snap_png.py); the whole 64 KiB window is compared with the DAC.
FRAME = (0xA0000, 0xB0000)
# The IRQ0 handler's private stack (runtime.h RT_IRQ_SS:RT_IRQ_SP down, I4): runtime
# state, no machine bytes; its depth is the footprint's (tests/irq_monitor.py checks).
IRQ_STACK = (0xB8000 - 0x200, 0xB8000)
REGS = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
DEAD_STACK = 0x60

TABLE = REPO / "reference/milestones.csv"
RUNS = REPO / "ref/dosbox/runs"
POLLS = REPO / "build/gen/poll-points.csv"


def elf_load(path: Path, function_extents: dict | None = None):
    d = path.read_bytes()
    entry, phoff, shoff = struct.unpack_from(">III", d, 0x18)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from(">HHHHH", d, 0x2A)
    segs = []
    for k in range(phnum):
        typ, off, vaddr, _, filesz, memsz = struct.unpack_from(">IIIIII", d, phoff + k * phentsize)
        if typ == 1:
            segs.append((vaddr, d[off:off + filesz], memsz))
    secs = [struct.unpack_from(">IIIIIIIIII", d, shoff + k * shentsize) for k in range(shnum)]
    syms = {}
    for s in secs:
        if s[1] != 2:  # SHT_SYMTAB
            continue
        strtab = secs[s[6]]
        for k in range(s[5] // 16):
            name, value, size, info, _, shndx = struct.unpack_from(">IIIBBH", d, s[4] + k * 16)
            if name and shndx:
                a = strtab[4] + name
                symbol = d[a:d.index(b"\0", a)].decode()
                syms[symbol] = value
                if function_extents is not None and info & 15 == 2 and size:
                    function_extents[symbol] = (value, value + size)
    return entry, segs, syms


def events(trace: Path):
    return gzip.open(trace / "events.csv.gz", "rt")


def iter_services(trace: Path):
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                vec, *kv = r["detail"].split()
                regs = {k: int(v, 16) for k, v in (x.split("=") for x in kv)}
                regs["vector"] = int(vec, 16)
                yield r["kind"], regs


def reference_services(trace: Path) -> list[tuple[str, dict]]:
    return list(iter_services(trace))


def reference_inputs(trace: Path, *, exact_releases: bool = False) -> tuple[list, list]:
    """The reference's hardware interrupts as (service events so far, poll
    point label, its executions since the last service event, vector), and
    the service-event count at each key release. Exact releases additionally
    retain recorded ineligible visits to the next trigger in that interval.
    The default preserves the existing diagnostic Amiga replay input format."""
    irqs, releases, n = [], [], 0
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                n += 1
            elif r["kind"] == "irq":
                vec, svc, hits = r["detail"].split()
                assert int(svc[4:]) == n, r
                irqs.append((n, emit.label(r["module"], int(r["offset"], 16)),
                             int(hits[5:]), int(vec, 16)))
            elif r["kind"] == "key_up":
                fields = r["detail"].split()
                release = n
                if exact_releases and len(fields) > 1:
                    if len(fields) != 2 or not fields[1].startswith("skip="):
                        raise ValueError(f"invalid key release: {r}")
                    skipped = int(fields[1][5:])
                    if skipped < 0:
                        raise ValueError(f"negative key release visits: {r}")
                    release = (n, skipped)
                releases.append(release)
    return irqs, releases


class KeyRelease:
    """Count trigger visits while held; IRQ replay remains independent.

    The recorder resets this count on key-down and each service event. For
    a snapshot, the release instruction itself is ineligible; for another
    key it is eligible. The recorded skip count already includes that order.
    Old captures retain their service-only behavior.
    """

    def __init__(self, release):
        self.service, self.skip = (release, None) if isinstance(release, int) else release
        self.interval, self.visits = None, 0

    def ready(self, service: int, target: bool) -> bool:
        if service != self.interval:
            self.interval, self.visits = service, 0
        if target:
            self.visits += 1
        if service != self.service:
            return service > self.service
        return self.skip is None or (target and self.visits > self.skip)


def fnv(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


SABOTAGE = {
    "read": "first byte of each guest file read flipped",
    "ax": "AX of the tenth service result off by one",
    "psp": "one PSP byte changed at the guest entry",
    "dac": "one DAC gun off at each DAC change",
    "vram": "stores to video memory not marked (rt_vram_mark returns at once)",
    "far": "every dispatch row near-only (rt_dispatch_far must stop, R14e)",
    "retrace": "one VGA status read answered with bit 3 flipped",
    "irq-stack": "rt_irq_async runs the IRQ0 handler on the interrupted stack (private SS:SP not set, I4)",
    "irq-state": "rt_irq_async restores no state block after the handler (I4)",
    "irq-sentinel": "rt_irq_async expects another sentinel CS:IP than its frame holds (I4)",
    "keyon": "rt_out8 counts no AdLib key-on edge (its addq dropped)",
    "resident": "the descriptors' resident bit ignored (machine.c resident: every row resident)",
    "song-requests": "the monitor counts no driver request (song buffer reloads become races)",
}


def dos_file_stamp(stamp):
    t = time.localtime(stamp)
    return ((t.tm_hour & 31) << 11 | (t.tm_min & 63) << 5 | (t.tm_sec // 2 & 31),
            ((t.tm_year - 1980) & 127) << 9 | (t.tm_mon & 63) << 5 | (t.tm_mday & 31))


class MemFile:
    """An open file the guest writes: kept in memory, never on disk."""

    def __init__(self, data: bytearray):
        self.data, self.pos = data, 0
        self.modified = False
        self.dos_stamp = None

    def read(self, n: int) -> bytes:
        out = bytes(self.data[self.pos:self.pos + n])
        self.pos += len(out)
        return out

    def write(self, b: bytes) -> int:
        self.modified = True
        if not b:  # DOS write of 0 bytes: truncate here
            del self.data[self.pos:]
            return 0
        if self.pos > len(self.data):
            self.data.extend(bytes(self.pos - len(self.data)))
        self.data[self.pos:self.pos + len(b)] = b
        self.pos += len(b)
        return len(b)

    def seek(self, off: int, whence: int) -> int:
        self.pos = max(0, (0, self.pos, len(self.data))[whence] + off)
        return self.pos

    def close(self) -> None:
        pass


class Host:
    def __init__(self, ref_root: Path, sabotage: str | None = None, elf: Path | None = None,
                 retrace: list | None = None):
        self.launch = ""
        self.root = ref_root
        self.file_clock = None
        self.calendar_date = None
        self.sabotage = sabotage
        functions = {}
        entry, segs, self.syms = elf_load(elf or ELF, functions)
        self.frame_writer = functions["push_frame"]
        e = self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(0, MEM)
        for vaddr, data, memsz in segs:
            e.write(vaddr, data + bytes(memsz - len(data)))
        self.entry = entry
        self.files: dict[int, object] = {}
        self.allocations = {}
        self.free_spans = [(0x900000, 0x500000)]
        self.next_file = 1
        self.written: dict[str, bytearray] = {}  # files the guest wrote (game path -> bytes)
        self.file_stamps: dict[str, tuple[int, int]] = {}
        self.deleted: set[str] = set()
        self.log: list[str] = []
        self.console = b""             # plat_console: the game's DOS console output
        self.exit: int | None = None
        self.services = ServiceLog()  # check() gives it the reference's log
        self.stopped_at: str | None = None
        self.stubs = {self.syms[n]: n for n in ("plat_alloc", "plat_free", "plat_open", "plat_create", "plat_read", "plat_write",
                                                "plat_delete", "plat_seek",
                                                "plat_calendar_date", "plat_file_stamp", "plat_close", "plat_dir_names", "plat_file_info", "plat_timer_rate", "plat_mouse", "plat_present", "plat_palette",
                                                "plat_service", "plat_vga_status", "plat_log", "plat_console",
                                                "plat_exit")}
        # VGA status replay: (service events, value, reads) runs of trace/retrace.csv
        self.retrace = list(retrace or [])
        self.retrace_i = self.retrace_used = 0
        self.retrace_bad: str | None = None
        self.mouse_dx = self.mouse_dy = self.mouse_buttons = 0
        self.presents = 0
        # D9 display: every byte the guest stores to the frame is inside the
        # rectangles of the next present (the runtime's marks vs the stores)
        self.vram_written: set[int] = set()
        self.display_miss: str | None = None
        e.write(self.syms["rt_present_due"], b"\1")  # a vertical blank is always due
        if sabotage == "vram":
            e.write(self.syms["rt_vram_mark"], b"\x4e\x75")  # rts
        if sabotage in ("irq-stack", "irq-state", "irq-sentinel"):
            a = self.syms["rt_irq_async"]
            code = e.read(a, self.syms["rt_irq_async_back"] + 0x40 - a)
            if sabotage == "irq-stack":     # move.w #$b000,G_SS(a6); move.w #$8000,rt_r+8 -> nops
                k = code.index(bytes.fromhex("3d7cb0000003"))
                e.write(a + k, bytes.fromhex("4e71") * 3)
                k = code.index(bytes.fromhex("33fc8000"))
                e.write(a + k, bytes.fromhex("4e71") * 4)
            elif sabotage == "irq-state":   # move.l (a0)+,d16(a6) x4 after the handler -> nops
                k = code.index(bytes.fromhex("2d580001"))
                e.write(a + k, bytes.fromhex("4e71") * 8)
            else:                           # move.l #$b0008000,d7 -> #$b0008002
                k = code.index(bytes.fromhex("2e3cb0008000"))
                e.write(a + k + 2, bytes.fromhex("b0008002"))
        if sabotage == "keyon":  # addq.b #1,(a0,d7.w) -> nop; nop
            a = self.syms["rt_out8"]
            code = e.read(a, 0x100)
            e.write(a + code.index(bytes.fromhex("52307000")), bytes.fromhex("4e714e71"))
        if sabotage == "resident":   # every row overlay 0: always resident, the first row wins
            rows = int.from_bytes(e.read(self.syms["dispatch_count"], 4), "big")
            for k in range(rows):
                e.write(self.syms["dispatch_table"] + 12 * k + 4, b"\0\0")
        if sabotage == "far":
            rows = int.from_bytes(e.read(self.syms["dispatch_count"], 4), "big")
            for k in range(rows):
                e.write(self.syms["dispatch_table"] + 12 * k + 6, b"\0\0")

        @U.MEM_CB
        def vram(h, kind, addr, size, value, user):  # the frame exists in mode 13h only
            if self.gmem(0x449, 1)[0] == 0x13:
                off = TOP - addr - size + 1 - 0xA0000
                self.vram_written.update(range(max(off, 0), min(off + size, 64000)))
            return True

        e.hook_range(U.HOOK_MEM_WRITE, vram, TOP - 0xA0000 - 63999, TOP - 0xA0000)

        @U.CODE_CB
        def stub(h, addr, size, user):
            n = self.stubs.get(addr)
            if n:
                self.platform(n)

        e.hook_range(U.HOOK_CODE, stub, self.syms["host_stubs"], self.syms["host_stubs_end"])

        # a service returns when the runtime glue's rts goes back to the
        # address after its jsr rt_int (static hooks: Unicorn retranslates
        # on every hook change)
        @U.CODE_CB
        def ret_hit(h, addr, size, user):
            if self.pending and self.u32(self.r("a7")) == self.pending[-1]:
                self.pending.pop()
                if self.sabotage == "ax" and len(self.services) == 19:
                    self.e.reg_write(U.M68K["d0"], (self.r("d0") + 1) & 0xFFFF)
                self.services.append(("svc_ret", self.guest_regs(self.pending_vec.pop())))
                self.in_service = bool(self.pending)

        for n in ("rt_exit", "rt_exit_guest"):
            e.hook_range(U.HOOK_CODE, ret_hit, self.syms[n], self.syms[n])
        self.pending: list = []
        self.pending_vec: list = []
        self.dead_planted = False

        @U.CODE_CB
        def int_entry(h, addr, size, user):
            d6 = self.r("d6")
            regs = self.guest_regs(d6 & 0xFF)
            if self.sabotage == "dead-written" and regs["vector"] == 0x21 and \
                    regs["ax"] >> 8 == 0x47 and self.bypass_n is not None and not self.dead_planted:
                # DL, a byte the guest wrote, logged with bit 7 flipped; the service
                # itself gets the guest's DL, so the run goes on (control of ServiceLog)
                self.dead_planted = True
                regs["dx"] ^= 0x80
            self.services.append(("svc", regs))
            self.in_service = True
            top = regs["ss"] * 16 + regs["sp"]
            self.masked.update(range(top - DEAD_STACK, top))
            self.pending.append(self.u32(self.r("a7")))
            self.pending_vec.append(d6 & 0xFF)

        a = self.syms["rt_int"]
        e.hook_range(U.HOOK_CODE, int_entry, a, a)

        # AdLib writes as the guest makes them (check_opl)
        self.opl: list[tuple[int, int]] = []
        self.opl_ports: list[tuple[int, int]] = []

        @U.CODE_CB
        def out8(h, addr, size, user):
            port, v = self.r("d7") & 0xFFFF, self.r("d6") & 0xFF
            if port in (0x388, 0x389):
                self.opl_ports.append((port, v))
            if port == 0x389:
                reg = self.mem(self.syms["rt_opl_index"], 1)[0]
                self.opl.append((reg, v))

        a = self.syms["rt_out8"]
        e.hook_range(U.HOOK_CODE, out8, a, a)

        # Hardware interrupts: the reference's BIOS handlers (and the INT frame)
        # use the interrupted stack, ours run in C; the window below SS:SP is dead.
        @U.CODE_CB
        def irq_entry(h, addr, size, user):
            g = self.guest_regs(0)
            top = g["ss"] * 16 + g["sp"]
            self.masked.update(range(top - DEAD_STACK, top))
            self.irq_top = top

        self.irq_top = None
        for n in ("rt_irq", "rt_bios_int08"):
            e.hook_range(U.HOOK_CODE, irq_entry, self.syms[n], self.syms[n])

        # I3: every guest access against the IRQ0 footprint (tests/irq_monitor.py)
        self.irq = irq_monitor.Monitor(self, GUEST_BYTES)

        @U.CODE_CB
        def irq_deliver(h, addr, size, user):
            # The reference runs the IRQ0 handler on the interrupted stack: its
            # frame and its proved depth there (irq-footprint.csv stack row) are
            # dead below SS:SP; ours runs it on the private stack (I4).
            if self.irq.deliver() and self.irq_top is not None:
                self.masked.update(range(self.irq_top - 6 - self.irq.depth, self.irq_top))

        @U.CODE_CB
        def irq_back(h, addr, size, user):
            self.irq.returned()

        e.hook_range(U.HOOK_CODE, irq_deliver, self.syms["deliver_guest"], self.syms["deliver_guest"])

        # the music driver's flight callback (FLIGHT.OVL +19424, called by ADLIB.IMS
        # +006B6 from the tick) and the request-0Fh enqueue's stores of argument
        # words (+02B4D, +02B6D) at interrupt level: the lockstep must run them
        # where the reference did (translator/irq.py; docs/design.md)
        self.irq_counts = Counter()
        for name, what in (("FLT_19424", "callback"), ("AD_02B4D", "enqueue"), ("AD_02B6D", "enqueue")):
            if name in self.syms:
                @U.CODE_CB
                def count(h, addr, size, user, what=what):
                    self.irq_counts[what + (" irq" if self.irq.in_handler else " main")] += 1
                e.hook_range(U.HOOK_CODE, count, self.syms[name], self.syms[name])
        for n in ("rt_irq_async_back", "rt_irq_interrupt_back"):
            if n in self.syms:
                e.hook_range(U.HOOK_CODE, irq_back, self.syms[n], self.syms[n])

        # a main-code driver request (the API entry, ADLIB.IMS +0000): song reuse
        # boundaries for the monitor's race check
        @U.CODE_CB
        def driver_request(h, addr, size, user):
            if self.sabotage != "song-requests":
                self.irq.request()
        e.hook_range(U.HOOK_CODE, driver_request, self.syms["AD_00000"], self.syms["AD_00000"])

        # memory watch from the guest entry on (rt_start's own writes are not watched)
        self.in_service = False
        self.masked: set[int] = set()
        self.machine_reads: set[int] = set()
        # dead-stack reads by generated code since the last service event: a word
        # read as (value, its bytes masked: bit 0 low, bit 1 high), a byte read as
        # (value, None); a service register loaded from them may differ (ServiceLog,
        # owner decision 2026-11-09); control dead-off records none
        self.dead_reads: set[tuple[int, int | None]] = set()
        self.dead_watch = sabotage != "dead-off"
        # guest bytes whose last write was generated code storing a value it read from
        # dead stack since the last service event (by value: a byte store of a byte
        # read, or a word's bytes masked in a read of that whole word); they may differ
        # at the label (owner decision 2026-11-10)
        self.dead_stored: set[int] = set()

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            self.irq.write(TOP - addr - size + 1, size)    # I3 (tests/irq_monitor.py)
            span = range(TOP - addr - size + 1, TOP - addr + 1)
            if self.dead_stored and not self.dead_stored.isdisjoint(span):
                self.dead_stored.difference_update(span)
            if self.dead_reads and not self.in_service \
                    and self.code[0] <= self.r("pc") < self.code[1]:
                dead_store(span.start, size, value & ((1 << 8 * size) - 1))
            if self.dead_flags is not None and self.dead_flags in span:
                self.masked.update(span)
                self.dead_flags = None
            elif (not self.in_service and self.masked
                  and not self.masked.isdisjoint(span)
                  and not self.frame_writer[0] <= self.r("pc") < self.frame_writer[1]):
                # The interrupt frame belongs to the runtime. Preserve only
                # the existing dead-stack mask; all other writes still clear it.
                self.masked.difference_update(span)
            return True

        def dead_store(lin: int, size: int, value: int) -> None:
            # memory is reversed: the guest's little-endian value is the 68k one
            reads = self.dead_reads
            for k in range(size):
                b = value >> 8 * k & 0xFF
                if (b, None) in reads:
                    self.dead_stored.add(lin + k)
                elif size > 1:
                    w = value >> 16 * (k // 2) & 0xFFFF
                    if any((w, m) in reads for m in (1, 2, 3) if m >> k % 2 & 1):
                        self.dead_stored.add(lin + k)

        # The FLAGS image of an annotations/flags.csv PUSHF is dead by that
        # annotation; its word below SS:SP is masked until the guest rewrites it.
        @U.CODE_CB
        def dead_pushf(h, addr, size, user):
            g = self.guest_regs(0)
            self.dead_flags = g["ss"] * 16 + ((g["sp"] - 2) & 0xFFFF)

        self.dead_flags = None
        for r in image.rows("flags.csv"):
            lab = emit.label(r["module"], int(r["save"], 16))
            for a in {self.syms[x] for x in (lab, lab + "_bp") if x in self.syms}:  # R6 copy
                e.hook_range(U.HOOK_CODE, dead_pushf, a, a)

        machine = bytearray(GUEST_BYTES)
        for lo, hi in machine_ranges():
            machine[lo:hi] = b"\1" * (hi - lo)

        # ems_alias: ems.c keeps a page mapped at two frame pages as copies and
        # merges them at the next map call; a guest read through one of them
        # must see what every other copy holds (DOSBox-X maps one memory).
        self.ems_map, self.ems_alias_reads, self.ems_alias_bad = None, 0, []

        @U.CODE_CB
        def ems_call(h, addr, size, user):
            self.ems_map = None
        e.hook_range(U.HOOK_CODE, ems_call, self.syms["rt_int67"], self.syms["rt_int67"])

        def ems_alias(lin, size):
            if self.ems_map is None:
                self.ems_map = struct.unpack(">4H", self.mem(self.syms["mapped"], 8))
            for b in range(lin, lin + size):
                if not 0xE0000 <= b < 0xF0000:
                    continue
                p, o = (b - 0xE0000) >> 14, b & 0x3FFF
                slot = self.ems_map[p]
                if not slot or self.ems_map.count(slot) < 2:
                    continue
                self.ems_alias_reads += 1
                v = self.gmem(b, 1)
                for k in range(4):
                    if k != p and self.ems_map[k] == slot and \
                            self.gmem(0xE0000 + k * 0x4000 + o, 1) != v:
                        self.ems_alias_bad.append((b, k, len(self.services)))

        @U.MEM_CB
        def read(h, kind, addr, size, value, user):
            lin = TOP - addr - size + 1
            self.irq.read(lin, size)    # I3 (tests/irq_monitor.py)
            if (machine[lin] or machine[lin + size - 1]) and not self.in_service \
                    and self.code[0] <= self.r("pc") < self.code[1]:
                self.machine_reads.update(b for b in range(lin, lin + size) if machine[b])
            if lin + size > 0xE0000 and lin < 0xF0000 and not self.in_service \
                    and self.code[0] <= self.r("pc") < self.code[1]:
                ems_alias(lin, size)
            if self.dead_watch and not self.in_service and \
                    any(b in self.masked for b in range(lin, lin + size)) and \
                    self.code[0] <= self.r("pc") < self.code[1]:
                # (value, bytes masked): each word read, or a byte read as (value, None)
                if size == 1:
                    self.dead_reads.add((self.gmem(lin, 1)[0], None))
                for w in range(lin, lin + size - 1, 2):
                    mask = (w in self.masked) | (w + 1 in self.masked) << 1
                    if mask:
                        self.dead_reads.add((int.from_bytes(self.gmem(w, 2), "little"), mask))
            return True

        @U.CODE_CB
        def guest_start(h, addr, size, user):
            if self.watching:
                return
            self.watching = True
            # Below the entry SS:SP the loader's own frame is dead stack (DOSBox-X's
            # EXEC leaves the entry CS:IP there): masked as at a service call
            sp = int.from_bytes(self.mem(self.syms["rt_r"] + 8, 2), "big")  # struct rt_regs
            top = self.state(3, 2) * 16 + sp
            self.masked.update(range(top - DEAD_STACK, top))
            # Model the DOS shell's no-argument launch before the first guest
            # instruction; normal fixtures retain machine.c's default PSP.
            if self.launch:
                psp = (self.u32(self.syms["load_segment"]) - 0x10) * 16
                for off in (0x5d, 0x6d):
                    self.e.write(TOP - psp - off, b" ")
                self.e.write(TOP - psp - 0xff, (b"\0\r" + bytes(126))[::-1])
            if self.sabotage == "psp":
                a = TOP - (0x8120 + 0x5d)
                self.e.write(a, bytes([self.mem(a, 1)[0] ^ 0x20]))
            self.e.hook_range(U.HOOK_MEM_WRITE, write, TOP - GUEST_BYTES + 1, TOP)
            self.e.hook_range(U.HOOK_MEM_READ, read, TOP - GUEST_BYTES + 1, TOP)

        # generated code: from the first guest label to program.s's data after
        # the modules (the runtime's own reads, e.g. the BIOS tick, are not the
        # guest's)
        tags = tuple(t + "_" for t in emit.TAG.values())
        self.code = (min(v for k, v in self.syms.items() if k.startswith(tags)),
                     self.syms["load_segment"])
        self.watching = False
        a = self.syms["rt_run_guest"]
        e.hook_range(U.HOOK_CODE, guest_start, a, a)

    def r(self, name: str) -> int:
        return self.e.reg_read(U.M68K[name])

    def mem(self, a: int, n: int) -> bytes:
        return self.e.read(a, n)

    def gmem(self, a: int, n: int) -> bytes:
        """Guest bytes a..a+n-1 in guest order."""
        return self.e.read(TOP - a - n + 1, n)[::-1]

    def u32(self, a: int) -> int:
        return struct.unpack(">I", self.mem(a, 4))[0]

    def cstr(self, a: int) -> str:
        b = self.mem(a, 256)
        return b[:b.index(b"\0")].decode("latin-1")

    def state(self, off: int, n: int) -> int:
        return int.from_bytes(self.mem(TOP + off, n), "big")

    def guest_regs(self, vector: int) -> dict:
        regs = {n: self.r(r) & 0xFFFF for n, r in zip(REGS, ("d0", "d1", "d2", "d3", "d4", "d5",
                                                             "a4", "a5"))}
        regs["sp"] ^= 0x7FFF    # mirrored (translator/lower.py MIRROR)
        regs["bp"] ^= 0x7FFF
        regs.update(es=self.state(5, 2), ss=self.state(3, 2), ds=self.state(1, 2))
        ccr = self.state(16, 1)
        regs["cf"], regs["zf"] = ccr & 1, ccr >> 2 & 1
        regs["df"], regs["if"] = int(self.state(12, 1) != 0), int(self.state(11, 1) != 0)
        regs["vector"] = vector
        return regs

    def platform(self, n: str) -> None:
        sp = self.r("a7")
        args = struct.unpack(">IIII", self.mem(sp + 4, 16))
        res = 0
        if n in ("plat_open", "plat_dir_names", "plat_file_info", "plat_create", "plat_delete"):
            name = self.cstr(args[0])
            path = self.root
            for part in filter(None, name.split("/")):
                matches = [p for p in path.iterdir() if p.name.upper() == part] if path.is_dir() else []
                path = matches[0] if matches else self.root / "\0"
            on_disk = path.is_file() and name not in self.deleted
            is_dir = path.is_dir() and path != self.root / "\0"
        if n == "plat_alloc":
            size = (args[0] + 3) & ~3
            for i, (address, length) in enumerate(self.free_spans):
                if length >= size:
                    self.allocations[address] = size
                    self.free_spans[i:i+1] = [(address+size, length-size)] if length > size else []
                    res = address
                    break
        elif n == "plat_free":
            address = args[0]
            size = self.allocations.pop(address)
            spans = sorted(self.free_spans + [(address, size)])
            self.free_spans = []
            for address, length in spans:
                if self.free_spans and sum(self.free_spans[-1]) == address:
                    previous, size = self.free_spans.pop()
                    self.free_spans.append((previous, size+length))
                else:
                    self.free_spans.append((address, length))
        elif n == "plat_dir_names":
            prefix = name + "/" if name else ""
            disk = {p.name for p in path.iterdir()
                    if p.is_file() and len(p.name) <= 12 and prefix + p.name.upper() not in self.deleted} \
                if path.is_dir() else set()
            dirs = {p.name + "/" for p in path.iterdir() if p.is_dir() and len(p.name) <= 12} \
                if path.is_dir() else set()
            disk.update(w[len(prefix):] for w in self.written
                        if w.startswith(prefix) and "/" not in w[len(prefix):])
            packed = b"".join(n.encode() + b"\0" for n in sorted(disk | dirs))
            fit = packed[:args[2]]
            fit = fit[:fit.rfind(b"\0") + 1]
            if fit:
                self.e.write(args[1], fit)
            res = len(packed)
        elif n == "plat_file_info":
            if name in self.written:
                self.e.write(args[1], struct.pack(">IHH", len(self.written[name]), *self.file_stamps[name]))
            elif on_disk or is_dir:   # a directory: its host stat, as DOSBox-X's FindNext
                self.e.write(args[1], struct.pack(">IHH", path.stat().st_size, *dos_file_stamp(path.stat().st_mtime)))
                res = int(is_dir)
            else:
                res = -1
        elif n == "plat_open":
            if args[1] and on_disk and name not in self.written:
                self.written[name] = bytearray(path.read_bytes())  # a copy: ref/ stays untouched
                self.file_stamps[name] = dos_file_stamp(path.stat().st_mtime)
            f = MemFile(self.written[name]) if name in self.written else \
                path.open("rb") if on_disk else None
            if f:
                self.files[self.next_file] = f
                res, self.next_file = self.next_file, self.next_file + 1
            else:
                res = -1
        elif n == "plat_create":
            self.written[name] = bytearray()
            self.file_stamps[name] = dos_file_stamp(self.file_clock if self.file_clock is not None else time.time())
            self.deleted.discard(name)
            self.files[self.next_file] = MemFile(self.written[name])
            res, self.next_file = self.next_file, self.next_file + 1
        elif n == "plat_delete":
            if name in self.written:
                del self.written[name]
            elif on_disk:
                self.deleted.add(name)
            else:
                res = -1
        elif n == "plat_read":
            f = self.files[args[0]]
            data = f.read(args[2])
            if self.sabotage == "read" and data and self.watching:
                data = bytes([data[0] ^ 0xFF]) + data[1:]
            self.e.write(args[1], data)
            res = len(data)
        elif n == "plat_write":
            f = self.files[args[0]]
            res = f.write(self.mem(args[1], args[2])) if isinstance(f, MemFile) else -1
        elif n == "plat_seek":
            f = self.files[args[0]]
            off = args[1] - (1 << 32) if args[1] & 0x80000000 else args[1]
            res = f.seek(off, args[2])
        elif n == "plat_calendar_date":
            calendar = time.localtime(time.time())
            res = self.calendar_date if self.calendar_date is not None else \
                calendar.tm_year << 16 | calendar.tm_mon << 8 | calendar.tm_mday
        elif n == "plat_file_stamp":
            f = self.files[args[0]]
            if not isinstance(f, MemFile):
                raise AssertionError('explicit timestamp on a read-only platform file')
            f.dos_stamp = (args[1], args[2])
        elif n == "plat_close":
            f = self.files.pop(args[0])
            if isinstance(f, MemFile) and f.modified:
                for name, data in self.written.items():
                    if data is f.data:
                        self.file_stamps[name] = f.dos_stamp or dos_file_stamp(self.file_clock if self.file_clock is not None else time.time())
            f.close()
        elif n == "plat_mouse":
            self.e.write(args[0], struct.pack(">i", self.mouse_dx))
            self.e.write(args[1], struct.pack(">i", 0 if self.sabotage == "mouse-motion" else self.mouse_dy))
            self.mouse_dx = self.mouse_dy = 0
            res = self.mouse_buttons & (3 if self.sabotage == "mouse-buttons" else 7)
        elif n == "plat_present":
            self.presents += 1
            shown = bytearray(64000)
            for k in range(args[2]):
                x0, y0, x1, y1 = struct.unpack(">4H", self.mem(args[1] + 8 * k, 8))
                for y in range(y0, y1):
                    shown[y * 320 + x0:y * 320 + x1] = b"\1" * (x1 - x0)
            miss = sorted(o for o in self.vram_written if not shown[o])
            if miss and not self.display_miss:
                self.display_miss = f"present {self.presents}: {len(miss)} stored pixels outside " \
                    f"its rectangles, first x={miss[0] % 320} y={miss[0] // 320}"
            self.vram_written.clear()
            self.e.write(self.syms["rt_present_due"], b"\1")
        elif n == "plat_palette":
            if self.sabotage == "dac":
                self.e.write(args[0] + 300, bytes([self.mem(args[0] + 300, 1)[0] ^ 1]))
        elif n == "plat_vga_status":
            res = self.vga_status()
        elif n == "plat_log":
            self.log.append(self.cstr(args[0]))
            print(self.log[-1])
        elif n == "plat_console":
            self.console += self.mem(args[0], args[1])
        elif n == "plat_exit":
            self.exit = args[0]
            self.halted = True
            self.e.stop()
        self.e.reg_write(U.M68K["d0"], res & 0xFFFFFFFF)

    def vga_status(self) -> int:
        """The reference's next 3DAh value, read in the same service interval."""
        n = len(self.services)
        while self.retrace_i < len(self.retrace) and self.retrace_used == self.retrace[self.retrace_i][2]:
            self.retrace_i, self.retrace_used = self.retrace_i + 1, 0
        if self.retrace_i == len(self.retrace):
            self.retrace_bad = self.retrace_bad or f"VGA status read after the reference's last (service events {n})"
            return 0
        svc, value, _ = self.retrace[self.retrace_i]
        if svc != n:
            self.retrace_bad = self.retrace_bad or \
                f"VGA status read #{sum(r[2] for r in self.retrace[:self.retrace_i]) + self.retrace_used} " \
                f"at service event {n}, the reference's at {svc}"
        self.retrace_used += 1
        if self.sabotage == "retrace" and self.retrace_i == len(self.retrace) // 2 and self.retrace_used == 1:
            value ^= 8
        return value

    def retrace_left(self) -> int:
        return sum(r[2] for r in self.retrace[self.retrace_i:]) - self.retrace_used

    def post(self, vector: int) -> None:
        tail = self.mem(self.syms["rt_irq_tail"], 1)[0]
        self.e.write(self.syms["rt_irq_ring"] + tail % 32, bytes([vector]))
        self.e.write(self.syms["rt_irq_tail"], bytes([(tail + 1) & 0xFF]))
        self.e.write(self.syms["rt_irq_pending"], b"\1")  # RT_RAISE_IRQ
        self.e.write(G_IRQ, b"\1")

    def guest_vector(self, vector: int) -> bool:
        """machine.c guest_vector: the IVT entry points into the program's memory,
        from its PSP to the top of DOS memory."""
        off, seg = struct.unpack("<HH", self.gmem(vector * 4, 4))
        psp = int.from_bytes(self.mem(self.syms["load_segment"], 4), "big") - 0x10
        return psp * 16 <= seg * 16 + off < 0x9FFF * 16

    def press(self, key: int) -> None:
        """The key's make and break scan codes (runtime.h rt_key_ring); the
        runtime's BIOS INT 09h model stores the word at the make interrupt."""
        # DOSBox posts one IRQ per scan byte, including modifiers and E0.
        events = key_events(key)
        for ev in events:
            tail = self.mem(self.syms["rt_key_tail"], 1)[0]
            self.e.write(self.syms["rt_key_ring"] + 2 * (tail % 16), struct.pack(">H", ev))
            self.e.write(self.syms["rt_key_tail"], bytes([(tail + 1) & 0xFF]))

    def run(self, script: dict | None, timeout: int) -> None:
        """Run to the script's last snapshot trigger (None: until a stop).
        Hardware interrupts replay the reference's (script["irqs"]): posted at
        the same visit of the same poll point after the same service event;
        key release eligibility uses recorded trigger visits when available."""
        steps = [(t, k) for t, k in script["keys"]] + [(t, None) for t in script["snapshots"]] \
            if script else []
        releases = list(script["releases"]) if script else []
        self.irqs = list(script["irqs"]) if script else []
        self.step, self.hits, self.release = 0, 0, None
        self.irq_i, self.visit_n, self.visits, self.groups = 0, None, {}, {}
        self.irq_lost: str | None = None
        makes = 0
        rep = script.get("rep") if script else None
        rep_labels = set(rep.labels) if rep else set()
        # an instruction's label and its guarded copy's (R6) are one guest instruction
        at = {lab: {self.syms[x] for x in (lab, lab + "_bp") if x in self.syms}
              for lab in {t[0] for t, _ in steps} | {lab for _, lab, _, _ in self.irqs} | rep_labels}
        canon = {a: lab for lab, addrs in at.items() for a in addrs}

        # --bypass: the copy-protection hook (annotations/hle.csv) replaces the
        # screen. The reference's service events from the hook to the screen's
        # return (its first snapshot, at the return site) are the screen's:
        # they stand in the service log unrun, so the interrupts, REP slices
        # and VGA reads after the return keep their service-event keys; the
        # screen's own are dropped. From the hook on only the snapshot steps
        # remain; the first is the return site itself.
        self.bypass_n = None
        if script and script.get("bypass"):
            first_snapshot = len(script["keys"])
            n1 = script["bypass"]

            @U.CODE_CB
            def bypass(h, addr, size, user):
                self.bypass_n = len(self.services)
                self.services.skip(n1)
                i = self.irq_i
                while i < len(self.irqs) and self.irqs[i][0] < n1:
                    i += 1
                self.bypass_irqs = i - self.irq_i
                del self.irqs[self.irq_i:i]
                while self.retrace_i < len(self.retrace) and self.retrace[self.retrace_i][0] < n1:
                    self.retrace_i, self.retrace_used = self.retrace_i + 1, 0
                if rep is not None:
                    while rep.index < len(rep.chunks) and rep.chunks[rep.index].service < n1:
                        rep.index += 1
                    rep.active = False
                self.step, self.hits, self.release = max(self.step, first_snapshot), 0, None

            a = self.syms["rt_hle_copy_protection"]
            self.e.hook_range(U.HOOK_CODE, bypass, a, a)

        # --bypass past the screen: the hook runs as in the production image; the
        # reference applied the same bypass at the same call (tools/reference.py
        # --bypass). Control "answer": the bypass leaves AX = 0, a wrong answer.
        self.bypass_hits = 0
        if script and "bypassed" in script:
            wrong = script["bypassed"] == "answer"
            ret = self.syms[RETURN_SITE]
            armed = []

            @U.CODE_CB
            def bypassed(h, addr, size, user):
                if not self.bypass_hits:
                    self.bypass_n = len(self.services)
                self.bypass_hits += 1
                armed.append(True)

            @U.CODE_CB
            def returned(h, addr, size, user):
                if armed and wrong:
                    self.e.reg_write(U.M68K["d0"], self.r("d0") & 0xFFFF0000)
                armed.clear()

            a = self.syms["rt_hle_copy_protection"]
            self.e.hook_range(U.HOOK_CODE, bypassed, a, a)
            self.e.hook_range(U.HOOK_CODE, returned, ret, ret)

        # --screen: the hook returns Z set, so the generated code goes on with the
        # call it replaces and the translated protection screen runs on the
        # reference's keys (annotations/hle.csv; byte-exact lockstep through it)
        if script and script.get("screen"):
            @U.CODE_CB
            def screen(h, addr, size, user):
                sp = self.r("a7")
                self.e.reg_write(U.M68K["a7"], sp + 4)
                self.e.reg_write(U.M68K["d7"], 0)
                self.e.reg_write(U.M68K["sr"], self.r("sr") | 4)
                self.e.reg_write(U.M68K["pc"], self.u32(sp))
                self.screen_n = len(self.services)

            self.screen_n = None
            a = self.syms["rt_hle_copy_protection"]
            self.e.hook_range(U.HOOK_CODE, screen, a, a)

        @U.CODE_CB
        def hit(h, addr, size, user):
            if self.step == len(steps):
                return
            (lab, _, n), key = steps[self.step]
            if self.release is not None:
                if not self.release.ready(len(self.services), addr in at[lab]):
                    return
                self.release = None
            if addr not in at[lab]:
                return
            self.hits += 1
            if self.hits < n:
                return
            self.step, self.hits = self.step + 1, 0
            if isinstance(key, str):
                if key.startswith('j'):
                    return  # Device effects come from recorded gameport accesses.
                amount = int(key[2:])
                if key[1] == "x":
                    self.mouse_dx += amount
                elif key[1] == "y":
                    self.mouse_dy += amount
                else:
                    self.mouse_buttons = amount
            elif key is not None:
                self.press(key)
                self.release = KeyRelease(releases.pop(0))
            elif self.step == len(steps):
                self.stopped_at = lab
                self.halted = True
                self.e.stop()

        @U.CODE_CB
        def poll(h, addr, size, user):
            try:
                replay(addr)
            except Exception as e:  # ctypes drops exceptions raised in hooks
                self.irq_lost = f"interrupt replay: {e!r}"
                self.halted = True
                self.e.stop()

        def replay(addr):
            if self.irq_i == len(self.irqs):
                return
            n = len(self.services)
            if n != self.visit_n:  # executions of each poll point since the service event
                self.visit_n, self.visits = n, {}
            here = canon[addr]
            svc, lab, hits, _ = self.irqs[self.irq_i]
            if n > svc and not self.irq_lost:
                self.irq_lost = f"reference irq #{self.irq_i} at {lab} svc={svc} hits={hits} " \
                                f"not reached (service events {n})"
            if n != svc or here != lab or self.visits.get(here, 0) != hits:
                return
            post_group(self.r("a7"))

        def post_group(a7):
            """Post the next interrupt of the reference's (svc, label, hits) group;
            for the BIOS's handlers (instant) the whole group. One the guest
            handles, the reference took the next of its group only after the IRET
            back to the same poll point (rt_irq_back at this stack depth)."""
            nonlocal makes
            key = self.irqs[self.irq_i][:3]
            while self.irq_i < len(self.irqs) and self.irqs[self.irq_i][:3] == key:
                vector = self.irqs[self.irq_i][3]
                guest = self.guest_vector(vector)
                if vector == 9:
                    makes += 1
                    vector = 9 if makes % 2 else 0x89  # make, then the key's break
                self.post(vector)
                self.irq_i += 1
                if guest:
                    self.groups[a7 - 12] = key  # a7 at rt_irq_back: jsr rt_irq, movem d6-d7
                    return

        @U.CODE_CB
        def back(h, addr, size, user):
            try:
                stack = self.r("a7")
                key = self.groups.pop(stack, None)
                if key and self.irq_i < len(self.irqs):
                    n = len(self.services)
                    if n != self.visit_n:
                        self.visit_n, self.visits = n, {}
                    # IRET returns before the instruction. Handler visits or
                    # services may make a new count eligible at this point.
                    resume = (n, key[1], self.visits.get(key[1], 0))
                    if self.irqs[self.irq_i][:3] == resume:
                        post_group(stack + 12)
            except Exception as e:  # ctypes drops exceptions raised in hooks
                self.irq_lost = f"interrupt replay: {e!r}"
                self.halted = True
                self.e.stop()

        # The poll entry precedes interrupt delivery; _np is the actual
        # instruction continuation, including returns from guarded copies.
        continuations = {}
        for lab in {r[1] for r in self.irqs} | rep_labels:
            for name in (lab + "_np", lab + "_bp_np"):
                if name in self.syms:
                    continuations[self.syms[name]] = lab
            if lab + "_np" not in self.syms:
                raise ValueError(f"missing replay execution continuation: {lab}")

        @U.CODE_CB
        def executed(h, addr, size, user):
            n = len(self.services)
            if n != self.visit_n:
                self.visit_n, self.visits = n, {}
            here = continuations[addr]
            self.visits[here] = self.visits.get(here, 0) + 1

        for a in continuations:
            self.e.hook_range(U.HOOK_CODE, executed, a, a)

        if rep is not None:
            @U.CODE_CB
            def rep_checkpoint(h, addr, size, user):
                try:
                    sp = self.r("a7")
                    point, done = struct.unpack(">II", self.mem(sp + 4, 8))
                    lab = rep.labels[point]
                    regs = tuple(self.r(r) & 0xffff for r in ("d1", "a4", "a5"))
                    resumed = rep.checkpoint(point, regs, len(self.services),
                                             self.visits.get(lab, 0), done)
                    self.e.write(sp + 4, struct.pack(">I", int(resumed)))
                except Exception as error:
                    self.irq_lost = f"REP replay: {error}"
                    self.e.stop()
            a = self.syms["rt_replay_rep"]
            self.e.hook_range(U.HOOK_CODE, rep_checkpoint, a, a)

        # static hooks (Unicorn retranslates on every hook change)
        for a in {a for t, _ in steps for a in at[t[0]]}:
            self.e.hook_range(U.HOOK_CODE, hit, a, a)
        for a in {a for _, lab, _, _ in self.irqs for a in at[lab]}:
            self.e.hook_range(U.HOOK_CODE, poll, a, a)
        self.e.hook_range(U.HOOK_CODE, back, self.syms["rt_irq_back"], self.syms["rt_irq_back"])
        self.e.reg_write(U.M68K["sr"], 0x2700)
        self.e.reg_write(U.M68K["a7"], STACK_TOP)
        self.halted = False
        err = self.e.start(self.entry, 0xFFFFFFFF, timeout_us=timeout * 1_000_000)
        self.timed_out = self.e.timed_out()
        if err:
            print(f"unicorn error {U.uc.uc_strerror(err).decode()} pc={self.r('pc'):x}")
            self.exit = -1
        if self.irq_i < len(self.irqs) and self.irqs[self.irq_i][0] < len(self.services) \
                and not self.irq_lost:
            svc, lab, hits, _ = self.irqs[self.irq_i]
            self.irq_lost = f"reference irq #{self.irq_i} at {lab} svc={svc} hits={hits} " \
                            f"not reached (service events {len(self.services)})"


def trigger(spec: str) -> tuple[str, int, int]:
    """MODULE+HEX[#N] -> (label, offset, N)."""
    at, _, n = spec.partition("#")
    mod, off = at.split("+")
    off = off.removeprefix("0x")
    return emit.label(mod, int(off, 16)), int(off, 16), int(n or 1)


def milestone_script(name: str, bypassed: bool = False) -> dict:
    """reference/milestones.csv row: the run stops at the last snapshot trigger;
    keys (those of `after`, then its own: tools/reference.py) are pressed in order,
    each counted from the previous key's release (the tracer's rules); the frame
    is compared at vga_mode 13. bypassed: the keys of a bypassed reference (those
    typed into the screen left out: tools/reference.py --bypass)."""
    rows = {r["name"]: r for r in csv.DictReader(TABLE.open())}
    r = rows[name]
    keys = []
    for k in R.keys(rows, name, bypassed):
        spec, _, key = k.rpartition("=")
        keys.append((trigger(spec), key if key.startswith(("mx", "my", "mb")) else key_code(key)))
    return {"keys": keys, "snapshots": [trigger(R.site(t)) for t in r["snapshots"].split()],
            "frame": r["vga_mode"] == "13"}


def host_reference(milestone: str, bypassed: bool = False) -> Path:
    """The newest host reference run's trace (tools/reference.py --polls; bypassed:
    --polls --bypass, the port's copy-protection bypass applied in the reference)."""
    runs = sorted(RUNS.glob(f"{'hostb' if bypassed else 'host'}-*-{milestone}"))
    if not runs:
        raise SystemExit(f"no host reference for {milestone}: python3 tools/reference.py --polls "
                         f"{'--bypass ' if bypassed else ''}{milestone}")
    return runs[-1] / "trace"


def reference_bypass(trace: Path) -> int:
    """A bypassed reference: the service events before its one bypass event."""
    n, at = 0, []
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                n += 1
            elif r["kind"] == "bypass":
                at.append(n)
    if len(at) != 1:
        raise SystemExit(f"{trace}: {len(at)} bypass events, not one")
    return at[0]


def retrace_runs(trace: Path) -> list[tuple[int, int, int]]:
    with (trace / "retrace.csv").open() as f:
        return [(int(r["service"]), int(r["value"]), int(r["repeat"])) for r in csv.DictReader(f)]


def machine_ranges() -> list[tuple[int, int]]:
    """Guest memory outside COMPARE."""
    out, at = [], 0
    for lo, hi in sorted(COMPARE + [FRAME, IRQ_STACK]):
        out.append((at, lo))
        at = hi
    return [(lo, hi) for lo, hi in out + [(at, GUEST_BYTES)] if lo < hi]


class ServiceLog:
    """The host's service log, compared event by event with the reference's as it
    grows, so neither log is held (m14's are 65 million events). CF/ZF: services
    read no flags, so the state block may hold dead ones at entry; at return they
    are checked where the reference service changed them or where they agreed at
    entry. The first difference is kept; the count is checked at the label.

    Dead stack (owner decision 2026-11-09): dead stack below SS:SP holds other
    bytes than DOS's (INFERRED: IRQ0's handler runs on the private stack, I4), and
    the game builds some service register blocks there (intdos with an uninitialized
    REGS: m10's INT 21h AH=47h loads AL, BX, CX, DH and DI from it). At an entry a
    byte of AX, BX, CX, DX, SI or DI may differ only when generated code read that
    byte value at that byte of a word from masked dead stack since the last service
    event (Host.dead_reads): a word read of its whole value with every differing
    byte masked, or byte reads of each differing byte's value; at the return only
    while both sides hold their entry values. SP, BP, the segments, the vector and
    the flags stay exact."""

    KEYS = REGS + ("es", "ss", "ds", "vector")
    DEAD = ("ax", "bx", "cx", "dx", "si", "di")

    def __init__(self, want=None, dead: set | None = None):
        self.want = want            # iterator of the reference's (kind, regs), or None
        self.dead = dead            # Host.dead_reads, cleared at each service event
        self.n = self.consumed = 0
        self.bad: list[str] = []
        self.entry: list = []
        self.dead_bytes = 0
        self.dead_first: str | None = None

    def __len__(self) -> int:
        return self.n

    def append(self, item) -> None:
        k, self.n = self.n, self.n + 1
        reads = set(self.dead) if self.dead else set()
        if self.dead is not None:
            self.dead.clear()
        if self.want is None or self.bad or self.consumed < k:
            return
        ref = next(self.want, None)
        if ref is None:
            return
        self.consumed += 1
        (gk, g), (wk, w) = item, ref
        dead = {}
        if gk == "svc":
            for n in self.DEAD:
                differ = (1 if (g[n] ^ w[n]) & 0xFF else 0) | (2 if (g[n] ^ w[n]) >> 8 else 0)
                if g[n] != w[n] and (
                        any(v == g[n] and m is not None and differ & ~m == 0 for v, m in reads)
                        or all((g[n] >> 8 * pos & 0xFF, None) in reads
                               for pos in (0, 1) if differ >> pos & 1)):
                    dead[n] = (g[n], w[n])
                    self.dead_bytes += bin(differ).count("1")
                    if self.dead_first is None:
                        self.dead_first = (f"#{k} int {w['vector']:02x} ax={w['ax']:04x} "
                                           f"{n}={g[n]:04x}/{w[n]:04x}")
            self.entry.append((g, w, dead))
            keep = dead
        else:
            ge, we, was = self.entry.pop() if self.entry else (g, w, {})
            keep = {n: v for n, v in was.items() if (g[n], w[n]) == v}
        diff = [f"{n}={g[n]:04x}/{w[n]:04x}" for n in self.KEYS if g[n] != w[n] and n not in keep]
        flags = w["flags"]
        for n, bit in (("cf", 0x1), ("zf", 0x40), ("if", 0x200), ("df", 0x400)):
            want = int(bool(flags & bit))
            if n in ("cf", "zf"):
                if gk == "svc":
                    continue
                if int(bool(we["flags"] & bit)) == want and ge[n] != want:
                    continue
            if g[n] != want:
                diff.append(f"{n}={g[n]}/{want}")
        if gk != wk or diff:
            self.bad.append(f"service #{k} {wk} int {w['vector']:02x} ax={w['ax']:04x}: "
                            f"{' '.join(diff) or gk}")

    def skip(self, n: int) -> None:
        """The reference's events to n are the host's too (the bypass skips the
        protection screen's): each counts as run and equal."""
        while self.n < n:
            ref = next(self.want, None) if self.want is not None and self.consumed == self.n else None
            if ref is not None:
                self.consumed += 1
                if ref[0] == "svc":
                    self.entry.append((ref[1], ref[1], {}))
                elif self.entry:
                    self.entry.pop()
            self.n += 1

    def finish(self, reached: bool) -> list[str]:
        """The first difference; at the label also the count. Sets total."""
        self.total = self.consumed + (sum(1 for _ in self.want) if self.want else 0)
        if reached and not self.bad and self.n != self.total:
            return [f"service count {self.n} vs reference {self.total}"]
        return self.bad


def compare_ram(ram: bytes, ref: bytes, residency: Path, masked: set[int]) -> list[str]:
    rows = image.M.residency(residency)
    bad, total = [], 0
    for lo, hi in COMPARE:
        k = lo
        while k < hi:
            if ram[k] == ref[k] or k in masked:
                k += 1
                continue
            j = k
            while j < hi and (ram[j] != ref[j] or j + 1 < hi and ram[j + 1] != ref[j + 1]):
                j += 1
            total += j - k
            where = image.M.locate(rows, k)
            owner = f"{where[0]}+{where[1]:05X}" if where else "-"
            if len(bad) < 40:
                bad.append(f"ram {k:05X}..{j:05X} ({owner}): ours {ram[k:min(j, k + 12)].hex()} "
                           f"ref {ref[k:min(j, k + 12)].hex()}")
            k = j
    if total:
        bad.append(f"{total} bytes differ")
    return bad


def compare_frame(ram: bytes, dac: bytes, snap: Path, size: int = FRAME[1] - FRAME[0],
                  boxes: int = 0, pending: set[int] | None = None) -> list[str]:
    """boxes: up to that many 16x16 boxes of differing pixels are the mouse arrow's
    (--bypass: drawn at the screen's mouse position in the reference). pending:
    pixels not compared (compare_shown)."""
    planes = (snap / "vram.bin").read_bytes()
    lo = FRAME[0]
    ref = bytes(planes[((a & ~3) << 2) | (a & 3)] for a in range(size))
    bad = [a for a in range(size) if ram[lo + a] != ref[a] and not (pending and a in pending)]
    corners: list[tuple[int, int]] = []
    for a in bad:
        x, y = a % 320, a // 320
        if not any(cx <= x < cx + 16 and cy <= y < cy + 16 for cx, cy in corners):
            corners.append((x, y))  # raster order: the arrow's tip, its top-left
    if boxes and len(corners) <= boxes:
        bad = []
    out = [f"frame: {len(bad)} bytes differ, first at A000:{bad[0]:04X} ours "
           f"{ram[lo + bad[0]]:02x} reference {ref[bad[0]]:02x}"] if bad else []
    want = (snap / "dac.bin").read_bytes()
    bad = [k for k in range(256) if dac[k * 3:k * 3 + 3] != want[k * 3:k * 3 + 3]]
    if bad:
        k = bad[0]
        out.append(f"DAC: {len(bad)} entries differ, first {k:02x} ours {dac[k * 3:k * 3 + 3].hex()} "
                   f"reference {want[k * 3:k * 3 + 3].hex()}")
    return out


def compare_shown(capture: Path, bytes_per_row: int, snap: Path,
                  pending: set[int] | None = None) -> list[str]:
    """The Amiga screen: 8 bitplanes, plane k = bit k of the pixel; colours =
    LoadRGB32 (count << 16, first 0), 32-bit guns whose top 6 bits are the DAC.
    pending: pixels stored since the last present, at a label that is not the
    game's mouse poll (D9: a frame is presented only there), not compared."""
    if not bytes_per_row:
        return ["amiga: no screen shown"]
    planes = [(capture / f"plane{k}.bin").read_bytes() for k in range(8)]
    lo, hi = FRAME
    shown = bytearray(320 * 200)
    for y in range(200):
        for xb in range(40):
            bits = [p[y * bytes_per_row + xb] for p in planes]
            for b in range(8):
                shown[y * 320 + xb * 8 + b] = sum(((bits[k] >> (7 - b)) & 1) << k for k in range(8))
    words = struct.unpack(f">{1 + 768 + 1}I", (capture / "colours.bin").read_bytes())
    dac = bytearray(w >> 26 for w in words[1:769])
    out = []
    if words[0] != 256 << 16:
        out.append(f"amiga: LoadRGB32 header {words[0]:08x}")
    dac = bytes(dac)
    ram = bytes(lo) + bytes(shown) + bytes(hi - lo - len(shown))
    out += [f"amiga shown: {p}" for p in compare_frame(ram, dac, snap, len(shown), pending=pending)]
    return out


# The emulator's own picture: a one-field trace screenshot of the native FS-UAE
# (tests/amiga_replay.py), 754x576 with the 320x200 screen at 2x2 from (74, 60)
# (DIWSTRT $3881). Composed planes and sprite words cannot show what the
# chipset does with them (a fetch window that took the sprites' DMA slots).
VIDEO_SIZE, VIDEO_ORIGIN = (754, 576), (74, 60)


def compare_video(png: Path, snap: Path) -> list[str]:
    """Every screen pixel of the real video against the DOSBox frame's colour
    (6-bit DAC guns as g << 2 | g >> 4), exactly."""
    from PIL import Image
    picture = Image.open(png).convert("RGB")
    if picture.size != VIDEO_SIZE:
        return [f"video: screenshot size {picture.size}, expected {VIDEO_SIZE}"]
    px = picture.load()
    planes = (snap / "vram.bin").read_bytes()
    dac = (snap / "dac.bin").read_bytes()
    rgb = [tuple(g << 2 | g >> 4 for g in dac[3 * k:3 * k + 3]) for k in range(256)]
    ox, oy = VIDEO_ORIGIN
    bad = []
    for a in range(320 * 200):
        x, y = a % 320, a // 320
        want = rgb[planes[((a & ~3) << 2) | (a & 3)]]
        if any(px[ox + 2 * x + i, oy + 2 * y + j] != want for i in (0, 1) for j in (0, 1)):
            bad.append(a)
    if not bad:
        return []
    a = bad[0]
    return [f"video: {len(bad)} of 64000 pixels differ from the DOSBox frame, first x={a % 320} "
            f"y={a // 320} shown {px[ox + 2 * (a % 320), oy + 2 * (a // 320)]}"]


def check_capture(tag, regs, state, ram, dac, ref_regs, ref, snap, h, exempt=None) -> list[str]:
    """Registers (state block: segments), RAM, framebuffer and DAC (dac None:
    not compared) of one capture vs the snapshot. exempt (--bypass, bypass_exempt):
    registers, frame boxes and machine bytes that are the screen's."""
    problems = []
    exempt = exempt or {}
    seg = {"es": state[4:6], "ss": state[2:4], "ds": state[0:2]}  # G_ES +5, G_SS +3, G_DS +1
    regs = dict(regs, **{n: int.from_bytes(v, "big") for n, v in seg.items()})
    for n in REGS + ("es", "ss", "ds"):
        if n in exempt.get("regs", ()):
            continue
        if regs[n] != int(ref_regs[n], 16):
            problems.append(f"{tag}: register {n} {regs[n]:04x} reference {ref_regs[n]}")
    dead = sum(ram[a] != ref[a] for a in h.masked if a < len(ref))
    print(f"{tag}: dead stack {len(h.masked)} bytes masked, {dead} of them differ")
    stored = sorted(a for a in h.dead_stored - h.masked if a < len(ref) and ram[a] != ref[a])
    print(f"{tag}: stores from dead stack {len(h.dead_stored)} bytes, {len(stored)} of them differ"
          f"{' (exempt), first ' + format(stored[0], '05X') if stored else ''}")
    problems += [f"{tag}: {p}" for p in compare_ram(ram, ref, snap / "residency.csv",
                                                     h.masked | h.dead_stored)]
    if dac is not None:
        problems += [f"{tag}: {p}" for p in compare_frame(ram, dac, snap, boxes=exempt.get("boxes", 0))]
    lo, hi = exempt.get("machine", (0, 0))
    reads = sorted(a for a in h.machine_reads if a < len(ref) and ram[a] != ref[a]
                   and not lo <= a < hi)
    print(f"{tag}: machine bytes read by the guest {len(h.machine_reads)}, {len(reads)} differ")
    for a in reads[:20]:
        problems.append(f"{tag}: machine byte {a:05X} read by the guest: ours {ram[a]:02x} "
                        f"reference {ref[a]:02x}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", default="m01-logo")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds of emulation before failing")
    ap.add_argument("--amiga", type=Path, help="also check this A1200-model capture")
    ap.add_argument("--label", action="store_true", help="print the milestone's label and exit")
    ap.add_argument("--sabotage", action="store_true",
                    help="each planted runtime fault (SABOTAGE) must fail the check")
    ap.add_argument("--dead-sabotage", nargs="*", choices=DEAD_SABOTAGE, metavar="CONTROL",
                    help="each named DEAD_SABOTAGE control (default all) of the dead-stack rule "
                         "must fail the check (registers: m10; stores: m14)")
    ap.add_argument("--screen", action="store_true",
                    help="the copy-protection hook declines: the translated screen runs on the "
                         "reference's keys, byte-exact lockstep through it (diagnostic)")
    ap.add_argument("--bypass", action="store_true",
                    help="the copy-protection hook replaces the screen: at "
                         f"{BYPASS_MILESTONE} lockstep to it, then the state at the return "
                         "outside the screen's; past it, lockstep with the bypassed reference")
    args = ap.parse_args(argv)
    if args.label:
        print(milestone_script(args.milestone)["snapshots"][-1][0])
        return 0
    if args.sabotage and args.bypass:
        missed = []
        controls = BYPASS_SABOTAGE if args.milestone == BYPASS_MILESTONE else {
            n: (w,) for n, w in BYPASS_LATE_SABOTAGE.items()}
        for name, (what, *_) in controls.items():
            problems = check(args.milestone, args.timeout, None, None, bypass=True,
                             bypass_sabotage=name)
            print(f"bypass sabotage {name:9} ({what}): {len(problems)} problems, first: "
                  f"{problems[0] if problems else '-'}", flush=True)
            if not problems:
                missed.append(name)
        print(f"bypass sabotage: {'all caught' if not missed else 'MISSED ' + ' '.join(missed)}")
        return 1 if missed else 0
    if args.dead_sabotage is not None:
        missed = []
        for name, what in DEAD_SABOTAGE.items():
            if args.dead_sabotage and name not in args.dead_sabotage:
                continue
            problems = check(args.milestone, args.timeout, None, name, bypass=args.bypass,
                             screen=args.screen)
            print(f"dead sabotage {name:12} ({what}): {len(problems)} problems, first: "
                  f"{problems[0] if problems else '-'}", flush=True)
            if not problems:
                missed.append(name)
        print(f"dead sabotage: {'all caught' if not missed else 'MISSED ' + ' '.join(missed)}")
        return 1 if missed else 0
    if args.sabotage:
        missed = []
        for name, what in SABOTAGE.items():
            problems = check(args.milestone, args.timeout, None, name)
            print(f"sabotage {name:12} ({what}): {len(problems)} problems, first: "
                  f"{problems[0] if problems else '-'}", flush=True)
            if not problems:
                missed.append(name)
        print("not caught: " + ", ".join(missed) if missed else "all sabotages caught")
        return 1 if missed else 0
    if args.screen and args.bypass:
        raise SystemExit("--screen and --bypass exclude each other")
    problems = check(args.milestone, args.timeout, args.amiga, None, bypass=args.bypass,
                     screen=args.screen)
    for p in problems:
        print(p)
    print(f"host run to {args.milestone}: {'ok' if not problems else 'FAIL'}")
    return 1 if problems else 0


def resident_problems(sabotage: str | None = None) -> list[str]:
    """machine.c rt_lookup chooses among the rows sharing a CS:IP by the overlay
    descriptors' resident bit (m01 dispatches none of them; MEASURED 2026-11-06):
    for each such key, each row's overlay alone resident must return that row."""
    h, problems = Host(image.M.REF, sabotage), []
    ret = h.syms["plat_exit"]  # stop address, never executed
    h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
    n = h.u32(h.syms["dispatch_count"])
    # the rows' overlays from an unplanted image (the plant zeroes them in h)
    craw = Host(image.M.REF).mem(h.syms["dispatch_table"], 12 * n)
    real: dict[int, list[tuple[int, int]]] = {}
    for j in range(n):
        cs, ip, overlay, _far, code = struct.unpack_from(">HHHHI", craw, 12 * j)
        real.setdefault(cs << 16 | ip, []).append((overlay, code))
    shared = {k: v for k, v in real.items() if len(v) > 1}
    if not shared:
        return ["resident probe: no CS:IP shared by dispatch rows"]
    flags_at = lambda ov: (h.u32(h.syms["load_segment"]) * 16 + h.u32(h.syms["overlay_table"])
                           + 18 * (ov - 1) + 7)
    for key, cands in sorted(shared.items()):
        for overlay, code in cands:
            if not overlay:
                continue
            for other, _ in cands:
                if other:
                    h.e.write(TOP - flags_at(other), bytes([0x02 if other == overlay else 0]))
            h.e.write(STACK_TOP - 16, ret.to_bytes(4, "big") + (key >> 16).to_bytes(4, "big")
                      + (key & 0xFFFF).to_bytes(4, "big") + (0).to_bytes(4, "big"))
            h.e.reg_write(U.M68K["sr"], 0x2700)
            h.e.reg_write(U.M68K["a7"], STACK_TOP - 16)
            h.e.start(h.syms["rt_lookup"], ret, timeout_us=1_000_000)
            if h.r("pc") != ret or h.r("d0") != code:
                problems.append(f"rt_lookup {key >> 16:04x}:{key & 0xFFFF:04x} with overlay "
                                f"{overlay} alone resident: {h.r('d0'):x}, want {code:x} "
                                f"(pc={h.r('pc'):x})")
    return problems


def rearm_problems() -> list[str]:
    """runtime.h poll-point contract on the C path the replay never reaches (it
    posts only where the reference took the interrupt, so with IF set):
    rt_set_flags_word with IF set re-arms G_IRQ from rt_irq_pending."""
    h, problems = Host(image.M.REF), []
    ret = h.syms["plat_exit"]  # stop address, never executed
    h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
    for flags in (0x0002, 0x0202):
        for pending in (0, 1):
            h.e.write(G_IRQ, b"\0")
            h.e.write(h.syms["rt_irq_pending"], bytes([pending]))
            h.e.write(STACK_TOP - 8, ret.to_bytes(4, "big") + flags.to_bytes(4, "big"))
            h.e.reg_write(U.M68K["sr"], 0x2700)  # first: it selects which a7
            h.e.reg_write(U.M68K["a7"], STACK_TOP - 8)
            h.e.start(h.syms["rt_set_flags_word"], ret, timeout_us=1_000_000)
            got, want = h.mem(G_IRQ, 1)[0], int(bool(flags & 0x200) and pending)
            if h.r("pc") != ret or got != want:
                problems.append(f"rt_set_flags_word({flags:04x}) with rt_irq_pending {pending}: "
                                f"G_IRQ {got}, want {want} (pc={h.r('pc'):x})")
    return problems


def check_opl(h, trace: Path, counts: bool = True) -> list[str]:
    """The host's AdLib writes, per port and value, are the reference's
    (ports.csv of the same run); rt_opl and rt_opl_keyon hold the registers and
    key-on edges (B0-B8 bit 5 rising) of the host's write sequence."""
    want: dict[tuple[int, int], int] = {}
    for r in csv.DictReader((trace / "ports.csv").open()):
        if r["direction"] == "out" and r["port"] in ("0x0388", "0x0389"):
            k = (int(r["port"], 16), int(r["value"], 16))
            want[k] = want.get(k, 0) + int(r["count"])
    got: dict[tuple[int, int], int] = {}
    for port, v in h.opl_ports:
        got[(port, v)] = got.get((port, v), 0) + 1
    data = sum(n for (p, _), n in want.items() if p == 0x389)
    print(f"OPL: {len(h.opl)} writes, {data} in the reference")
    if counts and got != want:
        diff = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
        return [f"OPL: {len(diff)} port/value counts differ, first {diff[0][0]:x}={diff[0][1]:02x}: "
                f"{got.get(diff[0], 0)} vs {want.get(diff[0], 0)}"]
    regs, edges = bytearray(256), bytearray(9)
    for reg, v in h.opl:
        if 0xB0 <= reg <= 0xB8 and v & 0x20 and not regs[reg] & 0x20:
            edges[reg - 0xB0] = (edges[reg - 0xB0] + 1) & 0xFF
        regs[reg] = v
    problems = []
    if h.mem(h.syms["rt_opl"], 256) != bytes(regs):
        problems.append("OPL: rt_opl differs from the writes")
    if h.mem(h.syms["rt_opl_keyon"], 9) != bytes(edges):
        problems.append(f"OPL: rt_opl_keyon {list(h.mem(h.syms['rt_opl_keyon'], 9))}, "
                        f"key-on edges {list(edges)}")
    print(f"OPL: key-on edges per channel {list(edges)}")
    return problems


def reference_clocks(trace):
    """Use recorded external inputs; old captures retain their unpinned clocks."""
    with events(trace) as f:
        arm = next(csv.DictReader(f))
    assert arm['kind'] == 'arm', arm
    detail = dict(kv.split('=', 1) for kv in arm['detail'].split())
    calendar = None
    if 'dos_date' in detail:
        y, m, d = map(int, detail['dos_date'].split('-'))
        calendar = y << 16 | m << 8 | d
    source = trace.parent / 'clock-inputs.json'
    clock = None
    if source.exists():
        fields = json.loads(source.read_text())
        assert fields['basis'] == 'local calendar'
        clock = time.mktime(time.strptime(fields['host_file_clock'], '%Y-%m-%dT%H:%M:%S'))
    return calendar, clock


# --bypass (annotations/hle.csv copy_protection; owner decision 2026-11-06): at the
# protection screen's return, the state outside the screen's equals the reference's
# after a correct first answer (m03p-protection-passed). The screen's state:
# - the regions of tests/bypass-screen.csv, each with its evidence;
# - bytes that differ between two correct-answer references (m03p and
#   m03q-protection-passed-late: another question, frozen and answered later),
#   which depend on when the screen's keys came (MEASURED at each check);
# - the stack below SS:SP (the screen's frames);
# - BX, CX, DX and ES, which the screen (MS C) need not preserve; the caller
#   reads none of them before writing it (3273:0B03..0B18);
# - the mouse arrow, drawn at the screen's mouse position: two 16x16 boxes;
# - the EMS page frame E0000h..EFFFFh, which holds the pages the screen mapped last.
BYPASS_TABLE = REPO / "tests/bypass-screen.csv"
BYPASS_STACK = 0x200
BYPASS_EXEMPT = {"regs": ("bx", "cx", "dx", "es"), "boxes": 2, "machine": (0xE0000, 0xF0000)}
# Controls: each leaves a state a correct first answer does not, and must fail.
BYPASS_SABOTAGE = {
    "tries": ("a wrong try left ([6562h]:000E = 1)", 0x6562, 0x000E, 1),
    "frozen": ("the glyphs not frozen ([6562h]:003A = 0)", 0x6562, 0x003A, 0),
    "question": ("another question than the glyphs' ([6562h]:0E06 = 17)", 0x6562, 0x0E06, 17),
}


def bypass_masked(g: dict) -> set[int]:
    def lin(so: str) -> int:
        seg, off = so.split(":")
        return int(seg, 16) * 16 + int(off, 16)
    out = set()
    for r in csv.DictReader(BYPASS_TABLE.open()):
        out.update(range(lin(r["first"]), lin(r["last"]) + 1))
    runs = []
    for name in ("m03p-protection-passed", "m03q-protection-passed-late"):
        found = sorted(RUNS.glob(f"ms-*-{name}"))
        if not found:
            raise SystemExit(f"no pinned run of {name}: python3 tools/reference.py {name}")
        runs.append((found[-1] / f"trace/snap-{name}-0/ram.bin").read_bytes())
    out.update(a for a in range(len(runs[0])) if runs[0][a] != runs[1][a])
    top = g["ss"] * 16 + g["sp"]
    out.update(range(top - BYPASS_STACK, top))
    return out


def bypass_return(trace: Path) -> int:
    """--bypass: the service events before the reference's first snapshot, the
    protection screen's return (reference/milestones.csv FRONTEND.OVL+79843)."""
    n = 0
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                n += 1
            elif r["kind"] == "snapshot":
                return n
    raise ValueError(f"{trace}: no snapshot event")


# Controls of the dead-stack rule at a milestone that uses it: registers (ServiceLog)
# at m10-film-room (INT 21h AH=47h), stores (Host.dead_stored) at m14-tour-battle
# (FLIGHT 126F:0A49); each must fail the lockstep.
DEAD_SABOTAGE = {
    "dead-off": "no dead-stack read recorded: register bytes loaded and RAM bytes stored from "
                "dead stack compared exactly",
    "dead-written": "DL of the first INT 21h AH=47h past the copy-protection hook logged with "
                    "bit 7 flipped (a byte the guest wrote, beside the bytes loaded from dead stack)",
    "dead-stored-beside": "at the label, bit 7 flipped in the RAM byte after a byte stored from "
                          "dead stack (a byte the guest wrote otherwise)",
}
# The game's mouse polls (tools/reference.py SITES menu and frame): a frame ends there.
FRAME_ENDS = {"FE_1808E", "FLT_1B7D2"}
BYPASS_MILESTONE = "m03p-protection-passed"
RETURN_SITE = "FE_79843"   # the protection screen's return, 3273:0B03 (annotations/hle.csv)
# Control past the screen: the bypass answers wrongly, and the lockstep must fail.
BYPASS_LATE_SABOTAGE = {"answer": "the bypass leaves AX = 0, a wrong answer"}


def check(milestone: str, timeout: int, amiga: Path | None, sabotage: str | None,
          trace: Path | None = None, elf: Path | None = None, bypass: bool = False,
          bypass_sabotage: str | None = None, screen: bool = False) -> list[str]:
    # past the screen (BYPASS_MILESTONE's return) the bypassed port runs in lockstep
    # with the bypassed reference (owner decision 2026-11-08): no state is exempt
    late = bypass and milestone != BYPASS_MILESTONE
    script = milestone_script(milestone, bypassed=late)
    script["screen"] = screen
    frame = script["frame"]
    trace = trace or host_reference(milestone, bypassed=late)
    snap = trace / f"snap-{milestone}-{len(script['snapshots']) - 1}"  # where the run stops
    # REP slices (rep_replay.py): a diagnostic image with REP hooks replays the
    # reference's decoder slices, so an interrupt inside a REP lands where it did
    chunks = rep_replay.read(trace, required=True)
    rep = rep_replay.Replay(chunks)
    script["rep"] = rep
    h = Host(image.M.REF, sabotage, elf=elf or rep_replay.host_image(rep.labels),
             retrace=retrace_runs(trace))
    h.calendar_date, h.file_clock = reference_clocks(trace)
    if bypass and not late:
        script["bypass"] = bypass_return(trace)
    if late:
        script["bypassed"] = bypass_sabotage
    label = script["snapshots"][-1][0]
    script["irqs"], script["releases"] = reference_inputs(trace, exact_releases=True)
    summary = dict(kv.split("=", 1) for kv in (trace / "summary.txt").read_text().split())
    problems = rearm_problems() + resident_problems(sabotage)
    if int(summary.get("polls", "0"), 16) != fnv(POLLS.read_bytes()):
        problems.append("reference recorded with other poll points: rerun tools/reference.py --polls")
    h.services = ServiceLog(iter_services(trace), h.dead_reads)
    t0 = time.monotonic()
    h.run(script, timeout)
    print(f"host run: {time.monotonic() - t0:.0f} s")
    if late:
        want_n = reference_bypass(trace)
        if h.bypass_hits != 1 or h.bypass_n != want_n:
            problems.append(f"bypass: the hook ran {h.bypass_hits} times, first after "
                            f"{h.bypass_n} service events; the reference's after {want_n}")
        else:
            print(f"bypass: hook after {h.bypass_n} service events, the reference's at the same "
                  "point; lockstep on from the return")
    elif bypass:
        if h.bypass_n is None:
            problems.append("bypass: the copy-protection hook was not reached")
        else:
            print(f"bypass: hook after {h.bypass_n} service events; the screen's "
                  f"{script['bypass'] - h.bypass_n} service events and {h.bypass_irqs} "
                  f"interrupts are the reference's only")
    try:
        rep.complete()
    except ValueError as error:
        problems.append(str(error))
    if h.irq_lost:
        problems.append(h.irq_lost)
    if h.retrace_bad:
        problems.append(h.retrace_bad)
    if h.stopped_at == label and h.retrace_left():
        problems.append(f"VGA status: {h.retrace_left()} reference reads not made")
    if h.display_miss:
        problems.append(h.display_miss)
    print("music driver at interrupt level: flight callback "
          f"{h.irq_counts['callback irq']} runs, request 0Fh enqueue stores {h.irq_counts['enqueue irq']} "
          f"(main code: {h.irq_counts['callback main']}, {h.irq_counts['enqueue main']})")
    ran = trace / "executed-ADLIB.IMS.bin"  # absent: the driver was never loaded (m00)
    ran = ran.read_bytes() if ran.exists() else b""
    if h.stopped_at == label and len(ran) > 0x6B6 and ran[0x6B6] and not h.irq_counts["callback irq"]:
        problems.append("the reference ran the driver's flight callback (ADLIB.IMS +006B6); "
                        "the host run never did at interrupt level")
    print(f"EMS: {h.ems_alias_reads} guest bytes read through a page mapped at two frame "
          f"pages, {len(h.ems_alias_bad)} differ from another copy")
    if h.ems_alias_bad:
        b, k, n = h.ems_alias_bad[0]
        problems.append(f"EMS: guest read of {b:05X} after service {n} differs from the copy "
                        f"at frame page {k}")
    problems += h.irq.finish(REPO / "tmp/test" / f"irq-monitor-{milestone}{'-' + sabotage if sabotage else ''}.json")
    if h.stopped_at == label:
        problems += check_opl(h, trace, counts=not bypass or late)
    marked = bytearray(64000)  # stored since the last present: still marked (rt_vram_rows)
    rows = h.mem(h.syms["rt_vram_rows"], 800)
    for y in range(200):
        lo, hi = struct.unpack_from(">2H", rows, 4 * y)
        marked[y * 320 + lo:y * 320 + hi] = b"\1" * max(0, hi - lo)
    unmarked = sorted(o for o in h.vram_written if not marked[o])
    if unmarked:
        problems.append(f"{len(unmarked)} pixels stored since the last present and not marked, "
                        f"first x={unmarked[0] % 320} y={unmarked[0] // 320}")
    print(f"frame presents: {h.presents}")
    print(f"hardware interrupts: {h.irq_i} replayed, {len(script['irqs'])} in the reference")
    print(f"VGA status reads: {sum(r[2] for r in h.retrace)} in the reference")
    if h.stopped_at != label:
        problems.append(f"milestone label {label} not reached (exit {h.exit}, pc={h.r('pc'):x}"
                        f"{', ' + h.log[-1] if h.log else ''}"
                        f"{f', the {timeout} s timeout, host sleep included' if h.timed_out else ''})")
    problems += h.services.finish(h.stopped_at == label)
    if h.services.dead_bytes:
        print(f"services: {h.services.dead_bytes} register bytes loaded from dead stack differ "
              f"(exempt), first {h.services.dead_first}")
    print(f"services: {len(h.services)} run, {h.services.total} in the reference")
    if h.stopped_at == label:
        ref_regs = dict(kv.split("=") for kv in (snap / "regs.txt").read_text().split())
        ref = (snap / "ram.bin").read_bytes()
        g = h.guest_regs(0)
        exempt = None
        if bypass and not late:
            if bypass_sabotage:
                seg, off, value = BYPASS_SABOTAGE[bypass_sabotage][1:]
                a = int.from_bytes(h.gmem(g["ds"] * 16 + seg, 2), "little") * 16 + off
                h.e.write(TOP - a - 1, struct.pack(">H", value))  # reversed: the high byte first
            h.masked |= bypass_masked(g)
            exempt = BYPASS_EXEMPT
            # The question and its glyphs depend on when the glyphs froze (the timing
            # mask): any question is a correct first answer's, but its glyphs must be
            # the ones its table row holds (3273:3939, [6562h]:1222h + 6 * question).
            base = int.from_bytes(h.gmem(g["ds"] * 16 + 0x6562, 2), "little") * 16
            q = int.from_bytes(h.gmem(base + 0xE06, 2), "little")
            if not q < 32 or h.gmem(base, 6) != h.gmem(base + 0x1222 + 6 * q, 6):
                problems.append(f"bypass: question {q} and the glyphs "
                                f"{h.gmem(base, 6).hex()} disagree")
        if sabotage == "dead-stored-beside":
            # a guest byte beside one stored from dead stack, flipped: the exemption
            # is per byte (control)
            a = next((a + 1 for a in sorted(h.dead_stored) if a + 1 not in h.dead_stored
                      and a + 1 not in h.masked and any(lo <= a + 1 < hi for lo, hi in COMPARE)),
                     None)
            if a is None:
                problems.append("dead-stored-beside: no byte stored from dead stack to plant beside")
            else:
                print(f"dead-stored-beside: {a:05X} flipped")
                h.e.write(TOP - a, bytes([h.gmem(a, 1)[0] ^ 0x80]))
        problems += check_capture("host", g, h.mem(STATE, 16), h.gmem(0, 0x100000),
                                  h.mem(h.syms["rt_dac"], 768) if frame else None,
                                  ref_regs, ref, snap, h, exempt)
        if amiga:
            regs = dict(kv.split("=") for kv in (amiga / "regs.txt").read_text().split())
            ga = {n: int(regs[n], 16) for n in REGS}
            if frame:
                # a label other than the mouse poll (a frame end) is mid-frame: what
                # the guest stored since the last present is not shown yet (D9)
                pending = None if label in FRAME_ENDS else set(h.vram_written)
                if pending:
                    print(f"amiga shown: {label} is not a frame end; {len(pending)} pixels "
                          f"stored since the last present are not compared (D9)")
                problems += compare_shown(amiga, int(regs["bpr"]), snap, pending)
            problems += check_capture("amiga", ga, (amiga / "state.bin").read_bytes(),
                                      (amiga / "ram.bin").read_bytes()[::-1],  # reversed
                                      (amiga / "dac.bin").read_bytes() if frame else None,
                                      ref_regs, ref, snap, h)
    return problems


if __name__ == "__main__":
    sys.exit(main())
