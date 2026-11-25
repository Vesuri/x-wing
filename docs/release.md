# Release

The Amiga release ships no game data. The user installs it from their own X-Wing DOS 1.0
floppies with `X-WingInstallData` (`tools/install-data`). The installer writes the same
284 files the original `INSTALL.EXE` installs and configures for the Sound Blaster under
DOSBox-X (its "SoundBlaster" entry: `LANDRU.CFG` with `adlib_w`, `OPTIONS.CFG` a copy of
`FASTNO.CFG`; MEASURED: `manifest/dos-configured-sb.sha256`,
`docs/dos-reference.md`).

## Pipeline

The pipeline is copied from Secret Weapons of the Luftwaffe (`manifest/references.tsv`) and
adapted. Its `docs/release.md` holds the converged rules and where each comes from. The slave
is described in [whdload.md](whdload.md).

- **Version:**
  - `VERSION` holds `0.3`.
  - The literal version and date 25.11.2026 appear in the game's `$VER`
    (`src/platform/amiga/version.s`), in the slave's `slv_info` and `$VER`, in the helper's
    `$VER` (`tools/install-data/install_config.h`), in `Install`'s `$VER` and in the ReadMe's
    History.
  - Nothing is stamped at build time, so `tools/check_release.py` asserts all of them.
- **Release image:**
  - `make amiga-release` builds `build/amiga-release` with `RELEASE=1`. The `XWING_RELEASE`
    build takes no diagnostic arguments or tool types, and has no listing.
  - Since 0.2 it is the Sound Blaster build (`RELEASE_DRIVER`, `XWING_DRIVER=ADLIB_W.IMS`:
    speech, P10); `build/gen` is regenerated for that driver when it holds the other.
  - It is stripped with `elf2hunk -s` to `amiga/out/XWing-release.exe`, and its RELOC32
    blocks are split (`tools/hunk_relocs.py`).
  - `hunk_relocs.py --release-of` checks that no symbol or debug hunk remains, and that every
    other record, header included, equals the unstripped `build/amiga-release/out/XWing.exe`.
  - `make release-repro` makes a second clean build in its own directory and `cmp`s the
    stripped images.
- **Package:**
  - `tools/package_release.py` takes an explicit allowlist: `X-Wing` (the stripped image),
    `X-Wing.slave`, `X-Wing.inf`, `X-WingInstallData`, `Install`, `Install.info`, `ReadMe`,
    `ReadMe.info` and `LICENSE.LGPL.txt`, under `X-Wing Install/` with the drawer icon.
    User-visible names keep the dash (owner, 2026-11-22); the build outputs keep theirs.
  - It packs them with AmigaXDev's `amigaxdev.release`: LH5, level-0 headers, sorted
    members and the DOS stamp of 25.11.2026. `tools/_amigaxdev.py` checks the module against
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
  - It installs an `X-Wing` drawer: `data/` with the game files and the program
    `data/X-Wing`, `X-Wing.slave`, the ReadMe and two copies of the game icon (a project
    icon), both with a 16 KiB stack. `X-Wing.info` starts the program directly: its
    default tool is `data/X-Wing`, and on a Workbench start the program makes the tool
    file's own drawer current (`amiga_platform.c`, `wb_options`). `X-Wing (WHDLoad).info`
    has WHDLoad as its default tool and the tool types `Slave=X-Wing.slave` and `PreLoad`.
  - 0.1 installed into `XWing`, set up for AdLib. Beside an `XWing/data`, the script says
    so, installs the game files from the disks and copies the old drawer's `#?.PLT` and
    `#?.CLP` (pilots and films) that `X-Wing/data` lacks; the old drawer stays.
  - The helper unpacks into `InstallStaging`, and its output is copied into `data/` only
    after it succeeds.
  - `tools/test_release_installer.py` drives real Installer 43 in FS-UAE on a 68020, with
    the Amiga helper. Modes:
    - `fresh`: images;
    - `files`: `XWING.001`–`005` with disk 1's files;
    - `keep` and `replace`: pilots survive;
    - `upgrade`: beside 0.1's `XWing` drawer with the AdLib setup, the images are
      installed and its pilot and film are copied;
    - `remove`;
    - `bad-disks`: a refused source leaves the install unchanged.
  - The installed tree must equal the configured DOS install, and the two icons must have
    their default tools, tool types and stack.
  - `make test-release-workbench` installs the package (`fresh --keep`) and Workbench
    starts the installed `X-Wing.info` from `SYS:WBStartup` (`amiga/debug.sh`
    `XWING_WORKBENCH`) on the 68030 with 8 MiB Fast. The release image must reach the m01
    label with the Workbench message held (`amiga/workbench.gdb.in`).
  - `make test-save-exit` (`tools/test_save_exit.py`, `amiga/save_exit.gdb`): a save
    and an exit on the 68030. The release image has no `KEYS`, so the non-release image
    runs from a Shell on the configured DOS install. Its `KEYS` script registers the
    pilot LUKE, clicks at the concourse, where m06 saves the pilot, then leaves as m16
    does. It must reach m16's exit point (the INT 21h at XWING.EXE+1660), `plat_exit`
    with the reference's exit code 3 (AX 4C03h, MEASURED) and the program's return of 0
    to the Shell. The `LUKE.PLT` it wrote must equal the reference's m06 file
    (`manifest/milestones.sha256`). It prints the ticks counted onto a ring entry
    (`rt_irq_counted`) and posted. MEASURED on 2026-11-23 with the counted ring: two runs
    passed, with 1,938 and 1,947 ticks counted of about 21,650 posted.
