# Open work

Steps of the [port plan](port-plan.md), in order; P3–P10 follow there. Reference setup and
the repo rules (P0) are in place.

1. P1: the two milestones not yet reached ([DOS reference](dos-reference.md#not-yet-reached)).
   The rest of P1 is in place: `make dos-reference` passes 17 pinned milestones.
   Acceptance:
   - A film-room replay: a flight is ended and its film played back in the film room.
   - A Star Destroyer battle, or the heaviest combat scene a reachable pilot state allows,
     chosen by a measured cost rather than instructions per frame, which the frame cap
     makes constant.
2. P2: static and live map.
   Acceptance: the overlay manager is modelled and checked over every trace. The census in
   the plan (opcodes, EMS, self-modifying code, indirect tables, hooked vectors, ports,
   music driver interface, VGA use) is recorded with counts. Static map and traces agree;
   zero executed bytes are unclassified; `docs/external-surface.md` exists. The Secret
   Weapons of the Luftwaffe translator's fit is confirmed or the gaps listed.
3. Optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
