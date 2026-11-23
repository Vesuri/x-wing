# X-Wing — Amiga

An unofficial Amiga port of the 1993 PC space combat simulator **X-Wing 1.0** by
LucasArts and Totally Games, designed by Lawrence Holland and Edward Kilham. Fly the
Rebel Alliance's starfighters against the Empire: training on the Pilot Proving
Ground, historical missions and the Tour of Duty campaigns.

The port runs the original game code, translated offline from 16-bit x86 to 68020 by
this repository's static translator; there is no x86 emulator. The game runs as the
original's VGA version (320×200, 256 colours) on AGA, set up as on a PC with a Sound
Blaster: its AdLib music and sound effects are resynthesised on Paula, and its digitized
speech plays on Paula.

Current Amiga release: **0.2 (23.11.2026), an early alpha**.

## What to expect from 0.2

0.2 runs the whole game, with speech, but nothing has been optimized yet. It is for people who
want to try the port early and report what they find.

- **Checked against the original:** the port was run on an emulated A1200 with a 68030
  and compared step by step with the PC original under DOSBox-X. At each of these points
  the screen, the memory and every call the game made matched:
  - the start, the logo and the title;
  - pilot registration and the concourse;
  - the Pilot Proving Ground, Historical Combat, the Tour of Duty and the tech room;
  - a training flight, a mission flight and a Tour of Duty battle;
  - the film room and film playback, including a combat film;
  - the exit to DOS.
- **Speed:** not optimized and not yet measured. Expect it to be slow, above all in
  flight. Speed is the next step of the port.
- **Unsupported paths stop the game:** where the game does something the port does not
  support yet, it stops rather than guessing, and the tests do not cover every mission
  or menu choice.
  - Under WHDLoad the requester says "X-Wing stopped".
  - From a Shell, a line starting with `XWING_STOP` appears.
  - Please [report it](https://github.com/Vesuri/x-wing/issues) with that line and
    what you were doing.
- **Saving:** pilots and films are written as on the PC, but saving has not been tested
  under WHDLoad yet. Keep copies of pilots you care about.
- **Testing:** only on an emulated A1200 with a 68030; not yet on real hardware, a
  68040 or 68060, or with WHDLoad's `MMU` option.
- **Memory:** started directly the game runs with 8 MB Fast RAM; under WHDLoad it needs
  more (see below).
- **Speech:** on a 68030 the intro runs slower than on the PC, so some of its spoken
  lines are cut short or overlap.
- **Not yet:** a joystick; Roland and General MIDI music.
- **Copy protection:** the code-name question is skipped. The game continues as if it
  had been answered correctly.

## Requirements and installation

- A PAL or NTSC Amiga with AGA, Kickstart 3.0+ and a 68020 or better; **68030 or better
  recommended**. Installer 43+.
- **2 MB Chip RAM and 8 MB Fast RAM** to start the game directly.
- To start it with WHDLoad instead: WHDLoad 17+, a supported Kickstart 3.1 image with
  its RTB, and **more than 8 MB Fast RAM** (for example 16 MB). The slave reserves 8.5 MB,
  including the Kickstart image.
- The five 1.44 MB PC floppies of **X-Wing 1.0** (LucasArts, 1993), as `disk1.img` to
  `disk5.img`, or as the files `XWING.001` to `.005` with `INSTALL.EXE`, `DETECT.EXE`
  and `READ.ME` from disk 1. Other releases, such as the CD-ROM editions, are not
  supported.

Extract `X-Wing-0.2.lha`, open its **X-Wing Install** drawer and run **Install**. Select
the destination and the drawer with the disks. Every file is checked, and damaged or
other disks are refused. The game is installed as the original installer sets it up for
a Sound Blaster, with digitized speech. Updating keeps pilots and films. 0.1 installed
into an `XWing` drawer, set up for AdLib: installing beside it creates `X-Wing` with the
game files from the disks and copies the pilots and films over.

The installed **X-Wing** drawer has two icons for the same program:

- **X-Wing** starts the game directly: 8 MB Fast RAM, no WHDLoad or Kickstart image.
  Quit from the game's menus.
- **X-Wing (WHDLoad)** starts it with WHDLoad: more memory, but **Help** quits at any
  time and Workbench comes back as it was.

No original game code or data, Kickstart image or WHDLoad binary is distributed. See
[the release ReadMe](release/ReadMe) for the supported ROM file names and the full
instructions.

## Controls

Keyboard and mouse work as in the PC original, with keys at their US keyboard
positions; see the original manual. Quit from the game's menus. Under WHDLoad, the
QuitKey (**Help**) quits immediately, without saving.

## Building

The game uses `m68k-amiga-elf-gcc`, `elf2hunk` and vasm; the WHDLoad slave also needs
the WHDLoad SDK includes. The environment comes from AmigaXDev's `make setup`
(`~/.local/share/amiga/env.sh`).

```sh
make release          # dist/X-Wing-$(cat VERSION).lha, audited; clean tree only
make amiga            # standalone executable: amiga/out/XWing.exe
make help             # every target: references, translator gates, replays, sound
```

From a Shell, the installed game runs in its `data` drawer as `X-Wing`.

The tests compare the port with the original running under a scripted DOSBox-X. They
need the inputs below, which you supply yourself, read-only, at these paths. Git
ignores them, and `manifest/` pins their SHA-256. Building the reference also needs
DOSBox-X's build dependencies (`make dos-emulator`); the postponed Macintosh reference
needs MAME 0.289, hfsutils and 7zz.

| Path | What |
|---|---|
| `tmp/originals/000110_x-wing.7z` | the DOS floppy release, five 1.44 MB images, 6,868,271 bytes, SHA-256 `c3efc7a4…a60b8c` |
| `tmp/X-Wing-Manual.pdf` | the DOS release's Starfighter Pilot Manual, a 9-page scan holding the copy-protection code-names, SHA-256 `d4596c98…993a61` |
| `ref/films/COMBAT.CLP` | the owner's combat film for m17 (`make dos-play`, X-Wing mission 4), 31,327 bytes, SHA-256 `f88e61a1…100125` |
| `tmp/originals/xwingdemo.sea__1.hqx` | the Macintosh demo, 8,805,322 bytes, SHA-256 `1cd9cf7a…dfd0cb` |
| `ref/mame/roms/macqd700/420dbff3.rom` | Quadra 700/900 ROM, 1 MiB, MAME SHA-1 `7a8ee468d16e64f2ad10cb8d1a45e6f07cc9e212` |
| `ref/mame/roms/adbmodem/342s0440-b.bin` | ADB modem ROM, MAME SHA-1 `4a35a44605073ae6076a0292e2056ee4d938d1bd` |
| `ref/mame/dl/755_2GB_drive.zip` | Steve Taylor's System 7.5.5 2 GB drive archive |

How the port works, its gates and what comes next are in the [port plan](docs/port-plan.md),
[design](docs/design.md) and [phases](docs/phases.md). Remaining work is in
[open-work.md](docs/open-work.md), and [AGENTS.md](AGENTS.md) indexes the other docs.

## Credits and licensing

X-Wing and its original assets belong to their respective copyright holders. This is an
unofficial fan port, not affiliated with or endorsed by them. Amiga port by Vesa
Halttunen (Vesuri).

The install helper uses the AmigaXDev installer helpers (LGPL-2.1-or-later; see
[its README](tools/install-data/README.md)). That licence applies to the helper only,
not to the original game.
