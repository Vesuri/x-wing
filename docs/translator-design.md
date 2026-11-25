# Translator design

Copied from Secret Weapons of the Luftwaffe (SWOTL) `docs/translator-design.md` at
`658fc602e94f773456e06ff0ef1631981905967e`.

The decision table below is X-Wing's. The text after it is SWOTL's contract as built. It
becomes X-Wing's contract section by section as P3–P6 of the [port plan](port-plan.md)
copy and adapt the code. Each adapted section is rewritten to X-Wing's state in the
commit that adapts it. Until then, its SWOTL-specific values do not describe X-Wing. These
include `LOADSEG` 0822h, PLINK, RTSVGA, SPAZ, the INT 33h frame boundary, guest offsets
and sizes. Links in the copied text name SWOTL's docs.

P3 copied `translator/` whole and adapted the front end: `image.py`, `decode.py`,
`sem.py` and `cfg.py` (rows below). P4 adapted the back end to X-Wing:
- `lower.py`: the 80186 forms; relocated words add their module's load segment
  (`LOADSEG` 0822h for the root and overlays, `DRVSEG` 522Ah for `ADLIB.IMS`, its
  INT 21h AX=4B03h segment in every reference run); no manager return skip.
- `emit.py`: module tags; CS expressions per module; dispatch rows tagged with the
  overlay segment's descriptor index + 1 (root and driver 0); D9 store marking in
  `FRONTEND` and `FLIGHT` (`VRAM_MODULES`); the INT 00h handler from `entries.csv`; a
  CS store reaches only cell caches of its own overlay file; an undecoded return site
  that ends in a stop has no live flag.
- `smc.py`: X-Wing's region lies above 64 KiB, so the segment check is a window, a low
  segment and a limit (`smc_seg_lo`, `smc_seg_limit`).
- `reglive.py`, `flags.py`: three-operand `imul` writes no DX; a shift count masked to 0
  sets no flag.
- `gen.py`, `check.py`: `xwing-gen 1` headers over `tools/xwing_model.py`.

P5 adapted the rest to the first vertical slice:
- `irq.py`: the footprint proof over `ADLIB.IMS`'s INT 08h handlers (`make gen` runs it,
  `build/gen/irq-footprint.csv`). G is the driver's DS (DRVSEG:0911, paragraph 04D0h);
  the game's DGROUP is root paragraph 3A07. Song data (S) is huge: a segment, or a
  word loaded from memory, plus a carry stays its type, typed by `SEGMENT_WORDS`
  (class, displacement) or, where the displacement is shared, `SEGMENT_LOADS` (site).
  A null far pointer's segment joins as `NULL`. Proved switch tables are followed,
  equality and unsigned branches after `cmp r16,imm` narrow the register, flags of
  interrupted state are tainted rather than fatal until read, and a byte write keeps
  the other byte of a word slot. An unwritten word of the handler's own stack area is
  interrupted state; `DEAD_READS` names one whose value is unused. No such word and no
  stack address may be stored outside the stack. A register half keeps a known low byte
  under an unknown high byte (`mov al,[bp+7]; cbw` after a segment in AX), so a
  request's code stays constant through the driver entry. `CONST_TABLES` are driver
  tables the image initialises and no code writes (the API and voice function tables
  and the voice switch): a load at a known index gives the image's word and a call
  through it keeps that one target of its `irq-hooks.csv` row; `tests/irq_monitor.py`
  fails any write into them. The relocated paragraph 04D0h of the driver's DS is G.
  A byte variable at a constant address shifted by an immediate lowers to a load and a
  `cas.b` that retries if the byte changed, so the CIA tick cannot split the x86
  read-modify-write (the driver's random generator at G:0300); the check accepts that
  form as one commit.
  `annotations/irq-hooks.csv` lists the indirect calls the handler reaches; each
  follows its traced targets and its generated call stops on any other.
  `annotations/irq-stops.csv` lists calls on a deferred interrupt-level path: the
  generated call stops and the proof ends the path (none: the driver's flight callback
  FLIGHT.OVL +19424 and its re-entries into the driver are hooks, `docs/design.md`). An `annotations/irq-sync.csv` row also covers an access the proof
  cannot type, such as a string instruction's implicit operand or an unreached site.
  The rows cover two root clears that run before the driver is loaded and the driver's
  pointer-argument routines that its requests call on the handler's data. The monitor
  lists each uncovered site with its class and span.
- `lower.py`: a `les`/`lds` from a constant address is one `move.l`, because the
  handler writes some far pointers (`check_atomic`). A video-memory store marks its
  segment's signed distance from A000h (the lower half is drawn through ES above A000h).
  `ret` at an `annotations/ret-jumps.csv` site, a pushed continuation, checks the
  popped IP and jumps to it.
- `emit.py`: one section per module (`.text.<module>`) so vasm's branch optimisation
  converges; dispatch rows sorted by absolute CS.
- `cfg.py`: a ret-jump RET seeds its target; any other non-plain RET raises.
- `tests/m68k_blocks.py`, `m68k_diff.py`: `rt_vram_mark` and `rt_vram_mark_short` return (the host lockstep
  checks the marks); a ret-jump RET that pops another IP must stop at `rt_ret_mismatch`.
  The cell-cache cases address a region through each store site's own CS (its
  `code_regions` delta), plant RETs only at cell starts inside the region (X-Wing's runs
  of mov cells continue past its last cell start) and hold the control segments above the
  segment window. Every target of each proved switch table (`indirect.csv`) runs to its
  own label. `tests/m68k_sabotage.py` names four plants inert while the program has no
  outlined ranges or guarded copies (P8 fills those annotations); each run checks that
  they leave the program unchanged, and one that changes it must be caught.

`flags`, `support`, `compute`, `region`, `reuse` and
`compact` are otherwise SWOTL's. The speed annotations (`align`, `outline`,
`seg-repeat`, `bp-regions`) are empty until P8 measures them.

## Decisions for X-Wing

SWOTL's D1–D16 are numbered as in its first design (`11f81ef`). "SWOTL as built" is the
settled form at the pinned commit.

| # | Decision | SWOTL as built | X-Wing |
|---|---|---|---|
| D1 | Calls and returns | Guest stack byte-exact; guest call is `jsr`, return checks the popped IP or CS:IP against the return site | Kept |
| D2 | Overlays | (a) All translated modules resident; the guest's PLINK manager runs translated and loads overlay bytes into guest RAM | Changed: X-Wing's own overlay manager, modelled in P2, runs translated; dispatch rows follow its residency. Overlay code loaded per residency is a memory option, adopted only if measured ([port plan](port-plan.md), Memory) |
| D3 | Segments | All computed: ES/SS/DS bases in a1–a3, biased, rebuilt on every segment write | Kept |
| D4 | Registers | Fixed program-wide mapping; SP/BP mirrored as offset ^ 7FFFh; upper words undefined | Kept |
| D5 | Byte order | (b) Byte-reversed guest RAM, no swaps | Kept |
| D6 | Flags | Demand-driven stores; CCR fused with the next reader | Kept |
| D7 | Indirect transfers | Compare chains over known targets; dispatch table; unknown stops | Kept; table seeds come from X-Wing's overlay manager entries instead of PLINK thunks |
| D8 | Interrupts | Guest handlers run translated. Production takes IRQ0 at the CIA-B tick when IF is set, proved disjoint by `translator/irq.py`; sync points only in sync builds | Changed: asynchronous delivery from the start, with no production polls. Handlers for every vector the P2 census finds hooked (INT 09h if present; the Sound Blaster IRQ in P10) |
| D9 | Display | The graphics driver (RTSVGA) translated; its A000h stores mark dirty rows; frame presented at the game's mouse poll (INT 33h AX=3); Kalms c2p into two Chip bitmaps | Changed: the code that writes A000h and X-Wing's per-frame call are found in P2; the frame boundary moves there. The SWOTL-specific mouse scaling and frame cap are re-decided against X-Wing's input. Stores through DS mark rows only in listed code; a DS load of the frame elsewhere marks the whole frame (owner decision 2026-11-23) |
| D10 | Sound | SPAZ translated; OPL writes reach `rt_out8`; FM re-hosted to Paula; effects prerendered | Changed: `ADLIB.IMS` translated for music and FM effects (P7); additive channels re-hosted at their operators' levels (Sound); worst-case effect priced first. Sound Blaster PCM through a DSP/DMA/IRQ model in P10 |
| D11 | Strings | IR loops; REP fast paths when DF and range are provable | Kept |
| D12 | Translator language | Python | Kept |
| D13 | Decoder | Own, cross-checked with Capstone; 186+ opcodes raise | Changed: the 80186 forms the census found are decoded, lifted and checked against Unicorn (P3); the other 186+ opcodes still raise |
| D14 | 68k oracle | Unicorn 68020 | Kept |
| D15 | Memory | (b) Fast RAM required; development on a 68030 model with 8 MiB Fast | Changed: 68030 minimum, 68040 recommended; 8 MB Fast target; the version started without WHDLoad measured down to its minimum ([design](design.md)) |
| D16 | Self-modified code | Regions found in the map; run-time cell walk with an exact cell cache; everything else stops | Kept as a mechanism; X-Wing's regions come from its P2 census |

## SWOTL contract as built

