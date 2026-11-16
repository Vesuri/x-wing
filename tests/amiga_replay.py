#!/usr/bin/env python3
"""Build and run a diagnostic Amiga image against the existing DOSBox-X reference.

Copied from Secret Weapons of the Luftwaffe's tests/amiga_replay.py (commit pinned in
manifest/references.tsv) and adapted: no joystick, no real-video capture (the shown
bitplanes are compared), and the reference's VGA status reads are replayed in their
service intervals (trace/retrace.csv), as by the host run. The image replays the
reference's hardware interrupts at their recorded poll points, its REP slices and its
calendar inputs; the guest code is the translator's, with diagnostic hooks only. At the
milestone's last snapshot the image holds, the fixture captures registers, state block,
guest RAM, DAC and bitplanes, and tests/host_run.py compares them with the reference
after its own host run. Generated hooks, tables and captures stay in tmp/; no reference
is re-recorded.
"""
import argparse
import csv
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import host_run as H  # noqa: E402
import rep_replay  # noqa: E402
from translator import cfg, emit, gen  # noqa: E402
from translator.lower import DRVSEG, LOADSEG  # noqa: E402

ROOT = H.REPO
TIMEOUT = 3600   # seconds of emulation for the whole run (the 68030 model at max speed)
HASH_STEP = 256  # service-history checkpoints: the hash is cumulative (amiga_replay.c)


def varint(value):
    assert value >= 0
    out = bytearray()
    while True:
        out.append(value & 127 | (128 if value > 127 else 0))
        value >>= 7
        if not value:
            return out


def delta(value, base):
    d = (value - base) & 0xffff
    d = d - 0x10000 if d & 0x8000 else d
    return varint(d << 1 if d >= 0 else (~d) << 1 | 1)


def rep_stream(records, ids):
    """The compacted REP slices as the byte stream amiga_replay.c rep_next reads:
    service difference, hits, point, start against the previous record's end,
    end against start (zigzag 16-bit), repeat << 1 | restart."""
    out, service, end = bytearray(), 0, (0, 0, 0)
    for c, n in records:
        assert c.service >= service and 0 < n < 0x8000
        out += varint(c.service - service) + varint(c.hits) + varint(ids[c.label])
        for k in range(3):
            out += delta(c.start[k], end[k])
        for k in range(3):
            out += delta(c.end[k], c.start[k])
        out += varint(n << 1 | int(c.restart))
        service, end = c.service, c.end
    return bytes(out)


def read_exempt(path, name, trace):
    """tests/host_run.py --exempt-out of this milestone and reference: {event: {register:
    and-mask}}, the bytes its service log exempts as loaded from dead stack (owner
    decision 2026-11-09)."""
    lines = path.read_text().splitlines()
    want = f'# milestone={name} reference={trace.parent.name}'
    if lines[0] != want:
        raise SystemExit(f'{path}: {lines[0]!r}, not {want!r}')
    exempt = {}
    for row in csv.DictReader(lines[1:]):
        mask = (0xff if int(row['bytes']) & 1 else 0) | (0xff00 if int(row['bytes']) & 2 else 0)
        exempt.setdefault(int(row['event']), {})[row['register']] = 0xffff & ~mask
    return exempt


