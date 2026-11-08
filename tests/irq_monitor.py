"""IRQ0 footprint monitor (Secret Weapons of the Luftwaffe's docs/irq-plan.md I3) for
tests/host_run.py. Copied from Secret Weapons of the Luftwaffe (manifest/references.tsv)
and adapted to X-Wing's music driver (ADLIB.IMS at DRVSEG).

Checks every guest memory access of a host run against I2's footprint
(build/gen/irq-footprint.csv):
- inside a delivered IRQ0 handler (deliver_guest from rt_irq_async or
  rt_irq_interrupt to its back label), which starts on the private stack (runtime.h
  RT_IRQ_SS:RT_IRQ_SP below its frame), every access, generated or runtime,
  lies in the footprint for its kind: the fixed classes (paragraphs at run time:
  the root's link paragraphs + the load segment, `A` and the driver's + DRVSEG,
  G = the word at DRVSEG:0911, BDA), song data (S, located at run time: a read of
  conventional memory outside every fixed class, or of the EMS page frame), or the handler's stack from the
  frame down by the proved depth (K);
- in main code, an access that meets the footprint (a read of a handler-written
  byte, a write of a handler-accessed byte) comes from a sync instruction whose
  row covers the address, runs with guest IF clear, or from a runtime service
  (recorded: the services that must mask the tick, I6); any other generated or
  runtime access fails;
- song data: per byte, the handler's reads; a generated main write of a byte the
  handler read before and reads again after, with no main-code driver request (an
  entry at ADLIB.IMS +0000, the API) between the earlier read and the write nor
  between the write and the later read, fails (song races): the music played across
  the write. A buffer the game loads, plays, leaves and reloads around requests is
  reuse. A write declared sync (irq-sync.csv) passes; a service's is recorded.
X-Wing's songs are huge objects the driver walks by far pointers (irq.py
SEGMENT_WORDS, SEGMENT_LOADS); their extent is not in a table the monitor could read,
so S is bounded by the fixed classes, video memory and the EMS frame, not by a song window.
Records the sync sites hit, IF-clear accesses, services and song bytes in
tmp/test/irq-monitor-<run>.json.
"""
from __future__ import annotations

import bisect
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FOOTPRINT = REPO / "build/gen/irq-footprint.csv"
from translator.lower import DRVSEG  # noqa: E402
GAME_DS_SLOT = DRVSEG * 16 + 0x911  # translator/irq.py GAME_DS_SLOT (linear)
SONG_LIMIT = 0xA0000               # S: conventional memory,
EMS_FRAME = (0xE0000, 0xF0000)     # and the EMS page frame (ems.c EMS_FRAME): a song the
                                   # game keeps in EMS (MEASURED: m12-training-flight);
                                   # its remaps are INT 67h services, which hold the tick off
WRITTEN, ACCESSED, READ_OK, WRITE_OK, LAYOUT = 1, 2, 4, 8, 16
LIMIT = 20
# Runtime code that runs as an interrupt handler, not main code: the BIOS tick
# (IRQ0 while IVT 08h is the BIOS's, and the end of the driver's chain)
INTERRUPT_SIDE = {"bios_tick"}
PRIVATE_STACK = (0xB000, 0x8000 - 6)   # runtime.h RT_IRQ_SS:RT_IRQ_SP, frame pushed
# translator/irq.py CONST_TABLES: the proof takes their words from the driver image,
# so no write may reach them (linear: G = DRVSEG + 04D0h, A0000 = DRVSEG)
from translator.irq import CONST_BASE, CONST_TABLES  # noqa: E402
CONST_SPANS = [(DRVSEG * 16 + CONST_BASE[c] + lo, DRVSEG * 16 + CONST_BASE[c] + hi, f"{c}:{lo:04X}")
               for c, lo, hi in CONST_TABLES]


def song_race(a: int, read: list, write: tuple, tick: int, epoch: int) -> str | None:
    """The handler reads song byte a at tick (request epoch epoch) after a pending
    generated main write (tick, epoch, the epoch of the byte's read before it, who):
    a race when no request separates the earlier read, the write and this read. A
    write no read follows (a reload of bytes already played) is no race."""
    w_tick, w_epoch, r_epoch, who = write
    if r_epoch == w_epoch == epoch:
        return (f"main write of {a:05X} into song {read[2]}'s buffer at {who} "
                f"(tick {w_tick}, read at ticks {read[1]} and {tick}, no driver request between)")
    return None


