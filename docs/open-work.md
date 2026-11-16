# Open work

Steps of the [port plan](port-plan.md), in order; P9 and P10 follow there. The repo rules (P0),
the reference loop (P1, but for the two milestones below), the static and live map (P2),
x86 semantics (P3: `make test-x86`), the 68020 backend (P4: `make test-m68k`) and the
first vertical slice (P5: `make test-amiga`, the Amiga replay and the host lockstep to m01)
and the whole game (P6: host lockstep and the Amiga replay over every pinned milestone,
gate 6) are in place, and P7's music and prerendered effects play on Paula (`make gates-audio`,
`make test-amiga-audio`, `make t-amiga-sfx`).

1. Host lockstep resumed from a verified milestone, so a check in flight need not replay
   the menus from boot (MEASURED: to m12, 4,286–4,802 s; the flight's sound loader at 4,619 s, after 39,962,872
   of the run's 40,066,706 services).
   The resume must work on a rebuilt host image, since most changes rebuild it:
   - save, at a milestone the run has just matched against the reference: the guest's
     RAM, state block and registers; the runtime's guest-visible state (DOS files and
     positions, EMS handles and mapping, video and DAC, PIT, PIC and IRQ state, OPL,
     input) through a versioned serializer in the runtime, by field, not by address;
     the open guest calls as their guest return CS:IP, read off the 68k stack with the
     saving image's symbols; and the harness's cursors (services, interrupts, REP
     slices, VGA status reads, OPL writes, input script, monitor state);
   - resume on any image: restore the state, push one frame a guest call that returns
     through a runtime stub dispatching to its guest return address (`rt_lookup`, as
     interrupt delivery does), and enter the generated code at the milestone's label;
     save only where no interrupt or service is in progress;
   - sound only for a change that does not touch what ran before the milestone: the
     saving run records which runtime functions and generated blocks ran; a change
     to none of them may resume, any other runs from boot and saves anew. Lockstep
     past the resume still fails loudly on anything the state missed.
   Acceptance: m12 and m14 resumed from their flight's start match their milestone as
   the boot run does, in minutes; a planted omission from the saved state (an EMS
   mapping, a file position) fails the resumed run; a change to code that ran before
   the save is refused a resume.
2. P1: the two milestones not yet reached ([DOS reference](dos-reference.md#not-yet-reached)).
   The rest of P1 is in place: `make dos-reference` passes 19 pinned milestones.
   Acceptance:
   - A film-room replay: a flight is ended and its film played back in the film room.
   - A Star Destroyer battle, or the heaviest combat scene a reachable pilot state allows,
     chosen by a measured cost. Instructions per frame rank scenes only if the flight does
     not pace its frames, which is not yet known.
3. P8, speed ([port plan](port-plan.md#p8-speed-gate-7)), after items 1 and 2: the fidelity
   checks it reruns at every step resume from a milestone (item 1), and its combat window
   is the heaviest scene of item 2. First step: copy SWOTL's `tools/cost_meter.py`,
   `cost_model.json`, `profile_report.py`, `profile_tree.py`, `ab_runs.py`, the `BENCH`
   fixture method and `docs/perf-method.md`; pin the FS-UAE build; meter the menus, a quiet
   flight, the heaviest combat scene and an EMS-heavy scene on the 68030 model.
   Acceptance of the first step: each window's meter repeats on a matched workload within
   its measured spread, and a planted slowdown in one generated routine moves its window
   and its profile row; frame-time targets are then set with the owner.
4. The x86 oracle under the cell-walk tests (`tests/x86_diff.py` Oracle.run): with
   `--seed 7` a walk case's x86 store faults at an unmapped address and the oracle then
   reads its recorded writes back, raising UC_ERR_READ_UNMAPPED (the same at P4's commit).
   Acceptance: `tests/m68k_blocks.py` completes for seeds 1–8; a faulting store is
   compared as an exception, not a crash.
5. Postponed (owner decision 2026-11-04); optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