def prepare(name, out, trace, late=False, exempt=None):
    script = H.milestone_script(name, bypassed=late)
    irqs, releases = H.reference_inputs(trace, exact_releases=True)
    reps = rep_replay.read(trace, required=True)
    summary = dict(x.split('=', 1) for x in (trace / 'summary.txt').read_text().split())
    assert int(summary['polls'], 16) == H.fnv(H.POLLS.read_bytes()), 'reference poll points differ'
    services = H.reference_services(trace)
    retrace = H.retrace_runs(trace)
    points = sorted({t[0] for t, _ in script['keys']} |
                    {t[0] for t in script['snapshots']} | {lab for _, lab, _, _ in irqs} | {c.label for c in reps})
    ids = {lab: i for i, lab in enumerate(points)}
    units = cfg.build()
    nodes = {emit.label(mod, off): (mod, off) for mod, u in units.items() for off in u.insns}
    hooks = {nodes[lab]: ids[lab] for lab in points}
    rep_hooks = {nodes[c.label]: ids[c.label] for c in reps}
    program = emit.Program(units, diagnostic_hooks=hooks, diagnostic_reps=rep_hooks)
    assert all(nodes[lab] in program.loop_heads for _, lab, _, _ in irqs)
    out.mkdir(parents=True, exist_ok=True)
    gen.generate(out / 'gen', program=program)
    hashes, digest = [], 2166136261
    exempt = exempt or {}
    for k, (kind, r) in enumerate(services):
        keep = exempt.get(k, {})
        values = [r[n] & keep.get(n, 0xffff) for n in H.REGS] + [r[n] for n in ('es', 'ss', 'ds', 'vector')]
        values += [r['flags'] & 0x600, int(kind == 'svc_ret')]
        for byte in struct.pack('>' + 'H' * len(values), *values):
            digest = ((digest ^ byte) * 16777619) & 0xffffffff
        hashes.append(digest)
    steps = []
    release = iter(releases)
    for (lab, _, hits), key in script['keys']:
        if isinstance(key, str):
            kind, value, end, skip = {'x': 2, 'y': 3, 'b': 4}[key[1]], int(key[2:]), 0, -1
        else:
            base = key & 0xffff
            r = next(release)
            end, skip = (r, -1) if isinstance(r, int) else r
            kind, value = 1, base >> 8 | (0x100 if base in H.GREY else 0) | ((key >> 7) & 0xe00)
        steps.append((ids[lab], hits, kind, value, end, skip))
    assert next(release, None) is None
    steps += [(ids[lab], hits, 0, 0, 0, -1) for lab, _, hits in script['snapshots']]
    locations = []
    for lab in points:
        mod, off = nodes[lab]
        base = DRVSEG if emit.loadseg(mod) == 'DRVSEG' else LOADSEG
        locations.append((base + units[mod].cs[off], units[mod].ip_of(off)))

    def array(ctype, name, rows):
        return f'static const {ctype} {name}[] = {{\n' + ''.join(
            '{' + ','.join(map(str, row)) + '},\n' for row in rows) + '};\n'
    reads = sum(n for _, _, n in retrace)
    text = ('/* Generated from the existing original reference; local only. */\n'
            'struct replay_point_info { uint32_t cs, ip; };\n'
            'struct replay_irq { uint32_t service, point, hits, vector; };\n'
            'struct replay_step { uint32_t point, hits, kind; int32_t value; uint32_t release; int32_t skip; };\n'
            'struct replay_retrace { uint32_t service, value, repeat; };\n'
            f'#define REPLAY_POINTS {len(points)}u\n#define REPLAY_IRQS {len(irqs)}u\n'
            f'#define REPLAY_SERVICES {len(services)}u\n#define REPLAY_STEPS {len(steps)}u\n'
            f'#define REPLAY_RETRACE {len(retrace)}u\n#define REPLAY_VGA_READS {reads}u\n')
    stream = rep_stream(rep_replay.compact(reps), ids)
    text += ('struct replay_rep { uint32_t service, hits; uint16_t point, cx, si, di, end_cx, end_si, end_di, restart, repeat; };\n'
             f'#define REPLAY_REPS {len(reps)}u\n'
             'static const uint8_t replay_rep_stream[] = {\n')
    text += ''.join(','.join(map(str, stream[k:k + 32])) + ',\n' for k in range(0, len(stream), 32)) + '};\n'
    text += array('struct replay_point_info', 'replay_points', locations)
    text += array('struct replay_irq', 'replay_irqs', [(s, ids[lab], h, v) for s, lab, h, v in irqs])
    text += array('struct replay_step', 'replay_script', steps)
    text += array('struct replay_retrace', 'replay_retrace', retrace)
    # (event, register index in H.REGS order, and-mask), by event
    rows = [(k, H.REGS.index(n), m) for k in sorted(exempt) for n, m in sorted(exempt[k].items())]
    text += ('struct replay_exempt { uint32_t service; uint16_t reg, mask; };\n'
             f'#define REPLAY_EXEMPTS {len(rows)}u\n')
    text += array('struct replay_exempt', 'replay_exempts', rows or [(0xffffffff, 0, 0xffff)])
    text += (f'#define REPLAY_HASH_STEP {HASH_STEP}u\n#define REPLAY_FINAL_HASH {digest}u\n'
             'static const uint32_t replay_service_hashes[] = {\n' +
             ','.join(map(str, hashes[HASH_STEP - 1::HASH_STEP])) + '};\n')
    (out / 'replay_data.h').write_text(text)
    calendar, clock = H.reference_clocks(trace)
    stamp = H.dos_file_stamp(clock) if clock is not None else (0, 0)
    (out / 'replay_clocks.h').write_text(
        '/* Recorded external calendar inputs, diagnostic build only. */\n'
        f'#define REPLAY_CALENDAR_DATE {calendar or 0}u\n'
        f'#define REPLAY_FILE_TIME {stamp[0]}u\n'
        f'#define REPLAY_FILE_DATE {stamp[1]}u\n')
    (out / 'expected.json').write_text(json.dumps(dict(
        services=len(services), interrupts=len(irqs), steps=len(steps), vga_reads=reads)))
    print(f'{name}: {len(points)} diagnostic points, {len(irqs)} interrupts, {len(services)} service events, '
          f'{len(reps)} REP slices, {reads} VGA status reads, {len(rows)} service register entries '
          f'exempt as loaded from dead stack', flush=True)


