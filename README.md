# X-Wing

Amiga port of LucasArts' X-Wing. The base is the 1993 DOS floppy release 1.0; the
Macintosh demo's 68k code is the intended donor of native routines, following Vette!,
Alone in the Dark, Prince of Persia 2 and Secret Weapons of the Luftwaffe. Only reference
setup exists. The DOS release is installed by its original installer and run unattended
under a scripted DOSBox-X. The Macintosh demo is installed on a fresh System 7.5.5 volume
and run on an emulated 68040 Macintosh (MAME `macqd700`). No analysis or port code exists
yet.

## Inputs

AmigaXDev's `make setup` supplies the shared tools (`~/.local/share/amiga/env.sh`); this
project also needs MAME 0.289, hfsutils, 7zz and DOSBox-X's build dependencies
(`make dos-emulator` builds the patched DOSBox-X). Supply these yourself, read-only, at the
paths below. Git ignores them; `manifest/` pins their SHA-256.

| Path | What |
|---|---|
| `tmp/originals/000110_x-wing.7z` | the DOS floppy release, five 1.44 MB images, 6,868,271 bytes, SHA-256 `c3efc7a4…a60b8c` |
| `tmp/X-Wing-Manual.pdf` | the DOS release's Starfighter Pilot Manual, a 9-page scan holding the copy-protection code-names, SHA-256 `d4596c98…993a61` |
| `tmp/originals/xwingdemo.sea__1.hqx` | the Macintosh demo, 8,805,322 bytes, SHA-256 `1cd9cf7a…dfd0cb` |
| `ref/mame/roms/macqd700/420dbff3.rom` | Quadra 700/900 ROM, 1 MiB, MAME SHA-1 `7a8ee468d16e64f2ad10cb8d1a45e6f07cc9e212` |
| `ref/mame/roms/adbmodem/342s0440-b.bin` | ADB modem ROM, MAME SHA-1 `4a35a44605073ae6076a0292e2056ee4d938d1bd` |
| `ref/mame/dl/755_2GB_drive.zip` | Steve Taylor's System 7.5.5 2 GB drive archive |

## Commands

```sh
make verify-input           # both archives and the manual
make dos-emulator           # build the scripted DOSBox-X
make dos-install            # five images, original INSTALL.EXE; prints INSTALL PASS
make dos-reference          # intro frames, copy protection and its control; prints REFERENCE PASS
make dos-play               # play on a period 386; the copy protection is answered for you
make extract-original-data  # Macintosh demo: both forks and Finder data into tmp/runtime-data
make reference              # fresh volume, configure, restart, launch; prints REFERENCE PASS
```

See [source inventory](docs/source-inventory.md), [DOS reference](docs/dos-reference.md),
[Macintosh reference](docs/mac-reference.md),
[design](docs/design.md), [port plan](docs/port-plan.md), [open work](docs/open-work.md) and [agent rules](AGENTS.md).
