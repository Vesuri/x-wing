# Open work

In playbook order. Only reference setup has been done.

1. Choose the Amiga target and confirm the approach with the owner.
   Acceptance: target CPU, chipset, memory and release decisions are in `docs/design.md`,
   including how Macintosh 68k routines may be transplanted into the DOS base.
2. Make the DOS reference loop reach named milestones past the intro and capture evidence.
   Acceptance: a bounded run reaches the concourse menu and a first flight frame, both
   identified by guest state, past pilot registration, which the reference already
   reaches. It writes framebuffers read from video memory and an interrupt, file and port
   trace, and reproduces their pinned hashes.
3. Map the DOS program statically and live.
   Acceptance: `XWING.EXE` and the two overlay formats are decoded. The runtime image is
   validated against the reference. The CPU mode, overlay mechanism, interrupt, DOS, EMS
   and device surface are inventoried. The Secret Weapons of the Luftwaffe translator's
   fit is assessed.
4. Make the Macintosh reference reach named milestones and map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
