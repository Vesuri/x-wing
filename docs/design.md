# Port design

## Owner decisions

| Decision | Status |
|---|---|
| Port X-Wing to the Amiga | Requested |
| Base | The DOS floppy release 1.0 (320×200), owner decision 2026-10-28 |
| Approach | Translate the DOS program offline to 68020 assembly as Secret Weapons of the Luftwaffe did, copying and adapting its translator, oracles, runtime, Amiga platform and release tooling rather than rewriting them (owner direction 2026-11-01); steps in [port plan](port-plan.md) |
| Macintosh 68k demo | Optional donor of native 68k routines in the speed phase, for parts that correspond to the DOS program, in the way Secret Weapons of the Luftwaffe used Their Finest Hour (owner direction 2026-10-26; optional optimisation route, owner decision 2026-11-01; Macintosh reference work postponed, owner decision 2026-11-04) |
| Current scope | Reference setup only: the DOS release installed and run under DOSBox-X, and the Macintosh demo run on an emulated 68040 Macintosh; no analysis |
| Reference machines | DOS: scripted DOSBox-X, 386 at fixed 30,000 cycles/ms ([DOS reference](dos-reference.md)). Macintosh: Quadra 700 (68040) under MAME, System 7.5.5 |
| Amiga CPU | 68030 minimum, 68040 recommended (owner decision 2026-11-01) |
| Memory | 8 MB Fast RAM is the target. The version started without WHDLoad uses as little memory as it can, but it gets what it needs (owner decision 2026-11-01) |
| Sound | AdLib for music and everything else; Sound Blaster for PCM audio, in a later phase (owner decision 2026-11-01) |
| Copy protection | Bypassed in the port (owner decision 2026-11-01): the protection screen is never shown and its call returns a correct first answer. The bypass is checked at the screen's return against the reference after the correct answer, with the screen's own state listed with evidence (owner decision 2026-11-06). Past the return the port runs in byte-exact lockstep with references recorded with the same bypass applied in DOSBox-X at the same call, because the game reads state the skipped screen leaves (owner decision 2026-11-08) |
| Music driver's flight callback at interrupt level | Runs at interrupt level (deferred past P5 by owner decision 2026-11-05; taken on at the owner's request 2026-11-07): the IRQ0 footprint proof follows the driver's far callback (ADLIB.IMS +006B6, FLIGHT.OVL +19424) through its re-entries into the driver (`annotations/irq-hooks.csv`). Every word the re-entry forwards and the request-0Fh enqueue queues is one the handler wrote and no stack address, so DOS and the port queue the same words; the host lockstep into flight (`tests/host_run.py --screen`) checks it |
| Music driver's request 0Fh at interrupt level | No stack words copied: the tick's two locals that request 0Fh leaves unwritten reach only the callback request (+0067C), which never reads them (the 2026-11-05 allowance of their copies at +2B4D and +2B6D is withdrawn: the proof had lost the request's high byte) |
| Service registers from dead stack | May differ from DOSBox-X's (owner decision 2026-11-09): dead stack below SS:SP holds other bytes than DOS's (INFERRED: IRQ0's handler runs on the private stack, I4, not on the interrupted one), and the game passes some service registers through uninitialized stack (an `intdos` REGS block: m10's INT 21h AH=47h loads AL, BX, CX, DH and DI from it). At a service entry AX, BX, CX, DX, SI or DI may differ only when generated code read its whole value as a word from dead stack since the last service event, the differing bytes being the masked ones (or read each differing byte alone), and at the return only while both sides hold their entry values; SP, BP, segments and flags stay exact (`tests/host_run.py` ServiceLog; controls `--dead-sabotage`) |
| Gate 5's Amiga half | The Amiga replay is part of gate 5 (owner decision 2026-11-06): live, m01's state depends on when the CIA ticks land, so a diagnostic image replays the reference's interrupts, REP slices, VGA status reads and clocks on the 68030 model and the strict compare runs on its capture; the production image's live run to the m01 label is a smoke test |
| Chipset and release requirements | Not decided; 256-colour mode 13h implies AGA, as in Secret Weapons of the Luftwaffe |

## Faithfulness boundary

The original DOS execution is the correctness reference for the port. Preserve game logic,
data interpretation and decisions; port-owned services handle Amiga display, audio, input
and platform integration. A Macintosh routine may replace a DOS one only when it is shown
to match the DOS behaviour against the DOS reference. Any behaviour-changing departure
needs an explicit owner decision and validation against the original. The copy-protection
bypass is one: from the bypass on, the port's state must equal the reference's after a
correct answer ([port plan](port-plan.md), P6). SWOTL's runtime is copied and adapted
([port plan](port-plan.md), P5).

The Macintosh application is a fat binary: 68k `CODE` resources and a PowerPC data fork.
Only the 68k `CODE` is a donor; the PowerPC code is out of scope unless the owner decides
otherwise.
