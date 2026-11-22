# Open work

Steps of the [port plan](port-plan.md), in order. The repo rules (P0),
the reference loop (P1: `make dos-reference` passes 21 pinned milestones, the combat film
m17 among them), the static and live map (P2), x86 semantics (P3: `make test-x86`), the 68020 backend (P4: `make test-m68k`) and the
first vertical slice (P5: `make test-amiga`, the Amiga replay and the host lockstep to m01)
and the whole game (P6: host lockstep and the Amiga replay over every pinned milestone,
gate 6) are in place, and P7's music and prerendered effects play on Paula (`make gates-audio`,
`make test-amiga-audio`, `make t-amiga-sfx`). Host lockstep to a flight milestone resumes
from a save at the flight's start (`make t-resume-<milestone>`). P9's 0.1 early alpha is packaged
(`make release`, [release](release.md)) on a reduced gate (owner decision 2026-11-19).
P10, worked ahead of P8 and P9 (owner decision 2026-11-20), is done: the Sound Blaster build
(`XWING_DRIVER=ADLIB_W.IMS`) matches the Sound Blaster references' DSP commands and blocks
in host lockstep over every pinned milestone, the exit included, with the AdLib gates
unchanged, and plays the intro's speech on Paula on the 68030 (`make test-amiga-speech`;
[translator design](translator-design.md), Speech); the pinned milestones are its speech
scenes (owner decision 2026-11-22, [DOS reference](dos-reference.md#sound-blaster-p10)).

1. P8, speed ([port plan](port-plan.md#p8-speed-gate-7)): the fidelity checks it reruns at
   every step resume from a flight's start (`make t-resume-<milestone>`), and its combat
   window is the combat film, m17 (owner decision 2026-11-19). The instruments are in place
   ([perf-method](perf-method.md)): the meter over m06, m12, m13 and m17, its plant caught,
   the cost model fit on the 68030, and the combat film's frames fixture, 360 ms per frame
   on the 68030 model.
   Target: the combat film at 100 ms per frame or less on the 68030 model (owner decision
   2026-11-19, `docs/design.md`). Step 2, the EMS guard's cache, brought the film to 320 ms
   ([perf-method](perf-method.md#steps)). Next: re-profile the film and price the next step;
   the 68040 check.
   Whether the film's playback costs what the same flight would live is still open: m13's
   window shows another scene.
   A second window, not yet a fixture: the intro's full-screen Star Destroyer scene runs at
   about one frame a second on the 68030 model, the rest of the intro at about seven
   (MEASURED: 2 presents in a 100-field profile from field 10,000 of the Sound Blaster
   image's intro; poll points 0.7%). Two front-end routines and the runtime calls they make
   take most of it:
   - the compare-and-copy FRONTEND 1A5E:0119, about 53%: a REPE CMPSW of the new frame
     against a copy of the screen in the EMS frame stops at each changed word, writes it to
     the copy and to VGA, and restarts (35,700 restarts in 100 fields). Each restart pays
     the REPE CMPSW lowering's setup, two `rt_ems_es` guards and an `rt_vram_mark`;
   - the sprite decoder FRONTEND 1B58:007A, about 34%: its runs of a few bytes each pay a
     REP STOSW or REP MOVSW setup, and its reads of sprite data in the EMS frame are
     guarded (`annotations/ems-ds.csv`, the sprite blitters; 114,731 `rt_ems_ds` calls).
   `tools/profile_report.py` refused the capture (one field 1.17% unaccounted, over its 1%;
   0.08% over the window) and does not know `ADLIB_W.IMS`'s label prefix `AW`.
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
