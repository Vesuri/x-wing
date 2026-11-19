# WHDLoad slave

`whdload/XWingSlave.s` (`make whdload` writes `build/whdload/`), copied from Secret Weapons of
the Luftwaffe's `whdload/SwotlSlave.s` (`manifest/references.tsv`) and adapted. SWOTL's
`docs/whdload.md` holds the reasons behind each rule below; the merged rules are in AmigaXDev's
`docs/playbooks/new-port-playbook.md` §13. Test: `tools/test_whdload.py`
(`make test-whdload`). Packaging: [release.md](release.md).

## Model

- **Kickemu:** `kick31.s` boots Kickstart 3.1 in WHDLoad's space. `BOOTDOS` and `HDINIT`
  mount `slv_CurrentDir` (`data`) through kickfs.
- **Start:** `_bootdos` loads `data/XWing` (the stripped release image), locks the current
  drawer as PROGDIR, and runs the image through `RunCommand` with a 16 KiB stack and an empty
  argument line. The same image runs from a Shell.
- **Failure:** a nonzero result, from a failed start or a runtime stop, gives
  `TDREASON_FAILMSG` ("X-Wing stopped"). A missing executable gives `TDREASON_DOSREAD`.
- **Header:**
  - `slv_Version` 17, with `WHDLF_NoError|WHDLF_ReqAGA|WHDLF_Req68020`;
  - `BLACKSCREEN`, `INITAGA`, `SEGTRACKER` and `NO68020`;
  - no `STACKSIZE` (kick31's A600 patch);
  - an empty `slv_config`: X-Wing has no Custom options yet.
- **Quit key:** Help (`$5f`), which has no entry in `Input.cpp`'s key table.
- **Caches:** `CACHE`. `_bootdos` reads CACR and, if the instruction cache is off (WHDLoad
  without the MMU), sets `CACHECHIP`'s value.

## Memory

- **Reservation:** `CHIPMEMSIZE` is `$200000`. `FASTMEMSIZE` is `$800000`, so ExpMem is
  8.5 MiB with the Kickstart image.
- **Release image (MEASURED):**
  - `.text` 4,130,108 bytes, `.rodata` 6,508 and `.bss` 420,528;
  - guest RAM 1,114,128 bytes with the state block, and the EMS store 1,048,576.
- **Free low-water marks (MEASURED, 2026-11-19):**
  - Setup: the `MemFree` slave, 68030 without MMU, 8 MiB Zorro II plus 16 MiB Zorro III
    Fast, Kickstart 40.68.
  - The lowest largest free chunk was 1,485,336 bytes Fast and 1,846,264 bytes Chip, the
    same after 3,000 and 30,000 fields.
  - Without input, that run covers the logo, the intro and the attract sequence. Flight's
    temporaries are not in it: the effect prerender's 256 KiB render buffer and the
    `sfx.cache` image.
- **Host:** 8.5 MiB of ExpMem does not fit in an 8 MiB Zorro II board, so WHDLoad needs more
  than 8 MB Fast RAM. On 8 MiB Zorro II it fails with DOS error 103 at the slave's load
  (MEASURED). This misses the 8 MB target (`docs/design.md`, Memory).
- **Without WHDLoad:** the same image runs to the m01 label from a Shell on the 68030 model
  with 8 MiB Fast (MEASURED). Its minimum Fast RAM is not measured yet (gate 8).

## Tests

`tools/test_whdload.py` uses FS-UAE with WHDLoad, Kickstart 3.1 A1200 and the configured DOS
install as `data/`:

| Mode | Slave | Checks |
|---|---|---|
| `smoke` | AmigaXDev's shared `SmokeSlave.s` | the harness |
| `boot` | `BootTest.slave` | kickemu boots |
| `load` | `LoadTest.slave` | LoadSeg and PROGDIR |
| `run` | `XWing.slave` | see below |

A `run`:

- ends by `TIMEOUT` with `COREDUMP`;
- needs "DEBUG caused" at the CIA-A event count, not a fault;
- needs at least half of the original `XWING.EXE`'s 64-byte blocks in guest RAM,
  byte-reversed;
- needs a CACR that matches the cache policy.

Each mode's options:

- `--setup a1200-030`, the default, is a full 68030 on `$FSUAE_MMU` with data-cache
  emulation. `--whdload-mmu` adds WHDLoad's MMU option; `a1200-040` and `a1200-060` need
  `TC=8000`.
- `--z3 KiB` adds Zorro III Fast RAM, on the 32-bit setups only.

Measured on 2026-11-19 on the 68030 without MMU: smoke, boot, load and run pass, with CACR
2011 and 332 of 608 blocks resident. The other CPU setups belong to gate 8.
