# Port plan

X-Wing reaches the Amiga the way Secret Weapons of the Luftwaffe did: the original x86 is
translated offline to 68020 assembly and linked with a hand-written runtime and Amiga
platform layer. SWOTL's translator, oracles, harnesses, runtime, platform code and release
tooling are copied at a pinned commit and adapted; nothing they already do is rewritten.
Steps are SWOTL's hard phase gates in order. `docs/open-work.md` carries the current step.

Owner decisions (2026-11-01, [design](design.md)) that shape the steps:
- **CPU:** 68030 minimum, 68040 recommended.
- **Memory:** 8 MB Fast RAM is the target. The version started without WHDLoad uses as
  little memory as it can.
- **Sound:** AdLib for music and everything else. Sound Blaster PCM comes later (P10).
- **Copy protection:** bypassed in the port.
- **Mac 68k donors:** an optional route in the speed phase (P8).

SWOTL is `Secret Weapons of Luftwaffe`, pinned at `658fc602e94f773456e06ff0ef1631981905967e`
(release 0.93). Paths below are SWOTL paths unless they start with `X-Wing:`.

## What SWOTL's history says to do differently

SWOTL drew its first picture from generated code 28 hours after its first commit
(`3ceb41a`), and had keyboard, mouse and a host-run flight on day 4. Most of the 23 days
from there to 0.90 (dated 28 October) went to speed, about 40% of all commits, much of it
undoing early choices. X-Wing makes these choices on day one:

| Day-one choice | What SWOTL did late | SWOTL evidence |
|---|---|---|
| Memory contract v2: byte-reversed guest RAM, biased segment bases, SP/BP mirrored as offset ^ 7FFFh, undefined upper register words | Little-endian RAM with swaps, zero-extended registers, flags in memory. Block-local speed steps under that contract yielded 1.19% from a 19.9% group. Redesigned on days 8–10, after mass generation (R1b −1.9%, R4 −2.6%, R5 −2.0%), re-plumbing the harness | `docs/speed-plan.md` §5, `276a0dd`, `f8da724`, `714d61e` |
| Asynchronous timer interrupt: the guest INT 08h handler runs from the CIA-B tick when guest IF is set, proved disjoint by `translator/irq.py`; sync points exist only in the test harness | Polls at 2,096 loop heads: 5.15% of the meter's cycles, and native routines needed exact-poll scopes that kept several unpriceable (R39, R43). Removed by irq-plan I1–I11: frames 330 → 300 ms (−9.1%) | `docs/irq-plan.md`, `f790ab0` |
| EMS map as cheap as a PC page-table change: long-word copies, identical remaps skipped, or no copy at all | Two byte-wise 16 KB copies per map, 240K cycles each: about 25% of the cycles in close-bomber windows, found by the flyby profile on 10-23 | `docs/speed-plan.md` F0, `e19a510` (F1, −27.7%) |
| Full machine takeover; dirty rows from the graphics code's own A000h stores; present at the game's per-frame call; two Chip bitmaps with their own copper lists | Display rebuilt four times (WritePixelArray8, timed c2p, dirty rows, double buffer, frame boundary) | `749b4ba`, `90ae46d`, `a86b15c`, `deec51c` |
| Deterministic cost meter and fixed-work bench before any speed step; price in code bytes and memory accesses (cycles ≈ 1.09·bytes + 2.27·reads + 3.07·writes) | Round 1 judged on frame times: trajectory modes and ±0.7% layout noise made verdicts noise | `docs/speed-plan.md` §5–6, M1 `b9b6374` |
| Profile several heavy scenes from the start, not the opening frames | 2.5 weeks tuned on one fixture | flyby profile `4838add` |
| Worst-case sound effect priced first; effects prerendered at start-up by running the original driver | Live FM synthesis; one cannon shot cost ~19 M cycles; prerendering came after release | `b87259e`, `8f963ac` |
| Exit to DOS, save files and every input device are milestones before the first release | EMS release (AH=45h), mode 3 on exit, mouse per request, joystick axes all fixed after 0.90 | `c3b06de`, `a1ddde0`, `4f2e480` |
| Emulator builds pinned before the first baseline | FS-UAE x86_64 → arm64 invalidated every number | `f10fde2` |
| Gates chosen by what changed; Unicorn never hooked per instruction | Serial checks: `make test` 22:50 → 4:38 in parallel; Unicorn's count hook made a host run 291 s instead of 43 s; change-scoped gates only from day 19 | `9d7600d`, `d4d254e` |
| Self-modifying code regions found in the map; cached cell walk with exact invalidation; every indirect transfer into them range-checked | Cell walk, then counted runs, then cell cache; a `call dx` crash after two minutes of play | `0d781dc`, `ccfa585`, `0020902`, `df529b7` |

