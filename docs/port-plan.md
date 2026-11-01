# Port plan

X-Wing reaches the Amiga the way Secret Weapons of the Luftwaffe did: the original x86 is
translated offline to 68020 assembly and linked with a hand-written runtime and Amiga
platform layer. SWOTL's translator, oracles, harnesses, runtime, platform code and release
tooling are copied at a pinned commit and adapted; nothing they already do is rewritten.
Steps are SWOTL's hard phase gates in order. `docs/open-work.md` carries the current step.

SWOTL is `Secret Weapons of Luftwaffe`, pinned at `658fc602e94f773456e06ff0ef1631981905967e`
(release 0.93). Paths below are SWOTL paths unless they start with `X-Wing:`.

## What SWOTL's history says to do differently

SWOTL produced pixels from generated code 28 hours after its first commit and was playable
after 3 days. Most of the remaining 23 days before 0.90 went to speed (about half of all
commits), much of it undoing early choices. X-Wing makes these choices on day one:

| Day-one choice | What SWOTL did late | SWOTL evidence |
|---|---|---|
| Memory contract v2: byte-reversed guest RAM, biased segment bases, SP/BP mirrored as offset ^ 7FFFh, undefined upper register words | Little-endian RAM with swaps, zero-extended registers; redesigned after release (R1b, R4, R5) | `docs/speed-plan.md` §5, commits 10-09 to 10-11 |
| Asynchronous timer interrupt: the guest INT 08h handler runs from the CIA-B tick when guest IF is set, proved disjoint by `translator/irq.py`; sync points exist only in the test harness | Loop-head polls cost 8.6–11.7% of CPU and blocked six native routines; removed by irq-plan I1–I11 | `docs/irq-plan.md`, `5bec0b6`, `f790ab0` |
| EMS map as cheap as a PC page-table change: long-word copies, identical remaps skipped, or no copy at all | Byte-wise 2×16 KB copies were 25% of CPU in bomber scenes, found on 10-23 | `e19a510` (F1, −27.7%) |
| Full machine takeover; dirty rows from the graphics code's own A000h stores; present at the game's per-frame call; two Chip bitmaps with their own copper lists | Display rebuilt four times (WritePixelArray8, timed c2p, dirty rows, double buffer, frame boundary) | `749b4ba`, `90ae46d`, `a86b15c`, `deec51c` |
| Deterministic cost meter and fixed-work bench before any speed step; price in code bytes and memory accesses (cycles ≈ 1.09·bytes + 2.27·reads + 3.07·writes) | Round 1 judged on frame times: trajectory modes and ±0.7% layout noise made verdicts noise | `docs/speed-plan.md` §5–6, M1 `b9b6374` |
| Profile several heavy scenes from the start, not the opening frames | 2.5 weeks tuned on one fixture | flyby profile `4838add` |
| Worst-case sound effect priced first; effects prerendered at start-up by running the original driver | Live FM synthesis; one cannon shot cost ~19 M cycles; prerendering came after release | `b87259e`, `8f963ac` |
| Exit to DOS, save files and every input device are milestones before the first release | EMS release (AH=45h), mode 3 on exit, mouse per request, joystick axes all fixed after 0.90 | `c3b06de`, `a1ddde0`, `4f2e480` |
| Emulator builds pinned before the first baseline | FS-UAE x86_64 → arm64 invalidated every number | `f10fde2` |
| Gates chosen by what changed; Unicorn never hooked per instruction | Full gates 66–82 min; per-instruction hooks 291 s vs 43 s | `d4d254e`, `9d7600d` |
| Self-modifying code regions found in the map; cached cell walk with exact invalidation; every indirect transfer into them range-checked | Cell walk, then counted runs, then cell cache; a `call dx` crash after two minutes of play | `0d781dc`, `ccfa585`, `0020902`, `df529b7` |

## X-Wing facts that change the work

