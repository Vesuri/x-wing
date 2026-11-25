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
   step 5, video stores through DS unchecked outside listed code, to 280 ms, and step 6,
   the EMS guard's cache hit checked inline, to 260 ms
   ([perf-method](perf-method.md#steps)). The intro has no target yet (the owner's to set).
   Whether the film's playback costs what the same flight would live is still open: m13's
   window shows another scene.
   Where the film's cost lies, in step 2's m17 meter: generated code 85.4% of the model
   cycles, about 61% of that in code bytes (DERIVED from the meter's counts and weights).
   The EMS ES guard ran 1,785,854 times with 861,401 flag saves around it, about 5.5%, and
   `rt_ems_es` takes 6.75%.
   A second window, the frames fixture's intro scene ([perf method](perf-method.md)): the
   intro's full-screen Star Destroyer scene runs at about one frame a second on the 68030
   model, the rest of the intro at about seven
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
   The steps, the biggest priced win first (the order agreed with the owner 2026-11-23,
   re-ranked at step 9's profile 2026-11-25).
   Each is one commit with its meter and frames figures; below about 5% the frames fixture
   cannot resolve a step and the meter decides.
   3. Instruments. The film is re-profiled for the costs only the Amiga has: C2P, the present
      and the FM render. The reference's own frame interval in the film and the intro is
      the ceiling. An intro meter window (which milestone: the owner's choice).
   10. The EMS guard's cache hit for ES on the main path, deferred behind steps 11 and 12
       (owner 2026-11-25): a hit still leaves the main path for the out-of-line check
       (`_ex`), whose labels take 7.3% of m17's generated model cycles (31.5M, about 59 per
       entry; MEASURED per label by the meter), and the inline D001h check with its CCR
       saves another 6.2% (DERIVED: `tools/overhead_census.py` on step 10's meter). The
       hit on the main path would save about 21 model cycles per hit, 11.2M (2.4%) in m17,
       and the cache in the state block about 8 bytes per hit, 4.5M (1.0%) (DERIVED from
       the cost model's weights and the meter's counts per site; every one of m17's 154
       sites always sees an EMS segment), before the larger loops' cost.
   11. Video checks through ES: decided once at each ES load and skipped after an EMS cache
       hit; 475,059 checks in m17, 33,051 of them marking (DERIVED, as above).
   12. Smaller translator items, each priced with `tools/overhead_census.py` or
       `tools/lowering_cost.py` first: the cell walk's reset (1.44%: 97 resets, each
       clearing 7,711 longs); the reversed index address reused while its
       register is unchanged (the address build is 10.9%); string flags through `G_FL` and
       the DF test per string instruction; REP's fixed setup at short counts; near calls
       and returns.
   13. Hand natives (owner decision 2026-11-25, `docs/design.md`), each with its
       `annotations/hle.csv` row and oracle, the intro's first:
       - the intro's compare-and-copy, FRONTEND 1A5E:0119 (about 39% of the scene with
         its runtime calls): longs compared, changed rows marked once;
       - the intro's sprite decoder, FRONTEND 1B58:007A (about 35% with its line skip);
       - FLIGHT's span sorts, FLIGHT.OVL+22541 (10.9% of the film's profile with the scanline
         walk): two stable bubble sorts, replaced by a stable sort with the same comparator;
       - the vertex transform (+20D5F, 4.1%), the coverage scan and remap (+233B2, 2.6%),
         the scaled sprite draw with its planted fill (+235FE and +24A4F, 7.4%) and the
         starfield (+1B0C8, 2.5%).
       The Macintosh survey found no donor for them ([Macintosh donors](mac-donors.md)).
   14. The Amiga platform's costs, where the film's profile shows them: the FM render
       (`render` 2.6%, `fm_field` 1.7%), the palette (`setPalette24Bit` 1.3%,
       `buildPalette` 1.0%) and C2P.
   15. The 68040 check and gate 7.

   Steps 10–12 may bring the film to about 200 ms: the census puts about 28% of its
   generated model cycles in translation overhead (DERIVED). 100 ms needs the natives.
2. Postponed (owner decision 2026-11-04) until P8 takes a donor; the survey found none for
   the film's hot code ([Macintosh donors](mac-donors.md)): make the Macintosh reference
   reach named milestones and map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
3. P9's gate 8 ([port plan](port-plan.md#p9-release-gate-8)), after P8. The CPU matrix
   passes under WHDLoad ([WHDLoad](whdload.md#tests)). Still open:
   - WHDLoad on 8 MB Fast: the slave reserves 8.5 MiB of ExpMem, and on 8 MiB of Zorro II
     WHDLoad refuses it with DOS error 103 ([WHDLoad](whdload.md#memory));
   - Fast RAM in flight, where the measured low-water marks do not reach;
   - the minimum Fast RAM without WHDLoad;
   - the input scenarios (`KEYS` feeds `Input.cpp`, not the hardware); save and exit
     pass (`make test-save-exit`, [release](release.md));
   - speech in flight on the Amiga: blocks from the EMS page frame (m14) are played only
     by hand, as the Amiga replays refuse Sound Blaster blocks;
   - a real-hardware pass.
   Acceptance: the P9 gate in the port plan.
