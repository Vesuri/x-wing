# Open work

Steps of the [port plan](port-plan.md), in order; P9 and P10 follow there. The repo rules (P0),
the reference loop (P1: `make dos-reference` passes 21 pinned milestones, the combat film
m17 among them), the static and live map (P2), x86 semantics (P3: `make test-x86`), the 68020 backend (P4: `make test-m68k`) and the
first vertical slice (P5: `make test-amiga`, the Amiga replay and the host lockstep to m01)
and the whole game (P6: host lockstep and the Amiga replay over every pinned milestone,
gate 6) are in place, and P7's music and prerendered effects play on Paula (`make gates-audio`,
`make test-amiga-audio`, `make t-amiga-sfx`). Host lockstep to a flight milestone resumes
from a save at the flight's start (`make t-resume-<milestone>`). P9's 0.1 early alpha is packaged
(`make release`, [release](release.md)) on a reduced gate (owner decision 2026-11-19).

1. P8, speed ([port plan](port-plan.md#p8-speed-gate-7)): the fidelity checks it reruns at
   every step resume from a flight's start (`make t-resume-<milestone>`), and its combat
   window is the combat film, m17 (owner decision 2026-11-19). The instruments are in place
   ([perf-method](perf-method.md)): the meter over m06, m12, m13 and m17, its plant caught,
   the cost model fit on the 68030, and the combat film's frames fixture, 360 ms per frame
   on the 68030 model.
   Target: the combat film at 100 ms per frame or less on the 68030 model (owner decision
   2026-11-19, `docs/design.md`). Next: the first step, priced at the EMS ES
   guard (`rt_ems_es` and its generated cold sections, 18.4% of m12 and 20.6% of m17).
   Whether the film's playback costs what the same flight would live is still open: m13's
   window shows another scene.
2. The x86 oracle under the cell-walk tests (`tests/x86_diff.py` Oracle.run): with
   `--seed 7` a walk case's x86 store faults at an unmapped address and the oracle then
   reads its recorded writes back, raising UC_ERR_READ_UNMAPPED (the same at P4's commit).
   Acceptance: `tests/m68k_blocks.py` completes for seeds 1–8; a faulting store is
   compared as an exception, not a crash.
3. Postponed (owner decision 2026-11-04); optional, for P8's donor route: make the Macintosh
   reference reach named milestones and map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
4. P9's gate 8 ([port plan](port-plan.md#p9-release-gate-8)), after P8. Still open:
   - the CPU matrix (030 with MMU, 040, 060), with CACR checks;
   - WHDLoad on 8 MB Fast: the slave reserves 8.5 MiB of ExpMem, and on 8 MiB of Zorro II
     WHDLoad refuses it with DOS error 103 ([WHDLoad](whdload.md#memory));
   - Fast RAM in flight, where the measured low-water marks do not reach;
   - the minimum Fast RAM without WHDLoad;
   - save, exit and input scenarios;
   - a real-hardware pass.
   Acceptance: the P9 gate in the port plan.