| Fact | Evidence | Consequence |
|---|---|---|
| `XWING.EXE` 269,237 B, `FRONTEND.OVL` 537,230 B, `FLIGHT.OVL` 249,118 B: about 2.5× SWOTL's x86 | MEASURED | More code to classify; more 68k code (see memory) |
| Each `.OVL` is a sorted table of 4-byte segment:offset fixups (1,696 and 1,212) followed by code at the next paragraph, the same layout as SWOTL's PLINK overlays | MEASURED | The file half of `tools/swotl_model.py` applies |
| The overlay manager is not SWOTL's Phoenix PLINK: no Phoenix copyright, different messages ("Cannot find/Open error/Read error on overlay file") | MEASURED | Reverse and model a new manager; `tools/plink_check.py` is rewritten |
| `FRONTEND.OVL` holds 186+ instructions: 396 `enter n,0` and 965 `leave; ret` byte patterns (about 8 and 33 expected by chance); `FLIGHT.OVL` 64 and 1 | MEASURED patterns; opcode use INFERRED | SWOTL's decoder rejects 0Fh, C0h/C1h, 68h/6Ah, C8h/C9h (`translator/decode.py`); add 186/286 forms |
| Six MZ music drivers (`ADLIB`, `ROLAND`, `GMIDI` and their `_W` variants, 19–26 KB) loaded at run time; `.LFD` music resources | MEASURED; iMUSE and the `_W` digital variants INFERRED | One more module class to translate, as SWOTL translated SPAZ |
| Digitised speech and effects ("Spoken Text" option) through the Sound Blaster | MEASURED option; SB use INFERRED | SWOTL has no DSP, DMA or SB IRQ model: new runtime work |
| 896K of EMS used | installer, MEASURED | EMS cost decision is critical |
| Copy-protection question depends on the DOS clock and CPU speed | MEASURED ([DOS reference](dos-reference.md)) | Pinned clock in the reference; the port runs the original check |
| Microsoft C 1990 run-time, as SWOTL | MEASURED | SWOTL's `annotations/runtime.csv` names transfer by signature |
| Macintosh demo's 68k CODE | [Macintosh reference](mac-reference.md) | Donor of native routines, as TFH's slave routines were for SWOTL (R35–F3b) |

Memory (INFERRED): SWOTL turned about 406K of x86 into 1.36 MB of 68k code and used 1.06 MiB of
guest RAM. At the same ratio X-Wing needs about 3.5 MB of code, 1 MiB of guest RAM and at
least 896K of EMS store: about 6 MB of Fast RAM before caches. Its 8 MiB Fast floor is
therefore tight; the target decision (P0) settles it.

## Steps

Each step lists what is copied, what is adapted, what is new, and the gate. A step's
gate passes before the next step's work is committed.

### P0. Owner decisions and repo rules

- Owner: Amiga target (CPU, chipset, Chip/Fast RAM floor; SWOTL: A1200, 68020, AGA,
  8 MiB Fast, 68030 recommended), sound scope (AdLib music and effects, SB digital,
  Roland/GM out?), copy-protection handling in the port, Mac donor scope.
- Copy into X-Wing's `AGENTS.md`: SWOTL's standing translator rules (guest code only as
  translator output, runtime named by surface item, HLE table, hard phase gates, loud stops,
  "never compare the port with itself") and validation-scope rules.
- Copy `docs/phases.md` (gates 1–8) and `docs/translator-design.md` (D1–D16) as X-Wing
  docs. Each decision is marked kept or changed for X-Wing (D2 overlays, D8 interrupts, D9
  display, D10 sound change).
- Record SWOTL's commit in `X-Wing:manifest/references.tsv`. Copied files keep a one-line
  provenance header naming SWOTL and the commit.
- Upstream to AmigaXDev the generic lessons it lacks: asynchronous IRQ instead of polls,
  EMS paging cost, the SMC cell cache, heavy-scene profiles, memory contract before mass
  generation. Then `make share`.

Gate: owner decisions in `docs/design.md`; rules and copied docs committed.

### P1. Reference loop (gate 1)

