# Open work

Steps of the [port plan](port-plan.md), in order; P6–P10 follow there. The repo rules (P0),
the reference loop (P1, but for the two milestones below), the static and live map (P2),
x86 semantics (P3: `make test-x86`) and the 68020 backend (P4: `make test-m68k`) are in
place.

1. P1: the two milestones not yet reached ([DOS reference](dos-reference.md#not-yet-reached)).
   The rest of P1 is in place: `make dos-reference` passes 17 pinned milestones.
   Acceptance:
   - A film-room replay: a flight is ended and its film played back in the film room.
   - A Star Destroyer battle, or the heaviest combat scene a reachable pilot state allows,
     chosen by a measured cost. Instructions per frame rank scenes only if the flight does
     not pace its frames, which is not yet known.
2. P5: first vertical slice on SWOTL's runtime ([port plan](port-plan.md#p5-first-vertical-slice-gate-5)).
   Acceptance: the LucasArts logo drawn by generated code on the A1200 model, and host
   lockstep to m1 (service log, registers, RAM, framebuffer and DAC). The runtime copy
   also takes what P4 left to it: `translator/irq.py` adapted to the music driver's
   INT 08h handlers, so `make gen` runs the footprint proof again; dispatch by the
   descriptors' resident bit (rows carry descriptor index + 1); the cell-cache segment
   window (`smc_seg_lo`, `smc_seg_limit`) in the runtime's register reload; a loud stop
   when AX=4B03h loads `ADLIB.IMS` at another segment than `DRVSEG`; X-Wing's pointer
   state for `pointer_guest`, or none.
3. Postponed (owner decision 2026-11-04); optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
