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
- **Frames fixture** (`tools/perf_film.py`, `amiga/perf_film.gdb`): the combat film (m17) on
  the non-release Amiga image, the frame time the owner sees.
  - **Route:** a `KEYS` script (`src/platform/amiga/amiga_platform.c`) goes from the intro
    to the film room and loads `COMBAT.CLP`. From P on its steps count published frames
    (`fN`), so the window starts at the same point of the film in every build.
  - **Output:** the field at each of the next 60 visits to the frame label `FLT_1B7D2`, then
    a 100-field instruction profile reported by `tools/profile_report.py`. The capture is
    deleted after the report.
- **Profile report** (`tools/profile_report.py CAPTURE ELF`): class, module, guest routine
  and instruction, and runtime shares of a `monitor profile` capture. The cycle-exact 68030
  leaves up to 1% of a field to no record. That is reported, and anything more is refused.
- **Lowering cost** (`tools/lowering_cost.py`) and **call tree** (`tools/profile_tree.py`):
  per x86 form and per routine, inclusive.

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
