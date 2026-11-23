#!/usr/bin/env python3
"""Run the WHDLoad slave in FS-UAE in an isolated tmp/whdload-test-* fixture.

    python3 tools/test_whdload.py --mode smoke     # Smoke.slave: harness only
    python3 tools/test_whdload.py --mode boot      # BootTest.slave: Kickstart 3.1 kickemu boots
    python3 tools/test_whdload.py --mode load      # LoadTest.slave: LoadSeg + PROGDIR
    python3 tools/test_whdload.py --mode run [--slave build/whdload/MemFree.slave]
    python3 tools/test_whdload.py --mode run --installed DIR [--setup a1200-040]
    python3 tools/test_whdload.py --mode run --setup a1200-030 [--whdload-mmu]

Copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and
adapted: no Custom options, X-Wing's oracles.

`run` starts the game under the release slave; WHDLoad TIMEOUT (needs the moved
VBR of a 68020) ends it with COREDUMP and the dump is judged:
  - the reason is the timeout ("DEBUG caused" at the CIA-A event count), not a fault;
  - the game is running: most 64-byte blocks of the original XWING.EXE lie in
    guest RAM, which holds guest bytes in reverse order (relocated and patched
    blocks differ);
  - the dump's CACR matches the slave's cache policy (docs/whdload.md, Caches):
    data cache on where WHDLoad uses the MMU (68040/060, 68030 with MMU),
    otherwise the instruction cache alone.
The MemFree slave's low-water marks (Chip, Fast) are read from its $100 slot.
--installed runs an installed X-Wing drawer as it is (slave, data/X-Wing, data).
--setup a1200-040: full 68040 with its MMU and FPU, JIT off, on $FSUAE_MMU;
the report must show TC=8000 (translation on; AmigaXDev whdload-mmu.md).
--setup a1200-030: full 68030 with its MMU on $FSUAE_MMU; WHDLoad uses the MMU
only with its MMU option (--whdload-mmu). --setup a1200-060: as the 68040, TC=8000 too.
These setups emulate the data cache.

Inputs are local, never shipped: Kickstart 3.1 A1200 + RTB, WHDLoad, the
Workbench floppy and the configured DOS install (tmp/dos/configured-sb/XWING,
make dos-configure-sb: the release image is the Sound Blaster build). Source amiga/env.sh first. The emulator is the one this
script started; it is stopped by its own PID only.
"""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
AMIGA = Path.home() / '.local/share/amiga'
KICKSTARTS = AMIGA / 'Kickstarts'
WHDLOAD = Path(os.environ.get('WHDLOAD', AMIGA / 'WHDLoad')) / 'C/WHDLoad'
WORKBENCH = Path(os.environ.get('WORKBENCH_ADF', AMIGA / 'Workbenchv2.04rev37.67Workbench.adf'))
KICK31 = Path(os.environ.get('KICKSTART_A1200', KICKSTARTS / 'kick40068.A1200'))
SLAVES = {'smoke': 'Smoke.slave', 'boot': 'BootTest.slave', 'load': 'LoadTest.slave', 'run': 'XWing.slave'}