## X-Wing facts that change the work

| Fact | Evidence | Consequence |
|---|---|---|
| `XWING.EXE` 269,237 B, `FRONTEND.OVL` 537,230 B, `FLIGHT.OVL` 249,118 B: about 2.5× SWOTL's x86 | MEASURED | More code to classify; more 68k code (see memory) |
| Each `.OVL` is a sorted table of 4-byte segment:offset fixups (1,696 and 1,212) followed by code at the next paragraph, the same layout as SWOTL's PLINK overlays | MEASURED | The file half of `tools/swotl_model.py` applies |
| The overlay manager is not SWOTL's Phoenix PLINK: no Phoenix copyright, different messages ("Cannot find/Open error/Read error on overlay file") | MEASURED | Reverse and model a new manager; `tools/plink_check.py` is rewritten |
| `FRONTEND.OVL` holds 186+ instructions: 396 `enter n,0` and 965 `leave; ret` byte patterns (about 8 and 33 expected by chance); `FLIGHT.OVL` 64 and 1 | MEASURED patterns; opcode use INFERRED | SWOTL's decoder rejects 0Fh, C0h/C1h, 68h/6Ah, C8h/C9h (`translator/decode.py`); add 186/286 forms |
| Six MZ music drivers (`ADLIB`, `ROLAND`, `GMIDI` and their `_W` variants, 19–26 KB) loaded at run time; `.LFD` music resources | MEASURED; iMUSE and the `_W` digital variants INFERRED | One more module class to translate, as SWOTL translated SPAZ |
| Digitised speech and effects ("Spoken Text" option) through the Sound Blaster | MEASURED option; SB use INFERRED | SWOTL has no DSP, DMA or SB IRQ model: new runtime work, deferred to P10 |
| 896K of EMS used | installer, MEASURED | EMS cost decision is critical |
| Copy-protection question depends on the DOS clock and CPU speed | MEASURED ([DOS reference](dos-reference.md#copy-protection)) | Pinned BIOS ticks in the reference, which answers from the manual; the port bypasses the check (P6) |
| Microsoft C 1990 run-time, as SWOTL | MEASURED | SWOTL's `annotations/runtime.csv` names transfer by signature |
| Macintosh demo's 68k CODE | [Macintosh reference](mac-reference.md) | Optional donor of native routines in P8, as TFH's slave routines were for SWOTL (R35–F3b) |

## Sibling: Wing Commander 2

Wing Commander 2 copied the same SWOTL commit and took X-Wing's 80186 front end, 68020
lowering, host lockstep and Amiga replay (its `docs/upstream.md`, "From X-Wing"). Before
building something listed here, start from the other port's commit. Its hashes are as of
Wing Commander 2 `e84cfe7` (its P6).

| Work | Where it is | Use |
|---|---|---|
| Copy-free EMS: frame pages copied in on first access, guarded ES accesses run on the store page | Wing Commander 2 `bfaebe3`, `c31004f`, `tools/ems_frame_profile.py` | Kept, with X-Wing's DS guard in listed routines (translator design, EMS model). X-Wing's `52be993` (a page mapped at two frame pages is one memory) is kept; the other port keeps two copies |
| IRQ footprint proof for more than one handler (`translator/irq.py`) | Wing Commander 2 `66e6de5`; X-Wing `6e1e46b` (the music driver's callback) | Extended in both ports separately; compare before either changes it again |
| FM on Paula: SWOTL's `fm_paula.c`, `Audio.cpp`, `fm_effect_run.s` copied unchanged | Wing Commander 2's import `e6e9808`: its music plays; effect capture (`sfx.c`) and the FM gates are its open work. X-Wing's P7: the FM gates on its music, additive channels at their operators' levels, `fm_check` on vibrato patches | Wing Commander 2 starts its FM gates from X-Wing's; the effect capture is adapted once and shared |
| Display and input: SWOTL's copper display, double buffer, changed-row C2P, key map, mouse, joystick | X-Wing, copied from SWOTL at P5 (`49b792b`); Wing Commander 2's open work (its P6b) | Wing Commander 2 starts from X-Wing's |
| Sound Blaster DSP, DMA channel 1 and IRQ 7 model | Wing Commander 2's open work (its P6) | P10 starts from it |
| Asynchronous timer interrupt in place of loop-head polls | Wing Commander 2's C2; SWOTL's irq-plan measured the polls at 5.15% of cycles | P8 |

X-Wing's P6 work Wing Commander 2 has not taken yet: service registers and RAM from dead
stack exempted (`40030a3`, `3dca119`, owner decisions 2026-11-09 and 2026-11-10) and the
replay's exempt table (`892b8d5`); flight logs in bounded memory (`9c59569`); parallel runs
from the entry (`2b047e5`); the shown frame at a mid-frame label (`a3f71a9`); the Amiga
program on the boot volume's `C:` so a find-first scan of the game directory counts the
guest's entries (`b2c1c29`; its launchers copy the program into the game directory); and
DOS findfirst directories, INT 16h enhanced keys, INT 21h AH=0Eh and 2Fh.

## Memory

The original ran in 2 MB: 640K conventional memory plus 896K of EMS. SWOTL turned about
406K of x86 into 1.36 MB of 68k code and used 1.06 MiB of guest RAM. At that ratio X-Wing
needs about 3.5 MB of code, 1 MiB of guest RAM and 896K of EMS store: about 6 MB of Fast
RAM before data and caches (INFERRED). That fits the 8 MB target with little margin. The
version started without WHDLoad takes only what it uses. Every build reports its Chip and
Fast high-water mark from P5 on (SWOTL `tools/hunk_size.py`), so growth is visible when it
happens.

Ways to use less, each measured before it is adopted:
- **Overlay code per residency:** load an overlay's translated code only while the guest
  has that overlay resident. FRONTEND and FLIGHT are both large; P2 shows whether they are
  ever resident together. SWOTL keeps all overlay code resident (D2).
- **Smaller code:** the cost model counts code bytes, so size and speed point the same way.
  Use SWOTL's `outline` annotations for cold paths.
- **Exact guest memory:** EMS store and guest RAM sized to what the game allocates and
  reaches, not to the full 1 MiB space.
- **Effect samples:** prerendered effects take Chip RAM (465 KB in SWOTL); price them
  against live synthesis in P7.

## Steps

Each step lists what is copied, what is adapted, what is new, and the gate. A step's
gate passes before the next step's work is committed.

### P0. Repo rules and AmigaXDev lessons

- Copy into X-Wing's `AGENTS.md`:
  - SWOTL's standing translator rules: guest code only as translator output, runtime named
    by surface item, the HLE table, hard phase gates, loud stops, "never compare the port
    with itself";
  - its validation-scope rules.
- Copy `docs/phases.md` (gates 1–8) and `docs/translator-design.md` (D1–D16) as X-Wing
  docs. Each decision is marked kept or changed for X-Wing (D2 overlays, D8 interrupts, D9
  display, D10 sound change).
- Record SWOTL's commit in `X-Wing:manifest/references.tsv`. Copied files keep a one-line
  provenance header naming SWOTL and the commit.
- Upstream to AmigaXDev the generic lessons it lacked: asynchronous IRQ instead of polls,
  EMS paging cost, the SMC cell cache, heavy-scene profiles, memory contract before mass
  generation. Then `make share`.

Gate: rules and copied docs committed; AmigaXDev's docs carry the lessons.

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
  - Sound: AdLib only until P10. DOSBox-X runs without a Sound Blaster and with OPL at
    388h. The census confirms that the game then selects `ADLIB.IMS` and never touches the
    DSP. Sound Blaster references are recorded in P10.
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
  - `tests/host_run.py`, `irq_monitor.py`, `rep_replay.py`.
- Adapt:
  - the command tail and environment; paths under `C:\XWING` and relative paths
    resolve against the game directory; the `EMMXXXX0` device's open, IOCTL and close;
    the BIOS data area from the m00 snapshot (CRTC base 03D4h included);
  - EMS: Wing Commander 2's lazy frame pages replace SWOTL's map-by-copy
    ([translator design](translator-design.md), EMS model); X-Wing's string ranges,
    reversed store slots and the DS guard in the routines that run with DS in the
    frame (`annotations/ems-ds.csv`) keep the guest's frame accesses on the store
    pages: the flight milestones copy no page. X-Wing maps a page at two
    frame pages at once (DOSBox-X: one memory); with no live copy both read its store
    page, and live copies are merged against the store at the next map call, stopping
    on a byte written differently through two of them; `host_run.py` checks every
    guest read through a live copy against the other live copies (`EMS: ... differ`);
  - the frame boundary for D9 (X-Wing's per-frame call);
  - INT 09h: the BIOS's handler (the census shows no guest one);
  - `translator/irq.py` to the music driver's INT 08h handlers, the driver's flight
    callback and its re-entries included ([design](design.md)); `tests/irq_monitor.py`
    checks every access;
  - dispatch residency by descriptor index, the cell-cache segment window and the
    driver's load segment (`DRVSEG`) as P4 emits them; m01 dispatches none of the seven
    CS:IPs that overlay rows share, so `tests/host_run.py` probes `rt_lookup` on each
    with one overlay resident at a time;
  - pointer state: none (X-Wing keeps no pointer state for `pointer_guest`);
  - REP slices: the reference records where DOSBox-X restarts a REP
    (`tools/reference.py --polls` adds `--rep-chunks`), and `tests/rep_replay.py`
    replays them in a diagnostic host image so an interrupt inside a REP lands where it did;
  - the Amiga replay (SWOTL's `tests/amiga_replay.*`, owner decision 2026-11-06): a
    diagnostic image (`XWING_REPLAY`, sync mode) delivers the reference's interrupts at
    their recorded poll points, its REP slices, VGA status reads (`trace/retrace.csv`)
    and calendar inputs; no joystick and no real-video capture; the service history is
    checked by a cumulative hash every 256 events and the REP slices are a varint stream.
    The reference data (2.3 MB at m01) leaves the guest block no room in the 8 MB of Fast
    RAM, so the replay machine adds a 64 MB Zorro III board (m14's is 15 MB); the production image keeps
    the 8 MB target. A program return before the label is a fixture stop.
- Gate: the LucasArts logo drawn by generated code on the 68030 model: the replay
  (`make test-amiga`) matches registers, RAM, DAC and the shown screen at m01. Host
  lockstep to m1: service log, registers, RAM, framebuffer and DAC.

### P6. Whole game (gate 6)

- Translate root, both overlays and `ADLIB.IMS`.
- Runtime surfaces complete, exit path included.
- Lockstep clean over every milestone on the host and on FS-UAE (`make test-amiga`).
- Host lockstep (`tests/host_run.py --milestone NAME`) against references recorded at the
  current poll points: m00–m02 plain; m03, m03c and m03q with `--screen`; m03p with
  `--bypass` (the oracle below); every milestone past the screen with `--bypass` against
  its `hostb-` reference. The service logs are compared as they run and the REP slices are
  held in packed arrays, so a flight's 65 million service events and 12 million slices fit
  in memory. Service registers loaded from dead stack, and RAM bytes stored from it, may
  differ ([design](design.md)).
- Exit path: the exit to DOS frees ES = 3752h, inside the program's own block; DOS answers
  error 9 (no MCB below it), and so does `dos.c`.
- Copy-protection bypass:
  - The check is the protection screen, FRONTEND.OVL 3273:3470, called once from
    3273:0AFF. It picks a question (`[6562h]:0E06`), shows its glyphs (`[6562h]:0000`),
    freezes them (`:003A`), counts wrong tries (`:000E`) and returns AX = 1 when the
    lowercased answer equals the question's code-name. No other code reads that state.
  - The bypass is one `annotations/hle.csv` entry, `copy_protection`, at the call: the
    screen is never built or shown, and `src/runtime/protection.c` leaves the state of a
    correct first answer (the reference's question 16, page 11, BRIGGIA). The screen's
    code is still translated.
  - Oracle (owner decision 2026-11-06): `tests/host_run.py --milestone
    m03p-protection-passed --bypass` runs in lockstep to the hook, then compares RAM and
    registers at the return with the reference's after BRIGGIA. The screen's own state
    is exempt with evidence (`tests/bypass-screen.csv`, bytes that differ between two
    correct-answer references, the stack below SP, the scratch registers, the mouse
    arrow, the EMS page frame). `--bypass --sabotage` leaves a wrong try, unfrozen glyphs
    or another question, and each must fail.
  - Past the return (owner decision 2026-11-08): the game reads state the skipped screen
    leaves (the mouse position it recorded, which picks the next menu's EMS pages; the
    music and timer state of its duration; its EMS frame), so the unbypassed references
    cannot be matched. `tools/reference.py --polls --bypass` records the milestones past
    the screen with the same bypass applied in DOSBox-X at the same call
    (`dosbox-x-xwing-bypass.patch`, `XWING_BYPASS`), and `tests/host_run.py --milestone
    <later> --bypass` runs in byte-exact lockstep with them from the start. Control:
    `--bypass --sabotage` at a later milestone leaves AX = 0, a wrong answer, and must
    fail.
  - `tests/host_run.py --screen` (diagnostic): the hook declines, so the translated
    screen runs on the reference's keys and the lockstep stays byte-exact through it
    and on to the later milestones.
- Indirect coverage: the 186 sites the P2 traces never ran are reviewed in
  [indirect coverage](indirect-coverage.md); none is excluded.
- Gate: all milestones in lockstep; zero unclassified; `indirect-coverage` reviewed; the
  bypass oracle passes.
- Passed: all 21 pinned milestones, the combat film m17 among them, in host lockstep
  (`tests/host_run.py`, m15 90,212,532 service events) and in the Amiga replay on the 68030
  model (`tests/amiga_replay.py` in the same modes with `--timeout 14400`, the flights 28800;
  m10, m15 and m17 with `--exempt`);
  `make gen`'s coverage report: 0 unclassified of 99,836 executed instruction starts, HLE 2 (`copy_protection`), self-modified 343 (FLIGHT,
  the D16 cell walk); the bypass oracle at m03p with its three sabotages caught, and the
  wrong-answer control past the screen caught at m04.

### P7. AdLib sound

- Copy:
  - `src/platform/amiga/fm_paula.c`, `Audio.cpp` and `fm_effect_run.s`;
  - `src/runtime/sfx.c` (effect capture by running the original driver);
  - `tools/opl_render.cpp` and `fm_check.cpp` (Nuked OPL oracle);
  - the `t-fm*` gates.
- Adapt: the re-hoster to the OPL use of `ADLIB.IMS` (music) and the game's FM effects.
- Price the worst-case effect before choosing live or prerendered playback, Chip RAM
  included.
- Gate: OPL register streams match the reference per milestone; the FM quality gates pass.
- Music, in place: `fm_paula.c`, `Audio.cpp` (without the TFH samples and prerendered
  effects), `opl_render.cpp`, `fm_check.cpp` and the render, phase, envelope,
  allocation, cache and quality gates are copied; the re-hoster renders additive
  channels at their operators' levels and `fm_check` measures vibrato patches
  ([translator design](translator-design.md#sound-d10)). `check_opl` holds the OPL
  writes to the reference in every host run; `make gates-audio` passes on m01, m02, m06
  and m13; `make test-amiga-audio` plays the music on the 68030 model.
- Effects, in place (prerendered, owner decision 2026-11-15): the capture (`sfx.c`), the
  render (`fm_effect`, `fm_effect_run.s`), and the player (`fx_play.c`, from SWOTL's
  `tfh_paula.c`) with its cache, played from the driver's players; 549,044 Chip bytes
  for the 32 one-shot effects (MEASURED, `make t-amiga-sfx`).

### P8. Speed (gate 7)

- Measurement machine: the 68030 model, as the cycle-exact preset `a1200-030` without its
  MMU (the profiler records nothing on the MMU core); a 68040 run checks the recommended
  machine. Frame-time targets are set with the owner when the first meter numbers exist.
- Copied and adapted ([perf-method](perf-method.md)): `tools/cost_meter.py` (its run is the
  host lockstep check), `cost_model.json` (fit on the 68030), `profile_report.py`,
  `lowering_cost.py`, `profile_tree.py` and `ab_runs.py`; SWOTL's `BENCH` fixture becomes
  the combat film's frames fixture (`tools/perf_film.py`). The FS-UAE build is pinned
  (`manifest/perf-tools.sha256`).
- Windows: menus, a quiet flight, the heaviest combat scene and an EMS-heavy scene.
- Translator rewrites already in SWOTL (`region`, `reuse`, `compact`, `reglive`, REP fast
  paths, `align`, `outline`) are on from the start; new work is priced first.
- Native routines only through `annotations/hle.csv`, with owner authorization per
  routine.
- Optional route, Mac 68k donors: matched to DOS routines by a correspondence table and
  validated against the DOS oracle, as TFH's routines were (`docs/native-compute.md`).
  Taken only where the meter shows the translated routine costs more than the donor.
- Gate: each step keeps fidelity gates green and moves the meter by a measured amount.

### P9. Release (gate 8)

- Copied and adapted for the 0.1 early alpha ([release](release.md), [WHDLoad](whdload.md)):
  - `whdload/XWingSlave.s` from `SwotlSlave.s` (kick31 kickemu, `BOOTDOS`, `CACHE` with
    CACR fallback, `RunCommand` with 16 KiB stack, Help to quit);
  - `tools/package_release.py`, `check_release.py`, `test_whdload.py`,
    `test_release_installer.py`, `release/Install`, `ReadMe` and icons;
  - `tools/install-data`, which unpacks the user's five floppies natively (format:
    `docs/release.md`, "Original data") into the 284 files of the configured DOS install.
  - `tool_icon.py` is not copied: SWOTL's Workbench start check uses it, and X-Wing has no
    such check yet.
- Gate (the 0.1 early alpha passed a reduced gate, `docs/design.md`):
  - the CPU matrix (030, 030+MMU, 040, 060) with CACR checks;
  - WHDLoad on 8 MB Fast; the version started without WHDLoad measured down to its minimum
    Fast RAM, which the ReadMe states;
  - save, exit and input scenarios;
  - the archive allowlist and the original-bytes scan;
  - a real-hardware pass for mouse, analog and digital joystick.

### P10. Sound Blaster PCM

- Record Sound Blaster references: the same milestones with a Sound Blaster 2.0 at 220h,
  IRQ 7, DMA 1 ([DOS reference](dos-reference.md#sound-blaster-p10)), plus the speech and
  digitised-effect scenes. The tracer logs DSP and DMA accesses and the DMA'd bytes.
- Translate the `_W` driver the game selects with a Sound Blaster.
- New: a DSP, DMA and IRQ model whose blocks play as Paula samples. Its oracle is the
  captured DSP stream.
- Gate: DSP command and sample streams match per milestone; AdLib gates unchanged.

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
| P10 | none | 3–5 days | New DSP, DMA and IRQ model; one more driver |
