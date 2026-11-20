# Phases and gates

Copied from Secret Weapons of the Luftwaffe (SWOTL) `docs/phases.md` at
`658fc602e94f773456e06ff0ef1631981905967e`, adapted to X-Wing.

Each gate must pass before work of the next phase is committed. Exit criteria name
generated-code coverage, not pictures. Later changes rerun only the affected gates
(`AGENTS.md`, Validation scope). Completed phases need no blanket revalidation for an
isolated subsystem change. The [port plan](port-plan.md) steps carry the work for each
gate. P0 (repo rules) comes before gate 1, and P7 (AdLib sound) and P10 (Sound Blaster PCM)
have their own gates in the plan. P10 is worked ahead of gates 7 and 8 (owner decision 2026-11-20, `docs/design.md`).

| # | Step | Phase | Exit | From SWOTL |
|---|---|---|---|---|
| 1 | P1 | PC reference loop | The original runs unattended from a disposable copy of the installed game, with deterministic input and pinned BIOS ticks. The root image and each overlay are captured at a named state, and each capture is reproduced from the files plus the loader semantics. | Kept |
| 2 | P2 | Static/live map | X-Wing's overlay manager, overlay load areas, entry points, indirect targets, interrupts, ports, VGA use and music-driver interface are mapped. Static map and traces agree, and no executed byte is unclassified. | Changed: X-Wing's manager instead of PLINK; the music drivers added |
| 3 | P3 | x86 semantics | Decoder and IR cover every opcode present, 186/286 forms included. The randomized instruction and short-block differential against Unicorn is clean. | Changed: 186/286 forms |
| 4 | P4 | 68020 backend | Generated blocks match the x86 oracle on the host 68k core. The audits pass: no unexpected spills, full-flag materializations or dispatcher exits. | Kept |
| 5 | P5 | First vertical slice | A traced subgraph runs on the Amiga model from generated code only, with the minimum runtime. RAM and frame match the reference at a named point. | Changed: 68030 model instead of A1200 |
| 6 | P6 | Whole game | All modules are translated and the runtime surfaces are complete. Lockstep against DOSBox-X is clean over the reference milestones. The coverage report shows the HLE share and zero unclassified. The copy-protection bypass oracle passes. | Changed: the bypass oracle added |
| 7 | P8 | Performance | Profiled on the 68030 model and checked on a 68040. Optimizations go in the translator or `annotations/hle.csv` only. All relevant fidelity gates stay green. | Changed: target CPUs; native rows in `hle.csv` |
| 8 | P9 | Package | WHDLoad slave, an installer for the user's own data, and the release audits, including the CPU matrix and the minimum Fast RAM of the version started without WHDLoad. | Changed: CPU matrix and memory measurement |
