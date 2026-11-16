#!/usr/bin/env python3
"""Prerendered effect playback (src/platform/amiga/fx_play.c) with synthetic
samples and driver states, no game bytes. Adapted from Secret Weapons of the
Luftwaffe's tests/test_sfx_play.py (commit pinned in manifest/references.tsv).

  python3 tests/test_fx_play.py [--sabotage]

A player that starts an effect with a sample: the OPL channels its voices play
muted while it plays it, a Paula voice reserved and restarted on the sample's
first chunk at the effect period and the sample's volume scaled by the
player's, the next chunk (or silence) latched a field after the latched one
starts, the voice given back once the last has played. A sample over one
Paula loop splits into equal chunks. Two players of one id play on two voices;
a start the driver took on a player that plays the same id restarts it; a
stop before the driver's end fades over FX_FADE_FIELDS, one at its end plays
out; a fourth play takes the oldest's voice, so the music keeps one. An id
with no sample (a loop) stays on FM. PAL and NTSC periods; volume from
fm_effect's peak; the volume gain against its formula.
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
PERIOD = {0: 214, 1: 216}           # FM_EFFECT_RATE on PAL, NTSC
FIELD = {0: 71051 / 214, 1: 119665 / 2 / 216}   # samples a field
FIELD8 = 256 * 71051 // 214         # fx_play.c's 24.8 samples a PAL field
IDS, PLAYERS, PLAYS, FADE = 48, 8, 3, 3


def RESERVE(v):
    return 1 << (12 + v)            # fm_paula.h FM_RESERVE


def gain(volume):                   # fx_play.c gain_of: ((4k + 1.5) / 127)^1.75, k 31 whole
    k = volume >> 2
    return 256 if k == 31 else round(256 * ((4 * k + 1.5) / 127) ** 1.75)


class Driver(C.Structure):
    _fields_ = [('active', C.c_uint8 * PLAYERS), ('id', C.c_uint8 * PLAYERS),
                ('volume', C.c_uint8 * PLAYERS), ('owner', C.c_uint8 * 9)]


class Rig:
    def __init__(self, lib):
        self.lib = lib
        lib.fx_field.argtypes = [C.c_void_p] * 3
        lib.fx_field.restype = C.c_uint16
        lib.fx_effect.argtypes = [C.c_uint8, C.c_void_p, C.c_uint32, C.c_uint8, C.c_uint32, C.c_void_p]
        lib.fx_effect_volume.argtypes = [C.c_uint32]
        lib.fx_effect_volume.restype = C.c_uint8
        self.d = Driver()
        self.d.id[:] = [0xff] * PLAYERS
        self.d.owner[:] = [0xff] * 9
        self.starts = (C.c_uint8 * IDS)()
        self.v = (Voice * 4)()

    def play(self, player, sid, channels, volume=127, start=True):
        self.d.active[player], self.d.id[player], self.d.volume[player] = 1, sid, volume
        for c in channels:
            self.d.owner[c] = player
        if start:
            self.starts[sid] = (self.starts[sid] + 1) & 255

    def stop(self, player):
        self.d.active[player] = 0
        for c in range(9):
            if self.d.owner[c] == player:
                self.d.owner[c] = 0xff

    def field(self):
        m = self.lib.fx_field(C.byref(self.d), self.starts, self.v)
        held = [i for i in range(4) if m & RESERVE(i)]
        return m & 0x1ff, held

    def addr(self, i):
        return C.addressof(self.v[i].loop.contents) if self.v[i].loop else 0


def checks(lib):
    for level, vol in [(0, 1), (32, 1), (4095, 64), (2048, 32), (9000, 64), (64, 1), (96, 2)]:
        assert lib.fx_effect_volume(level) == vol, f'volume of {level}'
    table = (C.c_uint16 * 32).in_dll(lib, 'gain_of')
    assert list(table) == [gain(4 * k) for k in range(32)], f'gain table {list(table)}'
    r = Rig(lib)
    ntsc = C.c_uint8.in_dll(lib, 'fm_ntsc')
    silence = (C.c_int8 * 4)()
    small = (C.c_int8 * 1000)(*[5] * 1000)
    big_bytes = 72184
    big = (C.c_int8 * big_bytes)()
    # Unregistered: FM keeps every channel and voice.
    r.play(0, 9, (0, 1))
    assert r.field() == (0, []), 'an id with no sample taken'
    r.stop(0)
    r.field()
    for sid in (5, 7, 8, 10):
        lib.fx_effect(sid, small, 1000, 40, 1000, silence)
    lib.fx_effect(6, big, big_bytes, 64, big_bytes, silence)
    lib.fx_effect(11, small, 131070, 64, 1000, silence)     # over two loops: refused
    base, sil = C.addressof(small), C.addressof(silence)
    for mode in (0, 1):
        ntsc.value = mode
        for player, channels in ((2, (0, 1, 8)), (7, (4,))):
            r.play(player, 5, channels)
            out = []
            for _ in range(12):
                out.append((r.field(), r.v[0].restart, r.addr(0), r.v[0].bytes, r.v[0].period, r.v[0].volume))
            want_mask = sum(1 << c for c in channels)
            assert all(f[0][0] == want_mask for f in out), f'player {player}: mask {out}'
            assert out[0][0][1] == [0] and out[0][1:] == (1, base, 1000, PERIOD[mode], 40), f'start {out[0]}'
            assert out[1][1:3] == (0, sil) and out[1][3] == 4 and out[1][5] == 40, f'latch {out[1]}'
            playing = [f for f in out if f[0][1]]
            want = -(-(1000 + FIELD[mode]) // FIELD[mode])
            assert abs(len(playing) - want) <= 1, f'player {player}: {len(playing)} fields, not {want}'
            assert not out[-1][0][1], 'voice kept after the sample'
            r.stop(player)
            assert r.field() == (0, []), 'channels kept after the stop'
    ntsc.value = 0
    # Two chunks: equal halves, the second latched at field 1, silence a field
    # after the second starts, then the voice back.
    r.play(1, 6, (3,))
    f = []
    while True:
        m = r.field()
        f.append((m, r.v[0].restart, r.addr(0), r.v[0].bytes))
        if not m[1]:
            break
    half, b = big_bytes // 2, C.addressof(big)
    assert f[0][1:] == (1, b, half), f'chunk 0 {f[0]}'
    assert f[1][1:] == (0, b + half, half), f'chunk 1 {f[1]}'
    k = next(n for n, x in enumerate(f) if x[2] == sil)
    want = next(n for n in range(1, 1000) if n * FIELD8 >> 8 >= half + (FIELD8 >> 8))
    assert k == want, f'silence latched at field {k}, not {want}'
    assert f[-1][0] == (1 << 3, []), 'the player still plays it: its channel stays muted'
    r.stop(1)
    r.field()
    # The player's volume scales the sample's.
    for vol in (127, 100, 64, 16, 3):
        r.play(0, 5, (2,), volume=vol)
        r.field()
        assert r.v[0].volume == (40 * gain(vol) + 128) >> 8, f'volume {vol}: {r.v[0].volume}'
        r.stop(0)
        for _ in range(FADE + 1):
            r.field()
        assert r.field() == (0, []), 'fade left a voice'
    # Two players of one id: two voices.
    r.play(0, 5, (0,))
    r.play(3, 5, (1,))
    assert r.field() == (3, [0, 1]) and r.v[0].restart and r.v[1].restart, 'two instances'
    # A start the driver took on a player that plays the id: a restart, no new voice.
    r.field()
    r.starts[5] += 1
    assert r.field() == (3, [0, 1]), 'restart took a voice'
    assert sum(r.v[i].restart for i in (0, 1)) == 1, 'restart not seen'
    assert r.field()[1] == [0, 1] and not r.v[0].restart and not r.v[1].restart
    r.stop(0)
    r.stop(3)
    # An early stop fades; the voice is back after it, the channels at once.
    vols = []
    for _ in range(6):
        r.field()
    r.play(4, 7, (5,))
    r.field()
    r.stop(4)
    for _ in range(FADE + 1):
        m = r.field()
        vols.append(r.v[0].volume if m[1] else None)
        assert m[0] == 0, 'a stopped player keeps its channels'
    assert vols == [40 * n // (FADE + 1) for n in range(FADE, 0, -1)] + [None], f'fade {vols}'
    # A stop at the driver's end: the tail plays out.
    lib.fx_effect(8, small, 1000, 40, 300, silence)
    r.play(4, 8, (5,))
    r.field()
    r.field()
    r.stop(4)
    m = r.field()
    assert m[1] == [0] and r.v[0].volume == 40, f'tail cut {m} {r.v[0].volume}'
    for _ in range(4):
        r.field()
    # Four at once: three play, the fourth on the oldest's voice; one voice
    # stays the music's.
    for p, sid in enumerate((5, 7, 8)):
        r.play(p, sid, (p,))
        assert len(r.field()[1]) == p + 1
    first = [r.addr(i) for i in range(4)]
    r.play(5, 10, (6,))
    m = r.field()
    assert m == (0b1000111, [0, 1, 2]), f'fourth play {m}'
    assert r.v[0].restart and not r.v[1].restart and not r.v[2].restart, 'not the oldest voice'
    del first
    lib.fx_clear()
    assert r.field() == (0, []), 'cleared samples still play'
    print('effect play: masks, chunks, latch, volume, instances, restart, fade, tail, voice cap, PAL/NTSC: ok')


def main():
    plants = {'latch': ('* e->chunk + (field >> 8)', '* e->chunk'),
              'chunk': ('(bytes + EFFECT_LOOP_BYTES - 1) / EFFECT_LOOP_BYTES', '1'),
              'volume': ('p->gain = gain_of[(d->volume[p->player] & 127) >> 2];', 'p->gain = 256;'),
              'mask': ('mask = (uint16_t)(mask | 1u << k);', ';'),
              'reserve': ('mask = (uint16_t)(mask | FM_RESERVE(p->voice));', ';'),
              'restart': ('fresh[tracked[k]]) {', '0) {'),
              'fade': ('p->phase = FADE;', 'p->phase = IDLE;'),
              'tail': ('(p->elapsed >> 8) + 2 * (field >> 8) < p->e->end', 'field'),
              'cap': ('if (plays[k].phase == IDLE) {\n                if (!p)', 'if (1) {\n                if (!p)'),
              'ntsc': ('fm_ntsc ? EFFECT_PERIOD_NTSC', '0 ? EFFECT_PERIOD_NTSC')}
    cases = plants.items() if '--sabotage' in sys.argv else [('normal', None)]
    missed = []
    for name, plant in cases:
        with tempfile.TemporaryDirectory(prefix='fx-play-', dir=ROOT / 'tmp') as tmp:
            paths = []
            for filename in ('fm_paula.c', 'fx_play.c'):
                text = (SRC / filename).read_text()
                if plant and filename == 'fx_play.c':
                    assert plant[0] in text, name
                    text = text.replace(plant[0], plant[1])
                if filename == 'fx_play.c':
                    text = text.replace('static const uint16_t gain_of', 'const uint16_t gain_of')
                path = Path(tmp) / filename
                path.write_text(text)
                paths.append(str(path))
            dll = Path(tmp) / 'fx.so'
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