The translator, runtime and test contract as built. Decisions D1–D16 are
settled where this file states them (D1 memory and calls, D2 overlays, D4
registers, D6 flags, D7 indirect transfers, D8 interrupts, D9 display, D11
strings, D15 memory, D16 self-modified code, D10 sound at the end); speed-plan
§8's decisions are cited as "speed-plan Dn". Speed forms are indexed in
speed-plan.md (SWOTL `docs/speed-plan.md`) §7. Overview and guardrails:
architecture.md (SWOTL `docs/architecture.md`).

### Fixed

#### Components

| Module | Role |
|---|---|
| `translator/image.py` | root, overlay and driver images (`tools/xwing_model.py`), annotations, run-time bytes of self-modified regions |
| `translator/decode.py` | own table-driven decoder: 8086 plus the 80186 forms X-Wing uses (`push imm`, three-operand `imul`, shifts by an immediate, `enter`, `leave`); the other 186+ and FPU opcodes raise |
| `translator/cfg.py` | recursive descent from `annotations/` seeds over the root, overlay segment and driver ranges; CS along flow; thunks resolved by descriptor index, other far targets by the parent chain (a far immediate whose segment word is not relocated is an absolute address and lowers to its named stop); self-modified regions recorded, not decoded |
| `translator/ir.py`, `sem.py` | IR ops; lifting of every decoded instruction |
| `translator/interp.py` | host IR interpreter (the semantics under test) |
| `translator/gen.py` | `make gen`: `build/gen/<module>.ir` and `.s` with hash header; audit against `tests/audit.csv`; coverage report (G6); sizes the R8 alignment pads by assembling the program (vasm) |
| `translator/check.py` | G1 header/digest/regeneration check, G2 lint |
| `translator/lower.py` | one decoded instruction -> 68020 text under the register contract (templates per op family, the 80186 forms included; the IR stays the semantic reference) |
| `translator/flags.py` | flag demand: per-instruction store set and CCR fusion with the next reader, or one past plain instructions |
| `translator/region.py` | BP-stable components, their direct-access range and guards (speed-plan R6) |
| `translator/reuse.py`, `compact.py`, `reglive.py` | run-local rewrites: repeated index/base formations (R13), folded displacements (R14f), native BP (R25), push/pop runs (R31); word-mask compaction within an instruction (R4); DX liveness within a block (word MUL/DIV store DX only where live) |
| `translator/smc.py` | self-modified region as a run-time cell walk with cell cache (D16, below); the segment check is a window |
| `translator/compute.py` | admission and emission of `kind=compute` HLE rows (native-compute.md (SWOTL `docs/native-compute.md`)) |
| `translator/emit.py` | program mode: global flag liveness, per-function return sets, leaders, labels, transfers, `build/gen/<module>.s`, `program.s` (assembly root, dispatch table) |
| `translator/support.py` | state-block equates, flag/BCD helpers (`build/gen/support.s`) |
| `src/runtime/` | runtime (C + `rt_entry.s`): machine model of the reference (PSP, environment, MCBs, IVT values), EXEC of `SWOTL.EXE`, INT 21h/10h/16h/33h/67h services, `rt_*` entries, dispatch lookup with PLINK residency; platform interface `platform.h` |
| `src/platform/host/`, `src/platform/amiga/` | `platform.h` for Unicorn (harness-served stubs) and AmigaOS (dos.library, private native stack) |
| `tests/` | `host_run.py` (generated program + runtime on Unicorn 68020 to a milestone vs the reference; `--amiga` capture; `--sabotage`), `test_decode.py` (Capstone), `x86_diff.py` + `x86_sabotage.py` (Unicorn x86-16), `m68k_diff.py` (instructions/short blocks, test mode) + `m68k_blocks.py` (generated program, traced blocks; `cross_flags_cases.py`, `m68k_assembly.py`) + `m68k_sabotage.py` (Unicorn 68020), `test_guards.py` (G1/G2 plants), `audit.csv` (audit expectations), `uc.py` (ctypes binding) |

Language: Python 3.11 (sibling tooling, Capstone binding present). Offline,
so translator speed is irrelevant.

#### IR

Specification in `translator/ir.py`. Per instruction: an op list over
width-typed temporaries with local labels (REP loops, CL-count guards,
divide checks), explicit stack traffic, and one exit (`jump`, `call`,
`ret`, far forms, `int`, `fault`) or fall-through. Flags: `flags kind w a b
r` defines the status flags of `kind` and marks the undefined ones
(`FLAG_KINDS`; count-dependent for shifts/rotates); reading an undefined
flag is an error, never a value. Guest registers 16-bit with explicit
8-bit halves; segment registers separate; FLAGS bits 12–15 as `flagsx`.
Listings in `build/gen` carry `(module, offset, CS:IP)` per instruction.

#### Generated code contract

Registers (D4, fixed program-wide; spill audit 0):

| 68k | Guest | Rule |
|---|---|---|
| d0 d1 d2 d3 d4 d5 | AX CX DX BX SP BP | low word; upper word undefined (speed-plan R4); SP and BP mirrored: offset ^ 7FFFh |
| a4 a5 | SI DI | same (not mirrored); `movea.w` loads, dead-flag add/sub/inc/dec in place |
| a1 a2 a3 | ES SS DS base | a6 − seg*16 − 7FFFh, recomputed on every segment write |
| a6 | guest RAM | TOP = linear 0, byte-exact and reversed (linear L at TOP − L); state block above |
| d6 d7 a0 | scratch | a0 also CS base (`lea (-cs*16-7FFFh,a6)`); CS is static per instruction |
| a7 | native stack | `jsr`/`rts` only |

State block (`G_*` equates at a6+1..a6+16): `G_FL` low byte = CCR image of
CF (C), OF (V), ZF (Z), SF (N), X not guest state; PF = even parity of
`G_PF`; AF = bit 4 of `G_AF`; `G_DF`/`G_IF`/`G_TF` bytes; `G_FX` = FLAGS
bits 12–15; `G_ES`/`G_SS`/`G_DS` segment values. Run-time CS =
`LOADSEG+link`, `LOADSEG` = 0822h (the reference load segment, so guest RAM
diffs directly); relocated words in instructions are emitted as
`LOADSEG+value`.

- Upper words (speed-plan R4): a lowering that reads a guest register's 32
  bits zero-extends it first (`read_zx`: segment loads, the cell walk's entry
  IP from an indirect call); the REP fast path converts SI/DI from their low
  words; the runtime masks what it takes.
- Segment loads in `annotations/seg-repeat.csv` (R30) compare the new value
  with `G_xS` first; only a change stores it, checks the cell caches and
  rebuilds the base, out of line (`lower.putseg_repeat`).
- Memory (D1, speed-plan R1): a little-endian word at linear L is the native
  word at TOP − L − 1 (68020 allows odd addresses), no byte swaps. The byte
  at offset o is `(7FFFh−o,aS)`, the word `(7FFEh−o,aS)`; a computed offset
  is mirrored into d7 (`move.w #7FFFh−disp` / `sub.w Rn`, or from a mirrored
  register `move.w Rn` / `sub.w #disp`) and indexes as `(0,aS,d7.w)` /
  `(−1,aS,d7.w)`, keeping the 16-bit wrap; SP/BP alone index directly. A word
  at offset FFFFh is two consecutive linear bytes. Push is `addq.w #2,d4` +
  `move.w v,(−1,a2,d4.w)`. A run of four or more pushes (pops) with no leader
  between steps SP once in its first instruction, `bvs` (only that step can
  overflow d4.w: the run wraps SS:0) to the exact lines out of line; the rest
  address from the final SP (`reuse.stack_runs`, R31; R29 for CALLF's long
  push). SP/BP as values convert with `eori.w #$7fff`
  (dead-flag add/sub/inc/dec, NOT and `or/and/test r,r` stay in place).
  Byte and word memory operands fold into the 68k op (source, read-modify-
  write destination, INC/DEC/NEG/NOT, CMP with an immediate) where AF and
  PF are dead.
- BP regions (speed-plan D2 and R6, `region.py`): a BP-stable component (the
  code after a BP write up to the next, calls continuing at their return
  site) chosen in `annotations/bp-regions.csv` (`tools/bp_regions.py`, from
  a meter run) gets a guarded copy (`<label>_bp`) in which `[bp+d]` and far
  pointers at `[bp+d]` are `(−d,aS,d5.w)` / `(−d−1,aS,d5.w)`: d5.w
  sign-extends to 32767 − BP, so this is exact while 0 ≤ BP + d ≤ FFFFh.
  One range check on d5.w covers every displacement of the component: at
  its entry after the BP write (`<S>_bpg`) and after each call or software
  interrupt in it (`<S>_bpr`); a failure continues in the exact code, as do
  exits, BP writes, poll stubs and divide-error retries. Entries, those
  return points and where a copy run falls into the exact code are leaders (a
  guard clobbers the CCR; the run passes start afresh there). Tools that hook an
  instruction's label (host run) hook its copy too.
