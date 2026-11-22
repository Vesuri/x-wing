#!/usr/bin/env python3
"""Sound Blaster speech playback (src/platform/amiga/sb_play.c) with synthetic
blocks, no game bytes; the shape of tests/test_fx_play.py.

  python3 tests/test_sb_play.py [--sabotage]

A block plays on Paula voice SB_VOICE, reserved from the FM re-hoster while
it plays: restarted on its first chunk at the rate's Paula period (PAL and
NTSC clocks), at full volume with the DSP speaker on and silent with it off;
the next chunk (or silence) latched a field after the latched one starts. Its
end, the card's terminal count that posts IRQ 7, comes once, at the first
field whose samples since the start reach the block's length, within a field
of length / rate; the voice is given back the field after. An odd length is
padded to even; a block over one Paula loop splits into equal chunks. A
pause holds the count with the voice silent and reserved; a continue
restarts the voice at the sample reached and the end comes after the rest.
"""
import ctypes as C
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_fm_quality import Voice  # noqa: E402

SRC = ROOT / 'src/platform/amiga'
VOICE, VOLUME = 3, 64                           # sb_play.h SB_VOICE, SB_VOLUME
CLOCK = {0: 3546895, 1: 3579545}                # Paula's colour clock, PAL and NTSC
FIELD_CLOCKS = {0: 313 * 227, 1: 263 * 227.5}   # colour clocks a field
FIELD_HZ = {0: CLOCK[0] / FIELD_CLOCKS[0], 1: CLOCK[1] / FIELD_CLOCKS[1]}
RESERVE = 1 << (12 + VOICE)                     # fm_paula.h FM_RESERVE


def period(rate, mode):
    return (CLOCK[mode] + rate // 2) // rate


def field8(rate, mode):                         # sb_play.c's 24.8 samples a field
    p = period(rate, mode)
    return 128 * 119665 // p if mode else 256 * 71051 // p


class Rig:
    def __init__(self, lib):
        self.lib = lib
        lib.sb_field.argtypes = [C.c_uint8, C.c_void_p, C.c_void_p]
        lib.sb_field.restype = C.c_uint16
        lib.sb_block.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p]
        lib.sb_pause.argtypes = [C.c_uint32]
        self.v = (Voice * 4)()
        self.silence = (C.c_int8 * 4)()
        self.ended = C.c_uint8()

    def field(self, speaker=1):
        m = self.lib.sb_field(speaker, self.v, C.byref(self.ended))
        v = self.v[VOICE]
        loop = C.addressof(v.loop.contents) if v.loop else 0
        return m, self.ended.value, v.restart, loop, v.bytes, v.period, v.volume

    def run(self, speaker=1, limit=2000):
        out = []
        while len(out) < limit:
            f = self.field(speaker)
            out.append(f)
            if not f[0]:
                return out
        raise AssertionError('the block never gave its voice back')


