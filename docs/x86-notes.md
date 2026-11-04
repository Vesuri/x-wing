# x86 real-mode notes for the translator

Copied from Secret Weapons of the Luftwaffe's `docs/x86-notes.md` (commit pinned in
`manifest/references.tsv`) and adapted: X-Wing's binary facts, overlay manager and the
80186 forms replace SWOTL's, whose measured rows stay tagged [SW] as a reference.

Facts the decoder, IR and 68020 lowering must get right. Source tags:

- **[XW]** measured here on X-Wing (command or method named).
- **[SW]** measured in Secret Weapons of the Luftwaffe on `SWOTL.EXE`.
- **[SL]** measured or documented in Slicks (file named).
- **[K]** general architecture knowledge (Intel/Motorola manuals). Not yet
  checked against our oracle; every [K] row needs a differential case before
  the lowering that relies on it is accepted.
- **[T]** checked by `tests/x86_diff.py` (IR on the host vs Unicorn x86-16,
  gate 3); the [K] rows below on shifts, rotates, flags, strings, stack and
  address wrap, MUL/DIV, BCD and the 80186 forms are covered by its boundary corpus.
- **UNKNOWN** — open; must be measured, not assumed.

Translation lessons and provenance: Secret Weapons of the Luftwaffe's
`docs/translation-lessons.md`.

## X-Wing binary facts [XW]