- **Make:**
  - `make release` refuses a tree with uncommitted changes. It builds the release image,
    the slaves and the helper, then packages and audits `dist/X-Wing-$(cat VERSION).lha`
    and writes its `.sha256`.
  - `make release-check` audits that archive again.

## Publishing

`make publish` follows the WHDLoad project's `make release PUBLISH=1`
(`tools/publish_release.py`, adapted from its `common/tools/publish_release.py`).

- **Dry run:** without `PUBLISH=1` it prints the tag, title, files and notes.
- **Checks:** it needs a clean tree. It remakes the build outputs at HEAD, audits the
  archive against them and checks the `.sha256`.
- **Publishing:** with `PUBLISH=1` it also checks the GitHub account (Vesuri) and that HEAD
  is on `main` on GitHub. It pushes a lightweight tag, the version (`0.1`), on HEAD, and
  creates the GitHub release `X-Wing <version> (dd.mm.yyyy)`, a normal release marked
  latest, as the WHDLoad project's (a prerelease is not shown as the latest release).
- **Notes:** the early-alpha notice, then the version's ReadMe history items.
- **Assets:** it uploads the archive and its `.sha256`, then downloads the archive again
  to compare.

### 0.1 early alpha

Released ahead of P8 with a reduced gate (`docs/design.md`, "Early alpha 0.1"):

- the archive allowlist and the original-bytes scan;
- matching version strings;
- a reproducible stripped image;
- the WHDLoad slave and the start without WHDLoad, both run on the 68030;
- an installer test;
- a ReadMe that says the port is an unoptimized early alpha.

The rest of gate 8 stays open (`docs/port-plan.md`, P9). The 8 MB Fast RAM target is not met
under WHDLoad ([whdload.md](whdload.md#memory)).

Built by `make release` from `1dfb2a5` on 19.11.2026:

| Artifact | SHA-256 |
|---|---|
| `XWing-0.1.lha`, 1,284,645 bytes | `d335939aad6790fc89a78d68a6fb1dcce478c83492a3822a4535337d5cb0cf93` |
| `XWing` (exe) | `d0db4f9f9ff6956d98481a2bc13c17e2e8462b4946378a4cfd733fb07b4ce847` |
| `XWing.slave` | `d45ad54d7f09911d5e7dea037b0238616b43ed609d46b12855dd38a831c07fbc` |
| `XWingInstallData` | `6beb192d17c1fd67ab6d69b3f8a64d564f8b0d9d37042cfc67b2fb00712bbeb0` |

### 0.2

The Sound Blaster build with its speech, the direct start beside WHDLoad and the `X-Wing`
drawer (`docs/design.md`, "Release 0.2's starts and names"), on 0.1's gate with
`make test-release-workbench` added. Built by `make release` on 23.11.2026, the source
equal to `871ea0a`'s:

| Artifact | SHA-256 |
|---|---|
| `X-Wing-0.2.lha`, 1,345,637 bytes | `91721e729768b0a2fcab4414b5ebdbd06a3db87ec2fd5bd491e6dacc6f8b654b` |
| `X-Wing` (exe) | `15223aa8b6a27587a364ed5af719c727d857ef9a4da29b82d899c0679bcc6e2e` |
| `X-Wing.slave` | `47a42c876410566e6785955bd09c7578a3a50af62e0b80caa4ee182eed55801f` |
| `X-WingInstallData` | `183256f446bf994ce293fdba069cd7eaf8b7eaac10fa66e64eec35cd06e9f112` |

### 0.3

P8 to step 11, partly optimized (`docs/design.md`, "Release 0.3"), on 0.2's gate:
`make release-repro`, `make test-whdload` (on the a1200-030 preset), the installer's
seven modes and `make test-release-workbench`. Built by `make release` on 25.11.2026, the
source equal to `aff4f24`'s:

| Artifact | SHA-256 |
|---|---|
| `X-Wing-0.3.lha`, 1,472,568 bytes | `a08309f83cf71708652ed5fea6e17b44d446ff96ae7e0c27a304ba42310b2b7f` |
| `X-Wing` (exe) | `ebfd06e0e4c2d95debd458c591e9c1de7fa5080f62dcc833cc873e76821b4780` |
| `X-Wing.slave` | `96c93b424a8ab6a6abbb6804c831f5d85cfa4be7ed4ce8b923f28227d644a378` |
| `X-WingInstallData` | `115af9814ad76f04d35bc6eab99f08151f30fdb5fdcb9214e03c935f49f3a5ed` |

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