- Copy: `tools/patches/dosbox-x-swotl-*.patch` (12 patches, same DOSBox-X tag
  `4f19017c` as X-Wing's tree), `tools/pc_run.py`, `tools/reference.py`,
  `reference/milestones.csv` format, `tools/trace_summary.py`, `tools/snap_png.py`.
- Adapt:
  - Rename `SWOTL_*` to `XWING_*`.
  - Arm the tracer at `XWING.EXE`'s MZ entry.
  - Attribute code to modules through X-Wing's overlay manager and the IMS driver loads,
    not PLINK.
  - Replace the DOS `date`/`time` commands with the pinned BIOS tick count (date and
    host-clock patches). Re-derive the copy-protection answer under it.
  - Keep `X-Wing:tools/patches/dosbox-x-xwing-script.patch` only where visit-count keys
    (`XWING_KEYS=MODULE+HEX#N=key`) cannot serve, such as the installer.
- New:
  - Milestones m0…: logo, copy protection answered, registration, concourse, each room
    (pilot proving ground, historical combat, tour of duty, film room, tech room), first
    training flight, a first mission flight, the heaviest combat scene found (Star
    Destroyer battle), a film-room replay, saving a pilot, exit to DOS.
  - Sound on: SB with AdLib, as installed.
- Gate:
  - Unattended runs repeat byte-exactly.
  - `events.csv` has `svc`/`svc_ret` for every software interrupt.
  - The root and overlay images are reproduced from the files plus a loader model:
    `tools/load_image.py` adapted, with a new `tools/xwing_model.py` from
    `swotl_model.py`'s file half.

### P2. Static and live map (gate 2)

- Copy: `tools/sweep.py` (recursive descent, never linear), `code_writes.py`,
  `surface.py`, `ovl_info.py`, `ghidra_import.py`, `ghidra_scripts/MarkEntries.java`,
  `make map`/`make ghidra`, `docs/indirect-coverage.md` format. Also the `annotations/`
  CSV schemas: `entries`, `runtime`, `indirect`, `tables`, `self-modifying`, `flags`,
  `hle` (empty), `irq-*`.
- Adapt: `plink_check.py` becomes a checker of X-Wing's manager over every trace. Apply
  `runtime.csv` MS C names by signature.
- New census, each with counts:
  - opcode set per module;
  - EMS calls and map frequency per milestone;
  - self-modifying regions;
  - indirect tables;
  - hooked vectors (INT 08h, 09h, SB IRQ, mouse callback);
  - ports (VGA, PIT, PIC, 201h, 388h, SB 22xh, DMA, MPU 330h);
  - the iMUSE driver call interface;
  - VGA mode use: chained 13h or unchained, page flips, palette writes.
- Gate: static map and traces agree; zero executed bytes unclassified;
  `docs/external-surface.md` written.

### P3. x86 semantics (gate 3)

- Copy `translator/` whole: `decode`, `ir`, `sem`, `interp`, `flags`, `cfg`, `emit`,
  `lower`, `region`, `reuse`, `compact`, `reglive`, `smc`, `irq`, `compute`, `support`,
  `gen`, `check`, `image`. Also copy `tests/x86_diff.py`, `x86_sabotage.py`,
  `test_decode.py`, `uc.py`, `test_oracle_*`, `docs/x86-notes.md` (Unicorn quirks), and
  AmigaXDev's patched Unicorn.
- Adapt: add the 186/286 forms the census found (`enter`, `leave`, `push imm`,
  `imul r,rm,imm`, shifts by immediate, `pusha`/`popa`, `bound`, `ins`/`outs` if
  executed) to decode, IR and interpreter. Extend the forms, space and boundary corpora.
- Gate: Capstone cross-check and Unicorn differential clean over every opcode present;
  sabotage plants caught.

### P4. 68020 backend (gate 4)

- Copy: `tests/m68k_diff.py`, `m68k_blocks.py`, `m68k_sabotage.py`, `test_guards.py`,
  `tests/audit.csv`, and the lowering with the memory contract v2 as SWOTL ends with it.
- Adapt:
  - `lower.py`: `LOADSEG` and the new forms.
  - `emit.py`: module tags, the graphics-code store marking for D9, and `overlay_table`
    for X-Wing's residency.
  - `cfg.py`: X-Wing's manager calls.
  - `gen.py`: names.
- Gate: blocks match on Unicorn 68020 from every traced leader; audits pass; generation is
  byte-identical and the G1 hash header checks.

### P5. First vertical slice (gate 5)

- Copy:
  - `src/runtime/` (`dos.c`, `machine.c`, `ems.c`, `ports.c`, `video.c`, `input.c`,
    `pointer.c`, `runtime.h`, `platform.h`, `rt_entry.s`);
  - `src/platform/host/`;
  - `src/platform/amiga/` without `compute_*`, `tfh_paula` and `Swotl.*` (which becomes
    `XWing.*`);
  - the vendored framework, Kalms c2p and `amiga/` harness scripts;
  - `tests/host_run.py`, `amiga_replay.*`.
- Adapt:
  - the command tail and environment;
  - copy-free EMS mapping;
  - the frame boundary for D9 (X-Wing's per-frame call);
  - INT 09h, as a guest handler if the census shows one.
- Gate: the LucasArts logo drawn by generated code on the A1200 model. Host lockstep to
  m1: service log, registers, RAM, framebuffer and DAC.

### P6. Whole game (gate 6)

- Translate root, both overlays and the selected IMS driver.
- Runtime surfaces complete, exit path included.
- Lockstep clean over every milestone on the host and on FS-UAE (`make test-amiga`).
- The copy-protection check runs as translated original code.
- Gate: all milestones in lockstep; zero unclassified; `indirect-coverage` reviewed.

### P7. Sound

- Copy:
  - `src/platform/amiga/fm_paula.c`, `Audio.cpp` and `fm_effect_run.s`;
  - `src/runtime/sfx.c` (effect capture by running the original driver);
  - `tools/opl_render.cpp` and `fm_check.cpp` (Nuked OPL oracle);
  - the `t-fm*` gates.
- New: an SB DSP, DMA and IRQ model feeding Paula samples, with its oracle the
  reference's captured DSP stream.
- Price the worst-case effect and speech before choosing live or prerendered playback.
- Gate: OPL register streams and DSP streams match the reference per milestone; the FM
  quality gates pass.

### P8. Speed (gate 7)

- Copy before any step: `tools/cost_meter.py`, `cost_model.json`, `profile_report.py`,
  `profile_tree.py`, `ab_runs.py`, the `BENCH` fixture method and `docs/perf-method.md`.
  Pin the FS-UAE build.
- Windows: menus, a quiet flight, the heaviest combat scene and an EMS-heavy scene.
- Translator rewrites already in SWOTL (`region`, `reuse`, `compact`, `reglive`, REP fast
  paths, `align`, `outline`) are on from the start; new work is priced first.
- Native routines only through `annotations/hle.csv`, with owner authorization per
  routine. Mac 68k donors are matched to DOS routines by a correspondence table and
  validated against the DOS oracle, as TFH's routines were (`docs/native-compute.md`).
- Gate: each step keeps fidelity gates green and moves the meter by a measured amount.

### P9. Release (gate 8)

- Copy:
  - `whdload/SwotlSlave.s`, which becomes `XWingSlave.s` (kick31 kickemu, `BOOTDOS`,
    `CACHE` with CACR fallback, `RunCommand` with 16 KiB stack, Help to quit);
  - `tools/package_release.py`, `check_release.py`, `test_whdload.py`,
    `test_release_installer.py`, `install-data`, `tool_icon.py`;
  - `docs/release.md`, `docs/whdload.md`.
- Adapt: the installer reads the user's five floppies (SHA-256 pinned). It unpacks
  `XWING.001`–`.005`, a format not yet identified, natively or by documented means.
- Gate:
  - the CPU matrix (020, 030, 030+MMU, 040, 060) with CACR checks;
  - save, exit and input scenarios;
  - the archive allowlist and the original-bytes scan;
  - a real-hardware pass for mouse, analog and digital joystick.

## Working rules for speed of delivery

- One translator, one fix: a wrong result is fixed in the translator or annotations and
  regenerated; this is also the fastest path.
- Run only the gates a change reaches (SWOTL `AGENTS.md`, "Validation scope").
- Independent work in parallel, without crossing ownership: P1 milestone scripting beside
  P2 census; P3 opcode work beside P5 runtime copy; P7 sound beside P8 meter setup.
- Read SWOTL's doc for a surface before deriving anything; fixes found here that are
  generic go back to AmigaXDev, and SWOTL-relevant translator fixes are noted for SWOTL.

## Schedule estimate (INFERRED)

| Stage | SWOTL | X-Wing estimate | Why |
|---|---|---|---|
| P1–P2 | 20 h | 3–4 days | New overlay manager, 2.5× code, music drivers, SB |
| P3–P5 | 8 h | 1–2 days | Copied translator; 186/286 forms added |
| P6 | 2 days | 1–2 weeks | Larger surface, SB, more milestones |
| P7–P9 | 3 weeks | 1–2 weeks | Day-one choices remove most of SWOTL's rework; X-Wing's 3D is heavier |
