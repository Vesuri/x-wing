# Macintosh reference

`make reference` builds a fresh volume and runs the original demo under headless MAME
0.289 until it has been the frontmost application for 12 checks, 600 frames apart. Success
is `REFERENCE PASS` from `tools/run_reference.py`, which requires the script's
`REFERENCE_RUNNING X-Wing` and no failure; a normal emulator exit alone is not success. No
game state is checked yet: this is a launch reference, not a milestone.

## Configuration

MEASURED: MAME `macqd700` (Quadra 700, 68040), 8 MB, built-in DAFB video at 640×480,
System 7.5.5 from Steve Taylor's 2 GB drive archive, Virtual Memory off. With 20 MB or 36 MB
the emulated machine loops in ROM (PC around `$4084BBF4`) before RAM is set up; 4 MB and
8 MB boot. 8 MB leaves enough for the demo's 4,500K partition.

`tools/prepare_reference.py` verifies every pinned input, makes a sparse copy of the
System disk in a new `ref/mame/runs/<name>/` and installs the folder on its desktop with
`tools/install_reference_volume.py`. That installer writes each file as MacBinary with
`hcopy -m` and reads it back to compare both forks and the Finder fields. It accepts one
normalization: `hcopy` clears Finder's initialized bit. Existing runs and game folders
are refused, never overwritten.

`tools/mac_reference.lua` drives the original System through `tools/mame_mac_input.lua`
(Prince of Persia 2's helper) and changes nothing in memory:

1. First boot, 24-bit addressing (`$CB2` = 0): Apple menu → Control Panels; Memory →
   32-Bit Addressing On; Monitors → Colors, 256; the main GDevice must then be 8-bit.
   Close both windows, Special → Restart.
2. Second boot: `$CB2` ≠ 0 and the main GDevice is 8-bit.
3. On the desktop, type-select `X` and ⌘O open the folder, then type-select `X-Wing` and
   ⌘O. `CurApName` must become `X-Wing` and stay so at each check.

Without step 1 the demo shows "X-Wing needs to run in 32-bit addressing mode" and stops.
With it, the demo shows its concourse main-menu screen in 256 colours (MEASURED from the
run's snapshots). The coordinates were read from snapshots of this exact disk and display.

Each run keeps `session.log`, `snap/macqd700/*.png` (MAME screen snapshots, one per
`SNAPSHOT` line), the disk, PRAM (`nvram/macqd700/`), cfg and `mame.pid`. Runs are never
reused. The launcher waits up to 900 s on the host and stops only its recorded MAME pid
through the shared `fsuae_kill_recorded`.
