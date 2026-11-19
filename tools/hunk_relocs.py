#!/usr/bin/env python3
"""Split HUNK_RELOC32 blocks the Kickstart 3.1 loader cannot read, in place.

LoadSeg counts a RELOC32 block's offsets in a 16-bit loop (Commodore's DevCon 1988
loadseg.asm: `move.w d0,d2`, `subq.w #1,d2`, `dbf d2`), so a block of 65536 or more
offsets fails with "file is not executable" (MEASURED: the copy-free EMS build's code
hunk relocates itself at 65839 offsets; Kickstart 40.63 on the 68030 model refuses it,
and the same file with the block split loads and reaches main). elf2hunk writes one
block per target hunk, so this tool rewrites each block of more than 65535 offsets as
consecutive blocks of at most 65535 for the same target, which is the same relocation.

usage: hunk_relocs.py FILE [--check]
       hunk_relocs.py --release-of FULL STRIPPED
--check only reports blocks over the limit and exits 1 if any (no rewrite).
--release-of checks that STRIPPED (elf2hunk -s) has no symbol or debug hunks and that
every other record, header and relocations included, equals FULL's (make amiga-release).
"""
import struct
import sys

LIMIT = 65535
HUNK_HEADER, HUNK_CODE, HUNK_DATA, HUNK_BSS = 0x3F3, 0x3E9, 0x3EA, 0x3EB
HUNK_RELOC32, HUNK_SYMBOL, HUNK_DEBUG, HUNK_END = 0x3EC, 0x3F0, 0x3F1, 0x3F2


class HunkError(Exception):
    pass


def split(data: bytes) -> tuple[bytes, list[tuple[int, int, int]]]:
    """The file with oversized RELOC32 blocks split, and the (hunk, target, count) of each
    block that was over the limit."""
    p = 0

    def word() -> int:
        nonlocal p
        if p + 4 > len(data):
            raise HunkError(f"truncated at {p:#x}")
        v = struct.unpack_from(">I", data, p)[0]
        p += 4
        return v

    if word() != HUNK_HEADER:
        raise HunkError("no HUNK_HEADER")
    while word():                                   # resident library names
        pass
    word()
    first, last = word(), word()
    for _ in range(last - first + 1):
        if word() >> 30 == 3:                       # memory attributes follow
            word()
    out = bytearray(data[:p])
    hunk, over = -1, []
    while p < len(data):
        start = p
        kind = word() & 0x3FFFFFFF
        if kind in (HUNK_CODE, HUNK_DATA, HUNK_BSS):
            hunk += 1
            n = word()
            if kind != HUNK_BSS:
                p += 4 * n
        elif kind == HUNK_DEBUG:
            n = word()
            p += 4 * n
        elif kind == HUNK_SYMBOL:
            while n := word():
                p += 4 * n + 4
        elif kind == HUNK_RELOC32:
            out += struct.pack(">I", HUNK_RELOC32)
            while count := word():
                target = word()
                offsets = data[p:p + 4 * count]
                if len(offsets) != 4 * count:
                    raise HunkError(f"truncated RELOC32 block at {p:#x}")
                p += 4 * count
                if count > LIMIT:
                    over.append((hunk, target, count))
                for i in range(0, count, LIMIT):
                    k = min(LIMIT, count - i)
                    out += struct.pack(">II", k, target) + offsets[4 * i:4 * (i + k)]
            out += struct.pack(">I", 0)
            continue
        elif kind != HUNK_END:
            raise HunkError(f"unknown hunk type {kind:#x} at {start:#x}")
        out += data[start:p]
    return bytes(out), over


def records(data: bytes) -> tuple[bytes, list[bytes], int]:
    """The header, the loadable records and the count of symbol and debug hunks."""
    p = 0

    def word() -> int:
        nonlocal p
        if p + 4 > len(data):
            raise HunkError(f"truncated at {p:#x}")
        v = struct.unpack_from(">I", data, p)[0]
        p += 4
        return v

    if word() != HUNK_HEADER:
        raise HunkError("no HUNK_HEADER")
    while word():
        pass
    word()
    first, last = word(), word()
    for _ in range(last - first + 1):
        if word() >> 30 == 3:
            word()
    header, out, dropped = data[:p], [], 0
    while p < len(data):
        start = p
        kind = word() & 0x3FFFFFFF
        # Read each count before adding it: `p += 4 * word()` would load p first.
        if kind in (HUNK_CODE, HUNK_DATA, HUNK_DEBUG):
            n = word()
            p += 4 * n
        elif kind == HUNK_BSS:
            word()
        elif kind == HUNK_SYMBOL:
            while n := word():
                p += 4 * n + 4
        elif kind == HUNK_RELOC32:
            while count := word():
                word()
                p += 4 * count
        elif kind != HUNK_END:
            raise HunkError(f"unknown hunk type {kind:#x} at {start:#x}")
        if kind in (HUNK_SYMBOL, HUNK_DEBUG):
            dropped += 1
        else:
            out.append(data[start:p])
    return header, out, dropped


def release_of(full: str, stripped: str) -> int:
    fh, frec, _ = records(open(full, "rb").read())
    sh, srec, dropped = records(open(stripped, "rb").read())
    if dropped:
        print(f"{stripped}: {dropped} symbol or debug hunks", file=sys.stderr)
        return 1
    if fh != sh or frec != srec:
        print(f"{stripped}: loadable records differ from {full}", file=sys.stderr)
        return 1
    print(f"{stripped}: stripped, {len(srec)} records equal to {full}'s")
    return 0


def main() -> int:
    if sys.argv[1:2] == ["--release-of"] and len(sys.argv) == 4:
        try:
            return release_of(sys.argv[2], sys.argv[3])
        except HunkError as e:
            print(e, file=sys.stderr)
            return 1
    args = [a for a in sys.argv[1:] if a != "--check"]
    if len(args) != 1:
        print("usage: hunk_relocs.py FILE [--check]", file=sys.stderr)
        return 2
    path = args[0]
    data = open(path, "rb").read()
    try:
        fixed, over = split(data)
    except HunkError as e:
        print(f"{path}: {e}", file=sys.stderr)
        return 1
    for hunk, target, count in over:
        print(f"{path}: hunk {hunk} RELOC32 to hunk {target}: {count} offsets "
              f"{'over' if '--check' in sys.argv else 'split at'} {LIMIT}")
    if "--check" in sys.argv:
        return 1 if over else 0
    if over:
        open(path, "wb").write(fixed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