def build(out, screen=False):
    work = out / 'amiga'
    work.mkdir(exist_ok=True)
    makefile = work / 'Makefile'
    if not makefile.exists():
        makefile.symlink_to(ROOT / 'amiga/Makefile')
    subprocess.run(['make', '-s', '-C', str(work), f'REPO={os.path.relpath(ROOT, work)}',
                    'GEN=../gen', 'REPLAY=..'] + (['REPLAY_SCREEN=1'] if screen else []), check=True)
    return work


def run(name, out, trace, work, late=False, screen=False, timeout=TIMEOUT, sfx=False):
    capture = out / 'capture'
    capture.mkdir(exist_ok=True)
    template = (ROOT / 'amiga/milestone.gdb.in').read_text()
    template = template.replace('@LABEL@', 'rt_replay_done').replace(
        '@OUT@', os.path.relpath(capture, ROOT / 'amiga'))
    expected = json.loads((out / 'expected.json').read_text())
    check = '\n'.join(f'if replay_{key} != {value}\n  printf "XWING_REPLAY_INCOMPLETE {key}\\n"\n  quit 1\nend'
                      for key, value in expected.items())
    assert 'set $bm = &amiga_bitmap' in template
    stop = '  x/s *(char **)($sp+4)\n'
    assert stop in template
    template = template.replace(stop, stop + (
        '  printf "XWING_REPLAY_STATE a=%u b=%u services=%u interrupts=%u steps=%u reps=%u vga=%u\\n", '
        '*(unsigned *)($sp+8), *(unsigned *)($sp+12), replay_services, replay_interrupts, replay_steps, '
        'replay_rep_index, replay_vga_reads\n'
        '  printf "XWING_REPLAY_REP service=%u hits=%u point=%u cx=%x end_cx=%x restart=%u repeat=%u offset=%u\\n", '
        'rep_record.service, rep_record.hits, rep_record.point, rep_record.cx, rep_record.end_cx, '
        'rep_record.restart, rep_record.repeat, replay_rep_offset\n'
        '  printf "XWING_REPLAY_VISITS %u epoch=%u\\n", visits[*(unsigned *)($sp+8)], epochs[*(unsigned *)($sp+8)]\n'))
    if sfx:
        check += '\n' + SFX_REPORT.replace('@OUT@', os.path.relpath(capture, ROOT / 'amiga'))
    template = template.replace('set $bm = &amiga_bitmap', check + '\nset $bm = &amiga_bitmap')
    (capture / 'fixture.gdb').write_text(template)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    # debug.sh copies the original data but does not delete game writes: a fresh
    # run directory, so a replay inherits no file from an earlier attempt.
    run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=out))
    env = dict(os.environ, DEBUG_PORT=str(port), FSUAE_PORT_PINNED='1',
               AMIGA_CPU=os.environ.get('AMIGA_CPU', '68030'),
               XWING_ELF=str(work / 'out/XWing.elf'), FSUAE_RUN=os.path.relpath(run_dir, ROOT / 'amiga'),
               FSUAE_CLAIM_STRICT='1', XWING_ARGS='',
               # The diagnostic image carries the reference (replay_data.h: 2.3 MB of
               # .rodata at m01, 15 MB at m14) beside the code: with the target's 8 MB
               # of Fast RAM the guest block no longer fits ("X-Wing not enough
               # memory"). The extra Zorro III board is for that data; the production
               # image keeps the 8 MB target (make test-amiga-live).
               EXTRA_ARGS='--zorro_iii_memory=65536')
    with (capture / 'gdb.log').open('w') as log:
        command = [str(ROOT / 'amiga/debug.sh'), '', str(capture / 'fixture.gdb'), str(work / 'out/XWing.exe')]
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            result = process.wait(timeout=timeout)
        except BaseException:
            # Only the process group created above belongs to this capture.
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    lines = (capture / 'gdb.log').read_text().splitlines()
    if result or 'XWING_MILESTONE_OK' not in lines:
        raise SystemExit(f'Amiga diagnostic replay {name}: no capture (exit {result})\n' + '\n'.join(lines[-20:]))
    regs = [line.removeprefix('XWING_REGS ') for line in lines if line.startswith('XWING_REGS ')]
    assert len(regs) == 1, regs
    (capture / 'regs.txt').write_text(regs[0])
    if sfx:
        problems = sfx_problems(capture, lines)
        if problems:
            raise SystemExit('\n'.join(problems))
        print(f'Amiga diagnostic replay {name}: the reference\'s service history, interrupts and REP '
              f'slices consumed with the effect capture and player running; every start a play, '
              f'every effect playing at the end started and its channels muted', flush=True)
        return
    problems = H.check(name, timeout, capture, None, trace=trace, bypass=late, screen=screen)
    if problems:
        raise SystemExit('\n'.join(problems))
    print(f'Amiga diagnostic replay {name}: registers, state, RAM, DAC, shown pixels and '
          f'service history match DOSBox-X', flush=True)


