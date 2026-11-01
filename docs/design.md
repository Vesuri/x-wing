# Port design

## Owner decisions

| Decision | Status |
|---|---|
| Port X-Wing to the Amiga | Requested |
| Base | The DOS floppy release 1.0 (320×200), owner decision 2026-10-28 |
| Approach | Translate the DOS program offline to 68020 assembly as Secret Weapons of the Luftwaffe did, copying and adapting its translator, oracles, runtime, Amiga platform and release tooling rather than rewriting them (owner direction 2026-11-01); steps in [port plan](port-plan.md) |
| Macintosh 68k demo | Optional donor of native 68k routines in the speed phase, for parts that correspond to the DOS program, in the way Secret Weapons of the Luftwaffe used Their Finest Hour (owner direction 2026-10-26; optional optimisation route, owner decision 2026-11-01) |
| Current scope | Reference setup only: the DOS release installed and run under DOSBox-X, and the Macintosh demo run on an emulated 68040 Macintosh; no analysis |
| Reference machines | DOS: scripted DOSBox-X, 386 at fixed 30,000 cycles/ms ([DOS reference](dos-reference.md)). Macintosh: Quadra 700 (68040) under MAME, System 7.5.5 |
| Amiga CPU | 68030 minimum, 68040 recommended (owner decision 2026-11-01) |
| Memory | 8 MB Fast RAM is the target. The version started without WHDLoad uses as little memory as it can, but it gets what it needs (owner decision 2026-11-01) |
| Sound | AdLib for music and everything else; Sound Blaster for PCM audio, in a later phase (owner decision 2026-11-01) |
| Copy protection | Bypassed in the port (owner decision 2026-11-01) |
| Chipset and release requirements | Not decided; 256-colour mode 13h implies AGA, as in Secret Weapons of the Luftwaffe |

## Faithfulness boundary

The original DOS execution is the correctness reference for the port. Preserve game logic,
data interpretation and decisions; port-owned services handle Amiga display, audio, input
and platform integration. A Macintosh routine may replace a DOS one only when it is shown
to match the DOS behaviour against the DOS reference. Any behaviour-changing departure
needs an explicit owner decision and validation against the original. The copy-protection
bypass is one: from the bypass on, the port's state must equal the reference's after a
correct answer ([port plan](port-plan.md), P6). No runtime has been copied or implemented.

The Macintosh application is a fat binary: 68k `CODE` resources and a PowerPC data fork.
Only the 68k `CODE` is a donor; the PowerPC code is out of scope unless the owner decides
otherwise.
