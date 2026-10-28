#!/usr/bin/env python3
"""Render or hash a VGA dump written by the scripted DOSBox-X `vga` step.

Layout: one text header line, 768 six-bit DAC bytes, then video memory in DOSBox's
plane-interleaved layout, where byte 4*b+p is plane p at planar offset b. Chain-4
(sequencer memory mode bit 3) stores CPU address a in plane a&3 at offset a&~3, as VGA
hardware does (DOSBox-X vga_memory.cpp chain4remap); unchained Mode X stores pixel x of a
row in plane x&3 at offset row_start + x/4.
"""
import argparse
import hashlib
from pathlib import Path

from PIL import Image

WIDTH, HEIGHT = 320, 200


def parse(raw: bytes) -> tuple[dict[str, str], bytes, bytes]:
    end = raw.index(b'\n')
    words = raw[:end].decode('ascii').split()
    if words[0] != 'XWVGA':
        raise ValueError('VGA DUMP / BAD HEADER')
    header = dict(word.split('=', 1) for word in words[1:])
    dac = raw[end + 1:end + 1 + 768]
    memory = raw[end + 1 + 768:]
    if len(dac) != 768 or len(memory) < 0x40000:
        raise ValueError('VGA DUMP / TRUNCATED')
    return header, dac, memory


def frame(header: dict[str, str], dac: bytes, memory: bytes) -> tuple[bytes, bytes]:
    """Return the visible 8-bit frame and its 8-bit RGB palette."""
    if header['mode'] != '13':
        raise ValueError(f"VGA DUMP / MODE {header['mode']} IS NOT 13")
    start = int(header['crtc_start'], 16)
    if int(header['seq_memory_mode'], 16) & 0x08:
        if start:
            raise ValueError('VGA DUMP / CHAIN-4 START ADDRESS NOT DECODED')
        index = [((a & ~3) << 2) + (a & 3) for a in range(WIDTH * HEIGHT)]
    else:
        index = [4 * (start + y * WIDTH // 4 + x // 4) + (x & 3)
                 for y in range(HEIGHT) for x in range(WIDTH)]
    if max(index) >= len(memory):
        raise ValueError('VGA DUMP / FRAME OUTSIDE MEMORY')
    pixels = bytes(memory[i] for i in index)
    palette = bytes((c << 2) | (c >> 4) for c in dac)
    return pixels, palette


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dump', type=Path)
    parser.add_argument('--png', type=Path, help='write the visible frame as a PNG')
    args = parser.parse_args()
    header, dac, memory = parse(args.dump.read_bytes())
    pixels, palette = frame(header, dac, memory)
    if args.png:
        image = Image.frombytes('P', (WIDTH, HEIGHT), pixels)
        image.putpalette(palette)
        image.save(args.png)
    print(f'{hashlib.sha256(pixels + palette).hexdigest()}  {args.dump.name}')


if __name__ == '__main__':
    main()
