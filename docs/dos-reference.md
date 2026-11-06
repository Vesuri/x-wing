# DOS reference

The original DOS floppy release is the ground truth. It runs under a patched DOSBox-X:
- **Install and configure:** the original installer, driven by a script that reacts to the
  text screen in emulated time.
- **Reference runs:** headless and instrumented. The tracer of Secret Weapons of the
  Luftwaffe (SWOTL) is adapted. Input fires at guest code visits, and the guest state is
  snapshotted at named code addresses.

Success is a named PASS line. A time limit or an emulator exit is never success.

## Emulator

DOSBox-X tag `dosbox-x-v2026.08.31` (`4f19017c`) is built by `make dos-emulator`
(`tools/build_dosbox_x.sh`). The tree lives in `~/.local/src/xwing-dosbox-x`
(`XWING_DOSBOX_X_SRC`). `tools/patches/ORDER` applies, in order:
- **SWOTL's 12 patches** (`dosbox-x-xwing-{trace,mouse,sound,time-limit,read-data,date,`
  `host-clock,release-visits,key-chords,rep-chunks,joystick,irq0-backlog}.patch`), copied
  at the SWOTL commit pinned in `manifest/references.tsv`. Only `SWOTL`/`swotl` is
  renamed to `XWING`/`xwing`.
- **`dosbox-x-xwing-game.patch`:** X-Wing's changes:
  - `XWING.EXE`'s entry and size;
  - no PLINK probe;
  - the 1993-02-01 DOS date and host file clock;
  - music drivers loaded by INT 21h AX=4B03 mapped as modules;
  - the event log written through gzip;
  - overlay manager events, `ovl_thunk` and `ovl_call` ([overlay manager](overlay-manager.md));
  - code writes logged with their target module and offset at the time of the write.
- **`dosbox-x-xwing-script.patch`:** the text-screen script used for the installer and for
  play.
- **`dosbox-x-xwing-retrace.patch`:** `XWING_RETRACE=1` logs every read of the VGA input
  status port 3DAh by module code to `retrace.csv`, as runs of one value per service-event
  interval; the host run answers its own reads from them.