def checks(lib):
    r = Rig(lib)
    ntsc = C.c_uint8.in_dll(lib, 'fm_ntsc')
    sil = C.addressof(r.silence)
    assert r.field()[:2] == (0, 0), 'a voice taken with no block'
    pcm = (C.c_int8 * 70000)(*[3] * 70000)
    base = C.addressof(pcm)
    for mode in (0, 1):
        ntsc.value = mode
        for length, rate in ((1000, 8000), (4001, 10989), (20000, 5494)):
            lib.sb_block(pcm, length, rate, r.silence)
            out = r.run()
            even = (length + 1) & ~1
            p = period(rate, mode)
            assert out[0] == (RESERVE, 0, 1, base, even, p, VOLUME), f'{length} at {rate}: start {out[0]}'
            assert out[1][2:5] == (0, sil, 4), f'{length} at {rate}: latch {out[1]}'
            ends = [n for n, f in enumerate(out) if f[1]]
            want = next(n for n in range(1, 2000) if n * field8(rate, mode) >> 8 >= even)
            assert ends == [want], f'{length} at {rate} ({mode}): ended at {ends}, not [{want}]'
            assert abs(want - length / rate * FIELD_HZ[mode]) <= 1, f'{length} at {rate}: {want} fields'
            assert all(f[0] == RESERVE for f in out[:-1]) and out[-1][:2] == (0, 0), \
                f'{length} at {rate}: voice kept or given back early'
    ntsc.value = 0
    # The speaker off (D3h): the block plays and ends, silent.
    lib.sb_block(pcm, 1000, 8000, r.silence)
    out = r.run(speaker=0)
    assert out[0][2] == 1 and all(f[6] == 0 for f in out), f'speaker off heard {out[:2]}'
    assert sum(f[1] for f in out) == 1, 'speaker off: no end'
    # Two chunks: equal halves, the second latched at field 1.
    lib.sb_block(pcm, 65536, 8000, r.silence)
    out = r.run()
    assert out[0][2:5] == (1, base, 32768) and out[1][2:5] == (0, base + 32768, 32768), \
        f'chunks {out[0]} {out[1]}'
    k = next(n for n, f in enumerate(out) if f[3] == sil)
    want = next(n for n in range(1, 2000) if n * field8(8000, 0) >> 8 >= 32768 + (field8(8000, 0) >> 8))
    assert k == want, f'silence latched at field {k}, not {want}'
    # Pause after three fields: silent, reserved, no end; a continue restarts at
    # the sample reached and ends after the rest.
    lib.sb_block(pcm, 20000, 8000, r.silence)
    for _ in range(4):
        r.field()
    played = 3 * field8(8000, 0) >> 8
    lib.sb_pause(1)
    for _ in range(50):
        f = r.field()
        assert f[0] == RESERVE and f[1] == 0 and f[6] == 0, f'paused {f}'
    lib.sb_pause(0)
    out = r.run()
    at = played & ~1
    assert out[0][2:5] == (1, base + at, 20000 - at), f'continue {out[0]}, from {at}'
    ends = [n for n, f in enumerate(out) if f[1]]
    want = next(n for n in range(1, 2000) if at + (n * field8(8000, 0) >> 8) >= 20000)
    assert ends == [want], f'after the continue: ended at {ends}, not [{want}]'
    # A new block replaces the one playing; a clear stops it.
    lib.sb_block(pcm, 20000, 8000, r.silence)
    r.field()
    lib.sb_block(pcm, 1000, 8000, r.silence)
    assert r.field()[2:5] == (1, base, 1000), 'a new block did not restart the voice'
    lib.sb_clear()
    assert r.field()[:2] == (0, 0), 'a cleared block still plays'
    print('speech play: restart, period, speaker, end field, chunks, pad, pause, continue, PAL/NTSC: ok')


def main():
    plants = {'end': ('if (b.base + at >= b.bytes) {', 'if (b.base + at > b.bytes + 512) {'),
              'latch': ('* b.chunk + (field >> 8)', '* b.chunk'),
              'chunk': ('(left + LOOP_BYTES - 1) / LOOP_BYTES', '1'),
              'pad': ('b.bytes = (bytes + 1) & ~1u;', 'b.bytes = bytes;'),
              'speaker': ('v->volume = speaker ? SB_VOLUME : 0;', 'v->volume = (speaker | 1) ? SB_VOLUME : 0;'),
              'reserve': ('    return FM_RESERVE(SB_VOICE);\n}', '    return 0;\n}'),
              'pause': ('b.phase = PAUSED;', 'b.phase = PLAY;'),
              'continue': ('restart_at(at & ~1u);', 'restart_at(0);'),
              'ntsc': ('fm_ntsc ? CLOCK_NTSC', '0 ? CLOCK_NTSC')}
    cases = plants.items() if '--sabotage' in sys.argv else [('normal', None)]
    missed = []
    for name, plant in cases:
        with tempfile.TemporaryDirectory(prefix='sb-play-', dir=ROOT / 'tmp') as tmp:
            paths = []
            for filename in ('fm_paula.c', 'sb_play.c'):
                text = (SRC / filename).read_text()
                if plant and filename == 'sb_play.c':
                    assert plant[0] in text, name
                    text = text.replace(plant[0], plant[1])
                path = Path(tmp) / filename
                path.write_text(text)
                paths.append(str(path))
            dll = Path(tmp) / 'sb.so'
            subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I', str(SRC), *paths, '-o', str(dll)], check=True)
            try:
                checks(C.CDLL(str(dll)))
            except AssertionError as e:
                if not plant:
                    raise
                print(f'plant {name}: caught ({e})')
            else:
                if plant:
                    print(f'plant {name}: MISSED')
                    missed.append(name)
    if missed:
        print('FAIL: plants missed:', ', '.join(missed))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
