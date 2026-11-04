# Open work

Steps of the [port plan](port-plan.md), in order; P4–P10 follow there. The repo rules (P0),
the reference loop (P1, but for the two milestones below) and the static and live map (P2)
are in place.

1. P1: the two milestones not yet reached ([DOS reference](dos-reference.md#not-yet-reached)).
   The rest of P1 is in place: `make dos-reference` passes 17 pinned milestones.
   Acceptance:
   - A film-room replay: a flight is ended and its film played back in the film room.
   - A Star Destroyer battle, or the heaviest combat scene a reachable pilot state allows,
     chosen by a measured cost. Instructions per frame rank scenes only if the flight does
     not pace its frames, which is not yet known.
2. P3: x86 semantics on SWOTL's translator.
   Acceptance: `translator/` copied whole with its x86 tests. The decoder, IR and
   interpreter accept the 80186 forms the census found
   ([external surface](external-surface.md#translator-fit)): `enter`, `leave`, `push imm`,
   `imul r,rm,imm`, shifts by an immediate. The Capstone
   cross-check and the Unicorn differential are clean over every opcode present; sabotage
   plants are caught.
3. Optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
