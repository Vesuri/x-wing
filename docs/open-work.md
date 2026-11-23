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
   ([perf-method](perf-method.md#steps)). The intro has no target yet (the owner's to set).
   Whether the film's playback costs what the same flight would live is still open: m13's
   window shows another scene.
   Where the film's cost lies, in step 2's m17 meter: generated code 85.4% of the model
   cycles, about 61% of that in code bytes (DERIVED from the meter's counts and weights).
   In the window the check whether DS is the VGA segment, before every store through DS,
   ran 3,468,938 times: 7–15% of the meter (DERIVED: 12 to 25.5 model cycles each, inside
   or outside a cached loop). The EMS ES guard ran 1,785,854 times with 861,401 flag saves
   around it, about 5.5%, and `rt_ems_es` takes 6.75%.
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
   The steps, the biggest priced win first (the order agreed with the owner 2026-11-23).
   Each is one commit with its meter and frames figures; below about 5% the frames fixture
   cannot resolve a step and the meter decides.
   3. Instruments. The film is re-profiled for the costs only the Amiga has: C2P, the present
      and the FM render. The reference's own frame interval in the film and the intro is
      the ceiling. An intro frames fixture over the Star Destroyer scene and an intro meter
      window (which milestone: the owner's choice).
   5. The VGA store check at DS loads: only the routines the traces show storing to VGA
      through DS keep it per store; elsewhere a DS load of the VGA segment falls back to a
      counted whole-screen mark. It changes D9 and needs the owner's OK. Controls: an
      unmarked VGA store and an unlisted VGA DS load are caught.
   6. The EMS guards: the one-entry cache's hit checked inline in generated code, and a
      guard repeated while ES is unchanged dropped with its flag save. Controls:
      `ems_guard_problems` and its sabotages, and a guard dropped across an ES change.
   7. The intro's compare-and-copy, FRONTEND 1A5E:0119: a cheap restart path in the
      REPE CMPSW lowering and the changed word's mark inline.
   8. The intro's sprite decoder, FRONTEND 1B58:007A: a short-count path for REP STOSW and
      REP MOVSW.
   9. Checkpoint: the film, the intro and a first 68040 run; the later steps re-ranked.
   10. The Amiga platform's costs, where step 3's profile shows them large: the FM render
       and C2P.
   11. Smaller translator items, each priced with `tools/lowering_cost.py` first: the
       reversed index address reused while its register is unchanged (3,803,561
       recomputations in the window), the cell walk (2.9% of the meter), near calls and
       returns (2.8%).
   12. Hand natives for flight's hot code. The Macintosh survey found no donor for it
       ([Macintosh donors](mac-donors.md)): two counterparts, 1.9% of the film, and the
       Macintosh engine renders other models at 640×480. Each native needs the owner's
       authorization and an `annotations/hle.csv` row with its oracle.
   13. The 68040 check and gate 7.

   Steps 5–11 may bring the film to about 230–260 ms (INFERRED). 100 ms needs about 7
   model cycles per guest instruction against 14.8 now, so step 12 carries the rest.
2. Postponed (owner decision 2026-11-04) until P8 takes a donor; the survey found none for
   the film's hot code ([Macintosh donors](mac-donors.md)): make the Macintosh reference
   reach named milestones and map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
3. P9's gate 8 ([port plan](port-plan.md#p9-release-gate-8)), after P8. The CPU matrix
   passes under WHDLoad ([WHDLoad](whdload.md#tests)). Still open:
   - a full interrupt ring stops the game while a long service blocks: a second
     `make test-save-exit` run stopped with "hardware interrupt posted to a full ring"
     after the pilot was saved (MEASURED), the first passed. The 32-entry ring fills in
     about 0.1 s at about 6.6 ticks a field (DERIVED from the reference's 33 ticks in
     five fields) while a runtime service holds the ticks (`rt_irq_mask`). The fix
     (owner decision 2026-11-23, `docs/design.md`): consecutive ticks share one ring
     entry with a count. Its validation is the host lockstep and the Amiga replay;
     acceptance: repeated `make test-save-exit` passes;
   - WHDLoad on 8 MB Fast: the slave reserves 8.5 MiB of ExpMem, and on 8 MiB of Zorro II
     WHDLoad refuses it with DOS error 103 ([WHDLoad](whdload.md#memory));
   - Fast RAM in flight, where the measured low-water marks do not reach;
   - the minimum Fast RAM without WHDLoad;
   - save and exit: `make test-save-exit` ([release](release.md)), reliable once the ring
     above is fixed; the input scenarios (`KEYS` feeds `Input.cpp`, not the hardware);
   - speech in flight on the Amiga: blocks from the EMS page frame (m14) are played only
     by hand, as the Amiga replays refuse Sound Blaster blocks;
   - a real-hardware pass.
   Acceptance: the P9 gate in the port plan.