def blocks(data, size=64):
    return [data[a:a + size] for a in range(0, len(data) - size + 1, size)
            if len(set(data[a:a + size])) > 8]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--mode', choices=tuple(SLAVES), default='run')
    p.add_argument('--slave', type=Path, help='slave override (default: build/whdload/ per mode)')
    p.add_argument('--exe', type=Path, default=ROOT / 'amiga/out/XWing-release.exe',
                   help='stripped (make amiga-release): LoadSeg reads symbol hunks in small pieces')
    p.add_argument('--data', type=Path, default=ROOT / 'tmp/dos/configured-sb/XWING')
    p.add_argument('--installed', type=Path, help='installed X-Wing drawer, used unchanged')
    p.add_argument('--setup', choices=('a1200', 'a1200-030', 'a1200-040', 'a1200-060'), default='a1200-030')
    p.add_argument('--whdload-mmu', action='store_true', help="WHDLoad's MMU option (68030)")
    p.add_argument('--rom', type=Path, default=KICK31)
    p.add_argument('--fast', type=int, default=8192, help='host Zorro II Fast RAM in KiB (8192 at most)')
    p.add_argument('--z3', type=int, default=0, help='host Zorro III Fast RAM in KiB (32-bit setups)')
    p.add_argument('--cpu', default='68020')
    p.add_argument('--ticks', type=int, default=3000, help='WHDLoad TIMEOUT in PAL fields (run)')
    p.add_argument('--no-preload', action='store_true')
    p.add_argument('--seconds', type=int, default=600, help='host safety ceiling')
    args = p.parse_args()
    if args.installed:
        assert args.mode == 'run' and not args.slave, '--installed runs its own slave'
        args.data = args.installed / 'data'
    mmu = args.setup != 'a1200'
    if mmu:
        args.cpu = '68' + args.setup[-3:]
    assert not args.whdload_mmu or args.cpu == '68030', '--whdload-mmu is for --setup a1200-030'
    assert args.fast <= 8192 and (not args.z3 or mmu), 'Zorro II holds 8 MiB; Zorro III needs a 32-bit setup'
    # Where WHDLoad uses the MMU, the slave's CACHE policy holds (data cache on).
    dcache = args.cpu in ('68040', '68060') or args.whdload_mmu

    (ROOT / 'tmp').mkdir(exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix='whdload-test-', dir=ROOT / 'tmp'))
    print('Fixture:', base, flush=True)
    boot, game = base / 'boot', base / 'game'
    data = game / 'data'
    if args.installed:
        shutil.copytree(args.installed, game)
    for d in (boot / 's', boot / 'devs/Kickstarts', data, base / 'state'):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WHDLOAD, game / 'WHDLoad')
    if not args.installed:
        shutil.copyfile(args.slave or ROOT / 'build/whdload' / SLAVES[args.mode], game / 'X-Wing.slave')
    if args.mode != 'smoke':
        shutil.copyfile(args.rom, boot / 'devs/Kickstarts' / args.rom.name)
        shutil.copyfile(args.rom.with_name(args.rom.name + '.RTB'), boot / 'devs/Kickstarts' / (args.rom.name + '.RTB'))
    if args.mode in ('load', 'run') and not args.installed:
        shutil.copyfile(args.exe, data / 'X-Wing')
    if args.mode == 'run' and not args.installed:
        shutil.copytree(args.data, data, dirs_exist_ok=True)
    options = ['SPLASHDELAY=0', 'NOREQ']
    if not args.no_preload:
        options.append('PRELOAD')
    if args.mode == 'run':
        options += ['COREDUMP', f'TIMEOUT={args.ticks}']
    if args.whdload_mmu:
        options.append('MMU')
    command = 'WHDLoad X-Wing.slave ' + ' '.join(options)
    print('Command:', command, flush=True)
    (boot / 's/WHDLoad.prefs').write_text('Expert\nReadDelay=0\n')
    (boot / 's/startup-sequence').write_text(
        'DF0:C/Assign C: DF0:C\nDF0:C/Assign LIBS: DF0:Libs\n'
        'DF0:C/Assign DEVS: DH0:devs\nStack 16384\nFailAt 999\n'
        f'CD DH1:\n{command} >DH0:result\n'
        'If WARN\nEcho failed >DH0:failed\nElse\nEcho passed >DH0:passed\nEndIf\n')

    fsuae = os.environ.get('FSUAE_MMU' if mmu else 'FSUAE', 'fs-uae')
    # Data-cache emulation needs the compatible core and, with directory drives, the
    # indirect UAE board (AmigaXDev headless-fsuae.md); otherwise FS-UAE drops it.
    cpu = {'68030': ['--uae_mmu_model=68030'],
           '68040': ['--uae_mmu_model=68040', '--uae_fpu_model=68040'],
           '68060': ['--uae_mmu_model=68060', '--uae_fpu_model=68060']}.get(args.cpu, []) if mmu else []
    if mmu:
        cpu += ['--uae_cpu_24bit_addressing=false', '--uae_cpu_compatible=true', '--uae_cpu_data_cache=true',
                '--uae_uaeboard=full+indirect']
    with (base / 'emulator.log').open('w') as log:
        emu = subprocess.Popen([fsuae, '--amiga_model=A1200', '--cpu=' + args.cpu,
            '--uae_cpu_model=' + args.cpu, *cpu, '--jit_compiler=0',
            '--chip_memory=2048', '--fast_memory=' + str(args.fast),
            *(['--zorro_iii_memory=' + str(args.z3)] if args.z3 else []),
            '--kickstart_file=' + str(KICK31),
            '--hard_drive_0=' + str(boot), '--hard_drive_0_priority=10', '--hard_drive_1=' + str(game),
            '--floppy_drive_0=' + str(WORKBENCH), '--audio_driver=dummy',
            '--joystick_port_0=mouse', '--joystick_port_1=nothing', '--warp_mode=1', '--fullscreen=0',
            '--automatic_input_grab=0', '--window_width=720', '--window_height=568',
            '--base_dir=' + str(base / 'fsuae'), '--state_dir=' + str(base / 'state')],
            stdout=log, stderr=log, env=dict(os.environ, SDL_AUDIODRIVER='dummy'))
        try:
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline and not any((boot / n).exists() for n in ('passed', 'failed')):
                if emu.poll() is not None:
                    raise SystemExit(f'FAIL: FS-UAE exited unexpectedly ({base})')
                time.sleep(.25)
            time.sleep(1)
        finally:
            emu.terminate()
            try:
                emu.wait(timeout=5)
            except subprocess.TimeoutExpired:
                emu.kill()
                emu.wait()

    output = (boot / 'result').read_text(errors='replace') if (boot / 'result').exists() else ''
    fsuae_log = base / 'fsuae/Cache/Logs/fs-uae.log.txt'
    if mmu and 'Data cache emulation' in (fsuae_log.read_text(errors='replace') if fsuae_log.exists() else 'Data cache emulation'):
        raise SystemExit(f'FAIL: FS-UAE did not keep data-cache emulation ({fsuae_log})')
    report = (game / '.whdl_register').read_text(encoding='latin1') if (game / '.whdl_register').exists() else ''
    if not any((boot / n).exists() for n in ('passed', 'failed')):
        raise SystemExit(f'FAIL: WHDLoad did not return within {args.seconds} s ({base})\n{output}')
    if args.mode != 'run':
        if not (boot / 'passed').exists():
            raise SystemExit(f'FAIL: {args.mode} ({base})\n{report[:2000]}{output}')
        if args.mode == 'smoke':
            assert (game / 'smoke-passed').read_bytes() == b'PASS'
        print(f'PASS: {args.mode} slave returned normally')
        shutil.rmtree(base)
        return

    if not report:
        raise SystemExit(f'FAIL: no WHDLoad core dump ({base})\n{output}')
    first = next((l for l in report.splitlines() if l.strip()), '')
    print('WHDLoad:', first.strip())
    chip = (game / '.whdl_memory').read_bytes()
    exp = (game / '.whdl_expmem').read_bytes() if (game / '.whdl_expmem').exists() else b''
    # TIMEOUT reports as "DEBUG caused" once the CIA-A TOD event count passes it.
    event = re.search(r'event=([0-9A-F]+)', report)
    if 'DEBUG caused' not in report or not event or int(event[1], 16) < args.ticks:
        raise SystemExit(f'FAIL: the run did not end by TIMEOUT ({base})\n' + report[:2000])
    if args.cpu in ('68040', '68060') and 'TC=8000' not in report:
        raise SystemExit(f'FAIL: {args.cpu} MMU translation was not enabled (no TC=8000)\n' + report[:2000])
    # CACR alone does not show the policy: with the MMU, WHDLoad enables both
    # caches whatever the slave asks; setcpu= holds the slave's request.
    cacr = int(re.search(r'CACR=([0-9A-F]+)', report)[1], 16)
    setcpu = re.search(r'setcpu=\S+', report)[0]
    ic, dc = (0x8000, 0x80000000) if args.cpu in ('68040', '68060') else (0x1, 0x100)
    print(f'CACR={cacr:X}', setcpu)
    if not cacr & ic or bool(cacr & dc) != dcache or (',DC,' in setcpu) != dcache:
        raise SystemExit(f'FAIL: CACR={cacr:X}: expected the instruction cache'
                         + (' and the data cache' if dcache else ' without the data cache'))
    memory = chip + exp
    image = blocks((args.data / 'XWING.EXE').read_bytes())
    found = sum(1 for b in image if b[::-1] in memory)
    print(f'XWING.EXE in guest RAM: {found} of {len(image)} blocks')
    if args.slave and args.slave.name == 'MemFree.slave':
        print('MemFree low water: Chip {:,} Fast {:,} bytes'.format(
            int.from_bytes(chip[0x100:0x104], 'big'), int.from_bytes(chip[0x104:0x108], 'big')))
    if found < len(image) // 2:
        raise SystemExit(f'FAIL: the game is not resident in guest RAM ({base})')
    print('PASS: game runs under WHDLoad'
          + (f', {args.cpu} MMU' + (' in use' if dcache else ' unused') if mmu else f', {args.cpu}')
          + f', CACR={cacr:X}')
    shutil.rmtree(base)


if __name__ == '__main__':
    main()
