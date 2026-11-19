# Release

The Amiga release ships no game data. The user installs it from their own X-Wing DOS 1.0
floppies with `XWingInstallData` (`tools/install-data`). The installer writes the same
284 files the original `INSTALL.EXE` installs and configures for AdLib under DOSBox-X
(`docs/dos-reference.md`).

## Pipeline

The pipeline is copied from Secret Weapons of the Luftwaffe (`manifest/references.tsv`) and
adapted. Its `docs/release.md` holds the converged rules and where each comes from. The slave
is described in [whdload.md](whdload.md).

- **Version:**
  - `VERSION` holds `0.1`.
  - The literal version and date 19.11.2026 appear in the game's `$VER`
    (`src/platform/amiga/version.s`), in the slave's `slv_info` and `$VER`, in the helper's
    `$VER` (`tools/install-data/install_config.h`), in `Install`'s `$VER` and in the ReadMe's
    History.
  - Nothing is stamped at build time, so `tools/check_release.py` asserts all of them.
- **Release image:**
  - `make amiga-release` builds `build/amiga-release` with `RELEASE=1`. The `XWING_RELEASE`
    build takes no diagnostic arguments or tool types, and has no listing.
  - It is stripped with `elf2hunk -s` to `amiga/out/XWing-release.exe`, and its RELOC32
    blocks are split (`tools/hunk_relocs.py`).
  - `hunk_relocs.py --release-of` checks that no symbol or debug hunk remains, and that every
    other record, header included, equals the unstripped `build/amiga-release/out/XWing.exe`.
  - `make release-repro` makes a second clean build in its own directory and `cmp`s the
    stripped images.
- **Package:**
  - `tools/package_release.py` takes an explicit allowlist: `XWing`, `XWing.slave`,
    `XWing.inf`, `XWingInstallData`, `Install`, `Install.info`, `ReadMe`, `ReadMe.info` and
    `LICENSE.LGPL.txt`, under `XWing Install/` with the drawer icon.
  - It packs them with AmigaXDev's `amigaxdev.release`: LH5, level-0 headers, sorted
    members and the DOS stamp of 19.11.2026. `tools/_amigaxdev.py` checks the module against
    `manifest/mac-helpers.sha256`.
  - It refuses any member whose SHA-256 is an original's: the five volumes in
    `release/originals.sha256`, and every manifest that pins original material.
  - It refuses to overwrite an archive.
- **Audit:** `tools/check_release.py`:
  - decodes every member with Lhasa, and checks the CRCs, the exact member set and identity
    with the build outputs;
  - checks the HUNK and icon magics and the version strings;
  - checks the ReadMe's sections, including its early-alpha notice;
  - checks the slave header: flags, 2 MiB Chip, 8.5 MiB ExpMem and Help;
  - refuses original file names;
  - scans every member for any 64-byte block, forward or byte-reversed, of the 284 files of
    the configured DOS install and of the five floppy images: 568,966 blocks.
  - Sabotage: a block of `FLIGHT.OVL` planted in the image is caught in either direction.
- **Installer:**
  - `release/Install` is the Installer 43 script, with SWOTL's flow: ReadMe first, the
    WHDLoad and Kickstart checks, `WHDLInstPath`, Remove/Keep and Use existing/Replace.
  - The helper unpacks into `InstallStaging`, and its output is copied into `data/` only
    after it succeeds.
  - `tools/test_release_installer.py` drives real Installer 43 in FS-UAE on a 68020, with
    the Amiga helper. Modes:
    - `fresh`: images;
    - `files`: `XWING.001`–`005` with disk 1's files;
    - `keep` and `replace`: pilots survive;
    - `remove`;
    - `bad-disks`: a refused source leaves the install unchanged.
  - The installed tree must equal the configured DOS install.
- **Make:**
  - `make release` refuses a tree with uncommitted changes. It builds the release image,
    the slaves and the helper, then packages and audits `dist/XWing-$(cat VERSION).lha`.
  - `make release-check` audits that archive again.

### 0.1 early alpha

