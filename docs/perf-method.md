# Performance method

P8's instruments and how its numbers are made. The method itself is AmigaXDev's
`docs/reference/measurement-method.md`: units, A/B discipline, pricing, budgets and the
traps that made measurements lie. The 68020 cost facts are in its
`docs/reference/m68k-optimisation.md`. The instruments are copied from Secret Weapons of the
Luftwaffe (`manifest/references.tsv`), whose `docs/perf-method.md` and `docs/speed-plan.md`
hold the reasons behind them. The steps and their gate are in the
[port plan](port-plan.md#p8-speed-gate-7).

## Machine

- **Measurement model:** the shared cycle-exact preset `a1200-030` (50 MHz 68030, data cache,
  2 MB Chip, 8 MB Fast) without its MMU (`--uae_mmu_model=0`). FS-UAE's profiler records no
  instruction on the 68030 MMU core, nor on a 68030 that is not cycle-exact (`amiga/debug.sh`
  without a preset). The game uses no MMU.
- **Emulator:** the native arm64 FS-UAE, pinned in `manifest/perf-tools.sha256` (relative to
  `~/.local/share/amiga`) and checked before every run. Numbers from another build do not
  compare.
- Emulated fields, never wall time. No warp.

## Instruments

- **Meter** (`tools/cost_meter.py`): the per-step acceptance. It is deterministic and
  layout-blind.
  - **Run:** `tests/host_run.py`'s lockstep check of a milestone (`--bypass`, and `--resume`
    from the save at the flight's start where the milestone has one), so every meter run is
    also a fidelity check. Any lockstep problem refuses the result.
  - **Window:** the milestone's first snapshot trigger to its last
    (`reference/milestones.csv`). A C block hook (`tests/host_meter.c`) counts every
    translated block and taken transfer in it.
  - **Model:** per executed 68k instruction its code bytes, inside or outside a cached loop
    of at most 256 bytes; its data reads and writes; its taken transfers; and its mul/div.
    These are weighted by `tools/cost_model.json` into model cycles.
  - **What it measures:** the host image is the sync image, so its poll tests (which
    production does not have) are reported apart. Its REP instructions that an interrupt
    split in the reference run `tests/rep_replay.py`'s diagnostic lowering. Interrupts arrive
    at the reference's poll visits, so a guest wait loop runs the reference's iteration count:
    its cost is the reference's waiting, not work.
  - **Usage:** `--out A.json` per arm, `--compare A.json B.json` for the deltas per class and
    x86 form. `--plant-check BASE.json [--label L --nops N]` is the meter's control: NOPs at
    one generated label must add exactly their instructions, bytes and cost.
- **Frames fixture** (`tools/perf_film.py`, `amiga/perf_film.gdb`): a scene on the
  non-release Amiga image, the frame time the owner sees.
  - **Film** (`--scene film`, the default): the combat film (m17). A `KEYS` script
    (`src/platform/amiga/amiga_platform.c`) goes from the intro to the film room and loads
    `COMBAT.CLP`. From P on its steps count published frames (`fN`), so the window starts
    at the same point of the film in every build. The window: the field at each of the
    next 60 visits to the frame label `FLT_1B7D2`.
  - **Intro** (`--scene intro`): the intro's full-screen Star Destroyer scene, with no keys.
    Its start varies by a few frames between runs, so the window is anchored to the
    scene's load: the first frame interval of more than 60 fields after present 1250, then
    100 presents on. The window: the field at each of the next 30 `plat_present` calls.
  - **Output:** the window's frame intervals, then a 100-field instruction profile
    reported by `tools/profile_report.py`. The capture is deleted after the report.
- **Profile report** (`tools/profile_report.py CAPTURE ELF`): class, module, guest routine
  and instruction, and runtime shares of a `monitor profile` capture. The cycle-exact 68030
  leaves a few thousand cycles of a field to no record (the intro's capture: 1.17% of one
  field, 0.08% of the window). More than 1% of the window is refused, as is a field
  accounted beyond its cycles; the report prints the window's share and the worst field
  (owner decision 2026-11-23). It knows the Sound Blaster build's label prefix `AW`.
- **Lowering cost** (`tools/lowering_cost.py`) and **call tree** (`tools/profile_tree.py`):
  per x86 form and per routine, inclusive.
- **Overhead census** (`tools/overhead_census.py`): a meter result's generated cycles by
  role, each executed 68k instruction classed from the shapes the translator emits (the
  reversed address build, the EMS check and its out-of-line path, the video check and mark,
  the return check, flags, the sync image's poll tests, the guest's own work). Each label's
  model cycles are shared among its instructions by the cost model's weights, so the role
  totals are DERIVED; per label they equal the meter's.

## Cost model

`tools/cost_model.json` is fit on the measurement model (`--calibrate`, a 100-field capture
of the combat film's window, 56,032 generated PCs): per instruction 0.679, per code byte
1.045 (0.593 inside a cached loop), read 1.100, write 3.453, taken transfer 7.091 (0 inside a
cached loop), mul/div 25.036; unsigned register long arithmetic keeps SWOTL's probed 4.125.
R² 0.810, the model 7.1% under the measured generated cycles. Recalibrate after a change to
the measurement model or when the meter and a capture disagree, then rerun `--plant-check`.

## Baseline (2026-11-19, the image at `60d0de7` plus the instruments)

Model cycles with the weights above, MEASURED. Per frame without poll tests is the
production estimate: production has no poll tests.

| Window | Instrument | Figure |
|---|---|---|
| m12 training flight, 50 frames | meter | 527,209,596 model cycles: 10.54M per frame, 10.31M without poll tests (2.2%). Runtime 19.4%; the EMS ES guard (`rt_ems_es` and its generated cold sections) 18.4%. The same counts in two runs. Plant: 8 NOPs at `FLT_22E3E` add exactly 210,472 instructions, 420,944 bytes and 582,689 model cycles |
| m06 concourse, 500,000 visits to `menu` | meter | 2,412,226,722 model cycles. Runtime 47.9% (`rt_int33` 7.9%, `push_frame` 7.9%, `rt_ems_segments` 6.3%); poll tests 1.0%. Mostly the menu's mouse-polling wait, at the reference's iteration count |
| m13 mission flight, 100 frames | meter | 675,549,750 model cycles: 6.76M per frame, 5.92M without poll tests (12.4% of the window, a wait). Runtime 11.4%; EMS ES guard 10.0% |
| m17 combat film, 50 frames | meter | 643,272,229 model cycles: 12.87M per frame, 12.57M without poll tests (2.3%). Runtime 20.8%; EMS ES guard 20.6% |
| m17 combat film, 59 frame intervals | frames fixture | median 360 ms per frame, mean 351 ms, range 220–440 ms; two runs of the same image, medians 360 and 360 ms, means 351.2 and 351.5 ms |
| m17 combat film, planted (8 NOPs at `FLT_22E3E`) | frames fixture, profile | the same intervals; `FLT_22E3E` 2.61% → 2.69% with the same 3,459 calls |
| m17 combat film, 100 fields | profile | generated 64.7%, runtime and platform 29.0% (`rt_ems_es` 13.5%) |
| intro's Star Destroyer scene, 29 frame intervals (the image at `b5dda4c`, step 6) | frames fixture, `--scene intro` | two runs: medians 520 and 520 ms, means 534.5 and 531.7 ms, range 380–700 ms |
| intro's Star Destroyer scene, 100 fields (`b5dda4c`) | profile | generated 57.8%, runtime and platform 36.8% (`rt_ems_ds` 9.0%, `rt_ems_es_miss` 8.0%, `vram_span` 5.5%, `guard` 4.2%); FRONTEND+174DA 26.4%, +165D9 24.3% |

Playback against live flight (open-work 1): per frame the film's window costs about twice
m13's (12.57M against 5.92M model cycles without poll tests), but the two windows show
different scenes, so this does not settle whether playback costs what the same flight
would live.

## Steps

Each step is one commit with its before and after figures; the meter runs are lockstep
checks, the frames figures come from `tools/ab_runs.py film` with three interleaved runs per
arm. MEASURED.

| Step | Change | Meter | Frames fixture (m17) |
|---|---|---|---|
| 2 | The EMS guard's one-entry cache per segment register (`rt_entry.s` `EMS_GUARD`, `ems.c`): the last segment, the offsets of its frame page and the base. Emptied by every change of the fast table; held over IRQ0's handler, which production delivers at any instruction. Controls: `ems_guard_problems` in every lockstep run; sabotages `ems-cache` and `ems-cache-irq` | m17 643,269,278 → 577,337,240 (−10.25%); m12 527,206,672 → 479,515,474 (−9.05%); generated code unchanged | run medians 360, 360, 360 → 320, 320, 320 ms; means 355.1 → 313.3 ms; `rt_ems_es` 13.1% → 4.9% of the profile |
| 5 | Video stores through DS (owner decision 2026-11-23, [translator design](translator-design.md) D9): FRONTEND and FLIGHT mark stores through DS only in `annotations/vram-ds.csv`'s code; elsewhere a DS load at the frame, or listed code left with DS there, marks the whole frame (`rt_vram_ds`, counted). Mark sites 11,569 → 4,972 in FLIGHT, 8,986 → 8,232 in FRONTEND. Controls: host lockstep at m01, m02 and m17 with the shown-frame check, no fallback taken; `make t-vram-ds-plant`; sabotage `vram` | m17 577,419,899 → 490,846,571 (−14.99%; 50 more guest instructions of 34,330,454, the HEAD arm run from boot and the step's resumed); m12 479,579,935 → 405,890,497 (−15.37%); the biggest deltas `mov m16[disp], r16` −16.6M and `mov m16[di], r16` −9.6M | run medians 320, 320, 320 → 280, 280, 280 ms; means 314.8 → 271.0 ms |
| 6 | The EMS guards ([translator design](translator-design.md), the EMS model): a non-string access checks the one-entry cache inline (the segment, the page's first offset, the end) and loads the base, entering `rt_ems_es_miss`/`rt_ems_ds_miss` on a miss; an ES guard repeated over the same operand, ES and its registers unchanged since the last, is dropped (`lower.ems_held`; 472 sites, about 1.5% of m17's guard executions, DERIVED from step 5's meter). Controls: the differential tests' cache states and `emshold` blocks, `ems_guard_problems` in every lockstep run, sabotages of the hit's three checks and of a guard held across an ES or offset-register change | m17 490,843,619 → 480,940,571 (−2.02%; runtime −38.8M, generated +28.9M); m12 405,887,573 → 396,002,991 (−2.44%; runtime −28.1M, generated +18.2M) | run medians 280, 280, 280 → 260, 260, 260 ms; means 271.6 → 259.5 ms |
| 7 | The intro's compare-and-copy ([translator design](translator-design.md), the EMS model and D9): the EMS guard cache holds the run of adjacent frame pages around an access that share its displacement, and an access across pages of one displacement decides in `EMS_GUARD` instead of the C path, so the compare's restarts over four store pages hit it; a byte or word video store marks through `rt_vram_mark_short`, without a call within a row. Controls: `ems_guard_problems` with an access in each page through the cache and the sabotage `ems-cache-run`; `vram_mark_problems` against `rt_vram_mark` over row, frame and offset edges and the sabotage `vram-short` | m17 480,940,571 → 480,285,181 (−0.14%; runtime −655,391, generated unchanged); m12 396,002,991 → 393,431,875 (−0.65%; runtime −2,571,117, generated unchanged) | run medians 260, 260, 260 → 260, 260, 260 ms; means 259.8 → 261.0 ms. The intro (`--scene intro`): medians 520, 520 → 460, 480 ms; means 534.5, 531.7 → 469.0, 469.7 ms; the profile's runtime and platform 36.8% → 24.0% (`rt_ems_es_miss` 8.0% and `guard` 4.2% → none) |
| 8 | The intro's sprite decoder ([translator design](translator-design.md), the EMS model and D11): one string element through one operand (LODS, STOS, SCAS, a MOVS or CMPS operand alone in its segment, no REP) checks the EMS guard's cache inline for its own bytes, whatever DF is; REP MOVS and REP STOS with CX at most `REP_SHORT` (3) run the element body (break-even 3.6 to 5 elements, DERIVED from the emitted code). Controls: the differential tests' cache states for single elements and the boundary corpus's REP counts 0 to 3 and 6 to 9; `ems_guard_problems` in every lockstep run | m17 480,285,181 → 479,818,228 (−0.10%; `rep stosw` −494,302); m12 393,431,875 → 393,119,868 (−0.08%; runtime −290,676) | run medians 260, 260, 260 → 260, 260, 260 ms; means 260.6 → 259.9 ms. The intro: medians 460, 480 → 440, 440 ms; means 469.0, 469.7 → 448.3, 449.7 ms; `rt_ems_ds` 9.65% → 2.63% of the profile. Its window lies earlier in the song (the scene loaded at field 6,603 against 6,933), so the FM render's share differs by the window's notes (INFERRED) |
| 10 | The EMS guard's CCR and out-of-line path ([translator design](translator-design.md), the EMS model): the CCR is saved around the main path's check only when a flag valid in it is still read (`lower.ccr_live_in`), X is kept out of line only where it carries the guest CF in, a cache hit returns at once, and d7 is no longer saved (free as the guard opens the instruction). The out-of-line path 73.3 → 59.0 model cycles per entry over the same 534,386 entries in m17 (MEASURED per label). Controls: the boundary corpus's flags across an ES access to their JNE and an ADD's CF in X across an ADC's guard, the stub of the EMS calls returning the CCR inverted; the sabotage of an out-of-line path losing X; host lockstep at m01 and the Amiga replay at m01 | m17 479,818,228 → 458,350,103 (−4.47%; generated −21.5M, `?` −16.9M); m12 393,119,868 → 377,917,037 (−3.87%; generated −15.2M); static generated bytes −83,300 | run medians 260, 260, 260 → 260, 260, 260 ms; means 260.0, 260.0, 259.7 → 253.6, 253.9, 253.6 ms (window 767 → 748 fields). The intro: medians 440, 440 → 420, 420 ms; means 448.3, 447.6 → 420.7, 420.7 ms; FRONTEND 41.3 → 38.6 cycle units per guest instruction |
| 11 | Video stores through SS not checked (owner decision 2026-11-25, [translator design](translator-design.md) D9): FRONTEND and FLIGHT mark no store through SS; an SS load of 9001h–AF9Fh, in any code, marks the whole frame (`rt_vram_ds`), and each present keeps marking it while DS or SS is there. The check was 662,484 executions at 743 sites in m17, none marking (step 10's meter). Controls: host lockstep at m01 with the shown-frame check; `make t-vram-ds-plant`; no fallback in m17 (video DS fallbacks 0) | m17 458,350,103 → 438,150,497 (−4.41%; generated only, `mov m16[bp], r16` −10.8M; 4 more guest instructions in the window, 34,330,508 against 34,330,504, both runs in lockstep with 0 problems); static generated bytes −329,654 | run medians 260, 260 → 240, 240 ms; means 254.9, 254.9 → 242.7, 243.4 ms (window 752 → 716, 718 fields) |