class Monitor:
    def __init__(self, host, size: int, footprint: Path = FOOTPRINT):
        from translator import emit
        self.h = host
        self.size = size
        self.mem, self.sync = [], defaultdict(list)
        self.depth = None
        for r in csv.DictReader(footprint.open()):
            if r["kind"] == "mem":
                self.mem.append((r["class"], int(r["first"], 16), int(r["last"], 16), r["access"]))
            elif r["kind"] == "stack":
                self.depth = -int(r["first"], 16)
            elif r["kind"] == "sync" and r["class"] != "port":
                mod, off = r["where"].split("+")
                self.sync[(mod, int(off, 16))].append(
                    (r["class"], int(r["first"], 16), int(r["last"], 16)))
        if self.depth is None:
            raise ValueError(f"{footprint}: no stack row")
        tags = {t: m for m, t in emit.TAG.items()}
        pat = re.compile(r"^(%s)_([0-9A-F]{5})(_bp)?$" % "|".join(tags))
        labels = sorted((a, (tags[m.group(1)], int(m.group(2), 16)))
                        for n, a in host.syms.items() if (m := pat.match(n)))
        self.label_at = [a for a, _ in labels]
        self.label_node = [n for _, n in labels]
        named = sorted((a, n) for n, a in host.syms.items())
        self.sym_at = [a for a, _ in named]
        self.sym_name = [n for _, n in named]
        self.backs = {host.syms[n] for n in ("rt_irq_async_back", "rt_irq_interrupt_back")
                      if n in host.syms}   # the second: I6 builds
        self.loadseg = None
        self.g = None
        self.mask = None
        self.dirty = True
        self.song_span = (1, 0)               # all song bytes read: quick reject
        self.song_reads: dict[int, list] = {}  # linear -> [first tick, last tick, "S", epoch]
        self.song_pending: dict[int, tuple] = {}  # linear -> (tick, epoch, read epoch, who)
        self.epoch = 0                        # main-code driver requests so far
        self.in_handler = False
        self.k = (0, -1)
        self.tick = 0
        self.entries = Counter()
        self.found = Counter()
        self.masked = Counter()
        self.services = Counter()
        self.song_writes: list[tuple[int, int, str, bool, int]] = []
        self.problems: list[str] = []
        self.uncovered = {}                   # site -> [class, first, last, accesses]

    # -- layout --------------------------------------------------------------
    def para(self, cls: str):
        if re.fullmatch(r"[0-9A-F]{4}", cls):
            return int(cls, 16) + self.loadseg
        if re.fullmatch(r"A[0-9A-F]{4}", cls):
            return int(cls[1:], 16) + DRVSEG
        return {"BDA": 0x40, "G": self.g}.get(cls)

    def word(self, lin: int) -> int:
        return int.from_bytes(self.h.gmem(lin, 2), "little")

    def layout(self):
        """Class paragraphs and the masks from guest memory."""
        if self.loadseg is None:
            self.loadseg = self.h.u32(self.h.syms["load_segment"]) & 0xFFFF
        self.g = self.word(GAME_DS_SLOT) or None
        mask = bytearray(self.size)
        for cls, lo, hi, access in self.mem:
            p = self.para(cls)
            if p is None:
                continue
            bits = (WRITTEN | ACCESSED | WRITE_OK) if access == "w" else (ACCESSED | READ_OK)
            for a in range(p * 16 + lo, min(p * 16 + hi + 1, len(mask))):
                mask[a] |= bits
        for a in range(GAME_DS_SLOT, GAME_DS_SLOT + 2):     # the G slot moves the layout
            mask[a] |= LAYOUT
        self.mask = mask
        self.dirty = False

    # -- sites -----------------------------------------------------------------
    def node(self, pc: int):
        k = bisect.bisect_right(self.label_at, pc) - 1
        return self.label_node[k] if k >= 0 else None

    def symbol(self, pc: int) -> str:
        k = bisect.bisect_right(self.sym_at, pc) - 1
        return self.sym_name[k] if k >= 0 else f"{pc:x}"

    @staticmethod
    def site(n) -> str:
        return f"{n[0]}+{n[1]:05X}"

    def fail(self, text: str):
        if len(self.problems) < LIMIT:
            self.problems.append(f"irq monitor: {text}")

    # -- events from host_run -------------------------------------------------
    def deliver(self):
        """deliver_guest reached: an IRQ0 delivery when it returns to rt_irq_async_back
        (sync) or rt_irq_interrupt_back (async, I6)."""
        if self.h.u32(self.h.r("a7")) not in self.backs:
            return False
        if self.dirty:
            self.layout()
        g = self.h.guest_regs(8)
        if (g["ss"], g["sp"]) != PRIVATE_STACK:
            self.fail(f"handler entered on {g['ss']:04X}:{g['sp']:04X}, not the private stack "
                      f"(tick {self.tick})")
        top = g["ss"] * 16 + g["sp"]
        self.k = (top - self.depth, top + 5)
        cs, ip = (int.from_bytes(self.h.mem(self.h.syms[n], 2), "big")
                  for n in ("rt_deliver_cs", "rt_deliver_ip"))
        self.entries[f"{cs:04X}:{ip:04X}"] += 1
        self.in_handler = True
        return True

    def request(self):
        """A main-code entry into the driver's API (ADLIB.IMS +0000)."""
        if not self.in_handler:
            self.epoch += 1

    def returned(self):
        if self.in_handler:
            self.in_handler = False
            self.tick += 1

    def read(self, lin: int, size: int):
        m = self.mask
        if self.in_handler or self.dirty or m is None:
            return self.access(False, lin, size)
        if m[lin] & WRITTEN or m[lin + size - 1] & WRITTEN or size == 4 and (m[lin + 1] | m[lin + 2]) & WRITTEN:
            self.main_access(False, lin, size)

    def write(self, lin: int, size: int):
        # the root's memset and the driver's load (INT 21h AX=4B03h) write them before
        # the driver's install sets its DS slot
        installed = self.word(GAME_DS_SLOT) if self.mask is not None else 0
        for lo, hi, name in CONST_SPANS:
            if installed and lin <= hi and lo <= lin + size - 1 and not self.h.in_service:
                pc = self.h.r("pc")
                where = self.site(self.node(pc)) if self.h.code[0] <= pc < self.h.code[1] else self.symbol(pc)
                self.fail(f"write of {lin:05X} into the constant table {name} (irq.py CONST_TABLES) "
                          f"at {where}")
        m = self.mask
        if self.in_handler or self.dirty or m is None:
            return self.access(True, lin, size)
        hot = ACCESSED | LAYOUT
        if m[lin] & hot or m[lin + size - 1] & hot or size == 4 and (m[lin + 1] | m[lin + 2]) & hot \
                or self.song_span[0] <= lin + size - 1 and lin <= self.song_span[1]:
            self.main_access(True, lin, size)

    def access(self, write: bool, lin: int, size: int):
        if self.mask is None or (self.dirty and not self.in_handler):
            self.layout()
        if self.in_handler:
            self.handler_access(write, lin, size)
        else:
            self.main_access(write, lin, size)

    def handler_access(self, write: bool, lin: int, size: int):
        need = WRITE_OK if write else READ_OK
        for a in range(lin, lin + size):
            if self.k[0] <= a <= self.k[1] or self.mask[a] & need:
                continue
            if not write and (a < SONG_LIMIT or EMS_FRAME[0] <= a < EMS_FRAME[1]) \
                    and not self.mask[a] & ACCESSED:
                r = self.song_reads.setdefault(a, [self.tick, self.tick, "S", self.epoch])
                w = self.song_pending.pop(a, None)
                if w and (race := song_race(a, r, w, self.tick, self.epoch)):
                    self.fail(race)
                r[1], r[3] = self.tick, self.epoch
                lo, hi = self.song_span
                self.song_span = (a, a) if lo > hi else (min(lo, a), max(hi, a))
                continue
            pc = self.h.r("pc")
            where = self.site(self.node(pc)) if self.h.code[0] <= pc < self.h.code[1] else self.symbol(pc)
            self.fail(f"handler {'write' if write else 'read'} of {a:05X} outside the footprint "
                      f"at {where} (tick {self.tick})")
            return

    def main_access(self, write: bool, lin: int, size: int):
        bits = 0
        for a in range(lin, lin + size):
            bits |= self.mask[a]
        if write and bits & LAYOUT:
            self.dirty = True
        hit = bits & (ACCESSED if write else WRITTEN)
        song = write and self.song_span[0] <= lin + size - 1 and lin <= self.song_span[1] and \
            any(a in self.song_reads for a in range(lin, lin + size))
        if not hit and not song:
            return
        pc = self.h.r("pc")
        generated = self.h.code[0] <= pc < self.h.code[1]
        if self.h.in_service:
            who = f"service {self.h.pending_vec[-1]:02X}h" if self.h.pending_vec else "service"
        elif generated:
            who = self.site(self.node(pc))
        else:
            who = self.symbol(pc)
        if song and not hit and generated and not self.h.in_service \
                and self.covered(self.node(pc), lin, size):
            self.found[who] += 1        # a declared sync write (irq-sync.csv)
            return
        if song:
            self.song_writes.append((lin, size, who, generated and not self.h.in_service, self.tick))
            if generated and not self.h.in_service:
                for a in range(lin, lin + size):
                    r = self.song_reads.get(a)
                    if r:
                        self.song_pending.setdefault(a, (self.tick, self.epoch, r[3], who))
        if not hit:
            return
        if self.h.in_service or (not generated and who in INTERRUPT_SIDE):
            self.services[f"{who} {self.cls_of(lin)}"] += 1
        elif not generated:
            self.fail(f"runtime {'write' if write else 'read'} of {lin:05X} meets the footprint "
                      f"at {who}")
        elif self.h.state(11, 1) == 0:
            self.masked[who] += 1
        elif self.covered(self.node(pc), lin, size):
            self.found[who] += 1
        else:
            self.fail(f"main {'write' if write else 'read'} of {lin:05X} meets the footprint at "
                      f"{who}, not a sync access for it")
            cls, off = (self.cls_of(lin).split(":") + [None])[:2]
            off = int(off, 16) if off else lin
            u = self.uncovered.setdefault(who, [cls, off, off + size - 1, set()])
            u[1], u[2] = min(u[1], off), max(u[2], off + size - 1)
            u[3].add("w" if write else "r")

    def cls_of(self, lin: int) -> str:
        for cls, lo, hi, _ in self.mem:
            p = self.para(cls)
            if p is not None and p * 16 + lo <= lin <= p * 16 + hi:
                return f"{cls}:{lin - p * 16:04X}"
        return f"{lin:05X}"

    def covered(self, node, lin: int, size: int) -> bool:
        for cls, lo, hi in self.sync.get(node, ()):
            p = self.para(cls)
            if p is not None and p * 16 + lo <= lin and lin + size - 1 <= p * 16 + hi:
                return True
        return False

    # -- result ----------------------------------------------------------------
    def finish(self, out: Path | None) -> list[str]:
        problems = list(self.problems)
        song = sorted(self.song_reads)
        record = dict(ticks=self.tick, handler_entries=dict(self.entries), g=self.g and f"{self.g:04X}",
                      sync_sites=dict(sorted(self.found.items())),
                      uncovered={w: [c, f"{lo:04X}", f"{hi:04X}", "".join(sorted(a))]
                                 for w, (c, lo, hi, a) in sorted(self.uncovered.items())},
                      if_clear=dict(sorted(self.masked.items())),
                      services=dict(sorted(self.services.items())),
                      song_bytes=len(song), song_span=song and [f"{song[0]:05X}", f"{song[-1]:05X}"],
                      service_song_writes=sorted({w for _, _, w, g, _ in self.song_writes if not g}))
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(record, indent=1) + "\n")
        print(f"irq monitor: {self.tick} ticks, {len(self.found)} sync sites hit, "
              f"{sum(self.masked.values())} IF-clear and {sum(self.services.values())} service accesses, "
              f"{len(song)} song bytes read, {len(problems)} problems")
        for w, (c, lo, hi, a) in sorted(self.uncovered.items()):
            problems.append(f"irq monitor: uncovered main site {w}: {c} {lo:04X}..{hi:04X} "
                            f"{''.join(sorted(a))}")
        return problems