A second build of the same tag serves as an oracle and is never used for reference runs:
`make dos-oracle` (`tools/build_dosbox_x_debug.sh`) builds it unpatched with
`--enable-debug=heavy` in `~/.local/src/xwing-dosbox-x-debug`
(`XWING_DOSBOX_X_DEBUG_SRC`), a worktree of the reference tree.
`tests/dosbox_retf.py` single-steps it for the `retf` cases where Unicorn deviates
([x86 notes](x86-notes.md#unicorn-x86-16-as-oracle)).

`tools/dosbox_x.py` checks the tree before every run:
- HEAD is the pinned tag;
- every file the series touches equals the series applied to the tag, built in a scratch
  index;
- no other tracked file has changed;
- the binary is newer than every patched file.

The script (`src/misc/xwing_script.cpp`) is ticked once per emulated millisecond. Its
steps:
- **Waits:** `text`/`notext` (the 80×25 screen), `mode` (BIOS byte `0040:0049`) and
  `delay`.
- **Actions:** `key` (50 ms press, 100 ms gap), `swap n` (floppy image n in A:), `shot`,
  `vga file` and `done`.

Each run logs every step's start and end in emulated ms in `script.log`, and the text
screen every 250 ms when it changes in `screen.log`.

Install machine (`MACHINE` in `tools/dos_reference.py`):
- 386 at a fixed 30,000 cycles/ms, normal core, 16 MB;
- DOSBox-X's default Sound Blaster 16, muted;
- `turbo` removes only the real-time throttle.

Stock DOSBox-X's `autotype` sleeps in host wall time, and keys were lost or arrived early.
Stock DOSBox-X also ignores SIGTERM. A host deadline therefore stops only the recorded pid,
through the shared `fsuae_kill_recorded`.

## Install and configure

`make dos-disks` verifies the 7z and extracts the five images to `tmp/dos/disks`, pinned
in `manifest/dos-disks.sha256`. `make dos-install` mounts all five on A: and runs
`A:\INSTALL.EXE` with `tools/dos/install.script`:
1. Main menu: Enter on "Install X-Wing From Floppy Disks". MEASURED: DOS 5.00, machine
   speed FAST, VGA, SoundBlaster, 607K main memory, EMS 4.00 with 14,912K, of which X-Wing
   uses 896K.
2. Drive list: Enter on C:.
3. Directory: Enter on the default `C:\XWING`.
4. For disks 2–5: swap the image, wait 1 s, Enter.
5. Wait until "Installing files" disappears and the main menu returns.

The 282 files of `C:\XWING` are pinned in `manifest/dos-installed.sha256` and kept in
`tmp/dos/installed/XWING`. A differing tree moves to `.replaced/`. Installing writes no
configuration.

Without a configuration, the game finds no `LANDRU.CFG`, loads no music driver and plays
no sound (MEASURED). `make dos-configure` runs `C:\XWING\INSTALL.EXE` on the AdLib-only
reference machine with `tools/dos/configure.script`:
1. "Set Sound Board Configuration".
2. "AdLib and compatibles". The installer had already detected AdLib.
3. Exit, declining the READ.ME.

Leaving the installer writes `LANDRU.CFG` (`adlib`, `FAST`, `ems`, `diff`) and
`OPTIONS.CFG`, pinned in `manifest/dos-configured.sha256`. The tree is kept in
`tmp/dos/configured/XWING`.

## Reference runs

`tools/pc_run.py NAME [options]` (`make dos-run RUN=NAME ARGS=...`) does one run:
- **Directory:** `ref/dosbox/runs/NAME`, which must be new.
- **Game:** a fresh copy of the configured installation, started as `C:` / `cd \xwing` /
  `xwing`. `XWING.EXE` must start from its own directory: started as `xwing\xwing` it
  cannot open `resource\xwing.lfd` and returns to DOS.
- **Machine:** `reference/dosbox-x.conf`. It is the install machine with no Sound Blaster
  and an OPL2 at 388h, so the game selects `ADLIB.IMS`.
- **Exit status:**
  - 0: the `--exit-after` snapshot was reached;
  - 2: time limit;
  - 3: guest fault (INT 0 or 6);
  - 4: emulator failure or host deadline.

The tracer arms at `XWING.EXE`'s first instruction (`PSP+10h+0406h:05AAh`; load segment
0822h in every run). On arming it sets:
- the BIOS tick count to `--bios-ticks` (default 0);
- the DOS date to 1993-02-01.

DOS time and INT 1Ah derive from those, so no host time reaches the game. The host file
clock is pinned to 1993-02-01 12:00 (`XWING_FIXED_FILE_CLOCK`).

Addresses are `(module, offset)`:
- the root: offset in `XWING.EXE`'s load image;
- an overlay: offset in its `.OVL` file, from the DOS read that put the bytes there;
- a music driver: offset in its load image. The game loads it with INT 21h AX=4B03, which
  DOSBox-X reads itself, so the tracer maps the driver's image at that call;
- `-`: an unowned linear address (BIOS, DOS, DOSBox-X callbacks).

Options are SWOTL's:
- `--keys MODULE+HEX[#N]=key,...` presses a key when the guest reaches that instruction for
  the Nth time since the previous key's release, and releases it after `--key-hold`
  instructions (default 600,000).
- Mouse actions take effect at once:
  - `mx±N`/`my±N` move the mouse by N mickeys. In mode 13h, horizontal mickeys count
    double (MEASURED: `mx-40` moves the pointer 20 pixels, `my-40` about 40).
  - `mb0`–`mb7` set the button mask.
- `--snapshots name@MODULE+HEX[#N],...` are counted after the key script, each after the
  previous. Each writes `snap-<name>/`:
  - `ram.bin`: 1 MiB, with the EMS frame read through its mapped pages;
  - `vram.bin` and `dac.bin`;
  - `regs.txt`;
  - `residency.csv`;
  - `writes.csv`: the last CPU writer of every module-owned byte since its load.
- `--services` logs every software interrupt raised by module code, with all registers
  and FLAGS at entry (`svc`) and again at its return (`svc_ret`).
- `--opl` logs every AdLib register write. `--probes` and `--polls` are as in SWOTL;
  `--retrace` writes `retrace.csv` and `--rep-chunks` the REP slices (`rep.csv`: where
  DOSBox-X restarts a REP at the end of its cycle slice). `tools/reference.py --polls`
  adds both: the host references (`m00-entry`, `m01-logo`) are re-recorded whenever
  generation changes the poll points.

Outputs in `trace/`:
- `events.csv.gz`: opens, reads, seeks, closes, `exec_overlay`, keys, snapshots, faults and
  the service log. The mouse is polled about 200,000 times per emulated second in the
  frontend, so the log reaches about 170 MB of gzip per emulated minute.
- `reads.bin`: the bytes of every DOS read.
- `modules.csv`, `executed-<module>.bin`, `edges.csv`.
- `interrupts.csv`, `ports.csv`, `vga.csv`;
- `code-writes.csv`: CPU writes into paragraphs that have executed, with the target's module
  and offset when written.
- `residency.csv`, `summary.txt`.

`tools/trace_summary.py` summarises a trace and `tools/snap_png.py` renders a snapshot's
chain-4 frame.

## Loader model and image proof

`tools/xwing_model.py` models the files (MEASURED):
- **Root:** the MZ load image at the load segment, plus 1,152 relocations.
- **Overlay segment table:** 26 records of nine words at root image offset 4A5Fh (ids
  2–27: 20 segments for `FRONTEND.OVL`, 6 for `FLIGHT.OVL`). Each record holds the link
  segment, file position and size in paragraphs, fixup count and parent.
- **Segment layout in the `.OVL`:** a segment is its fixup table (offset and link segment
  per entry) followed by its code at the next paragraph.
- **Segment placement:**
  - A file's base segment loads at link segment 5BAh. FRONTEND's base is 183,184 bytes
    with 1,696 fixups; FLIGHT's is 185,440 bytes with 1,212 fixups.
  - The other segments share an area at 3273h (FRONTEND) or 3300h/359Ah (FLIGHT) and are
    read on demand.
- **Relocation:** loading adds the load segment to every fixup word. For the root's
  relocations and the overlay fixups this is SWOTL's PLINK rule. For a music driver the
  value added is its relocation segment.

`tools/load_image.py SNAPSHOT` (gate 1) rebuilds every resident row from the files and the
model. Every byte must:
- equal the model;
- or have a CPU writer since its load;
- or be the byte the last DOS read put there.

Bytes of a row past the end of a module's file or image count as "beyond".

## Milestones

`make dos-reference` (`tools/reference.py`) runs `reference/milestones.csv`, one traced
run with `--services` per milestone, six at a time. A milestone's keys are those of its
`after` milestone followed by its own. Input sites:
- `menu`: `FRONTEND.OVL+1808E`, the frontend's mouse poll (INT 33h AX=3). It runs in busy
  loops, about 200,000 times per emulated second.
- `frame`: `FLIGHT.OVL+1B7D2`, the flight's once-per-frame mouse poll.

Checks for each milestone:
- every snapshot is reached;
- the listed modules are resident and the BIOS mode is as listed;
- consecutive snapshots differ in RAM and VRAM;
- every snapshot passes the image proof;
- the frame relation holds;
- there is an `svc` for every software interrupt and a `svc_ret` for all but those still
  pending;
- RAM, VRAM (graphics modes only) and DAC equal their pins in `manifest/milestones.sha256`,
  as do the listed files.

The pins were taken in one invocation and every milestone reproduced them in a second; the
entry milestone's VRAM differed until text-mode VRAM was excluded. Instruction counts at a
milestone can differ slightly between runs with equal pins, so they are reported only.

| Milestone | Input after `after` | Signal |
|---|---|---|
| m00-entry | none | `XWING.EXE+460A`, the MZ entry |
| m01-logo | none | LucasArts logo, `menu` #600,000 and 100,000 later |
| m02-title | none | Star Wars title, `menu` #2,000,000 and 100,000 later |
| m03-question | Enter (skips the intro), Enter (freezes the glyphs) | "See Manual Page 11" |
| m03c-wrong-answer | MASSASSI, Enter | The dialog stays and the field is cleared: the frame equals m03-question outside the text field |
| m03p-protection-passed | BRIGGIA, Enter | The protection screen's return (`FRONTEND.OVL+79843`, 3273:0B03): the bypass oracle's reference |
| m03q-protection-passed-late | none after: Enter (skips the intro), Enter later (`menu` #2,600,000: page 6), ITHOR typed slower, Enter | The same return after another question answered later: its bytes that differ from m03p's depend on the screen's timing |
| m04-registration | BRIGGIA, Enter | Registration desk; the frame differs from m03-question |
| m05-pilot-named | LUKE, Enter | Pilot record shown |
| m06-concourse-pilot-saved | Pointer to the left door ("Enter Spaceport"), click | Concourse; `LUKE.PLT` is written on leaving the desk and pinned |
| m07-proving-ground | Left, Enter | Proving Ground, X-Wing Level One |
| m08-historical-combat | Right ×4, Enter | Historical Combat, X-Wing Mission 1 |
| m09-tour-of-duty | Right, Enter | Tour of Duty, Tour I |
| m10-film-room | Down, Right, Enter | Film room, "Load Mission Film" |
| m11-tech-room | Down, Enter | Tech room |
| m12-training-flight | Left, Right ("Enter Maze"), Enter | Maze flight, `frame` #300 and 50 later |
| m13-mission-flight | (Left, Right, Enter) ×3: briefing, flight deck, launch | X-Wing Mission 1 flight, `frame` #300 and 100 later |
| m14-tour-battle | Right ("Enter Tour of Duty"), Enter (skips the crawl), (Left, Right, Enter) ×2 | Tour I mission 1, "Destroy Imperial Convoy", `frame` #2,500 and 100 later |
| m16-exit-to-dos | Esc, pointer to "Exit to DOS", click | `XWING.EXE+1660`, INT 21h AX=4C03, after mode 3 at `+11F1` |

In the concourse, ready rooms, briefing and flight deck, the arrow keys move the pointer
between hotspots and Enter selects. "Left, Right" lands on the door that proceeds.

### Copy protection

After the intro, a "Copy Protection" dialog cycles triples of glyphs. A key press freezes
one triple and shows "See Manual Page n". The answer is the code-name printed under the
same glyphs in a corner of that page ([source inventory](source-inventory.md#manual)). The
question depends on the clock and on when the key arrives:
- Under the pinned BIOS tick count and the `menu` key triggers, every run asks page 11. Its
  left corner matches (BRIGGIA); MASSASSI, the right corner, is the control.
- With the host clock, runs started at different host times got pages 4, 8 and two other
  frames; two runs started in the same host second got the same page (MEASURED).
- At 8,000 cycles/ms with DOS clock 1993-02-01 12:00, the question is page 16's right code,
  ALTAR (used by `make dos-play`).

### Not yet reached

- **Film-room replay.** Pressing C in flight turns the camera on: `INPUT.SPL` is appended
  every few seconds, and `START.RPY`, `SAVEGAME.RPY` and `RPYBUFF.TMP` appear. A film needs
  a flight that ends, and none has yet:
  - Esc opens "Inflight Options" (two pages: options and detail) with only "Return to
    Simulator" and "Exit to DOS".
  - Alt-E, Alt-Q, Ctrl-E and Ctrl-Q do not return to the frontend.
  - Left alone, the maze flight stops executing instructions after frame 23,367, about
    18.2 billion instructions (about 607 emulated seconds) into the game, in two runs.
- **A Star Destroyer battle.** A new pilot can open only the first mission of each
  Historical Combat craft and of Tour I. None of them holds a Star Destroyer. Instructions
  per frame over 50–100 frames after the first snapshot (MEASURED): maze about 644,000,
  X-Wing mission 1 about 506,000, Tour I mission 1 about 499,000. Whether the flight paces
  its frames is not known:
  - it never reads the retrace status (3DAh) or the timer ports;
  - `ADLIB.IMS` sets PIT channel 0 to divisor 1000h (about 291 Hz) and hooks INT 8, which
    chains to the BIOS at 18.2 Hz.
  A run at another CPU speed would settle it. Runs at 15,000 and 60,000 cycles/ms did not
  reach the flight, even with the menu key counts scaled by the speed. The key triggers
  count visits, and the visit counts do not transfer across speeds.

## Play

`make dos-play` opens a DOSBox-X window with sound on a fresh copy of the unconfigured
installation, unthrottled, as a 1993 386DX-class machine (`PLAY_MACHINE`): 8,000
cycles/ms, 4 MB and a Sound Blaster Pro 2. It:
1. sets the DOS clock to 1993-02-01 12:00:00;
2. runs `tools/dos/play.script`, which skips the intro and answers ALTAR about 30 s after
   start;
3. leaves the keyboard and mouse to the player.

Input before then can change the question. Without `LANDRU.CFG` this installation is
silent.
