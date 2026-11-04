# External surface

Everything the DOS program does outside its own code, with counts, plus the
translator fit. The sources are the sweep of the root, both overlays and `ADLIB.IMS`, and
the newest milestone set (17 traces, m00–m16). `make map` regenerates the tables
(`tmp/sweep/surface.md`, `tmp/sweep/census.md`); counts are summed over the 17 traces.
`tools/surface.py` fails if a traced interrupt or port site is not a decoded static
instruction; none is. Module offsets are as in [overlay manager](overlay-manager.md).

## Map

| Module | Code bytes | Static code | Executed | Switch tables | Indirect sites (executed, traced targets) |
|---|---|---|---|---|---|
| `XWING.EXE` (code and data, without the overlay area) | 52,565 | 19,119 | 11,297 | 0 | 25 (5, 5) |
| `FRONTEND.OVL` (20 segments) | 490,414 | 256,189 | 148,873 | 1,534 | 86 (68, 68) |
| `FLIGHT.OVL` (6 segments) | 241,102 | 200,580 | 89,866 | 818 | 148 (60, 60) |
| `ADLIB.IMS` | 21,368 | 17,341 | 13,328 | 130 | 29 (28, 28) |

The sweep finds:
- 0 conflicts;
- 0 executed bytes outside decoded code;
- every traced instruction start is a static start.

The sweep's switch rule needed a second form beyond MS C's. Here the index is already a
byte offset (`shr ax,3` of a multiple of 16), so a bound of N gives N/2+1 entries.

Far functions have their own CS: the entry rounded down to a paragraph. The sweep
therefore keeps, per CS, the lowest entry it is known from.

The root's data holds 721 relocated segment words:
- 528 point into the overlay area;
- 149 point to root code;
- 44 point to data.

The pointers into the overlay area are far pointers whose target depends on which base
segment is resident.

## Overlay manager

[Overlay manager](overlay-manager.md) describes the manager. Over the 17 traces:
- 29,237 thunk calls;
- 45,943 manager calls, 45,842 of them on a segment already resident;
- 101 segment loads;
- 0 model violations (`tools/overlay_check.py`; each `--sabotage` rule fails as it must).

The EMS cache is never on.

## Software interrupts

| INT | Functions (sites) | Callers |
|---|---|---|
| 10h | AH=00h (modes 13h ×16, 03h ×1), 0Fh, AX=1012h ×14 | root; `FLIGHT` sets the palette by AX=1012h |
| 16h | AH=00h, 01h, 02h | `FRONTEND` keyboard; root shift-state poll |
| 21h | AH=0Bh 0Eh 19h 1Ah 1Bh 2Ah 2Ch 2Fh 30h 3Ch–3Fh 40h 42h–44h 47h–4Bh 4Eh 4Fh; AX=25xxh, 35xxh | root (C run-time, startup, overlay manager), `FLIGHT` AH=2Ch ×3, `ADLIB.IMS` vector 08h |
| 33h | AX=0000h, 0003h, 0004h, 000Bh | `FRONTEND` 0003h in busy loops (186,510,590 calls); `FLIGHT` 0003h and 000Bh once per frame |
| 67h | AH=41h 42h 43h 44h 45h 4Ch | root allocates (43h) and frees (45h); `FRONTEND` and `FLIGHT` map pages (44h) |

Of 144 static `int` sites, 86 were traced. The untraced ones include `FLIGHT.OVL+181A9..`
(INT 21h) and three INT 67h sites at `FLIGHT.OVL+18256..182A7`.

### EMS per milestone

INT 67h AH=44h (map a page) counts:

| Milestone | Maps |
|---|---|
| m01 logo | 1,606 |
| m02 title | 2,824 |
| m03 question | 4,372 |
| m04 registration | 10,780 |
| m05 pilot named | 22,972 |
| m06 concourse | 28,922 |
| m07 proving ground | 45,824 |
| m08 historical combat | 49,460 |
| m09 tour of duty | 31,740 |
| m10 film room | 29,816 |
| m11 tech room | 36,838 |
| m12 training flight | 100,907 |
| m13 mission flight | 148,537 |
| m14 tour battle | 267,265 |
| m16 exit to DOS | 27,250 |

The flights also call AH=4Ch (handle pages): 16,235, 7,773 and 70,277 times. Every run
from m01 calls AH=41h (page frame), 42h (page count) and 43h (allocate) once or twice. The
handle is freed (AH=45h) only on exit.

## Hooked vectors

| Vector | Set by | Handler |
|---|---|---|
| 00h (divide error) | root `+01174`, `+01533` (once per run); `+011DE`, `+0167B` (once, in the exit run: INFERRED restore) | not raised |
| 05h, 23h (print screen, Ctrl-Break) | root `+01155`, `+01136` (once per run); `+011CC`, `+011BA` (once, in the exit run) | not raised |
| 08h (timer) | `ADLIB.IMS+0093E..00A13` | `ADLIB.IMS+00A1B` ×287,850; it chains to the BIOS at 18.2 Hz. Before it, `+00938` installs a calibration handler `+00978` that counts ticks while `+0094D` waits; `+00968` restores the previous vector |
| 09h (keyboard) | not hooked | BIOS ×522 |
| 74h (mouse IRQ 12) | not hooked | BIOS ×44 |

