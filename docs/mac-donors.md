# Macintosh donors

P8 step 4: does the Macintosh demo's 68k code have counterparts of the DOS routines the
combat film spends its time in, and could they be transplanted? `tools/mac_code_survey.py`
(the method is in its docstring) reads the demo's resource fork and the translator's flight
IR. It uses AmigaXDev's `amigaxdev.mac` resource reader and recursive-descent walk.

## The answer

The hot code of the film has no donor. Two medium routines have counterparts, but they cost
1.9% of the film between them. A transplant is a hand rewrite against the DOS oracle, not a
copy. The route to the 100 ms target is the translator and hand natives
([open work](open-work.md), P8 steps 5–12), not the Macintosh code.

## The Macintosh engine is a later one

| Finding | Evidence |
|---|---|
| Seven `CODE` resources, named: 0 the jump table, 1 `GameMain` 24,226 B, 2 `Landru` 60,540 B, 3 `Interface` 5,247 B, 4 `Flight engine` 269,055 B, 5 `MacLib` 30,097 B, 6 `Libraries` 46,676 B | MEASURED |
| The walk reaches 90.9–96.0% of CODE 1, 2, 4 and 5, 83.7% of 3, and 6.9% of 6, a library mostly called from code it cannot follow. It finds 1,583 functions | MEASURED |
| No FPU instruction on any reached path. Flight engine has 2,056 instructions that need a 68020 (`muls.l`, scaled indexes and the like), which the 68030 runs | MEASURED. A linear sweep instead finds about 500 FPU mnemonics in CODE 4: data decoded as code |
| Mission files are shared: `LEVEL1`–`LEVEL8.XWI` and `VGA.PAC` are byte-identical to the DOS files, so the Macintosh reads the DOS little-endian mission layout | MEASURED, SHA-256 |
| The art is 640×480. The cockpit `LFD`s hold a `MASK` and a `PLTT` named `640480` and are 3–4× the DOS size. `MAINMENU.LFD` is 4.4× and the fonts 19–32× | MEASURED |
| The ships are another model format. `SPECIES.LFD` holds 71 `CPLX` models and 27 `XACT` bitmaps where DOS has 71 `CRFT` and 27 `BTMP`, ship for ship. `BLAST.LFD` has 72 explosion and shot animations against 37 | MEASURED |
| The flight engine therefore renders other models at another resolution. It is the later high-resolution X-Wing engine, not a recompile of the DOS floppy one | INFERRED |

## The film's routines and their counterparts

These are the top 20 guest routines of the film's profile (`tools/perf_film.py`, 2026-11-23,
after step 2), with their share of the profile. A function is found when its score
(IDF-weighted Jaccard similarity of structure-field displacements and immediates) beats
the best score of 20 rarity-matched random controls. A match on common tokens alone
(`0`, `1`, `2`, `ff`, `80`) is not counted.

| DOS routine | Share | Character (DERIVED from the IR) | Macintosh counterpart | Score / control |
|---|---|---|---|---|
| FLIGHT.OVL+22541 | 10.67% | called once a frame; ES stores, no multiplies | none | 0.148 / 0.191 |
| +235FE | 6.06% | 45 near returns, 28 multiplies, shifts | none | 0.186 / 0.332 |
| +21E61 | 5.84% | shifts and tests, no multiplies | none (only common tokens) | 0.589 / 0.437 |
| +20D5F | 3.66% | 108 `imul`, `sar`/`rcr` pairs: fixed-point transforms | none | 0.345 / 1.000 |
| +1C288 | 3.03% | spans: 55 `stos`, 116 shifts | marginal: CODE 4+16836, 34 field offsets shared | 0.261 / 0.246 |
| +22E3E | 2.73% | 3,557 calls in the 100 fields; one token | not resolvable | 0.485 / 1.000 |
| +233B2 | 2.37% | ES stores, shifts | none | 0.199 / 0.313 |
| +1B0C8 | 2.03% | 42 divides, 117 `sar` | none | 0.172 / 0.402 |
| +24A4F | 1.90% | the self-modified cell, entered only by the walk | not comparable | — |
| +202C0 | 1.58% | shifts, 19 multiplies | none (only common tokens) | 0.449 / 0.290 |
| +1D846 | 1.34% | 248 `sar`/`rcr` pairs: 32-bit shifts | none | 0.319 / 0.330 |
| **+06344** | 1.13% | C: 22 multiplies, 58 tokens | **CODE 4+017B2**, 46 shared, among them the constants 3000, 0xAB, 0x37 and 0x4C | 0.578 / 0.226 |
| +24927 | 1.10% | three tokens | not resolvable | 0.384 / 0.684 |
| +1D6AF | 1.10% | 15 `imul` | not resolvable | 0.615 / 1.000 |
| +06D3C | 1.07% | C | marginal: CODE 4+02202, 7 shared | 0.357 / 0.283 |
| +1E900 | 0.96% | 124 ES stores | none | 0.406 / 0.441 |
| +218F3 | 0.94% | 14 multiplies | none | 0.301 / 0.400 |
| +2867B | 0.82% | 24 `rep`, 21 far returns | none | 0.612 / 0.718 |
| **+26A20** | 0.79% | 32 multiplies, angle constants | **CODE 4+286E4**, 30 shared, among them 0x2000, 0x6000, 0xA000, 0xD800, 0xE000 and 0x7FFF | 0.472 / 0.214 |
| +1F7EF | 0.74% | ES stores, 16 multiplies | none | 0.194 / 0.418 |

What the table shows:
- **Pixels and spans have no counterpart.** The routines without one take about 50% of the
  profile in its top 30 (DERIVED). Among them are all the routines that store through ES
  and run spans; the span routine +1C288 clears its control by 0.015 only. That is
  expected of a rasterizer for other models at 640×480 (INFERRED).
- **The two counterparts are C logic.** They compare the same structure fields and
  constants, as code that reads the shared mission data would.
- **What the method cannot do:** short routines with fewer than about eight tokens cannot
  be resolved. A routine rewritten in different style would also be missed. The bound on
  that: the walk covers every Macintosh function, and the matches it does find carry rare
  constants.

## Transplanting

A Macintosh routine cannot be dropped into the port. Running one would mean rewriting it:
- **Memory.** The port keeps the DOS guest's memory byte-exact and byte-reversed
  (`docs/translator-design.md` D5): x86 little-endian structures with 16-bit near and
  segment pointers, linear L at TOP − L. The Macintosh routine reads big-endian structures
  with 32-bit pointers, laid out by another compiler. Every load and store of a donor would
  have to be rewritten.
- **Fidelity.** A native routine must give the DOS routine's results bit for bit
  (lockstep, `annotations/hle.csv` with its oracle). A Macintosh routine for the later
  engine computes for other models and other precision unless shown otherwise.
- **Gain.** The two counterparts cost 1.13% and 0.79% of the film. Even replaced by no code
  at all they move the film by about 6 ms of its 320 (DERIVED), below the frames fixture's
  resolution.

What the Macintosh code can still give is a reference: how the later engine computes the
same quantity, read beside the DOS routine when a hand native is written (step 12).
Taking that needs no Macintosh milestones. Open work item 2 (Macintosh milestones and the
CODE map) is needed only if a donor routine is ever run, and nothing found here asks for
one.

## Not covered

- The intro (FRONTEND), whose two hot routines are a compare-and-copy and a sprite
  decoder. The Macintosh front end draws 640×480 art (`MAINMENU.LFD`), and the demo's intro
  was not examined.
- The PowerPC data fork.
