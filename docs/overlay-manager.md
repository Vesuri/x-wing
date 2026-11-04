# Overlay manager

`XWING.EXE` is a small root: startup, the C run-time, the device layer and the overlay
manager. Almost all of the game is in two overlay files, `FRONTEND.OVL` and `FLIGHT.OVL`,
loaded segment by segment into one overlay area. Addresses are root load-image offsets
(`XWING.EXE+hex`) or overlay file offsets. Evidence: the disassembly of root segment 0406h
(MEASURED by reading); the model holds over every milestone trace (`tools/overlay_check.py`).
The model is in `tools/xwing_model.py`.

## Root layout

| Link range | Contents |
|---|---|
| 0000h–5B9Fh | Root code: segments 0000h, 00E7h, 0125h, 0141h, 03DEh, 0406h (manager, descriptors, thunks), 056Bh |
| 5BA0h–395FFh | Overlay area (link segments 05BAh–3960h). Zero in the image. |
| 39600h–407B4h | Root data (segment 3960h and above) |

The root's 1,152 relocations include 721 segment words above the overlay area, in the
data. Of those, `tools/census.py` counts the ones that point into the overlay area: far
pointers whose meaning depends on which base segment is resident.

## Descriptors

The table is at `0406h:09FFh` (`XWING.EXE+4A5F`): 18-byte records, with the count word at
`0406h:09FBh`. The count is 27; the last record is empty. Index 0–19 are `FRONTEND.OVL`,
20–25 `FLIGHT.OVL`.

| Offset | Field |
|---|---|
| +0 | link segment |
| +2 | file-name offset in segment 0406h; the byte before the name is a flag |
| +4, +6 | file position in paragraphs (a word and a high byte) |
| +7 | flags: 04h in the image; bit 1 set while resident; bit 4 (locked) refuses eviction; bit 5 reads through a callback; 0Ch selects the EMS cache |
| +8 | memory size in paragraphs |
| +0Ah | fixup count |
| +0Ch | parent index, FFFFh for a file's base segment |
| +0Eh | id (index + 2) |
| +10h | paragraphs read |

Each base segment (index 0 and 20) loads at link segment 05BAh. Its children share an
area: `FRONTEND` 3273h and, under child 3, 32F1h; `FLIGHT` 3300h and 359Ah. Each child's
parent is its file's base segment, or for `FRONTEND` 4 and 5, segment 3. In the file a
segment is its fixup table (offset and link segment, 4 bytes each) followed by its code at
the next paragraph. The segments tile both files.

## Calls

All 241 thunks are at `XWING.EXE+4D47..56B0`, 10 bytes each:
`call 048Ah; jmp far seg:off; dw index`. Callers far-call a thunk. The handler at
`0406h:048Ah` (`+44EA`) reads the index after the far jump and calls the manager. When
the manager returns, the far jump runs. The far jump's segment is the target's link
segment plus the load segment, relocated like any other.

The manager is at `0406h:017Ch` (`+41DC`), with AX = index:
1. AX = FFFFh returns at once.
2. If the segment is resident, the manager goes to step 6. A memory size of 0 also skips
   the load.
3. Every resident segment whose memory range overlaps the target is evicted: its resident
   bit is cleared. A locked segment refuses and the manager reports an error. With the EMS
   cache on, an evicted segment is first saved to EMS.
4. If the file is not the one open, the manager closes the old file and opens this one.
   It then seeks to the code and reads `+10h` paragraphs to load segment + link segment,
   at most 0F80h paragraphs per read. The paragraphs between the read size and the memory
   size are zero-filled (`+4529`, writer `+454E`).
5. The manager seeks to the fixup table and reads it in blocks of 58h entries into its
   buffer at `0406h:0878h` (`+4392`). To each fixup word it adds the word at
   `0406h:086Eh` plus 10h, which is the load segment (`+43AD`). Then it sets the resident
   bit.
6. AX = the parent index. When `0406h:09D8h` is nonzero (FFh in the image), the manager
   calls itself for the parent, resident or not.

The EMS cache (`0406h:086Ch`) is 0 at every call in every trace, so every load comes from
the file.

## Tracer events and the check

The game patch logs two events:
- `ovl_thunk`, at `+44EA`: the thunk, its index and the far caller (module and offset);
- `ovl_call`, at `+41E2`: the index, the descriptor's resident bit and flags, and the EMS
  cache byte.

`tools/overlay_check.py` replays each trace against the model:
- every call follows its thunk or its child's call;
- the resident bit equals the model's;
- the `.OVL` reads between calls are exactly the predicted code and fixup reads;
- each thunk's caller is resident when its chain ends;
- at every snapshot, each resident segment's code is mapped at its predicted address.

`--sabotage` breaks one rule, and the check must then fail:
- `no-evict`: overlapping segments are not evicted;
- `no-parent`: the parent call is dropped;
- `position`: the code is read one paragraph later.

`tools/load_image.py` rebuilds every resident row from the files and the same model
(gate 1).
