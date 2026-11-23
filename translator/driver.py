"""The music driver a build translates and the driver addresses its proofs name.

A build translates one driver (image.DRIVER, environment XWING_DRIVER): ADLIB.IMS, the
AdLib setup's, by default, or ADLIB_W.IMS, the Sound Blaster setup's (P10), which the game
loads at the same segment (DRVSEG, MEASURED). ADLIB_W.IMS is ADLIB.IMS with the Sound
Blaster's voice code added: below SHARED its code is ADLIB.IMS's instruction for
instruction, at the same offsets, but for the data displacements and immediates, which
move because the data segment grows (DERIVED: the translator's decoder over both images,
8344 instructions); ADLIB.IMS's code from SHARED to its data moved as a block (TAIL).

The proofs name driver addresses as ADLIB.IMS has them, each with the instruction that
shows it (`value(site, old)`): for ADLIB_W.IMS the value is read from its own instruction
at the same offset, which must decode to the same operation and operand kinds; nothing is
assumed about how the data moved (a table at 2250h moved by 30h, most data by 28h, and
some displacements kept their value). Annotation rows naming ADLIB.IMS code carry over to
ADLIB_W.IMS at the same offset under the same check (`carry`), unless the file has rows of
its own for ADLIB_W.IMS; rows whose `driver` column names a driver apply to that driver's
build only (image.rows).
"""

from __future__ import annotations

from functools import lru_cache

from . import image
from .decode import DecodeError, Imm, Insn, Mem, Rel, decode

BASE = "ADLIB.IMS"            # the driver the annotations and proofs were written for
DRIVER = image.DRIVER
SHARED = 0x4C28               # ADLIB.IMS's code below this is ADLIB_W.IMS's at the same offset
TAIL = (0x4C28, 0x4CFE, 0x272)  # ADLIB.IMS's arithmetic helpers moved to +0272h (DERIVED: bytes)


class DriverError(Exception):
    pass


@lru_cache(maxsize=None)
def _data(name: str) -> bytes:
    return image.load()[name].data


def _insn(name: str, off: int) -> Insn:
    try:
        return decode(_data(name), off, off)
    except DecodeError as e:
        raise DriverError(f"{name}+{off:05X}: {e}") from None


def _kinds(n: Insn) -> tuple:
    return (n.op, n.size, n.width, n.cc, n.rep, n.seg,
            tuple((type(o).__name__, getattr(o, "name", None), getattr(o, "base", None),
                   getattr(o, "index", None), getattr(o, "seg", None)) for o in n.operands))


def same(off: int) -> Insn:
    """The selected driver's instruction at a BASE code offset, checked to be the same
    operation on the same operand kinds (values may differ)."""
    if DRIVER == BASE:
        return _insn(BASE, off)
    if not 0 <= off < SHARED:
        raise DriverError(f"{BASE}+{off:05X}: not in the code {DRIVER} shares")
    a, w = _insn(BASE, off), _insn(DRIVER, off)
    if _kinds(a) != _kinds(w):
        raise DriverError(f"{BASE}+{off:05X} {a} is {w} in {DRIVER}")
    return w


def value(off: int, old: int) -> int:
    """`old` as the BASE instruction at `off` names it (a displacement, the word after a
    far pointer's displacement, an immediate or a near target) -> the value the selected
    driver's instruction at the same offset names."""
    w = same(off)
    if DRIVER == BASE:
        return old
    a = _insn(BASE, off)
    hits = []
    for p, q in zip(a.operands, w.operands):
        if isinstance(p, Mem) and old - p.disp in ((0, 2) if p.width == 32 else (0,)):
            hits.append(q.disp + old - p.disp)
        elif isinstance(p, Imm) and p.value == old:
            hits.append(q.value)
        elif isinstance(p, Rel) and p.target == old:
            hits.append(q.target)
    if len(hits) != 1:
        raise DriverError(f"{BASE}+{off:05X} {a}: names 0x{old:x} {len(hits)} times")
    return hits[0]


def carry(off: int) -> int:
    """A BASE code offset an annotation row names -> the selected driver's offset of the
    same instruction (checked by same)."""
    same(off)
    return off


# The effect capture's driver layout (src/runtime/sfx.c, tools/sfx_capture.py): each
# value as ADLIB.IMS's instruction at the site names it; the selected driver's is read
# from its own instruction there (value, checked by same). Order: runtime.h RT_DRV_*.
CAPTURE = (
    ("TIMER", 0x09DE, 0x0A1B),        # mov dx: the INT 08h handler's offset
    ("DATA", 0x0BEF, 0x04D0),         # mov ax: DS, paragraphs above CS
    ("DS_SLOT", 0x0916, 0x0911),      # CS word: the handler's DS
    ("BIOS_COUNT", 0x0A2D, 0x0910),   # CS byte: ticks to the BIOS chain
    ("TIMER_ACC", 0x0188, 0x0678),    # DS word: the game-timer accumulator
    ("SOUNDS", 0x07C2, 0x06E2),       # DS far pointer: the game's sound table
    ("SHADOW", 0x4BD2, 0x0342),       # DS: the OPL register shadow
    ("QUEUE_HEAD", 0x29E4, 0x0EBE),   # DS words: the request queue's read and write index
    ("QUEUE_TAIL", 0x29E1, 0x12C0),
    ("PLAYERS", 0x0E8E, 0x06EA),      # DS: the 8 players
    ("VOICES", 0x3F1E, 0x1ED2),       # DS: the 9 voices
)


def driver_bytes(name: str = DRIVER) -> int:
    """The driver's image and minimum allocation, from its MZ header, in paragraphs' bytes."""
    import struct
    head = (image.M.REF / name).read_bytes()[:12]
    last, pages, _, hdr, minalloc = struct.unpack_from("<HHHHH", head, 2)
    size = pages * 512 - (512 - last if last else 0) - hdr * 16
    return (size + minalloc * 16 + 15) & ~15


def capture_layout() -> list[tuple[str, int]]:
    """The capture's layout for the selected driver, in CAPTURE's order, then BYTES."""
    return [(n, value(site, old)) for n, site, old in CAPTURE] + [("BYTES", driver_bytes())]
