# DOS reference

The DOS floppy release runs under a patched DOSBox-X, driven unattended by a script
that reacts to guest state in emulated time. `make dos-install` runs the original
installer; `make dos-reference` runs the game to three pinned intro frames. Success is
`INSTALL PASS` / `REFERENCE PASS` from `tools/dos_reference.py`. Each needs the script's
`DONE` and the pinned hashes; a time limit or emulator exit alone is never success. The
reference stops in the opening crawl. No menu or flight milestone exists yet.

## Emulator

DOSBox-X tag `dosbox-x-v2026.08.31` (`4f19017c`) with `tools/patches/` applied, built by
`make dos-emulator` (`tools/build_dosbox_x.sh`, adapted from Secret Weapons of the
Luftwaffe) in `~/.local/src/xwing-dosbox-x` (`XWING_DOSBOX_X_SRC`). Before each run the
tool checks the tree's HEAD, that every patch is applied (`git apply -R --check`), and
that the binary is newer than the patched sources.

The patch (`dosbox-x-xwing-script.patch`) adds `src/misc/xwing_script.cpp`, ticked once
per emulated millisecond from `TIMER_AddTick` (`pic.cpp`) after the `-time-limit` check. The step
language is documented at the top of that file:

- Waits: `text`/`notext` (the 80×25 screen at `B800:0000`), `mode` (BIOS byte
  `0040:0049`) and `delay`.
- Actions: `key` (50 ms press, 100 ms gap), `swap n` (DOSBox-X's own `IMGSWAP` path,
  `swapInDrive(0, n)`), `shot`, `vga file` and `done`.

`script.log` records each step's start and end in emulated ms. `screen.log` records the
text screen every 250 ms when it changes.

Machine (MEASURED, `MACHINE` in the tool): 386 at a fixed 30,000 cycles/ms, normal core,
16 MB, DOSBox-X's default Sound Blaster 16 at 220h, IRQ 7, DMA 1, sound muted for headless runs. Turbo
removes only the real-time throttle. With it, the whole install takes about 32 s on the
host and the intro frames hash identically to unthrottled runs.

Stock DOSBox-X `autotype` sleeps in host wall time (a `,` sleeps twice the pace), and the
installer's timing drifts by seconds between runs. Keys were lost or arrived early, and one
early Enter made the installer exit. Stock DOSBox-X also ignores SIGTERM, and its quit
confirmation dialog appears on the desktop even under `SDL_VIDEODRIVER=dummy`. Runs
therefore set `quit warning=false`, and a host deadline stops only the recorded pid
through the shared `fsuae_kill_recorded`.

## Install

`make dos-disks` verifies the 7z and extracts the five images to `tmp/dos/disks`, pinned
in `manifest/dos-disks.sha256`. `make dos-install` mounts all five as one swap list on
A: (`imgmount -t floppy`) and runs `A:\INSTALL.EXE` with `tools/dos/install.script`:

1. Main menu (MEASURED: DOS 5.00, machine speed FAST, VGA, SoundBlaster, 607K main
   memory, EMS 4.00 with 14,912K, of which X-Wing uses 896K): Enter on "Install X-Wing
   From Floppy Disks".
2. Drive list (it replaces "One moment, please…" while drives are scanned): Enter on C:.
3. Directory: Enter on the default `C:\XWING`.
4. "Please insert the X-Wing Disk n disk into drive A." for n = 2–5: swap to image n,
   wait 1 s, Enter.
5. "Installing files" disappears and the main menu returns.

The emulated install finishes at 348,603 ms. The installer writes no configuration file;
the machine speed and sound card it shows are only detected. It also leaves a temporary
`C:\ISFYZQVO.TWJ\SWAPFILE.HDR`, which is not part of the installation. The 282 files of
`C:\XWING` are pinned in `manifest/dos-installed.sha256`. One unthrottled run and two
turbo runs produced identical trees. The verified tree is kept in
`tmp/dos/installed/XWING`; a differing one moves to `.replaced/`.

## Game

`make dos-reference` copies the verified installation into a new run, then runs
`C:` / `cd \xwing` / `xwing` with `tools/dos/intro.script`. XWING.EXE must start from its
own directory: started as `xwing\xwing` it cannot open `resource\xwing.lfd` and returns
to DOS. The script dumps VGA state 5, 20 and 40 s after the first switch to mode 13h. It
then requires mode 13h to still be set; this fails for the wrong-directory launch, which
never reaches `DONE`.

`tools/vga_dump.py` decodes a dump (header, 6-bit DAC, 256 KiB of DOSBox-X's
plane-interleaved video memory) into the visible 320×200 frame. The pinned hash in
`manifest/dos-reference.sha256` covers the frame bytes plus the 8-bit palette. MEASURED
contents: the LucasArts logo with "LucasArts Entertainment Company", the opening crawl's
first lines, and the crawl further on. The display uses chain-4 mode 13h at start address
0. The three hashes reproduced across six runs, unthrottled and turbo, including runs
started minutes apart.
The DOS date still comes from the host clock; no later milestone tests whether it
matters.

`make dos-play` opens a DOSBox-X window with sound on a fresh copy of the
installation, using the same machine settings, unthrottled and without a script.

Each run keeps `session.log`, `dosbox.log`, `script.log`, `screen.log`, `capture/`, the VGA
dumps and the C: tree in `ref/dosbox/runs/<name>/`. Runs are never reused.
