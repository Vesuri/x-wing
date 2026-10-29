# Source inventory

The owner supplied `000110_x-wing.7z`, the DOS floppy release, its manual
`X-Wing-Manual.pdf`, and `xwingdemo.sea__1.hqx`, the Macintosh X-Wing demo.

## DOS floppy release

| Property | Value | Evidence |
|---|---|---|
| Archive | `000110_x-wing.7z`, 6,868,271 bytes, one LZMA solid block | MEASURED |
| SHA-256 | `c3efc7a472bc19903136167967f13d83343a54d8c1fc1239ed049653f3a60b8c` | MEASURED |
| Contents | folder `000110_x-wing`: `disk1.img`–`disk5.img`, each 1,474,560 bytes (FAT12 1.44 MB) | MEASURED |
| Release | "X-Wing Space Combat Simulator", version 1.0 (`DISK.ID`); files dated 15 February 1993 | MEASURED |
| Disk 1 | `DISK.ID`, `READ.ME`, `DETECT.EXE`, `INSTALL.EXE` (dated 28 July 1992), `XWING.001` | MEASURED |
| Disks 2–5 | `DISK.ID` and `XWING.002`–`XWING.005`; one split archive in a format not yet identified, unpacked by `INSTALL.EXE` | MEASURED |
| Installed | 282 files, about 13 MB, in `C:\XWING` with `CP\`, `MISSION\` and `RESOURCE\` (`.LFD`) | MEASURED |
| Program | `XWING.EXE` (269,237 bytes): MZ, 1,152 relocations, Microsoft C run-time 1990 | MEASURED |
| Overlays | `FRONTEND.OVL` (537,230 bytes) and `FLIGHT.OVL` (249,118 bytes) are not MZ files | MEASURED |
| CPU mode | 16-bit real mode: segment relocations, no DOS-extender or DPMI strings, EMS and not XMS (`READ.ME`) | INFERRED |
| Stated requirements | DOS 3.1+, VGA or MCGA, 550K main memory; uses EMS, not XMS | installer, `READ.ME` |

`make dos-disks` and `make dos-install` ([DOS reference](dos-reference.md)) pin the
images and the installed tree. Nothing else has been examined.

### Manual

| Property | Value | Evidence |
|---|---|---|
| File | `X-Wing-Manual.pdf`, 1,443,985 bytes, SHA-256 `d4596c98604a51d27d48a3aa7fa6aaac61b5f08ff129a391e7cdf0774e993a61` | MEASURED |
| Contents | "Starfighter Pilot Manual": the cover and 8 two-page scans covering pages 2–17; no text layer; pages 18–20 and the back cover are absent | MEASURED |
| Copy protection | each page from 3 to 17 has a code-name under three glyphs in both bottom corners, 30 in all ("Security Check", page 3) | MEASURED |

The game shows one glyph triple and its page number and asks for the code-name
([DOS reference](dos-reference.md#copy-protection)). Whether it also asks for codes on the
missing pages is not known.

## Macintosh demo

| Property | Value | Evidence |
|---|---|---|
| Archive | `xwingdemo.sea__1.hqx`, 8,805,322 bytes | MEASURED |
| SHA-256 | `1cd9cf7a6905eaad0c986e6c00295bdde33e742b63fd3673848c8d4aabfdd0cb` | MEASURED |
| Container | BinHex 4.0 around a Compact Pro self-extracting archive (`lsar` 1.10.7) | MEASURED |
| Release | X-Wing Demo version 1.01, January 25, 1996 (its Read Me) | MEASURED |
| Contents | folder `X-Wing Demo ƒ`: 67 files in 16 folders | MEASURED |
| Application | `X-Wing`, type/creator `APPL`/`xwng`; resource fork 831,408 bytes, data fork 563,796 bytes | MEASURED |
| Code | fat: 68k `CODE` 0–6 in the resource fork, a `cfrg` and a PowerPC PEF (`Joy!peffpwpc`) data fork | MEASURED |
| `SIZE` -1 | flags `$58E0`; preferred and minimum partition 4,608,000 bytes | MEASURED |
| Stated requirements | 68040 or PowerPC; 4,500K free on 68040 (5,500K preferred); Virtual Memory off advised | Read Me, MEASURED |
| Requirement found by running | 32-bit addressing (its own alert under 24-bit) | MEASURED |
| Data | `X-Wing Data/` with `CP/`, `MISSION/` and `RESOURCE/` (`.LFD`, `.PNL`, `.XWI`, `.FNT`), and the resource-only `X-Wing Patches` (2,445,146 bytes) | MEASURED |

`tools/extract_original_data.py` (`make extract-original-data`) verifies the archive and
writes `tmp/runtime-data/`, laid out like Prince of Persia 2's: each file's data fork under
its own name (empty when absent), `name.rsrc` for a resource fork, and `name.finfo` (a
32-byte AFI1 record holding Finder info and dates). `manifest/runtime-data.sha256` pins all
151 outputs; names in it escape `ƒ` and the `\r` in `Icon\r` (Python `unicode_escape`).
Folder Finder info (custom folder icons) is not in `lsar`'s listing and is not
reproduced. Nothing else has been examined.
