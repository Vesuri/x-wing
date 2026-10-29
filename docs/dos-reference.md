# DOS reference

The DOS floppy release runs under a patched DOSBox-X, driven unattended by a script
that reacts to guest state in emulated time. `make dos-install` runs the original
installer; `make dos-reference` runs the game to three pinned intro frames, through the
copy-protection check to pilot registration, and a wrong-answer control. Success is
`INSTALL PASS` / `REFERENCE PASS` from `tools/dos_reference.py`. Each needs the script's
`DONE` and the pinned hashes; a time limit or emulator exit alone is never success. The
reference stops at the registration screen. No concourse or flight milestone exists yet.

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

`make dos-reference` runs three scenarios (`SCENARIOS` in the tool), each from a new copy
of the verified installation in its own run. Each sets the DOS clock to 1 February 1993
12:00:00 (`date 02-01-1993`, `time 12:00:00`), then runs `C:` / `cd \xwing` / `xwing`.
XWING.EXE must start from its own directory: started as `xwing\xwing` it cannot open
`resource\xwing.lfd` and returns to DOS. Every script ends by requiring mode 13h to still
be set; this fails for the wrong-directory launch, which never reaches `DONE`.

`tools/vga_dump.py` decodes a dump (header, 6-bit DAC, 256 KiB of DOSBox-X's
plane-interleaved video memory) into the visible 320×200 frame. The pinned hash in
`manifest/dos-reference.sha256`, named `<scenario>/<dump>`, covers the frame bytes plus the
8-bit palette. All frames use chain-4 mode 13h at start address 0.

### Intro

`tools/dos/intro.script` presses nothing and dumps VGA state 5, 20 and 40 s after the
first switch to mode 13h. MEASURED contents: the LucasArts logo with "LucasArts
Entertainment Company", the opening crawl's first lines, and the crawl further on.
Without the clock commands, the second frame catches the crawl's first lines at a
different point (rows 165–199 differ); the program evidently times them from a clock
whose phase depends on the start time.

Keys during the intro (MEASURED): Esc opens the Options dialog (music, sound, transitions,
spoken text, Exit to DOS); Space skips to the next scene; Enter skips the whole intro to
the copy-protection dialog.

### Copy protection

After the intro, a "Copy Protection" dialog over the registration room cycles triples of
glyphs with "Press to Continue". A key press freezes one triple and shows "See Manual
Page n" with a text field and OK / Exit to DOS. The answer is the code-name printed under
the same glyphs in a corner of that page ([source inventory](source-inventory.md#manual)).

The triple chosen depends on the DOS clock (MEASURED). With the host clock, runs with the
same script started at different host times got pages 4, 8 and two different frames
again; two runs started in the same host second got the same page. With the clock set,
every run so far has asked the same question.

`tools/dos/security.script` presses Enter 5 s after mode 13h, Enter 20 s later, and dumps
the question 3 s after that: page 16, glyphs matching the left corner's EHAPAH. It types
`EHAPAH` and Enter. 3 s later the dialog is gone and the registration screen shows the
protocol droid and an empty pilot-name field. `tools/dos/security-control.script` is the
same run answering ALTAR, page 16's other code. The tool requires the control's question
frame to equal the security run's and its answered frame to differ. The control's answered
frame equals its question frame: the dialog stays and the field is cleared.

The full reference reproduced the seven pinned hashes in four runs started over nearly
three minutes. Without the clock commands, the intro frames reproduced across six runs
started minutes apart; the commands changed only the title frame's hash.

`make dos-play` opens a DOSBox-X window with sound on a fresh copy of the
installation, using the same machine settings, unthrottled and without a script. It keeps
the host clock, so the copy-protection question varies; answer it from the manual.

Each run keeps `session.log`, `dosbox.log`, `script.log`, `screen.log`, `capture/`, the VGA
dumps and the C: tree in `ref/dosbox/runs/<name>/`. Runs are never reused.
