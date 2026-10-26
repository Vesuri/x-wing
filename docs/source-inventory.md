# Source inventory

The owner supplied `xwingdemo.sea__1.hqx`, the Macintosh X-Wing demo.

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
