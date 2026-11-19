# Indirect coverage

`annotations/indirect.csv` (written by `make map`) records execution separately from
static targets: 366 indirect sites, 161 executed in the P2 traces (`ms-p2c-*`, 17 runs)
and 205 not. A default initializer or a snapshot value is not execution evidence or a
proof against later writes. Every unexecuted site keeps its guard: a proved switch table
falls back to a named stop outside the table, and any other site dispatches through
`rt_lookup`, which stops on a target with no translated entry. No site is marked executed
and none is excluded; an exclusion is an owner decision, and there are none.

In the tables, "ran" and "never ran" say whether the site's routine ran. Routines are counted as run when their `push bp; mov bp, sp` entry is an executed
instruction start of the P2 traces (INFERRED: a site after a nested frame or in a routine
without that prologue is counted by its enclosing one).

## Proved switch tables

92 sites have a proved table, 40 of them unexecuted (below). Every target of the table is
translated and runs to its own return check (`docs/translator-design.md`); an index
outside it stops. Besides the MS C bounds checks, the proofs are `annotations/tables.csv`
(cs: word tables) and `annotations/data-tables.csv` (word tables in a data segment, read
directly or loaded into a register first).

| Module | Sites |
|---|---|
| ADLIB | +00387, +0047B, +004DE, +005D2, +005FA (`call cx`, `call ax` through fields of the driver's descriptor at DS:007Ah, `annotations/data-tables.csv`) |
| FLIGHT | +0E1DE, +0EE8C, +142FA, +16352, +16408, +351B3 |
| FRONTEND | +2F150, +33A39, +3903C, +3A95A, +3AC7E, +3F2C6, +3F6A5, +41CCD, +42761, +43C20, +5A768, +5BEF4, +5E465, +5E793, +5ED1E, +5EFB5, +5F1A6, +649D0, +67121, +67302, +676F1, +67E97, +6804C, +6953E, +696BA, +80F41, +81A82, +81DA9, +8235A |

### Executed tables with untraced entries

Three executed sites whose tables hold entries the traces never reached
(`annotations/tables.csv`); the untraced entries are translated from the table words.

| Site | Table | Traced targets |
|---|---|---|
| XWING+02180 | the C run-time `printf` state machine, its class and transition bytes at DGROUP 610Ah (89 bytes, equal to RAM in every snapshot) | 5 of 8 |
| FLIGHT+23981 | 8 words, index 2·[571Ah] (bound INFERRED) | 5 of 8 |
| FLIGHT+239B0 | 8 words; entry 7, FLIGHT+245A9 (200E:8D79), is the loud stop a live flight reached before it was translated | 3 of 8 |

## Calls through pointers

165 sites. Each group's executed sites reached the targets named; the unexecuted ones
dispatch through the same pointer.

### FLIGHT pointers to overlay thunks

FLIGHT 089D:05D0 copies the far pointers at DGROUP 0F04h–0F27h into the slots below;
no translated instruction writes 0F00h–0F2Fh directly (DERIVED: `build/gen` x86 listing).
Each pointer is a root overlay thunk (`call 048Ah; jmp far`, docs/overlay-manager.md),
the same value in the m01 and m14 reference snapshots, and every executed site through a
slot reached that thunk.

| Slot | Thunk | Sites |
|---|---|---|
| [BE2Ah] | XWING+050CB | in routines that ran: +01617, +01823, +0191B, +0193B, +019CE, +12F47, +12FAC; never ran: +292E2, +29364 |
| [CFB4h] | XWING+050C1 | ran: +01907 |
| [CFC4h] | XWING+050B7 | never ran: +290B5, +291C4, +29440 |
| [CFE0h] | XWING+05099 | never ran: +290DB, +291EA, +29466 |
| [CFE6h] | XWING+0508F | ran: +2F491, +2F4C5, +2F4F4, +2F53C, +2F69E, +2F748, +30860, +30920; never ran: +290CD, +291DC, +29458, +31F0C |
| [CFF2h] | XWING+05085 | ran: +28B49, +399EF; never ran: +33402, +33439, +3344F, +334DA, +334F2, +335D6, +335EE, +33618 |
| [CFFEh] | XWING+0507B | ran: +01870, +01898, +018C0, +2F2E2, +2F407, +2F5D4, +2F612, +2F8DF, +2F9CD, +307D2, +30EC0; never ran: +043E0, +04408, +04453, +044A9, +04500, +04557, +294D0, +31F3C, +31F58, +31F85, +31FA1, +31FD1, +32039, +320AA, +32111, +3217F, +3219B, +321CD, +321E9, +3221E, +32285, +322FB, +32363, +32678, +327FC, +328A6, +329AE, +32A05 |

### Music driver entry

`lcall es:[bx]` with the driver's far entry: the 41 executed sites all reached ADLIB+00000.

| Module | Sites |
|---|---|
| FLIGHT | ran: +18A34, +18A9A; never ran: +189E1, +189F6, +18A0C, +18AB0, +18AE4, +18B48, +18B61, +18B79, +18B97, +18BB5, +18BD9, +18BEE, +18C0A, +18C44, +18D79, +18D91, +18DA9, +18DBE |
| FRONTEND | never ran: +0C79E, +0C7B3, +0C892, +0C8E5, +0C97C, +0C999, +0C9B2, +0CA0C, +0CA32, +0CA49, +0CA81, +0CB5F |

### Music driver internal

`call cx` and `call ax` in ADLIB.IMS through its own tables; executed sites reached
+00C06, +00C66, +00C96, +00CA2, +00D84, +015C6 (`call cx`) and +011C2, +01204, +01408,
+0168E (`call ax`). The unexecuted ones are proved tables (above).

### FRONTEND object methods

Far calls through a method slot of a FRONTEND object (`es:[reg+6Ah]`, `+3Eh`, `+46h`)
or a local far pointer: many targets (the one executed `es:[si+6Ah]` site reached 24,
+086B2 to +7F738; the executed `es:[bx+6Ah]` sites reached +0936E).

| Call | Sites |
|---|---|
| `es:[bx+6Ah]` | never ran: +2F537, +2FD51, +3068B, +30E47, +3169D, +4119D, +532FD, +5B89D, +5C329, +5E9BD, +5FEFB, +6068D, +613A5, +61AF1, +63B73, +65087, +67925, +68771, +68F97, +6E477, +6ED2F, +6F613, +6FF74, +7162D, +73837, +7559D, +772B3, +800A4, +81FAE |
| `es:[di+6Ah]` | never ran: +5F6E2, +644AE |
| `es:[si+6Ah]` | never ran: +6314B, +6FEA7 |
| `es:[si+3Eh]`, `es:[si+46h]` | ran: +04CDD, +04BE1 |
| `[bp-4]` | ran: +09DC6 |

### Root C run-time and overlay manager

Values are the m01 and m14 reference snapshots' (DGROUP 4229h at run time).

| Sites | Pointer and value |
|---|---|
| ran: +0290F, +029EC, +02EAF, +02EDD; never ran: +01978 | `call [6344h]`: 00D8h, a `ret` at XWING+014E8 |
| ran: +0150D, +01623 | `call [6346h]`, `[6348h]`: 00D8h, the same `ret` |
| ran: +0154E, +01564, +0166F | `lcall [6352h]`: 0000:0000, a null far hook |
| ran: +01517 | `call [5F42h]`: 01DAh, the exit path (`annotations/noreturn.csv`) |
| ran: +014BD | `call cx` in the exit path |
| ran: +023A4, +023AE, +023C6, +023DA | `lcall [6184h]`, `[6170h]`, `[617Ch]`, `[6174h]`: 0963:02B8, XWING+016C8 (`mov ax, 2; jmp`), the floating-point-not-loaded error path |
| never ran: +016B8, +016EE | `lcall [5FB0h]`: 0000:0000; `ljmp [5FB4h]`: FFFF:FFFF |
| ran: +0488C, +0489C | the overlay manager's `jmpf es:[si]` through its callback pointer (CS:085Ch), descriptor flags bit 5 (docs/overlay-manager.md), never set in the traces |

## Paths still requiring execution coverage

All 165 sites in "Calls through pointers". The film-room milestones (m15's replay, m17's
combat film) have not been reviewed against these sites.
