# Open work

Steps of the [port plan](port-plan.md), in order; P10 is worked ahead of P8 and P9 (owner decision 2026-11-20). The repo rules (P0),
the reference loop (P1: `make dos-reference` passes 21 pinned milestones, the combat film
m17 among them), the static and live map (P2), x86 semantics (P3: `make test-x86`), the 68020 backend (P4: `make test-m68k`) and the
first vertical slice (P5: `make test-amiga`, the Amiga replay and the host lockstep to m01)
and the whole game (P6: host lockstep and the Amiga replay over every pinned milestone,
gate 6) are in place, and P7's music and prerendered effects play on Paula (`make gates-audio`,
`make test-amiga-audio`, `make t-amiga-sfx`). Host lockstep to a flight milestone resumes
from a save at the flight's start (`make t-resume-<milestone>`). P9's 0.1 early alpha is packaged
(`make release`, [release](release.md)) on a reduced gate (owner decision 2026-11-19).

1. P10, Sound Blaster PCM ([port plan](port-plan.md#p10-sound-blaster-pcm)). With a Sound
   Blaster the game loads `ADLIB_W.IMS` (MEASURED: the installer's "SoundBlaster" writes `adlib_w` to `LANDRU.CFG`), whose
   embedded Creative CT-VOICE code drives the DSP; WC2's DSP, DMA and IRQ 7 model is the
   copy source (WC2 `d8c9860`, `dfd3db4`), fitted to WC2's own commands. Steps:
   - Sound Blaster references (the machine, the configuration and the tracer's streams are
     in place: [DOS reference](dos-reference.md#sound-blaster-p10)): the pinned milestones,
     the speech and digitised-effect scenes and the exit. The intro's speech already shows
     the driver's commands: reset, E0h, E1h, E2h, E4h, E8h, F2h and C6h while it detects the
     card, then 40h, 14h, D1h and D3h (speaker off, which WC2 met at its exit) around every
     clip (MEASURED);
   - `ADLIB_W.IMS` in the static map and the translator;
   - the DSP, DMA and IRQ 7 model at the commands the references show, its host lockstep
     and block oracle, and its sabotages;
   - the blocks played on Paula (new: WC2 times them silently).
   Acceptance: the P10 gate: DSP command and sample streams match per milestone; AdLib
   gates unchanged.
2. P8, speed ([port plan](port-plan.md#p8-speed-gate-7)): the fidelity checks it reruns at
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
3. The x86 oracle under the cell-walk tests (`tests/x86_diff.py` Oracle.run): with
   `--seed 7` a walk case's x86 store faults at an unmapped address and the oracle then
   reads its recorded writes back, raising UC_ERR_READ_UNMAPPED (the same at P4's commit).
   Acceptance: `tests/m68k_blocks.py` completes for seeds 1–8; a faulting store is
   compared as an exception, not a crash.
4. Postponed (owner decision 2026-11-04); optional, for P8's donor route: make the Macintosh
   reference reach named milestones and map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
5. P9's gate 8 ([port plan](port-plan.md#p9-release-gate-8)), after P8. Still open:
   - the CPU matrix (030 with MMU, 040, 060), with CACR checks;
   - WHDLoad on 8 MB Fast: the slave reserves 8.5 MiB of ExpMem, and on 8 MiB of Zorro II
     WHDLoad refuses it with DOS error 103 ([WHDLoad](whdload.md#memory));
   - Fast RAM in flight, where the measured low-water marks do not reach;
   - the minimum Fast RAM without WHDLoad;
   - save, exit and input scenarios;
   - a real-hardware pass.
   Acceptance: the P9 gate in the port plan.
