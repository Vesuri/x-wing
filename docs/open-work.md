# Open work

Steps of the [port plan](port-plan.md), in order; P6–P10 follow there. The repo rules (P0),
the reference loop (P1, but for the two milestones below), the static and live map (P2),
x86 semantics (P3: `make test-x86`), the 68020 backend (P4: `make test-m68k`) and the
first vertical slice (P5: `make test-amiga`, the Amiga replay and the host lockstep to m01)
are in place.

1. P1: the two milestones not yet reached ([DOS reference](dos-reference.md#not-yet-reached)).
   The rest of P1 is in place: `make dos-reference` passes 19 pinned milestones.
   Acceptance:
   - A film-room replay: a flight is ended and its film played back in the film room.
   - A Star Destroyer battle, or the heaviest combat scene a reachable pilot state allows,
     chosen by a measured cost. Instructions per frame rank scenes only if the flight does
     not pace its frames, which is not yet known.
2. P6: the milestones after the copy-protection screen, checked from the bypass on
   ([port plan](port-plan.md), P6). The bypass is checked at the screen's return
   (`tests/host_run.py --milestone m03p-protection-passed --bypass`), but the references
   past it answer the screen, whose EMS map calls leave the resource mapping differently,
   so byte-exact lockstep from the hook on fails at the first EMS map after the return.
   Acceptance: m04-registration and the later milestones are reached by the bypassed port
   with a check against the reference that holds across that mapping difference, and a
   control in which the bypass leaves a wrong answer fails.
   On the Amiga (a1200-040) the bypassed port passes the registration desk and stops
   on the way into a mission with `transfer into untranslated code` at CS:IP 522A:1B04.
3. The music driver's interrupt-level paths the P5 proof defers or allows
   ([design](design.md), owner decisions 2026-11-05).
   Acceptance: the driver's far callback (ADLIB.IMS +006B6, `annotations/irq-stops.csv`)
   runs at interrupt level in flight with the footprint proved through its re-entry into
   the driver, and the stack words that re-entry and request 0Fh queue (`irq.py`
   STACK_COPIES) equal the reference's in a host lockstep that queues them.
4. Copy-free EMS mapping in place of SWOTL's map-by-copy (`src/runtime/ems.c`).
   Acceptance: no EMS map copies a page; the host lockstep to m01 still passes.
5. The x86 oracle under the cell-walk tests (`tests/x86_diff.py` Oracle.run): with
   `--seed 7` a walk case's x86 store faults at an unmapped address and the oracle then
   reads its recorded writes back, raising UC_ERR_READ_UNMAPPED (the same at P4's commit).
   Acceptance: `tests/m68k_blocks.py` completes for seeds 1–8; a faulting store is
   compared as an exception, not a crash.
6. Postponed (owner decision 2026-11-04); optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
