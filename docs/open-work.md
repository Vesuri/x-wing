# Open work

Steps of the [port plan](port-plan.md), in order; P7–P10 follow there. The repo rules (P0),
the reference loop (P1, but for the two milestones below), the static and live map (P2),
x86 semantics (P3: `make test-x86`), the 68020 backend (P4: `make test-m68k`) and the
first vertical slice (P5: `make test-amiga`, the Amiga replay and the host lockstep to m01)
and the whole game (P6: host lockstep and the Amiga replay over every pinned milestone,
gate 6) are in place.

1. P1: the two milestones not yet reached ([DOS reference](dos-reference.md#not-yet-reached)).
   The rest of P1 is in place: `make dos-reference` passes 19 pinned milestones.
   Acceptance:
   - A film-room replay: a flight is ended and its film played back in the film room.
   - A Star Destroyer battle, or the heaviest combat scene a reachable pilot state allows,
     chosen by a measured cost. Instructions per frame rank scenes only if the flight does
     not pace its frames, which is not yet known.
2. Copy-free EMS mapping in place of SWOTL's map-by-copy (`src/runtime/ems.c`).
   Acceptance: no EMS map copies a page; the host lockstep to m01 still passes.
3. The x86 oracle under the cell-walk tests (`tests/x86_diff.py` Oracle.run): with
   `--seed 7` a walk case's x86 store faults at an unmapped address and the oracle then
   reads its recorded writes back, raising UC_ERR_READ_UNMAPPED (the same at P4's commit).
   Acceptance: `tests/m68k_blocks.py` completes for seeds 1–8; a faulting store is
   compared as an exception, not a crash.
4. Postponed (owner decision 2026-11-04); optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