Released ahead of P8 with a reduced gate (`docs/design.md`, "Early alpha 0.1"):

- the archive allowlist and the original-bytes scan;
- matching version strings;
- a reproducible stripped image;
- the WHDLoad slave and the start without WHDLoad, both run on the 68030;
- an installer test;
- a ReadMe that says the port is an unoptimized early alpha.

The rest of gate 8 stays open (`docs/port-plan.md`, P9).

## Original data

The floppies' files are pinned in `manifest/dos-disks.sha256` and their tree in
`manifest/dos-installed.sha256`. All sizes and offsets below are MEASURED on those disks,
and the decoders are checked by `tools/install-data/test_install.py`.

- **Volumes:** `XWING.001`..`005` on disks 1..5, with sizes:

  | Volume | Size (bytes) |
  |---|---|
  | `XWING.001` | 1,270,992 |
  | `XWING.002`..`004` | 1,457,152 each |
  | `XWING.005` | 1,176,599 |

  - The archive data is `XWING.001` up to offset 1,256,066, then the other volumes
    whole. A file's data may run on into the next volume.
  - At offset 1,256,066 of `XWING.001` is the catalog: `05 '[PVM]'`, then 279 records of
    47 bytes.
- **Catalog record:**

  | Offset | Field |
  |---|---|
  | +0 | 1Ah |
  | +1 | LE32 offset in the volume of +30 |
  | +5 | method: C8h stored, D0h tree-coded LZ (254 files), E0h LZW (18 files) |
  | +6 | name (13 bytes, NUL-padded) |
  | +19 | DOS attributes |
  | +20 | LE32 stored size |
  | +24 | DOS date, then time |
  | +28 | a 16-bit value, not used |
  | +30 | disk |
  | +33 | LE32 size |
  | +43 | directory: 1 the game directory, 2 `RESOURCE`, 3 `MISSION`, 4 `CP` |

- **Files outside the archive:** disk 1's `INSTALL.EXE`, `DETECT.EXE` and `READ.ME` are
  copied as they are. Configuring for AdLib writes:
  - `LANDRU.CFG`: `adlib`, `FAST`, `ems` and `diff`, CR LF each;
  - `OPTIONS.CFG`, a copy of `FASTYES.CFG`.
- **Bits:** both compressed methods read bits least significant first.
- **Method D0h:**
  - **Tree:** N (LE16, at most 275h) and W (a byte), then N tree entries of W bits. An
    entry below N is a node base; any other entry is a leaf with symbol entry−N.
  - **Symbols:** decoding starts at node N−2 and takes `node = tree[node + bit]` until it
    reaches a leaf. Symbols below 256 are literals, 256 is the end, and anything larger
    is a match of symbol−254 bytes.
  - **Match position:** a high part from a fixed 64-value prefix code, with LZHUF's
    lengths (1×3, 3×4, 8×5, 12×6, 24×7 and 16×8 bits). The code's value order is the
    original installer's own (`docs/design.md`, "Installer's position code").
    - The low bits follow: 7 once the output count + 3Ch reaches 2000h, else
      bit_length((count + 3Ch) >> 5) − 1, and 0 when that shift gives 1 or less.
    - The distance is (high << low bits | low) + 1, in an 8 KiB window that starts as
      spaces.
- **Method E0h (read from INSTALL.EXE's decoder in memory, checked on the 18 files):**
  - **Codes:** LZW over the entries 1..1EFFh. Codes start 1 bit wide and widen when the
    next entry reaches 2^width.
  - **Flag bit:** each code is preceded by a bit, where 0 means an 8-bit literal follows.
  - **End and new entries:** entry 0 ends the stream. Each symbol after the first adds
    the previous symbol plus its own first byte.
  - **Runs:** the output is run-length coded. 90h n repeats the previous byte n−1 more
    times, and 90h 0 is 90h itself.
  - **Not reached:** the original also drops the flag bit once 375 of the last 500
    symbols were entries, and reuses aged entries when the table is full. None of the 18
    files reaches either, so `xwunpack.c` refuses both.