There are no mouse event handlers: INT 33h AX=000Ch, 0014h and 0018h are never called.
Input is polled.

## Ports

| Device | In | Out | Ports, sites |
|---|---|---|---|
| PIC | 16 | 269,962 | 20h/21h: `ADLIB.IMS` (EOI and mask) |
| PIT | 0 | 50 | 40h/43h: `ADLIB.IMS+009E9..00A02`, channel 0 divisor 1000h (about 291 Hz) |
| Game port | 4,194,368 | 32 | 201h: root `+0106E..010AB`; the read loop times out at 65,536 per call without a joystick |
| AdLib | 0 | 366,820 | 388h/389h: `ADLIB.IMS+04BE1..04C11` only |
| VGA | 23,579,354 | 1,804,399 | 3C8h/3C9h palette: `FRONTEND+17917..` and root `+013A9..`; 3DAh retrace: `FRONTEND+17908/1790D` |
| DMA, keyboard controller, Sound Blaster (22xh), MPU-401 (330h) | 0 | 0 | never touched |

There are also six untraced static sites. Five are in the root at `+012B9..012D0` (PIT
40h/43h); the sixth is root `+0103E` (`in dx`).

## Music driver interface

`ADLIB.IMS` is loaded by INT 21h AX=4B03h and called through one far entry,
`ADLIB.IMS+00000`, from 43 sites: `FRONTEND` 26, `FLIGHT` 15, root 2. It calls back into the
game in two ways:
- through a far pointer at its `[06DE]` from `+0019C`, to root `+013C6`, on its tick
  divider;
- through a far pointer passed by its caller from `+006B6`, to `FLIGHT.OVL+19561`.

Its INT 08h handlers (the calibration handler, then the timer handler) are the only other ways into it.

## VGA

- Mode 13h, chained: no sequencer, graphics-controller or CRTC writes, so no unchained mode
  and no page flips.
- Palette:
  - `FRONTEND` and the root write 3C8h/3C9h directly (3,331 index and 1,801,068 data
    writes);
  - `FLIGHT` uses INT 10h AX=1012h ×14.
- A000h:
  - `FRONTEND` writes 85,479,335 times and reads 9,128;
  - `FLIGHT` writes 2,855,655 and reads 484,156;
  - both stay below offset 0FA00h, one 64,000-byte page.

## Self-modifying code

There is one region, in `FLIGHT.OVL+25A57..26165`: an unrolled run of
`mov byte [bx+w],al` cells (`88 87 ww`, 4 bytes each). It has an embedded
`mov bx,cs:[w]; mov ds,cs:[w]` at `+25CD7`. Its writers (`annotations/self-modifying.csv`):
- `+26974`, `+26993`, `+269A7` build the run through `es:`;
- `+2498D`, `+249E8`, `+24A46` rewrite cell displacements through `cs:`;
- `+23789` and `+2384C` plant a `ret` at a cell start before a call into the run, and
  `+23795` and `+23857` restore the byte.

The forms (`8887ww`, `2e8b1eww2e8e1eww`, a planted `c3`) are those of Secret Weapons of
the Luftwaffe's cell walk at `SWOTL.EXE+06A4D` (DERIVED from its
`annotations/self-modifying.csv`).
Over the corpus, 2,567 bytes are written into decoded code, all in this region.

`tools/code_writes.py` places every other write into module images:
- 91,170 relocation bytes, each on a segment fixup word by linear address;
- 144 bytes of the manager's zero fill, each in a segment's fill range;
- DOS reads;
- data.

## Translator fit

`translator/decode.py`, Secret Weapons of the Luftwaffe's decoder copied unchanged,
decodes every static instruction start except the 80186 forms:

| Module | Starts | 80186 starts (executed) |
|---|---|---|
| `XWING.EXE` | 8,034 | 3 (3): `enter` 1, `leave` 2 |
| `FRONTEND.OVL` | 97,040 | 1,681 (1,403): `leave` 713, `push imm8` 440, `enter` 277, `push imm16` 211, `shift imm` 39, `imul imm8` 1 |
| `FLIGHT.OVL` | 71,853 | 0 |
| `ADLIB.IMS` | 7,305 | 406 (275): `leave` 195, `push imm` 108, `shift imm` 52, `enter` 46, `imul imm` 5 |

The corpus has:
- no `pusha`/`popa`, `bound`, `ins`/`outs` or 0Fh opcodes;
- no 386 operand- or address-size prefixes;
- no FPU code.

P3 closed the gap: the decoder, IR and interpreter handle `enter`, `leave`, `push imm`,
`imul r,rm,imm` and shifts by an immediate, checked against Capstone and Unicorn
(`make test-x86`, [x86 notes](x86-notes.md)). The flight code, where SWOTL's
cell-walk support (`translator/smc.py`) applies, needs none of them.

Everything else the census found is already covered by SWOTL's design:
- the timer handlers in the music driver;
- polled keyboard, mouse and game port;
- chained mode 13h;
- EMS 4.0 page mapping;
- one self-modifying cell run.

What is new is the overlay manager, which replaces PLINK.
