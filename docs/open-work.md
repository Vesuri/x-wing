# Open work

Steps of the [port plan](port-plan.md), in order; P3–P10 follow there. Only reference setup
has been done.

1. P0: repo rules.
   Acceptance: SWOTL's standing translator rules are in `AGENTS.md`. Its phase gates and
   translator decisions are copied as X-Wing docs, each decision marked kept or changed.
   SWOTL's commit is pinned in `manifest/references.tsv`.
2. P1: reference loop on SWOTL's tracer.
   Acceptance:
   - SWOTL's DOSBox-X patches and `pc_run.py` are adapted.
   - Runs are unattended and byte-exact with pinned BIOS ticks, on an AdLib-only machine
     (no Sound Blaster) on which the game selects `ADLIB.IMS`.
   - Every software interrupt is logged with registers in and out.
   - Modules are attributed through X-Wing's overlay manager and the music drivers.
   - The root and overlay images are reproduced from the files plus a loader model.
   - The milestones in the plan are reached by guest state, through the heaviest combat
     scene and exit to DOS.
3. P2: static and live map.
   Acceptance: the overlay manager is modelled and checked over every trace. The census in
   the plan (opcodes, EMS, self-modifying code, indirect tables, hooked vectors, ports,
   music driver interface, VGA use) is recorded with counts. Static map and traces agree;
   zero executed bytes are unclassified; `docs/external-surface.md` exists. The Secret
   Weapons of the Luftwaffe translator's fit is confirmed or the gaps listed.
4. Optional, for P8's donor route: make the Macintosh reference reach named milestones and
   map its 68k CODE.
   Acceptance: a bounded run reaches a positively identified game state by guest state,
   writes a framebuffer read from video memory and a trap log, and reproduces their pinned
   hashes. The CODE resources are classified and the trap surface inventoried, ready for a
   correspondence table against the DOS routines.
