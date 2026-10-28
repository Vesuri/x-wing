# Port design

## Owner decisions

| Decision | Status |
|---|---|
| Port X-Wing to the Amiga | Requested |
| Base | The DOS floppy release 1.0 (320×200), owner decision 2026-10-28 |
| Macintosh 68k demo | Donor of native 68k routines for parts that correspond to the DOS program, in the way Secret Weapons of the Luftwaffe used Their Finest Hour (owner direction, 2026-10-26); method and scope not decided |
| Current scope | Reference setup only: the DOS release installed and run under DOSBox-X, and the Macintosh demo run on an emulated 68040 Macintosh; no analysis |
| Reference machines | DOS: scripted DOSBox-X, 386 at fixed 30,000 cycles/ms ([DOS reference](dos-reference.md)). Macintosh: Quadra 700 (68040) under MAME, System 7.5.5 |
| Amiga CPU, chipset, memory budget and release requirements | Not yet decided |

## Faithfulness boundary

The original DOS execution is the correctness reference for the port. Preserve game logic,
data interpretation and decisions; port-owned services handle Amiga display, audio, input
and platform integration. A Macintosh routine may replace a DOS one only when it is shown
to match the DOS behaviour against the DOS reference. Any behaviour-changing departure
needs an explicit owner decision and validation against the original. No runtime has been
copied or implemented.

The Macintosh application is a fat binary: 68k `CODE` resources and a PowerPC data fork.
Only the 68k `CODE` is a donor; the PowerPC code is out of scope unless the owner decides
otherwise.
