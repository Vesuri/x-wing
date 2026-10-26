# X-Wing

Macintosh-to-Amiga port of the LucasArts X-Wing demo, following Vette!, Alone in the
Dark and Prince of Persia 2. Only the initial setup exists: the original demo is
extracted, installed on a fresh System 7.5.5 volume and run unattended on an emulated
68040 Macintosh (MAME `macqd700`). No analysis or port code exists yet.

## Inputs

AmigaXDev's `make setup` supplies the shared tools (`~/.local/share/amiga/env.sh`); this
project also needs MAME 0.289 and hfsutils. Supply these yourself, read-only, at the
paths below. Git ignores them; `manifest/` pins their SHA-256.

| Path | What |
|---|---|
| `tmp/originals/xwingdemo.sea__1.hqx` | the demo, 8,805,322 bytes, SHA-256 `1cd9cf7a…dfd0cb` |
| `ref/mame/roms/macqd700/420dbff3.rom` | Quadra 700/900 ROM, 1 MiB, MAME SHA-1 `7a8ee468d16e64f2ad10cb8d1a45e6f07cc9e212` |
| `ref/mame/roms/adbmodem/342s0440-b.bin` | ADB modem ROM, MAME SHA-1 `4a35a44605073ae6076a0292e2056ee4d938d1bd` |
| `ref/mame/dl/755_2GB_drive.zip` | Steve Taylor's System 7.5.5 2 GB drive archive |

## Commands

```sh
make verify-input           # the demo archive
make extract-original-data  # both forks and Finder data into tmp/runtime-data
make reference              # fresh volume, configure, restart, launch; prints REFERENCE PASS
```

See [source inventory](docs/source-inventory.md), [Macintosh reference](docs/mac-reference.md),
[design](docs/design.md), [open work](docs/open-work.md) and [agent rules](AGENTS.md).
