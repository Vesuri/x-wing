# Port design

## Owner decisions

| Decision | Status |
|---|---|
| Port the Macintosh X-Wing demo to Amiga following Vette!, Alone in the Dark and Prince of Persia 2 | Requested |
| Current scope | Initial setup only: install on System 7 and run on an emulated 68040 Macintosh; no analysis |
| Reference machine | Macintosh Quadra 700 (68040) under MAME, System 7.5.5 |
| Approach | Intended native execution of the original 68k instructions with Macintosh services implemented, as in the reference ports; unverified for this program |
| Amiga CPU, chipset, memory budget and release requirements | Not yet decided |

## Faithfulness boundary

The original Macintosh execution is the correctness reference. Preserve game logic, data
interpretation and decisions; port-owned services handle Amiga display, audio, input and
platform integration. Any behaviour-changing departure needs an explicit owner decision and
validation against the original. No runtime has been copied or implemented.

The application is a fat binary: 68k `CODE` resources and a PowerPC data fork. A port
of the 68k path runs the `CODE` resources; the PowerPC code is out of scope unless the
owner decides otherwise.