- Flags (D6): a setter stores the defined flags live after it (`flags.py`,
  global liveness in `emit.py`). The next instruction reads the CCR directly
  when it is not a leader, reads only flags the setter's 68k op holds with
  x86 meaning (`CCR_OK`), and the setter's tail leaves the CCR intact; else
  readers load `G_FL`. Plain instructions (no flags, no transfer) may stand
  between the two (speed-plan R3b). Their 68k lines keep the CCR, or the
  last one that changes it moves the setter's result register at its width
  (unchanged since), which leaves N and Z equal to SF and ZF. PF/AF are
  stored as result / `a^b^r` bytes only when live. adc/sbb/rcl/rcr take CF
  from X when the instruction before (not across a leader: add, sub, adc,
  sbb, neg, shifts) leaves X = CF, else from `G_FL`; an adc/sbb operand
  setup that changes X keeps it in d6 (`subx.b d6,d6` first, `add.b d6,d6`
  before the setup's load into d6, R28). Z is preset for `addx`/`subx`.
- Strings (D11): per-element loops, one body per DF; the backward body is
  out of line and rejoins the forward body's continuation (R21). REP with DF = 0,
  CX ≠ 0 and SI/DI + size × CX < 10000h takes a fast path with host pointers
  descending: `move -(a4),-(a5)`, `move d,-(a5)`, `move -(a4),d6` + `cmp
  -(a5),d6` or `cmp -(a5),d` with `db<cc>`, the last pair's flags
  recomputed. REP STOSW and REPE CMPSW move or compare two words per
  `move.l`/`cmp.l` (speed-plan R12: an odd element alone, a mismatching
  long's guest-first word first), eight longs per pass (R24: STOSW stores
  a first word to long-align; R26). REP MOVS and REP STOS with CX at most
  `REP_SHORT` (3) run the element body instead: below the fast path's fixed
  cost (break-even 3.6 to 5 elements, DERIVED from the emitted code; the intro's
  sprite runs). Checked by the boundary corpus (guard and stop edges, overlap)
  and sabotage plants.
- Calls (D1): the guest stack stays byte-exact; a guest call is `jsr` and
  returns with `rts`. Near returns carry IP in d7.w; RETF and IRET carry
  CS:IP in d7.l (R33). RETF pops one long after a word SP step guarded by
  overflow; a wrap pops the two words out of line, wrapping SP between
  them. IRET pops flags and words separately, then packs the pair.
  Return sites compare the near word or far long and branch to a module-local
  `<tag>_rm<n>` trampoline after a run that cannot fall through. Far failure
  normalizes CS into d6 before the fail-loud diagnostic. A PLINK
  manager call's return site is 2 bytes later (the manager advances the IP).
- Indirect transfers (D7): compare chain over the known targets
  (`annotations/indirect.csv`); a proved switch table falls back to
  `rt_stop_unknown`, other sites to `rt_dispatch_near`/`rt_dispatch_far`
  (target in d7, CS in d6). The first walk call falls through to its return
  check; its remaining targets and fallback are out of line, with both walk
  range checks retained (R22). Table rows (`program.s`): the cfg seeds (MZ
  entry, PLINK thunks, `runtime.csv`, `indirect.csv` targets) as (CS, IP,
  overlay id, far, label); overlays sharing an area share CS:IP, so the row whose
  overlay is resident (PLINK record bit 15) wins; anything else stops. A far
  target CS:IP that two overlays share stays out of the compare chain and goes to
  `rt_dispatch_far` (`FRONTEND.OVL+0A6D2`, 3273:1738 and one more); on a site with a
  complete target set it is a generation error.
  `far` = 0 for a row seeded only as a target of indirect near `jmp`/`call`
  sites: `rt_dispatch_far` (and interrupt delivery, the guest entry) stops
  there (R14e).
- Layout: runs in offset order, stubs (poll, cold paths) after a run that
  cannot fall through. A forward jcc listed in `annotations/outline.csv`
  (R27) branches, inverted, to its fall-through range, which goes first among
  the stubs after the next closing transfer and ends with `bra` to the target
  unless it ends in a transfer; every instruction keeps its lowering.
  `build/gen/outline-sites.csv` lists every eligible site and where its range
  would go.
- Runtime entries (`jsr`, contract in registers): `rt_int` (d7 next IP, d6
  CS << 16 | vector; the runtime writes the CPU's IRET frame below SS:SP;
  services read no guest flags and leave undefined-by-them flags in the
  state block; a vector pointing into the program's memory runs the guest
  handler on that frame), `rt_fault` (same d6/d7; returns to re-execute),
  `rt_in8/16`, `rt_out8/16` (d7 port, d6 value), `rt_halt`,
  `rt_stop_unknown` (prints and halts; never resumes).
- EMS model (Wing Commander 2's lazy frame pages, `ems.c`): a map copies no page
  in; a frame page holds its mapped page's bytes only while it is live. Before
  every instruction that accesses memory through ES, `cmp.w #$d001,G_ES(a6)` and,
  at or above, `rt_ems_es` out of line (d7 the lowest offset, d6 the bytes from
  it; a string passes the range of its operands in ES, ES:DI and an ES-overridden
  [SI], its size times CX plus their distance, or 0 with DF set: the whole
  window). A range within one frame page, or across frame pages that map
  consecutive store pages, whose pages have no live copy runs on the store (a1
  displaced onto it; store slots are reversed as guest memory is, so consecutive
  pages share one displacement); anything else copies its pages in and runs on
  the frame with the plain base. A one-entry cache per segment register
  (`EMS_GUARD`, `ems.c`) holds the last decided segment, the offsets of the run of
  adjacent frame pages around its access that share its displacement, and the
  base, emptied at every change of the store mapping; the out-of-line
  path (out of line, the CCR saved around the main path's check only when a flag
  valid in it is still read, `lower.ccr_live_in`, and X kept out of line only where
  it carries the guest CF in; a hit returns at once, d7 free as the guard opens
  the instruction) checks it inline for an operand's access, and for one string element
  through one operand (LODS, STOS, SCAS, a MOVS or CMPS operand alone in its
  segment, no REP: its own bytes, whatever DF is), and calls `rt_ems_es_miss` only
  on a miss (any other string calls `rt_ems_es`, which checks it itself). So a1 is the
  plain ES base only below D001h, and every access at or above runs right after
  its guard or after an earlier instruction's guard of the same operand, held
  (`lower.ems_held`): in one run, with no leader, region guard or hook between,
  the earlier access at least as wide, and every instruction from it on a plain
  one (`HOLD_OPS`) that writes neither ES nor the operand's registers and guards
  nothing else; nothing then reaches the EMS state, so the guard would return the
  same base. DS and SS accesses are
  not guarded, so a DS or SS load of D001h or above calls `rt_ems_seg` and the
  pages their window meets are copied in, as at service returns. Listed code
  (`annotations/ems-ds.csv` guard, owner decision in [design](design.md)) guards
  its DS accesses the same way (`rt_ems_ds`, a3), its DS loads copy nothing, and
  a far exit with DS still at D001h or above copies the pages in
  (`rt_ems_ds_leave`, counted): before a RETF, IRET, INT, INTO, far call or far
  jump not aimed at listed code, and after a range's last instruction when it
  falls through; a RETF listed as keep has none, as its far function writes no
  DS and only listed code calls it (`emit.py check_ems_keep` refuses the row
  otherwise, or when the function is a dispatch row; controls in
  `tests/ems_keep_check.py`). `translator/emit.py` refuses a near call into a range from
  outside, a direct transfer leaving one and an indirect transfer inside one, so
  a near RET stays inside; jumps into a range are allowed, as unlisted code
  has DS below the frame or its pages copied in, which the guards also handle. A POP DS listed as a
  restore (the music driver's INT 08h handler) reloads the interrupted DS without
  a check: its pages are live or guarded, as the handler maps no EMS page
  (`rt_int67` stops at interrupt level). The runtime's accessors report frame
  bytes (`rt_frame`). A live page is written back when its frame page is
  remapped. Live copies of a page mapped at two frame pages equal the store when
  the second is made and are merged at the next map call; a byte written
  differently through two is a stop. Checked by the 68020 differential's `ems`
  and `emsds` cases at the D001h edges, with the cache empty, covering the access
  or missing it by its first byte, its last or the segment, the `emshold` blocks
  (each access at D001h or above guarded or within the last guard's bytes at the
  same ES; a CMP's flags across an ES access to their JNE, an ADD's CF in X across
  an ADC's guard, the stub of the EMS calls returning the CCR inverted as the
  runtime keeps none), and their sabotage plants (the guards, the exit check, a
  string's count, the inline hit's three compares, a guard held across an ES
  change or a write of its offset's register, an out-of-line path losing X), by
  `tests/host_run.py`'s routing check on the
  run's own image (`ems_guard_problems`: a range within a page, across
  consecutive and across other store pages, then an access in each page through
  the cache; sabotage `ems-cache-run` takes every page above into the run), and
  by the host lockstep; host
  captures and Amiga dumps show non-live pages from the store.
- Returns: a `ret` continues at the return sites of the calls whose targets
  reach it without entering a call (the divide-error edge is not flow);
  calls through the dispatcher return from any `ret` a table row reaches
  (far calls: a far row, R14e).
- Generated files: `build/gen/<module>.s`, `support.s` and `program.s`
  (equates, runtime xrefs, includes, dispatch table, `load_segment`,
  `overlay_table`), header = SHA-256 of translator sources, annotations and
  input image (`make gen-fresh`; `make gen-check` also regenerates and requires
  byte-identical output). One assembly unit (`vasm -Felf`), linked with the
  runtime: `make host` (`build/host/xwing.elf`), `make amiga`; both check only
  `gen-fresh`. After `elf2hunk`, `tools/hunk_relocs.py` splits any RELOC32 block
  of more than 65535 offsets: Kickstart 3.1's LoadSeg counts them in 16 bits and
  refuses the file as not executable (the code hunk relocates itself at 65839).
- Overlays (D2 = a): every translated module resident in native code; the
  guest's own PLINK manager runs translated and loads the overlay bytes into
  guest RAM (data, CS-relative reads, RAM equal to the reference).
- Memory (D15 = b): Fast RAM required (1.36 MB code at R34 + 1.06 MiB guest RAM);
  the A1200 model runs with 8 MiB Fast; development runs set `--cpu=68030`
  (`AMIGA_CPU`, ~3× the 68020: logo at 80 vs 252 frames); timing runs
  leave it unset (68020).

#### Annotations (`annotations/`, CSV)

`entries.csv`, `indirect.csv` (site -> targets; written by `make map`),
`tables.csv` (cs: word tables sized by evidence other than an MS C bounds
check, read by the sweep), `data-tables.csv` (near call sites whose target comes from a
word table in a data segment, through a memory operand or a register loaded from it: the
table's module offset, entries and evidence; the sweep reads the words from the file into
the site's proved targets), `code-pointers.csv`
(far functions found statically by `make map`: far pointer constants `mov r,offset;
mov r,seg`, stored as two words `mov [m],offset; mov [m+2],seg` (a FRONTEND method slot) or
pushed as `push seg; push offset`, with the segment relocated and the target a function
start: a prologue, or the byte after a decoded RETF and up to three NOPs (a FRONTEND
object's empty method is a lone RETF, `FRONTEND.OVL+68236`); and prologues right after a decoded RETF and up to three NOPs, whose CS is the highest
known code segment at or below them (the module's own, not the previous one's); cfg seeds
them, so they are far dispatch rows), `runtime.csv` (MS C runtime entries: name,
class, evidence), `self-modifying.csv` (D16 regions and cell forms),
`flags.csv` (PUSHF/POPF pairs that only save and restore FLAGS),
`noreturn.csv` (X-Wing: calls with no fall-through, read by cfg and the sweep; the
return of one stops), `hle.csv` (guest range, service, reason, oracle; below), `align.csv`
(R8 pads; `tools/align_targets.py`), `bp-regions.csv` (BP writes whose
component gets a guarded copy; a profile choice, `tools/bp_regions.py`),
`outline.csv` (forward jcc whose fall-through range goes out of line, R27;
a profile choice, `tools/outline_sites.py` from `build/gen/outline-sites.csv`),
`seg-repeat.csv` (segment loads that compare first, R30; a profile choice,
`tools/seg_repeat.py`), `irq-bounds.csv` (value bounds of variables that index
the IRQ0 handler's accesses, and class extents, I2), `irq-ds.csv` (entries that return the
caller's DS where the I2 analysis cannot see it; host runs check, I3) and `irq-sync.csv`
(monitored accesses the I3 monitor found meeting the footprint, or writing song bytes the
handler reads: sync for the declared span).

#### Tests

- Instruction differential (`make test-m68k`): the x86 corpora (forms,
  space, boundary, blocks) lowered in test mode (every exit through a stub,
  all flags live at the end), Unicorn x86-16 vs Unicorn 68020 on the same
  guest-memory layout; registers, segments, CS:IP, defined flags, FLAGS
  12–14, memory, OUT sequence, interrupt/fault. A case with a direct
  `[bp+d]` form also runs behind a region guard (copy, exact fallback).
- Block differential (`make test-blocks`): the generated program as emitted,
  run from executed leaders to the first transfer with random states. Every
  branch to an instruction's label targets a leader (copy exits, divide-error
  retries: `lower.exit_fault` re-executes the instruction), except exact code
  branching to its own fall-through (R27). Guest CFG
  exits remain stopping boundaries when a zero-code jump aliases its target;
  direct zero-code entries stop without executing the target. Each outlined
  jcc (R27) runs from the leader that falls into it, and its fall-through
  range as paths from there (registers and the words a path loads at edge
  values or its immediates; cases taking a jump on the way are skipped). Flags
  compared where live at the successor reached (at a cell walk: live at the
  transfer; the walk reads no flags); calls also run the return protocol
  (right IP/CS reaches the return site, wrong IP or CS reaches the mismatch
  handler; near IP’s upper word random, far CS:IP packed). Register calls and jumps that
  can enter a self-modified region also run with the target in each region.
  Every executed block of a guarded copy runs with BP at both ends of the
  range its guard admits and inside it; every guard runs just inside and
  outside that range. Every `annotations/tables.csv` row also runs from
  its call site to the target read from the original table, then every
  reachable block runs against x86, including untraced targets.
- File dates (`tests/test_file_dates.py`): live DOSBox-X find-first/next
  over synthetic files verifies Amiga DateStamp conversion and runtime
  DTA time/date, including leap centuries, pre-1980 wrapping and odd seconds.
- Host run (`make test-host`, gate 5): `build/host/swotl.elf` on Unicorn
  68020 from the MZ entry to milestones m1–m3 (`make test-host-all`: m1–m7,
  the Makefile's `HOST_COVERAGE` scenarios and `t-hle-music-skip`; files the
  guest writes are kept in memory); every software
  INT's registers at entry and return vs the tracer's service log (a register
  byte loaded from masked dead stack may differ: [design](design.md)); registers
  and RAM (environment MCB to A0000h) vs the snapshot (a byte last stored from a
  dead-stack read may differ: [design](design.md)), dead stack masked
  (below SS:SP at a service or hardware interrupt; at an IRQ0 delivery to the
  guest handler, which the reference runs on the interrupted stack, its frame and
  the depth `irq-footprint.csv` proves; and the FLAGS image of an `annotations/flags.csv`
  PUSHF, until the guest rewrites it); at m1b-logo the A0000h window and the
  DAC; machine bytes the guest read hold reference values; every guest
  access against the IRQ0 footprint (`tests/irq_monitor.py`, irq-plan I3:
  handler accesses inside it, main accesses meeting it only from sync
  instructions, IF clear or services; a main write of a song byte the handler reads
  before and after with no main-code driver request on either side is a race, a
  buffer reloaded around requests is reuse; record `tmp/test/irq-monitor-<run>.json`).
  `make test-amiga` (`tests/amiga_replay.py`): the same per milestone on the 68030 model
  (A1200 chipset, FS-UAE, `amiga/milestone.gdb.in`) from a diagnostic replay image,
  in the host run's modes (m00–m02 plain; `--screen` for m03, m03c, m03p and m03q,
  where `XWING_REPLAY_SCREEN` makes the copy-protection hook decline; `--bypass` past
  the screen against the `hostb-` references; key releases at their recorded visits;
  at a label other than the mouse poll, m03p's and m03q's screen return, the shown
  pixels the guest stored since the last present are not compared, as D9 shows them
  only at the next poll),
  plus the shown screen (bitplanes, colour table) decoded against the reference
  framebuffer and DAC. The image (`XWING_REPLAY`, sync mode, built in
  `tmp/amiga-replay/`) adds `rt_replay_point` hooks at the reference's interrupt,
  snapshot and REP points and the service hooks in `rt_entry.s`; it posts each recorded
  interrupt at its poll point and visit count, answers 3DAh with the recorded reads of
  the same service interval, takes the recorded calendar and file clock, checks the
  service history by a cumulative FNV hash (every 256 events and the last; `--exempt`
  takes `tests/host_run.py --exempt-out` of the same milestone and reference and leaves
  out of both sides' hash the register bytes the host's service log exempts as loaded
  from dead stack, m10's INT 21h AH=47h; every entry must be met) and holds
  at `rt_replay_done` when the last snapshot is reached with every service, interrupt,
  REP slice and VGA read consumed. `make test-amiga-live`: the production image to the
  m01 label in real time, not compared.
- Resume (`tests/host_resume.py`; `make t-resume-<milestone>`, `t-resume-plants`,
  `t-sab-resume`): host lockstep to a flight milestone from a save at the flight's
  start (`POINTS`: FLIGHT.OVL+2856C, the flight's first instruction, before its sound
  loader and the effect capture; m12–m15 and the combat film m17). `host_run.py --save` makes it in a boot run where the
  point is reached in main code with no service, interrupt handler, REP slice or
  capture in progress, and keeps it (`tmp/resume/`) only once that run passes its
  milestone. A save holds the guest RAM, state block and EMS store; the runtime's
  fields (`src/runtime/snapshot.c`: each module names its fields in a versioned
  record, loaded only by a runtime whose fields agree in name, order and size; caches
  stay empty and pointers the new image's; an open directory search, a pending
  interrupt-level stop or a running handler or capture refuses the save); the
  generated code's registers; the open guest calls, each 68k return address read as
  its return site (`cmp #ip,d7` or `#cs:ip`, the guest label after it, its mismatch
  stop); the harness's cursors and checks (services, interrupts, VGA reads, REP
  slices, keys, files and positions, dead-stack and machine-read sets, OPL writes,
  the I3 monitor); and the fingerprints of what ran before it, recorded by a C block
  hook (`tests/host_cov.c`): each guest label region's assembly text, the program
  header and the dispatch rows per CS:IP, each runtime input section's bytes and
  relocations by name (host objects are built one section per function and object,
  linked with a map) and the harness source that decides guest-visible behaviour.
  `--resume` boots the current image to its guest entry, restores the save, returns
  each open call through a stub that repeats its site's compare and jumps to its label
  in this image, and enters at the point's label; the lockstep and the milestone
  checks then run as from boot, reading the reference from the save's line on. Any
  fingerprint that differs runs from boot and saves anew. `--resume-plants` changes,
  on the save, a label and a runtime section that ran, a dispatch row and the harness
  (each refused) and a label and a section that did not (each may resume);
  `--resume-plant ems|file` resumes with the handles' EMS page tables (`ems.page_of`)
  or the open files' SFT entries (`dos.file_of_sft`) left out of the record, and
  `t-sab-resume` requires a lockstep divergence, not the timeout alone (MEASURED, m12:
  a lost reference interrupt after 4,152 services; a seek returning invalid handle
  after 2,819). An open file's position is not a control at this point: the only file
  open is FLIGHT.OVL, and the overlay manager seeks it absolutely before each of its
  11 reads after the save line (MEASURED, m12 reference trace), so a resume with it
  rewound passes. MEASURED (host runs sharing the machine with other projects' runs,
  not a matched workload): to m12 5,288 s from boot, 125 s resumed; to m14 11,787 s
  from boot, 2,355 s resumed (13,449 of its 58,737 interrupts after the save); every
  check of the resumed runs equal to their boot runs'.
- Display (D9 slice): FRONTEND and FLIGHT write video memory
  (`emit.VRAM_MODULES`). Before each of their stores through ES or SS the
  lowering checks whether the segment's window meets the frame and calls
  `rt_vram_mark` (offset, bytes; `rep stos/movs` once for the whole run), which
  widens per-row changed columns; a byte or word store calls `rt_vram_mark_short`,
  which marks one within a row without saving a register or calling and passes
  any other to `rt_vram_mark` (`tests/host_run.py` `vram_mark_problems` compares
  the two over row, frame and offset edges; sabotage `vram-short`). Stores through DS are checked so only in the
  routines the traces show storing to the frame through DS
  (`annotations/vram-ds.csv`, measured by `tools/vram_ds_profile.py`; owner
  decision 2026-11-23). Its ranges are shaped as `ems-ds.csv`'s guard ranges
  (`emit.vram_ctx`). Elsewhere, in every module, a DS load of 9001h–AF9Fh, and
  listed code left with DS there (`lower.vram_exit`), call `rt_vram_ds`: every
  row is marked, and each present marks the whole frame again until one finds DS
  off the frame (`rt_vram_ds_on`). The fallback is counted in `rt_vram_ds_falls`. In
  m01, m02, m12, m13 and m17 no store reaches the frame through DS (MEASURED), so the
  list holds only routines that load DS at the frame or at a buffer whose window meets
  it, listed to keep them off the fallback; m13's front-end loaders at 1918:007C and
  3273:36D5 take it. Control: `make t-vram-ds-plant` (`tests/host_run.py
  --vram-ds-plant`): an image that leaves ES stores unmarked as well
  (`XWING_VRAM_PLANT=es`) passes m01 on 124,833 fallbacks, and is caught by the
  shown-frame check with `rt_vram_ds` returning at once. The game's mouse poll (INT 33h AX=3, after all of a
  frame's drawing) ends a frame (`rt_video_frame`): its changed rows go to
  `plat_present` as 32-pixel-aligned rectangles there if a vertical blank is
  due, otherwise at the next one (`rt_present_due`; Amiga: the field task,
  host: always due) while no driver call and no main-thread present or video
  BIOS call runs; publications between polls are not presented, so an erase
  and its redraw (PANEL gauges) are never shown apart (user 2026-10-28).
  Before the first poll, or after one second of IRQ0 deliveries without one,
  each publication presents as before. Frame cap (production Amiga,
  `rt_frame_cap`; user 2026-10-29): a poll returns at most once per field
  (`rt_fields`), waiting with the service's tick hold lifted so IRQ0 runs; the
  game's loop never reads the retrace, so on a fast CPU it would outpace the
  display, and each frame takes at least a field of mouse motion (AX=0Bh, the
  flight stick). Sync builds and the host leave it off. Flight mouse scaling
  (production Amiga, `rt_mouse_scale`; user 2026-10-29): AX=0Bh returns the
  motion times `MOUSE_FRAME_MS` (input.c, 300 ms, the tweakable sensitivity)
  over the game-clock time since the last AX=0Bh, remainders carried, so the
  stick's deflection follows mouse speed alone at any frame rate; off while the
  guest's pointer was shown at the last present or within 25 fields (menus,
  film room). Vertical mickeys (`rt_mickeys_y`): 2 per count as DOSBox-X
  (host pixels), 1 on the production Amiga, as a real PC mouse's equal counts
  per inch (user 2026-10-29). Mode set marks the whole
  frame; DAC block sets go to `plat_palette` at once. No frame is read to
  find changes. Amiga (machine taken over, `Swotl.cpp`): an 8-plane copper
  display (framework `CopperList`/`Bitmap`), Kalms `c2p1x1_8_c5_bm` per
  rectangle (one call per full-width band, per row otherwise) into the
  inactive bitmap. Both bitmaps retain dirty rows since their own last
  conversion. A pending frame is withdrawn before reuse; updates can
  coalesce without waiting. Each bitmap has a complete
  copper list and palette. VERTB switches lists before input, only at beam
  lines below 8; a late VBI defers the handoff. `amiga_bitmap` and
  `amiga_colours` describe the handed-off frame. Checked by the host run
  (every guest A0000h store lies in the next present's rectangles; sabotage
  `vram`), `tests/test_display_queue.py` (inheritance and queue races; production
  `video.c` with the field task interrupting driver calls, presents and video BIOS
  calls, the cap's once-per-field return and lifted hold, plants), and
  `amiga/display_audit.sh` (40 handoffs against published guest snapshots
  and DAC, no conversion into the shown bitmap, zero late handoffs).
- Interrupts (D8; irq-plan (SWOTL `docs/irq-plan.md`)): poll points (`build/gen/poll-points.csv`,
  `module,offset,kind`, all block leaders, so live flags are in the state block) are the
  I8 sync points (`irq.Proof.sync_points`: `access` footprint accesses and `int` sites
  with IF possibly set, `clear` CLI/POPF/IRET, `if` the instruction after an IF 0→1) and
  the loop heads (`loop`, targets of backward branches outside native rows; user
  2026-10-26: they keep the reference on the original's timing). A native row is atomic
  to the interrupt (irq-plan RC5): loop heads in its body, callees and re-entries
  included, are not in the set. Only sync builds
  (`XWING_SYNC`: host runs, replays, `make amiga-sync` for the bench) test at `access`,
  `int`, `clear` and `loop` points; every build tests at `if` points and at the
  `annotations/irq-polls.csv` points (ADLIB.IMS's calibration loops: their handler reads
  the interrupted CX and DX, so its ticks are taken there with the registers live). Production takes
  IRQ0 at the CIA-B tick (below). A test is `tst.b G_IRQ(a6)`
  and `bne` to the poll's stub `X_irq`, placed after the next run that cannot
  fall through: d6 = CS << 16, d7 = IP, `jsr rt_irq`, back past the test to
  `X_np` (the tools fold `X_np` into `X`; the block differential also runs
  every poll block with an interrupt posted). The platform raises `G_IRQ` and
  `rt_irq_pending` together (`RT_RAISE_IRQ`); with IF clear `rt_irq` clears
  `G_IRQ` only, and `sti`, `__set_flags` (POPF, IRET) and
  `rt_set_flags_word` re-arm it from `rt_irq_pending` when they set IF
  (checked in the 68020 differential and `host_run.py rearm_problems`;
  sabotage plants). With guest IF set posted interrupts run in order: IRQ0's guest
  handler (`annotations/entries.csv`) through `rt_irq_async` on the private guest
  stack `B000:8000` down (frame with the sentinel CS:IP `B000:8000` its IRET must pop;
  68k registers, state block and `rt_r` restored after it; nothing posted is taken
  until it returns, the PIC's in-service IRQ0, irq-plan I4; on the Amiga the CIA-B
  tick runs it at once through `rt_irq_interrupt`, which hands the handler `rt_r`, not
  the interrupted registers, only for the handler the footprint proof covers
  (`irq0_async_handler`, `entries.csv`) and when `rt_irq0_ready`: IF set, none
  running, no runtime service (`rt_irq_mask`) or main-thread OPL index/data pair
  (`rt_opl_pair`), nothing posted, not `BENCH`; a stop raised in it unwinds through
  `rt_irq_abort` and is raised at the next poll; a tick posted while it could not run
  is taken by the next CIA tick before its own, `rt_irq0_take`; with IVT 08h the
  BIOS's, the CIA tick counts the tick at once under the same conditions, the posted
  ones first, `rt_irq0_bios_tick`, so no backlog reaches a handler installed later; host runs inject recorded ticks
  the same way with `host_run.py --stress SEED`, `tests/irq_stress.py`, I6), another
  guest handler on a pushed frame, else the BIOS one (INT 08h ticks; INT 09h, posted in
  sync builds only, takes the next `rt_key_ring` event; production drains the ring at
  service entry with IF set, `rt_keyboard_drain`: a set 1 scan code with break bit and E0 flag, as
  DOSBox-X's IRQ1 handler does: its scan-code table, shift and lock flags,
  words like `48E0`/`xxF0` in the buffer, which DOS AH=08h converts as its
  CON device over INT 16h AH=10h);
  a guest handler's `jmp far` to F000:FEA5 is the BIOS tick plus IRET
  (`rt_bios_int08`). INT 33h is DOSBox-X's driver with the mouse captured
  (8/16 mickeys per 8 pixels, 640x200, mode 13h X even) over `plat_mouse`
  counts, the Amiga's JOY0DAT deltas taken at each vertical blank. Recorded
  IRQ12 (74h) at the exact DOSBox-X external vector F000:D020 drains no
  guest callback: the supported INT 33h surface installs none and never
  shows the DOS driver cursor. Guest-installed vectors still dispatch;
  other external targets stop. `c9-mouse-menu` checks motion, buttons and
  these recorded interrupts; `test_mouse_irq.py` checks the IVT/IF edges.
  The platform posts vectors to `rt_irq_ring` (08h tick,
  09h/89h key make/break in sync builds): Amiga a CIA-B timer per PIT period
  (`plat_timer_rate`) and the CIA-A keyboard read at the vertical blank (`Input.cpp`: raw
  key -> scan code, PC typematic repeat from the vertical blank; diagnostic
  argument `KEYS=when:key,...` feeds keys (letters, digits, `enter`, `esc`, `space`,
  `up`/`down`/`left`/`right`, `$hh` raw codes outside a Shell line), `lmb`/`rmb` and
  `mx±N`/`my±N` into the same paths at a field, `pN`, N guest mouse reads after the
  previous step, or `fN`, N published frames (`plat_present` calls) after it (host load
  moves field timings), and `shot`/`quit` call `amiga_script_mark` for a gdb fixture;
  `XWING_ARGS` in `amiga/debug.sh`); host run the reference's `irq` events, replayed at the
  same visit of the same sync point after the same service event, one of a
  same-visit group per return of the guest handler to that point (the
  reference takes interrupts only at sync points, `build/gen/poll-points.csv`, IRQ0
  edges only the gate held raised again in order, `dosbox-x-xwing-irq0-backlog.patch`;
  a key at a blocking read's poll point waits there for its IRQ1, `dosbox-x-xwing-key-wait.patch`;
  references are re-recorded when the sync set changes, irq-plan RC3).
- IRQ0 footprint (irq-plan I2, `translator/irq.py`, run by `make gen`): the guest
  handler's memory, ports, IF changes, hooks and runtime calls, register
  transparency proved over the lifted IR; every main-code access classified
  masked, disjoint, sync (may meet the footprint) or monitored, with segment
  registers per (entry, DS, SS) context. A sync access to a handler-written
  byte lowers to one memory-touching 68k instruction, no compute row holds a
  sync access, bounded G variables keep their bound, else generation fails.
  Output `build/gen/irq-footprint.csv`; `t-irq-footprint` and its sabotage.
- HLE (`annotations/hle.csv`, G3): at a range's first instruction
  `jsr rt_hle_<service>`; NE skips to the instruction after `last`, EQ runs
  the guest code. X-Wing's entries are `copy_protection` ([port plan](port-plan.md),
  P6) and the effects' `sfx_prerender` and `sfx_start` (Sound); the SWOTL entries below
  are not used. `args`: up to two guest word registers (not SP, BP), in d7
  and d6. Both ends are leaders, the first's live-in includes the
  resume's, and a hook where the CCR holds live flags fails `make gen`. The
  block differential runs the guest path. Entries: `sfx_start` (observe
  only: SPAZ's effect start, BX = slot·6, DI = id·4 → `rt_sfx_id`,
  `rt_sfx_starts`; oracle `check_sfx` in every host run: each report equals
  the guest's store of DI after the hook; sabotage `sfx_start` on c6);
  `pointer_tracked` (observe only: the pointer tracker's exit, DS = DGROUP →
  `rt_pointer_ds`; oracle `check_pointer` in every host run, sabotage
  `pointer-ds` on c9; pointer-plan.md (SWOTL `docs/pointer-plan.md`));
  `music_skip` (SPAZ song
  start, sound-plan.md (SWOTL `docs/sound-plan.md`)): `rt_music_skip`, 0 by default
  (music enabled, user 2026-10-15; 1 skips) and 0 with the argument
  `MUSIC`; `amiga/debug.sh` passes `MUSIC` and host runs
  clear it, since the references hold the music. Oracle `make
  t-hle-music-skip` (in `test-host-all`): m2 with the skip on; the interrupt
  the reference took in the song code is posted at the next sync point;
  services and interrupts equal the reference, RAM too outside SPAZ's state
  (its data segment, its effect counts at DS:6564, dead stack below SP).
  Optional `kind=compute` uses the complete generated register ABI and a d7.l
  handled result; admission proves the reachable flow (`compute.validate`: loops,
  callees, several returns, continuation `exits`, re-entry hooks `entries`). It
  leaves the guest return and check generated. A row is atomic to the interrupt
  (irq-plan RC5): its body's loop heads leave the sync set in both arms. U8: REP,
  the divide-fault edge as a decline edge, every root return a resume
  (d7 dispatch), `end` for code past the return. Contract, oracle and the
  enabled rows: native-compute.md (SWOTL `docs/native-compute.md`).
- Self-modified code (D16, `translator/smc.py`): the root block
  `+6A4D..+8E2C` is one generated cell walk (the whole template block: the
  [2581]=0 variant fills it at 190 cells per run). The setup (+E50E) writes opcodes
  as well as operands, and the shape (cell counts [2587]/[2591], reload position) varies,
  so cells are matched at run time against the forms the writers produce
  (`annotations/self-modifying.csv` kind `form`: `mov [bx+w],al`, the
  `bx`/`ds` reload, the planted `ret`), each checked against the decoder,
  operand words read from guest RAM; anything else stops. Mov cells run
  counted (R7): the cells that fit before the bound are counted once, each
  still matched when it runs (one long read: opcode and operand). That
  exact walk (`_walk_x`) serves a cell cache (speed-plan D3, R20): a cell is
  matched once, when a walk first reaches it, and its bytes are covered; a
  mov cell records its operand and the end of its run of consecutive
  destinations, which the walk stores AL to a long at a time (under 8 bytes
  one by one, offsets wrapping at 16 bits one by one). Every store that may
  change a covered byte is seen: a CS store that may reach a region calls its
  hook after storing (`lower.code_store`; byte `mov`s plant or restore inline):
  a RET at a covered cell start is the walk's stop (one at a time), its first
  byte back ends it, anything else drops the cache. A DS, ES or SS value whose
  window reaches a region drops every cache where it is loaded
  (`lower.putseg`, the reload cells, the runtime's `load_regs`; reloading the
  value a segment holds changes nothing, R30), and so does a
  runtime store into a region (`rt_wrote`; bounds and segment limit from the
  program). A dropped cache is cleared at the next walk with no segment
  reaching a region; until then walks are exact, and so is the rest of a walk
  whose reload loads such a DS. Bytes not covered are read when reached: a
  RET returns, other cells are decoded or walked exactly. Unresolved
  near indirect transfers range-check every walk in their module and CS,
  regardless of traced targets; proved tables retain their closed target set.
  The graph includes the walk edge. If every decoded cell instruction preserves
  arithmetic flags, a call propagates its return site's live flags through the
  walk; otherwise all flags are live. Return checks remain in place. The EGA/Tandy and/or variant ([2581]=0) is out
  of scope. Checked by `make test-blocks` (walks over every snapshot image
  vs x86, through a dropped cache and exactly; per entry, mov cells to the
  bound and past it, a RET at the bound, unknown cells; warm walks between
  RET plants, restores and operand patches made by the hooks or by the
  lowered stores, and cells rewritten after a lowered segment load or
  `smc_expose`; RETs inside and at the ends of runs, 16-bit wraps, a DS
  reaching the region at the entry and from a reload, entries inside a cached
  cell) and `make t-cell-cache` (the runtime's notifications).
- Trap flag: the game never sets TF (its four POPF/IRET sites pop PUSHF or
  interrupt-frame images; no INT 1 and no TF in any reference). A popped
  image with TF set stops (IR exit `trap`, `rt_trap`; `rt_set_flags_word`
  likewise); no single-step delivery. Checked by the TF cases of
  `flag_extract_cases` (x86, 68k) and `flag_helper_entries` (POPF, IRET).
- Audits (`make gen`): spills, full-flag materializations, PF/AF stores,
  dispatcher exits, `stop_unknown` sites against `tests/audit.csv` (above
  expected fails), plus flag stores/merges/loads and return checks; HLE count.

### Sound (D10)

`ADLIB.IMS` runs translated; its OPL2 writes reach `rt_out8` (the register file `rt_opl`
and the key-on edges `rt_opl_keyon` in `src/runtime/ports.c`), and `check_opl` holds them
to the reference's writes in every host run. The FM re-hoster
(`src/platform/amiga/fm_paula.c`, Secret Weapons of the Luftwaffe's, its
`docs/sound-plan.md`) turns them into four Paula voices once a field: the field task runs
it from `plat_service`, and the vertical blank stages its commands
(`src/platform/amiga/Audio.cpp`, Secret Weapons of the Luftwaffe's without its TFH
samples). Voices 0 and 3 play left, 1 and 2 right; an effect takes the voice the effect
player gives it.

Changed for `ADLIB.IMS`:
- Additive channels (C0 bit 0): the music uses them (271 of its 1,905 C0 writes over the
  sound references, mostly feedback 3) and Secret Weapons of the Luftwaffe's effects
  never did. Its loop held the carrier at 0 dB and the modulator at its own level, halved,
  at the louder operator's volume: 7–9 dB too quiet on 2,787 of 2,884 additive fields (MEASURED: `fm_check`). A loop
  key's high word now holds each operator's level relative to the louder (`ADD_MOD`,
  `ADD_CAR`), the modulator's feedback still runs at its own level, and the volume takes
  back the halved sum's 6 dB. FM patches keep a zero high word and their loops.
- `tools/fm_check.cpp` measures pitch on patches with shallow vibrato or tremolo (on most
  of the music's; at most 6.8 cents), not on a note released or one whose registers
  changed within the measured field (its header states the evidence).

Checks (`make gates-audio`): `t-fm` runs the re-hoster on the OPL logs of four milestone
runs (`make sound-reference`: `tools/reference.py --opl`, `ref/dosbox/runs/sound-*`)
against Nuked OPL per channel, level within 3 dB on 95% of fields and pitch within 10
cents on 99% of the measured ones. MEASURED (level; pitch): m01 99.4%, 100% of 94; m02
99.7%, 100% of 167; m06 98.1%, 100% of 342; m13 97.7%, 99.8% of 2,807. Secret Weapons of
the Luftwaffe's unchanged re-hoster fails the same check at 78.0% (m01) and 92.0% (m13)
level. `t-sab-fm` plants a pitch and a level fault. The render, phase, envelope,
allocation, cache and quality gates and their plants are Secret Weapons of the
Luftwaffe's; the render gate's reference model also renders the additive levels, and
its additive cases at 0 dB carrier keep their samples. On the Amiga, `make test-amiga-audio` runs the production
image on the 68030 model to m01's label and 500 fields past it, and requires OPL key-ons,
re-hoster renders and Paula restarts (MEASURED: 16, 91, 8; at the label itself, 107
fields after the start, all 0).

Effects are prerendered (owner decision 2026-11-15), as Secret Weapons of the Luftwaffe's
(its `docs/sound-plan.md`). In place:
- Capture (`src/runtime/sfx.c`, HLE `sfx_prerender`, observe only): at the return of
  FLIGHT's sound loader (`FLIGHT.OVL+19977`, AX the effects registered from id 4), the
  runtime saves the driver's memory (its image and minimum allocation: 7760h bytes for
  `ADLIB.IMS`, 87D0h for `ADLIB_W.IMS`), holds the tick, and per effect runs the
  driver's own commands and timer handler as `tools/sfx_capture.py` describes. The
  driver's layout (its handler, DS, sound table, queue, players, voices and OPL shadow)
  is the build's driver's, read from its own code by the translator
  (`translator/driver.py` `CAPTURE`, each value at an instruction the two drivers share,
  emitted as `driver_layout`), for the runtime and the oracle alike. Its
  writes go to `rt_sfx_capture` (`rt_out8` while `rt_sfx_capturing`), not the chip;
  then the driver's memory and the OPL index are restored. MEASURED (the m13 reference
  snapshot under Unicorn): 34 effects, ids 4–37, from 13 to 696 writes; 32 end within
  0.07–2.8 s, ids 31 and 32 loop until stopped.
- Render (`fm_effect`, `src/platform/amiga/fm_paula.c`; its inner loop
  `fm_effect_run.s` on the Amiga): changed from Secret Weapons of the Luftwaffe's for
  `ADLIB.IMS`: writes at its 291.3 Hz tick (512/9 samples); each channel's output shifted
  so nine fit the 16-bit mix; the envelope at each tick's middle, slow rates (below
  12) stepped at Nuked's envelope-timer values with the render split at each step;
  the modulator's feedback at the chip's rate; the chip's tremolo and vibrato (11
  effects set AM and VIB); and the 8-bit scaling rounded (its floor put a quiet tail
  half a step low). Each fixed a miss of the check below; MEASURED before them, 29 of
  the 32 one-shot effects passed.
- Checks: `make t-fm-effect` renders each one-shot effect against Nuked OPL from the
  same registers (`tools/fm_effect_check.cpp`, Secret Weapons of the Luftwaffe's
  thresholds: level within 3 dB on 90% of 20 ms windows and none past 6 dB, pitch within
  10 cents on 99% of tonal windows, the end and fade); MEASURED: all 32 pass, 548,551
  bytes (33.1 s at 16,572 Hz). `t-sab-fm-effect` plants pitch, level, end and fade
  faults. `make t-fm-effect-asm` runs `fm_effect` with the assembly loop on the Unicorn
  68020 core against the C loop on every capture and 12 synthetic variants (feedback,
  connection, shift): every byte equal; its plants alter the phase mask, the feedback,
  its history, the shift and the chip-rate steps. `make t-sfx-capture` runs the host
  lockstep to m12 with the capture on and compares every capture with
  `tools/sfx_capture.py` run from the guest RAM at the hook, and the guest's RAM (the
  private stack aside), state block, registers and OPL index at the capture's return
  equal to the hook's; the run ends there. The harness's own replays (interrupts,
  polls, REP slices, ports, EMS stores) are suspended while the capture runs, and the
  model answers DSP status reads. Of the Sound Blaster's, DMA's and the PIC mask's
  ports the capture may touch only the DSP: `ADLIB_W.IMS`'s stop all turns the speaker
  off (D3h, one per id), which `rt_sfx_prerender` restores; the check turns the speaker
  on at the capture's start and requires it on at the return. The capture is saved, and `t-sab-sfx-capture` plants a tick, a value, an end and a guest
  byte left changed on it, without a host run. MEASURED: 34 ids, 6,394 writes, ids 31
  and 32 without an end, all equal; a run with the capture on to m12 matched the
  reference (40,066,706 services, 31,703 interrupts and 20,651 OPL writes equal).

Play (`src/platform/amiga/fx_play.c`, the effect half of Secret Weapons of the
Luftwaffe's `tfh_paula.c`, its fixed slots replaced by the driver's players):
- The capture now runs every flight; `Audio.cpp` renders the one-shot effects (ids with
  an end; 31 and 32 stay on FM) at the capture's end, game time still paused, keeps them
  when the next capture's key is the same, and caches them in the game drawer
  (`sfx.cache`, keyed by `fm_effect`'s version, PAL/NTSC and the captures). An effect
  that does not fit in Chip stays on FM.
- Once a field, under the masked tick, `rt_sfx_read` (`sfx.c`) reads the driver's 8
  players and 9 voices ([external surface](external-surface.md#music-driver-interface)),
  and HLE `sfx_start` (observe only, `FLIGHT.OVL+18A53` after FLIGHT's start call) counts
  each start the driver took (AX 0) in `rt_sfx_starts`. A player that newly plays an
  effect with a sample, or whose id gained a start no new player shows (a stop and start
  within the field), starts a play: the sample on a Paula voice from its first sample,
  at the sample's level scaled by the player's volume (`((4k + 1.5) / 127)^1.75` for
  volume 4k..4k+3; MEASURED by `tools/sfx_capture.py --volume`: within 1.05 dB of the
  driver's carrier levels for volume 16 up). The OPL channels of a player playing an
  effect with a sample are muted from the re-hoster, and the play's voice reserved
  (`fm_field`'s `FM_RESERVE`). A stop more than two fields before the driver's end fades
  over three fields, a later one plays out; at most three play, the oldest giving way,
  so the music keeps a voice. The pan is not used: the AdLib is mono.
- Checks: `make t-fx-play` (in `make gates-audio`) runs the player on synthetic driver
  states (masks, chunks and their latch, volume, two instances of an id, the restart
  seen in the counts, fade, tail, the voice cap, PAL and NTSC); `t-sab-fx-play` plants
  ten faults. `t-fm-allocation` checks the reserved voices; its plant drops them.
  `make t-amiga-sfx` runs the Amiga replay to m12 (`--screen`) with the capture, render
  and player on and no host check: the replay must consume the reference's service
  history, interrupts and REP slices (the guest undisturbed), every start of an effect
  with a sample must become a play, and each effect a driver player plays at the end
  must have a counted start and its channels muted. The replay's points and REP slices
  ignore the capture (`tests/amiga_replay.c`), as the host run's. Whether a play holds
  a voice at the end is not checked: the replay runs the driver on the reference's game
  time, slower here than the fields the sample plays in. MEASURED: the capture 332
  fields, the render and cache write 1,007 fields (549,044 Chip bytes), 8 starts of id
  17 and 8 plays, at the end id 17 on OPL channels 1–7, all muted.

Speech (P10) is the Sound Blaster build's (`XWING_DRIVER=ADLIB_W.IMS`, translator/image.py):
it translates `ADLIB_W.IMS` in place of `ADLIB.IMS`, and the driver's embedded CT-VOICE code
drives the card. The AdLib build's generated code is unchanged by it.
- Model (`src/runtime/ports.c`, Wing Commander 2's DSP, DMA and IRQ 7 model fitted to the
  commands the references show; its comment lists them): the detection (reset, E0h, E1h,
  E2h's identification byte by DMA, E4h/E8h, F2h's IRQ 7), the OPL2 timer test at
  228h/229h, and playback: the time constant (40h), one 8-bit single-cycle block (14h) per
  clip over DMA channel 1, the speaker (D1h, D3h) around it, pause and continue (D0h, D4h).
  CT-VOICE stops a clip by pausing it and starts the next with a new 14h; the paused
  block's IRQ 7 never comes (MEASURED: m02i, blocks 9 to 12), so a 14h over a paused
  block replaces it, as one over a playing block does (DERIVED: the reference DOSBox-X's
  `sblaster.cpp` restarts the count with the new length and drops the old end; reached on
  the 68030, where the intro's lines overlap).
  Status reads answer as the model stands; `plat_dsp_status` reports the device's timing.
  A block's end posts IRQ 7 (vector 0Fh); `machine.c` stops on one with neither a block
  nor F2h pending. IRQ 7 is the reference's line (DERIVED: DOSBox-X's `sblaster.cpp`
  `SB_RaiseIRQ` and its 22Eh read, `pic.cpp`): while 21h masks it a raise stays latched and
  is taken once unmasked, and reading 22Eh lowers it, dropping a raise not yet taken
  (`runtime.h` `rt_irq7_ack`). CT-VOICE's clip stop (`+0581C`) masks DMA channel 1 and
  IRQ 7, then reads 22Eh, so a block that ends during a stop is never delivered. The port
  takes interrupts at poll points only, so on the 68030 such an end could still be
  untaken at the mask, which was a stop (MEASURED: "IRQ 7 while the PIC masks it" at
  m08's door). `tests/host_run.py --sb-race` posts a block end after each clip pause
  (D0h) of a milestone at the write that masks IRQ 7 (`+056AD`, IF clear): lockstep must
  hold with no post left. A post at the pause itself is not this race: the driver sets IF
  again before the mask, so the end is the original's to take, and lockstep then diverges.
  Its control, `sb-race-late`, posts after the stop's 22Eh read, where the raise stays
  latched and must fail the check. The IVT holds the reference BIOS's vectors 0Ah,
  0Bh, 0Dh and 0Fh, which the detection reads and restores.
- Proof (`translator/irq.py`): the tick reaches CT-VOICE's far entry (`+05AE4`) through
  queued requests and the flight callback. Its calls through tables are `irq-hooks.csv`
  rows (the function table at `+05B0C`, the block types at `+05968`); the variables they
  depend on are `irq-bounds.csv` rows of that driver (its I/O base and IRQ, the E2h-written
  table index, the status word's pointer, the unset callback); its PUSHF pairs are
  `flags.csv` rows; range arithmetic wraps; a call nested one level deeper than itself (the
  seek's fast-forward re-entering the tick, `+01B04`) is an exit row the I3 monitor checks
  by the stack depth. The driver's adc/sbb of a constant address and an immediate stays one
  68k instruction on memory (`Ctx.atomic_carry`): its code runs in main code and at
  interrupt level. An annotation row of one driver's code applies to that driver's build
  only (`image.rows`).
- Delivery: an IRQ0 for a guest handler the proof does not cover (the voice install's
  timing check at `+05297`, which inverts the interrupted AX that its loop at
  `+05216..+05222` watches; `ADLIB.IMS`'s calibration handler) waits for a poll point and
  is delivered there like any guest vector, on the live registers; only the proved handler
  runs on the private stack with the interrupted state restored. IRQ 7 is delivered the
  same way. Production polls the waits that need such a delivery (`irq-polls.csv`): the
  timing check's loops (`+0521A`, `+0521E`), without which the Amiga image spins at the
  install (MEASURED), the detection's wait for F2h's IRQ 7 (`+050A9`) and CT-VOICE's
  interrupt test (`+055AC`), whose one-byte block's IRQ 7 must arrive within 2000h passes
  or the driver installs no tick (MEASURED). Those alone leave a voice's end late:
  CT-VOICE's status word, which the IRQ 7 handler writes, is read where production does
  not poll, and the intro's first voice's IRQ 7 was taken 1,414 fields after its post
  (MEASURED). So this build's production image compiles in every generated poll point,
  the reference's own delivery points (`amiga/Makefile`: `XWING_SYNC` for the generated
  code alone, which gates only the poll checks); its runtime stays the production one.
  IRQ 7 is posted outside the ring (`runtime.h` `rt_irq7_tail`): a pending one holds no
  CIA tick, and a poll point takes it after the posted ring, IRQ0 and IRQ1 being the
  PIC's higher priorities. In the ring, 33 ticks posted behind it overwrote it (MEASURED);
  a post to a full ring is now a stop at the next poll point (`rt_irq_post`). An IRQ0 tick
  posted behind another, while the consumer has not reached it, is counted onto that
  entry instead (`rt_irq_more`, owner decision 2026-11-23): a runtime service that holds
  the ticks for longer than the ring's 32 entries no longer fills it, and every tick is
  still delivered in order. The producer counts only onto an entry the consumer is not
  taking (tail − 1 ≠ head), and the consumer touches only the head entry, so neither
  masks interrupts.
- Checks: host lockstep against the Sound Blaster references (`tools/reference.py --polls
  --sb`, then `XWING_DRIVER=ADLIB_W.IMS python3 tests/host_run.py`): every DSP status
  read against `trace/dsp-status.csv`, its value differing only by the device's timing
  and none left over; every block's (linear, length, rate) against the reference's DSP and
  DMA writes (`trace/sound.csv`, decoded independently of `ports.c`); and the run's other
  checks (services, interrupts, OPL writes, RAM, frames, the I3 monitor), whose sync rows
  the build re-measured (`irq-sync.csv`, column `driver`). The voices' VOC data lies in the
  front end's song buffer, which the handler reads through its song pointers: a handler
  read at a footprint song site (class S) is a song read wherever it lands, so the voice
  bytes take the song check against the driver requests around their load
  (`tests/irq_monitor.py`). An access in an STI's shadow is masked for the monitor as for
  the proof, which lists such instructions (footprint kind `shadow`: CT-VOICE's stop,
  whose wait at `+055F0` re-enables interrupts before each read of its flag). The plants `sb-block` (the first
  block one byte long), `sb-irq` (an IRQ 7 with no block playing) and `dsp-status` (22Eh
  reporting no data after the reset) must fail it. MEASURED at m01: 1,117 interrupts,
  1,404,004 services, 495 OPL writes and 1 block equal, 97 status reads replayed; all
  three plants caught. MEASURED over every pinned milestone (m00 to m17 and m02i): all
  pass, with 120 blocks equal (m02i 44 with 44 pauses and 29 continues; m15 10; m14 9)
  and 3,647 status reads replayed; at m01 every runtime plant but `song-requests` is
  caught, and `song-requests` is at m07 (the front end's load into the song and voice
  buffer racing the handler's reads).
- Play (`src/platform/amiga/sb_play.c`): `plat_sb_block` converts the block's bytes to
  signed in one of two Chip blocks (`Audio.cpp`; a block in the EMS page frame, which
  flight plays from, has its frame pages copied in first: the m14 reference's E9741h),
  and the player plays it on Paula voice 3 (the effects take voices 0–2), in chunks of at
  most one Paula loop, at the rate's period, at full volume while the DSP's speaker is
  on, from the next field; a pause holds it, a continue restarts at the sample reached.
  The card's terminal count is timed apart from the voice (`amiga_platform.c`): the
  other CIA-B timer counts length / rate in E-clocks from the 14h, one-shot in 16-bit
  slices, held while a D0h pause lasts and dropped when a new block replaces the one
  before it, and posts IRQ 7 at zero (interrupts disabled around the post; the main program
  runs in user mode, where SR is privileged); without that timer a block stops.
  `make t-sb-play` (in `make gates-audio`) runs the player on synthetic blocks: the
  restart, period, speaker, end field (within a field of length / rate), chunks, pad,
  pause, continue, PAL and NTSC; `t-sab-sb-play` plants nine faults. `make
  test-amiga-speech` runs the production image of this build on the Sound Blaster setup
  on the 68030 model through the intro to m02i's label, where real blocks must have
  started (more than CT-VOICE's one-byte test), then 500 fields, in which more must end;
  any stop fails, and so does no label within 60,000 fields (MEASURED: 45 started by the
  label, 46 started and 40 ended at its end, 8,560 Paula restarts). The count is not the
  reference's 44: on the 68030 the intro runs about 3.5 times slower than on DOS, its
  lines on the PIT clock run ahead of its pictures, and some differ and overlap. `amiga/run.sh`
  boots the Sound Blaster setup when the image is this build.