# The effect smoke (--sfx, make t-amiga-sfx): at the replay's end the effect
# capture's and player's state (runtime.h rt_sfx_*, fx_play.h, Audio.cpp).
SFX_REPORT = r"""printf "XWING_SFX captures=%u capture_fields=%u fields=%u bytes=%u cached=%u started=%u mask=%u\n", rt_sfx_captures, amiga_sfx_capture_fields, amiga_audio_effect_fields, amiga_audio_effect_bytes, amiga_audio_effect_cached, fx_started, fx_mask
dump binary memory @OUT@/sfx-starts.bin &rt_sfx_starts[0] &rt_sfx_starts[48]
dump binary memory @OUT@/sfx-ticks.bin &rt_sfx_ticks[0] &rt_sfx_ticks[48]
dump binary memory @OUT@/sfx-writes.bin &rt_sfx_writes[0] &rt_sfx_writes[48]"""
DRV_DATA, DRV_PLAYERS, DRV_VOICES = 0x4D0, 0x6EA, 0x1ED2    # runtime sfx.c


def sfx_problems(capture, lines):
    """The capture ran and rendered; every start the driver took of an effect
    with a sample became a play; each driver player playing an effect at the
    end (guest RAM, the driver's players and voices as sfx.c reads them) has a
    counted start, and one with a sample its OPL channels muted. Whether its
    play still holds a Paula voice is not checked: the replay runs the driver
    on the reference's game time, here slower than the fields the sample
    plays in."""
    report = [x for x in lines if x.startswith('XWING_SFX ')]
    if len(report) != 1:
        return ['no XWING_SFX report']
    print(report[0], flush=True)
    f = dict(kv.split('=') for kv in report[0].split()[1:])
    f = {k: int(v) for k, v in f.items()}
    ram = (capture / 'ram.bin').read_bytes()
    b = lambda a: ram[0xFFFFF - a]
    w = lambda a: b(a) | b(a + 1) << 8
    starts = (capture / 'sfx-starts.bin').read_bytes()
    ticks = struct.unpack('>48H', (capture / 'sfx-ticks.bin').read_bytes())
    writes = struct.unpack('>48H', (capture / 'sfx-writes.bin').read_bytes())
    problems = []
    if f['captures'] < 1 or not f['bytes']:
        return [f'no capture or no samples: {f}']
    ds = (w(8 * 4 + 2) + DRV_DATA) * 16
    owner = {}
    for v in range(9):
        part = w(ds + DRV_VOICES + 0x62 * v)
        if part:
            k, r = divmod(w(ds + part) - DRV_PLAYERS, 0x12)
            if not r and 0 <= k < 8:
                owner.setdefault(k, set()).add(b(ds + DRV_VOICES + 0x62 * v + 7))
    seen = 0
    for k in range(8):
        at = ds + DRV_PLAYERS + 0x12 * k
        sid = w(at + 8)
        if b(at + 6) != 1 or not 4 <= sid < 48:
            continue
        seen += 1
        channels = owner.get(k, set())
        print(f'player {k}: effect {sid}, volume {b(at + 14)}, channels {sorted(channels)}, '
              f'starts {starts[sid]}, ticks {ticks[sid]}', flush=True)
        if not starts[sid]:
            problems.append(f'effect {sid} plays with no start counted')
        if ticks[sid] and writes[sid]:
            if any(not f['mask'] >> c & 1 for c in channels):
                problems.append(f'effect {sid}: channels {sorted(channels)} not muted (mask {f["mask"]:#x})')
    took = sum(starts[i] for i in range(48) if ticks[i] and writes[i])
    if f['started'] != took:
        problems.append(f'{f["started"]} plays for {took} starts of effects with samples')
    if not seen:
        problems.append('no effect plays at the end: nothing to check')
    return problems


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--milestone', required=True)
    ap.add_argument('--screen', action='store_true',
                    help='the copy-protection hook declines: the translated screen runs on the '
                         "reference's keys (m03, m03c, m03p, m03q), as tests/host_run.py --screen")
    ap.add_argument('--bypass', action='store_true',
                    help='past the screen: the production hook bypasses it, against the bypassed '
                         'reference (tools/reference.py --polls --bypass), as tests/host_run.py --bypass')
    ap.add_argument('--exempt', type=Path, metavar='CSV',
                    help='tests/host_run.py --exempt-out of the same milestone and mode: the service '
                         'hash leaves out the register bytes the host exempts as loaded from dead stack')
    ap.add_argument('--sfx', action='store_true',
                    help='the effect smoke: no host check; at the end the effect capture and player '
                         'state against the driver players in the guest RAM')
    ap.add_argument('--timeout', type=int, default=TIMEOUT,
                    help='seconds for the FS-UAE run and for the host run of the check')
    args = ap.parse_args()
    if args.bypass and args.milestone == H.BYPASS_MILESTONE:
        ap.error(f'{H.BYPASS_MILESTONE} is the host oracle (tests/host_run.py --bypass); '
                 'replay it with --screen')
    out = ROOT / 'tmp/amiga-replay' / args.milestone
    trace = H.host_reference(args.milestone, bypassed=args.bypass)
    prepare(args.milestone, out, trace, late=args.bypass,
            exempt=read_exempt(args.exempt, args.milestone, trace) if args.exempt else None)
    work = build(out, screen=args.screen)
    run(args.milestone, out, trace, work, late=args.bypass, screen=args.screen, timeout=args.timeout,
        sfx=args.sfx)
