# XWingInstallData

Standalone C99 installer helper. Installs the X-Wing game directory from the user's
five DOS 1.0 floppies (`disk1.img`..`disk5.img` FAT12 images, or the files
`XWING.001`..`005` with disk 1's `INSTALL.EXE`, `DETECT.EXE` and `READ.ME`).

- The volumes are one archive: stored, tree-coded LZ and LZW streams, one per file, with
  a 279-record catalog (47 bytes each) at XWING.001 offset 1,256,066. The format is in
  `docs/release.md`, under "Original data".
- **Checks:**
  - each volume's size and SHA-256 first;
  - each file's catalog size and the exact end of its stream;
  - the three copied files by size and SHA-256.
- **Writes:**
  - the 279 archived files and the 3 copies;
  - the AdLib configuration the original installer writes: `LANDRU.CFG`, plus
    `OPTIONS.CFG` as a copy of `FASTYES.CFG`.

  That makes 284 files, the tree of `manifest/dos-installed.sha256` and
  `manifest/dos-configured.sha256`.
- **Original data:** none, except the position code's value order
  (`docs/design.md`, "Installer's position code").
- **Safety:** the destination must be new. On failure or Ctrl-C, the files and drawers
  the helper created are removed. Exit codes are 0 or 20.
- **Licences:**
  - `io*`, `sha256*`, `start.s` and `COPYING.LIB` are AmigaXDev install-data
    (LGPL-2.1-or-later), as Secret Weapons of the Luftwaffe vendors them. They are
    unchanged and pinned in `vendored.sha256`.
  - `install.c` and `xwunpack.*` are LGPL-2.1-or-later.

To build or test, source `amiga/env.sh`, then run one of:

- `make -C tools/install-data amiga` builds the Amiga binary (68020, freestanding, no
  unresolved symbols).
- `make -C tools/install-data test` runs the host test, which checks:
  - the 284 files against the original DOS install;
  - both source forms;
  - refusals;
  - cleanup and cancel.

The test inputs are local: `XWING_IMAGES` and `XWING_REFERENCE`.