| Item | Value | Method |
|---|---|---|
| Code units | root `XWING.EXE` (overlay area 5BA0h..39600h excluded), 20 `FRONTEND.OVL` and 6 `FLIGHT.OVL` segments, `ADLIB.IMS` | [overlay manager](overlay-manager.md), `translator/cfg.py` |
| Decoded instructions | 183,747 static starts from annotations alone (root 8,022, `FRONTEND` 97,040, `FLIGHT` 71,368, `ADLIB.IMS` 7,285, the self-modified cell run excluded); every traced start decoded (99,493, plus 343 in the cell run from snapshot bytes) | `tests/test_decode.py` |
| Instruction set | 8086 plus five 80186 forms: `push imm`, `imul r16,r/m16,imm`, shifts and rotates by an immediate, `enter`, `leave` (in `FRONTEND`, `ADLIB.IMS` and the root; `FLIGHT` is 8086). No `pusha`/`popa`, `bound`, `ins`/`outs`, 0Fh, 386 prefixes, FPU, `WAIT` or `LOCK` | `tests/test_decode.py`, [external surface](external-surface.md#translator-fit) |
| Code segment frames | a far function's CS is its entry rounded down to a paragraph, so the bytes just below an entry belong to the previous frame: CS follows control flow, not address | `translator/cfg.py`, `tools/sweep.py` |
| Entries static descent cannot see | the two `ADLIB.IMS` INT 08h handlers (set by `mov dx,imm; AX=2508h`) and a continuation the root pushes as a return address (`mov bx,0236h; push bx` at `+058BE`) | `annotations/entries.csv` |
| Overlay format | per segment a fixup list (offset, link segment) padded to a paragraph, then code; loader in [overlay manager](overlay-manager.md) | P2 model check |

### Linear-sweep inventory is garbage [SW]

A Capstone linear sweep (every byte from 0) of SWOTL's `FLIGHT.OVL` gives 126 `OUTSW`,
105 `OUTSB`, 104 `INSB`, 42 `BOUND`, 30 `DAA`: ASCII decoded as instructions. Use only
recursive descent from proved entries plus the trace (`tools/sweep.py`,
`translator/cfg.py`).

## Overlay manager [XW]

Mechanism, table and verified rules: [overlay-manager.md](overlay-manager.md). For the
translator: a thunk (`call 048Ah; jmp far; dw index`) is "make segment `index` resident"
plus the far jump; the manager keeps a segment's parents resident; a far target resolves
to the calling segment, its parent chain, else the root. Translated code is keyed by
(file, offset).

## Flags vs 68k CCR [K]

FLAGS bits: CF0, 1, PF2, AF4, ZF6, SF7, TF8, IF9, DF10, OF11. On a 286 in
real mode `PUSHF` stores bits 12–15 as 0 (8086: 1; 386 can set 12–14) — the
classic CPU probe. [SL] found a CPU probe selecting an optional 386 path
(operand-size prefixes, `PUSHAD`, `PUSHFD`, FS/GS) in Borland's runtime
(Slicks `docs/source-inventory.md`).

| Topic | x86 | 68k | Lowering consequence |
|---|---|---|---|
| Carry on SUB/CMP/SBB/NEG | CF = borrow | C = borrow (X too) | Same convention; reuse CCR |
| CMP operand order | `cmp a,b` = a−b | `cmp src,Dn` = Dn−src | Swap operands |
| Unsigned/signed branches | JB JAE JBE JA / JL JGE JLE JG / JS JO | BCS BCC BLS BHI / BLT BGE BLE BGT / BMI BVS | Direct map when the producer is ADD/SUB/CMP |
| `MOV`, `LEA`, `XCHG`, `CBW`, `CWD`, `PUSH`/`POP` | no flags | `MOVE`/`CLR`/`EXT` write N Z, clear V C; `MOVEA`, `LEA`, `EXG`, `MOVEM` don't | 68k data moves clobber CCR: schedule flag consumers first or rematerialise |
| `INC`/`DEC` | OF SF ZF AF PF; **CF kept** | `ADDQ/SUBQ` to Dn write C and X; to An write nothing | Preserve CF when live (`MOVE CCR,Dn` is 68010+) |
| `AND OR XOR TEST` | CF=OF=0, SF ZF PF, AF undefined | V=C=0, N Z | Match except PF |
| `ADC`/`SBB` | ZF from result | `ADDX`/`SUBX` use X, Z only cleared (sticky); Dn,Dn or −(An),−(An) only | Set X=CF first; Z needs seeding or separate test |
| `NEG` | CF = (src≠0) | C = X = (result≠0) | Same |
| `MUL`/`IMUL` | CF=OF = high half significant; SF ZF AF PF undefined | `MULU/MULS` N Z, V=C=0 | Compute CF/OF only if live |
| `DIV`/`IDIV` | flags undefined; quotient AX, remainder DX; overflow or /0 → INT 0 (286+: return address = the DIV) | `DIVU/DIVS.W`: quotient low word, remainder high; /0 → vector 5; overflow sets V, no trap, operand unchanged | Swap halves; overflow must raise the guest INT 0 path |
| IDIV rounding | toward zero, remainder has dividend's sign | same | Same |
| AF | nibble carry | none | Compute lazily: needed by `DAA DAS AAA AAS`, `LAHF`, `PUSHF` |
| PF | even parity of low 8 result bits | none | Lazy; consumers `JP JNP LAHF PUSHF` |
| `LAHF`/`SAHF`, `PUSHF`/`POPF` | expose SF ZF AF PF CF / whole word | — | Full materialisation boundary; [SL] architecture: build it only when observed |
| `LOOP`, `JCXZ` | no flags | `SUBQ` clobbers CCR; `DBcc` doesn't | `DBcc` with a biased counter, or keep flags virtual |

## Shifts and rotates [K]

- 186+ (incl. 286) mask the count to 5 bits; 8086 does not. Count 0 after
  masking: no flags change. 68k register counts are mod 64; count 0 clears C
  (X unchanged), `ROXL/ROXR` count 0 set C=X.
- `SHL/SAL`: CF = last bit out; OF defined only for count 1 (MSB(result) xor
  CF); SF ZF PF from result, AF undefined. 68k `ASL` sets V if the MSB changed
  at any step; `LSL` clears V. Lower SHL as `LSL`, derive OF only when live and
  count = 1.
- `SHR`: count 1 OF = MSB(original). `SAR`: count 1 OF = 0. 68k `LSR`/`ASR`
  clear V.
- Count ≥ operand width (possible after 5-bit masking of a 16-bit operand):
  CF/OF undefined per Intel. Mask in the oracle; reproduce the result bits.
- `ROL/ROR`: only CF and OF change; SF ZF PF kept. 68k `ROL/ROR` write N Z and
  clear V — clobbers flags x86 keeps.
- `RCL/RCR`: through CF; 16-bit count is 5-bit masked then mod 17. 68k
  `ROXL/ROXR` rotate through X, not C: set X from CF first.
- Signedness [SL]: coordinates include `FFFFh`; keep unsigned 16-bit
  arithmetic and logical shifts (Slicks `docs/external-surface.md`).

## Segments, addresses, endianness

- [K] Physical = seg×16 + off. Effective-address offsets wrap mod 64 KiB
  (`[bx+si+disp]`, `SI/DI` in string ops, `SP`). Above 1 MiB: wraps or HMA
  depending on A20 — UNKNOWN whether X-Wing ever forms such addresses.
- [K] A word access at offset `FFFFh`: 8086 wraps to offset 0; 286+ real mode
  faults (INT 0Dh). DOSBox and the port: [T] below.
- [K] Default segments: `BP`-based → SS, others → DS, string destination
  ES:DI (not overridable), stack SS:SP. Prefixes `26 2E 36 3E` (ES CS SS DS).
  `MOV SS` / `POP SS` inhibit interrupts for one instruction.
- [K] Far pointer in memory = offset word, then segment word. `LES`/`LDS`.
- [SL] 16-bit address wrap is real in game code: VGA plane offsets and a
  screen-transition source wrap at 64 KiB; plot offset is the low 16 bits of
  `base + y×stride + x/4` (Slicks `docs/native-graphics-abi.md`,
  `external-surface.md`).
- [SL] Guest RAM stays byte-exact little-endian; every native word/long access
  states its endian rule. Never alias guest RAM as a wide native pointer (RV
  learned the same; see translation-lessons #43).
- [SL] Callers pass bytes as words; callees use only the low byte (far fill
  value, readback height). Do not assume a zero high byte
  (Slicks `external-surface.md`).

## String instructions [K]

- `MOVS STOS LODS SCAS CMPS` (+`INS OUTS` 186+). DF=0 increments, DF=1
  decrements. `REP` with CX=0 runs zero iterations and changes no flags.
- `REPE/REPNE` with `CMPS/SCAS` stop on ZF; flags are those of the last
  comparison. Source segment overridable, destination ES fixed.
- Overlap is defined per element, forward: `rep movsb` with DI = SI+1
  replicates a byte. Never lower to `memmove`.
- SI/DI wrap at 64 KiB independently mid-string.
- DF: assume nothing. Treat DF as a live guest flag; a translated block may
  specialise on DF=0 only where analysis proves it.
- [SL] An instrumented trace shows `REP` iterations as self-edges (Slicks
  `tools/analyze_execution_trace.py` classifies `destination == source` as
  "repeat").

## Calls, returns, stack [K]

- Near `CALL` pushes IP; far `CALL` pushes CS then IP; `RETF n` pops IP, CS,
  then adds n to SP. Compiler idiom `push cs; call near` calls a far routine
  in the same segment; `push seg; push off; retf` is a far jump.
- Code can pop or rewrite its return address (inline parameters, dispatch).
  Guest stack bytes must stay guest CS:IP values to keep RAM byte-exact, so a
  `RET` is a mapping from guest IP to native code unless call/return pairing is
  proved. Decided: [translator-design.md](translator-design.md) Calls (D1).
- [SL] Borland far cdecl: caller cleans arguments; a far pointer argument is
  two words; static callers' `add sp,n` confirms arity.

SWOTL calling convention [SW] (MS C 5.x medium), kept as the reference until X-Wing's is
measured. X-Wing differs at least in its prologues: `FRONTEND` and `ADLIB.IMS` use
`enter`/`leave` [XW].

| Item | SWOTL fact | Evidence |
|---|---|---|
| Memory model | MS C medium: far code (`lcall`/`retf`), near data in DGROUP; far pointers explicit (`les` 539 sites) | 3,587 `lcall`, 965 `retf` in decoded game code |
| DGROUP | DATA.OVL; DS = SS = load seg + `3BABh`; near stack in DGROUP, SP = `EF2Eh` at start; BSS `5E32h..EF30h` cleared | `__astart` `+1369C..+13707` |
| Argument passing | right to left on the stack; first argument at `[bp+6]` | prologues; `__astart` pushes envp, argv, argc |
| Cleanup | caller pops (`add sp,N` after 2,503 of 3,587 far calls); long-arithmetic helpers pop their own (`retf 4/6/8`) | runtime.csv |
| Return values | AX (int, near pointer); DX:AX (long, far pointer) | `__aFlmul`, `_atol` |
| Preserved | SI, DI, BP, DS, SS; AX, BX, CX, DX, ES clobbered | prologue `push di; push si`, epilogue `pop si; pop di; mov sp,bp; pop bp; retf` |
| Prologue | `push bp; mov bp,sp; sub sp,N; push di; push si` (649 frames); no `enter` | sweep |
| Same-segment far calls | `push cs; call rel16` (1,111 sites; every near call in the overlays); the callee returns with `retf` | treat as a far call |
| Stack probe | `__chkstk` (`1369:24DA`) called only by `__output`: game built without stack checks | call-target scan |
| Long helpers | `__aFlmul` `098E`, `__aFldiv` `0292`, `__aFlrem` `239A`, `__aFuldiv` `08A8`, `__aFlshl` `1A56`, `__aFlshr` `0DAA`, `__aFulshr` `2442`; assign forms `__aFNalmul` `0862`, `__aFNaldiv` `096A`, `__aFNauldiv` `09C2`, `__aFNalshl` `010E`, `__aFNalshr` `0886`, `__aFNaulshr` `0D88` | runtime.csv |
| Floating point | not linked: `__fpmath` (DGROUP `[5876]`) = 0, no INT 34h–3Dh or `WAIT`+`ESC` decoded or traced | `__cinit` `+137E0` |

## Real-mode details fixed by the differential [T]

- Word access at offset `FFFFh` reads/writes linear `base+FFFFh` and
  `base+10000h` (no wrap inside the word, no fault), as DOSBox. Whether
  X-Wing forms one: UNKNOWN.
- No 1 MiB wrap (A20 on): `FFFF:0010` is linear `100000h`.
- `LES/LDS`, far `CALL/JMP [m]`: the segment word is at offset+2 mod 64 KiB.
- `push sp` stores SP before the decrement; `pop sp` loads the popped word.
- `IDIV` accepts the most negative quotient (−128 / −32768); `DIV`/`IDIV`
  overflow and divide-by-zero fault with IP at the instruction, registers
  unchanged; `AAM 0` faults the same way.
- `POPF` in real mode keeps FLAGS bits 12–14 (IOPL/NT, 386) and clears 15.
- 80186 forms (`i186_cases`):
  - shifts and rotates by an immediate mask the count to 5 bits, as by CL; a masked
    count of 0 changes neither the operand nor the flags;
  - `push imm8` (6Ah) and `imul r16,r/m16,imm8` (6Bh) sign-extend the byte;
  - three-operand `imul` keeps the low 16 bits of the signed product, CF = OF = product
    not representable in 16 bits, SF ZF AF PF undefined;
  - `enter size,level` masks the level to 5 bits: it pushes BP, then for level > 0
    copies level − 1 frame pointers from `SS:BP−2`, `−4`, … and pushes the new frame
    pointer; BP = the frame pointer, SP −= size; every SP and BP step wraps at 64 KiB;
  - `leave` is SP = BP, then pop BP.

## Unicorn x86-16 as oracle

Deviations and quirks of Unicorn 2.1.4 the harness works around (each
probed on this host):

| Quirk | Handling |
|---|---|
| `uc_mem_write` does not invalidate translated blocks | flush (`UC_CTL_TB_FLUSH`) after every patch |
| `count=1` runs one `REP` iteration | stop from a code hook at the next instruction boundary |
| Interrupt hook skips QEMU delivery: `old_exception` stays set, the next exception becomes #DF (8), then a silent triple fault | reopen the engine after every exception |
| `REP` string right after a flag setter in one translation block recomputes OF/AF wrongly (e.g. `add cx,3636h; rep movsb` clears OF) | one instruction per `uc_emu_start` |
| `RETF` at SP ≥ `FFFDh` reads CS at `SS:SP+2` without 16-bit wrap (Intel/DOSBox wrap) | single-instruction cases retain the existing deviation count; multi-instruction cases execute the affected instruction in live DOSBox-X (`tests/dosbox_retf.py`), comparing full registers/flags and checking the 1 MiB memory window unchanged |
| Self-overwriting `REP` refetches the modified instruction | case discarded |
| A store into the 4 KiB page of the executing instruction makes QEMU restart it; stopped after one instruction it has not run (IP unchanged, no store) | counted as an oracle deviation (only when IP did not move) |
| Software `INT n` on an exception vector (0, 1, 5, 6, 8, 13) goes through QEMU's exception path (intno indistinguishable from the fault, sometimes `UC_ERR_EXCEPTION`) | counted as an oracle deviation, not compared |
| A `count` to `uc_emu_start` hooks every instruction (the m2 host run 291 s vs 43 s) | long runs stop on a timeout |
| Capstone prints `notrack` for `3Eh`-prefixed `call/jmp`, `cdq`/`cwde` for `CWD`/`CBW` in 16-bit mode | normalised in `tests/test_decode.py` |

## Interrupts [K] unless tagged

- IVT at `0000:0000`, 4 bytes per vector (offset, segment). Set by
  `int 21h AH=25h` or direct stores; read by `AH=35h`. Every handler a program
  installs is an entry point.
- `INT n` pushes FLAGS, CS, IP and clears IF, TF; `IRET` pops IP, CS, FLAGS.
  `INTO` = INT 4 if OF; `INT3` = `CCh`; `BOUND` failure = INT 5 (186+).
- Master PIC IRQ0–7 → INT 08h–0Fh. IRQ0 PIT → 08h; IRQ1 keyboard → 09h. BIOS
  08h increments the dword tick count at `0040:006C` and calls INT 1Ch.
- [SL] Observed DOS services (Slicks): `1A 25 29 2A 2C 2F 30 35 37 38 3B 3D 3E
  3F 41 42 43 44 4A 4B 4D 4E 4F`; INT 10h `00 08 0F 12`; INT 2Fh `4300/4310`
  (XMS); INT 33h `0000 0003 0008 0009`. Trace kept AX..BP, SP, FLAGS per event
  (Slicks `docs/external-surface.md`). X-Wing's set: [external-surface.md](external-surface.md).
- [SL] Timer handler entered from game code and while a DOS service was
  active: asynchronous state, not a call (Slicks `external-surface.md`).
- Delivery in the port: at safe guest boundaries, never as game code inside an
  Amiga interrupt (PK; translation-lessons #31).

## Port I/O

| Ports | Device | Notes |
|---|---|---|
| `20h`, `21h` | PIC | `out 20h,20h` = EOI; 21h = mask [K]; observed [SL] |
| `40h`–`43h` | PIT | 1,193,182 Hz input; 43h control (channel, access, mode); latch then read lo/hi from 40h; ch2 (42h) drives the speaker [K]. [SL]: millions of PIT reads per race |
| `60h`, `61h` | Keyboard / PPI | Set-1 scancodes, break = make\|80h, `E0` prefix; 61h bit 0 PIT gate 2, bit 1 speaker, bit 7 XT ack [K]. [SL] keyboard ISR at INT 09h |
| `201h` | Joystick | [SL] polled |
| `3C0h` | Attribute | flip-flop reset by reading 3DAh [K] |
| `3C4h/3C5h` | Sequencer | idx 02h map mask, idx 04h memory mode (chain-4) [K] |
| `3C7h–3C9h` | DAC | 3C8h write index, then R,G,B 6-bit to 3C9h, auto-increment; 3C7h read index [K] |
| `3CEh/3CFh` | Graphics ctrl | idx 04h read map, 05h mode, 08h bit mask [K] |
| `3D4h/3D5h` | CRTC | 0Ch/0Dh start address (page flip), 14h/17h for unchained modes [K] |
| `3DAh` | Input status 1 | bit 3 vertical retrace, bit 0 display disabled [K]. [SL] polled millions of times |

X-Wing port use (swept + traced): [external-surface.md](external-surface.md). [SL] rule: replace the routines around port traffic,
not ports one by one (translation-lessons #25).

## Mode 13h

- [K] `int 10h AX=0013h`: 320×200, 256 colours, chain-4, linear at
  `A000:0000`, 64,000 bytes, pixel at `y×320+x`. DAC 6-bit components.
- [K] Clearing chain-4 (sequencer 04h) plus CRTC 14h/17h gives an unchained
  planar layout (four 64 KiB planes, multiple pages).
- [SL] Slicks set mode 13h through BIOS, then went unchained: 100-byte stride,
  page separation 32,700, sequencer/GC programming in the inner loops. "Treating
  mode 13h as only a flat 320×200 framebuffer would be insufficient"
  (Slicks `external-surface.md`).
- X-Wing stays chained: no sequencer, graphics-controller or CRTC writes, no page flip
  [XW] ([external-surface.md](external-surface.md#vga)).

## MZ relocation [K]

- Header: `+02` bytes in last page, `+04` 512-byte pages, `+06` relocation
  count, `+08` header paragraphs, `+0A/+0C` min/max alloc, `+0E/+10` SS/SP,
  `+14/+16` IP/CS, `+18` relocation table offset, `+1A` overlay number.
- Image loads at PSP+10h; each relocation `(offset, segment)` adds the load
  segment to the word at `load+segment : offset`. Entry DS = ES = PSP.
- [SL] Normalise by subtracting the load segment (4,192 relocations reversed
  by Slicks `tools/rebuild_runtime_mz.py`) and compare traces against that.
- The relocation table marks segment-valued words: a free data/code
  classifier for far pointers and segment immediates. Not every segment value
  is relocated (computed segments, overlay segments, PSP-relative values).

## Borland/runtime surprises [SL]

- Compack unpacker at entry: no disassembly trusted before the handoff image
  was captured twice independently. SWOTL has no Compack signature [SW]; X-Wing's root
  is decoded from its MZ image directly and matches the trace [XW].
- CPU probe plus a reachable 386 path in a "16-bit" program; reference runs
  pinned to a 286 personality with a 386 comparison.
- Far fill helper: byte-aligns an odd destination, then word stores, repeating
  only the low byte; also used on `A000h` and `B800h`, so library helpers can
  be device code.
- Palette nearest-colour helper: asymmetric signed/unsigned component handling
  exposed only by high input bytes (Slicks `docs/validation-harness.md`).
- Sub-rectangle blit: source x truncated to a byte offset yet added to the
  destination origin — an original quirk the oracle had to confirm.
- Borland RNG reproduced; RNG call order is checked by an oracle
  (Slicks `docs/toolchain.md` verify-surface-effects, `docs/performance.md`).
- No writes into executed instruction bytes on the measured path; other paths
  unproven (Slicks `external-surface.md`).
