# Open work

Steps of the [port plan](port-plan.md), in order; P5–P10 follow there. The repo rules (P0),
the reference loop (P1, but for the two milestones below), the static and live map (P2)
and x86 semantics (P3: `make test-x86`) are in place.

1. P1: the two milestones not yet reached ([DOS reference](dos-reference.md#not-yet-reached)).
   The rest of P1 is in place: `make dos-reference` passes 17 pinned milestones.
   Acceptance:
   - A film-room replay: a flight is ended and its film played back in the film room.
   - A Star Destroyer battle, or the heaviest combat scene a reachable pilot state allows,
     chosen by a measured cost. Instructions per frame rank scenes only if the flight does
     not pace its frames, which is not yet known.
2. P4: 68020 backend on SWOTL's lowering ([port plan](port-plan.md#p4-68020-backend-gate-4)).
   Acceptance: SWOTL's m68k differential, block test, sabotage, guards and audits copied;
   `lower.py`, `emit.py` and `gen.py` adapted to X-Wing (`LOADSEG`, the 80186 forms,
   the overlay manager's residency, module names). Blocks match on Unicorn 68020 from
   every traced leader, the audits pass, and generation is byte-identical with the G1
   hash header checked.
3. Postponed (owner decision 2026-11-04); optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
