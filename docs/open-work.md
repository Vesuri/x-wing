# Open work

Deferred until the owner asks for work beyond initial setup, in playbook order.

1. Choose the Amiga target and confirm the approach with the owner.
   Acceptance: target CPU, chipset, memory and release decisions are in `docs/design.md`.
2. Make the reference loop reach named milestones and capture evidence.
   Acceptance: a bounded run reaches a positively identified game state (for example the
   concourse menu or first flight frame) by guest state, writes a framebuffer read from
   video memory and a trap log, and reproduces their pinned hashes.
3. Map the 68k CODE resources and the external surface statically and live.
   Acceptance: the runtime image is validated against the reference, code and data are
   classified, the trap and service inventory is complete, and reused components are pinned.
