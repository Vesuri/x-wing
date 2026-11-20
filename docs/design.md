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
| RAM stored from dead stack | May differ from DOSBox-X's (owner decision 2026-11-10), for the same cause: the game copies uninitialized stack into its data (m14's flight routine at FLIGHT 126F:08C6 sets its local `[bp-12h]` on one branch, 126F:09E5, and stores it into a flight-object field on both, 126F:0A49, so DS:7095 ends 06 in the port and 12 under DOSBox-X). At the milestone a RAM byte may differ only when its last write was generated code storing a value it read from dead stack since the last service event: a byte store of a byte read, or a byte of a word store that a read of that whole word masked (`tests/host_run.py` `Host.dead_stored`; controls `--dead-sabotage dead-off` and `dead-stored-beside`) |
| EMS frame through DS | Guarded in listed code (owner decision 2026-11-13): the routines the traces show running with DS in the EMS frame (`annotations/ems-ds.csv`, measured by `tools/ems_frame_profile.py`) have their DS accesses guarded as ES accesses are, so they run on the store pages; a DS load of the frame anywhere else, or listed code left with DS there, copies the pages in as a counted fallback, so untraced paths stay correct |
| FM effects | Prerendered, as Secret Weapons of the Luftwaffe's (owner decision 2026-11-15): at FLIGHT's sound loader the runtime captures each effect's OPL writes from the driver's own code, the Amiga renders them to samples once, and Paula plays them in place of the driver's channels while they sound; effects that loop stay live |
| P1 combat scene | The owner's combat film (owner decision 2026-11-19): `COMBAT.CLP`, recorded by the owner in X-Wing mission 4 and played in the film room tracking Red 3 (m17-combat-film), is P1's combat scene in place of a Star Destroyer battle or a measured ranking, and P8's combat window. A milestone may start with a file the owner supplied, pinned and placed beside the installation in every harness (`reference/seeds.csv`, `tools/seeds.py`) |
| Installer's position code | Interoperability data in our code (owner decision 2026-11-19): the native installer (`tools/install-data`) unpacks the user's floppies itself, and the one thing it needs from the original program is the value order of the 64-entry prefix code for match positions in the archive's 0xd0 streams (its lengths are LZHUF's), which exists only in INSTALL.EXE's memory once that has unpacked itself. The 64 codes are a table in `xwunpack.c`; every file the installer writes comes from the user's disks |
| Gate 5's Amiga half | The Amiga replay is part of gate 5 (owner decision 2026-11-06): live, m01's state depends on when the CIA ticks land, so a diagnostic image replays the reference's interrupts, REP slices, VGA status reads and clocks on the 68030 model and the strict compare runs on its capture; the production image's live run to the m01 label is a smoke test |
| P8 frame-time target | The combat film (m17) at 100 ms per frame or less on the 68030 model (the cycle-exact `a1200-030` preset without its MMU), measured by the frames fixture ([perf-method](perf-method.md)) (owner decision 2026-11-19). Baseline: 360 ms |
| Early alpha 0.1 | Released ahead of P8 as an unoptimized early alpha, version 0.1 (19.11.2026) (owner decision 2026-11-19), with a reduced gate: the archive allowlist and original-bytes scan, matching version strings, a reproducible stripped image, the WHDLoad slave and the start without WHDLoad run on the 68030, an installer test, and a ReadMe saying it is an unoptimized early alpha ([release](release.md)). The full gate 8 stays open |
| P10 ahead of P8 and P9 | Sound Blaster PCM (P10) is worked and committed now, before P8's and P9's gates pass (owner decision 2026-11-20). P8 resumes after it; P10's own gate and every AdLib gate stay as they are |
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
