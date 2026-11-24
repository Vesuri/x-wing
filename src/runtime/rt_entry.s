; Runtime entries of the generated-code contract (docs/translator-design.md),
; copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and
; adapted:
; guest registers d0-d5/a4/a5 (SP/BP mirrored: offset ^ 7FFFh), segment bases
; a1-a3 = a6 - seg*16 - 7FFFh, guest RAM reversed below a6 (translator/lower.py),
; d6/d7/a0 scratch. C (gcc, 68020 ABI) clobbers d0/d1/a0/a1 only.

; State block offsets (translator/lower.py STATE_EQU)
G_IRQ	equ	9
G_ES	equ	5
G_SS	equ	3
G_DS	equ	1

	ifd XWING_REPLAY
	xref	rt_replay_enter,rt_replay_return
	endif

	xdef	rt_int
	xdef	rt_irq
	xdef	rt_irq_back
	xdef	rt_irq_async
	xdef	rt_irq_async_back
	xdef	rt_irq_interrupt,rt_irq_interrupt_back
	xdef	rt_irq_abort
	xdef	rt_exit
	xdef	rt_exit_guest
	xdef	rt_bios_int08
	xdef	rt_fault
	xdef	rt_halt
	xdef	rt_trap
	xdef	rt_guest_call
	xdef	rt_in8
	xdef	rt_in16
	xdef	rt_out8
	xdef	rt_out16
	xdef	rt_ret_mismatch
	xdef	rt_ret_far_mismatch
	xdef	rt_dispatch_near
	xdef	rt_dispatch_far
	xdef	rt_stop_unknown
	xdef	rt_hle_copy_protection
	xref	rt_hle_copy_protection_c
	xdef	rt_hle_sfx_prerender,rt_hle_sfx_prerender_done
	xref	rt_sfx_prerender
	xref	rt_sfx_capturing
	xref	rt_sfx_write
	xdef	rt_hle_sfx_start
	xref	rt_sfx_starts
	xdef	rt_run_guest
	xdef	rt_vram_mark
	xdef	rt_vram_ds
	xdef	rt_vdrv_return
	xdef	rt_ems_es
	xdef	rt_ems_seg
	xdef	rt_ems_ds
	xdef	rt_ems_ds_leave

	xref	rt_r
	xref	smc_expose
	xref	smc_seg_limit
	xref	smc_seg_lo
	xref	rt_guest
	xref	rt_entry_cs
	xref	rt_entry_ip
	xref	rt_deliver_cs
	xref	rt_deliver_ip
	xref	rt_deliver_code
	xref	rt_int_c
	xref	rt_irq_c
	xref	rt_bios_int08_c
	xref	rt_fault_c
	xref	rt_halt_c
	xref	rt_trap_c
	xref	rt_port_in
	xref	rt_port_out
	xref	rt_lookup
	xref	rt_ret_mismatch_c
	xref	rt_stop_unknown_c
	xref	rt_vram_rows
	xref	rt_vram_top
	xref	rt_vram_bottom
	xref	rt_vram_ds_on
	xref	rt_vram_ds_falls
	xref	rt_vdrv_depth
	xref	rt_video_publish
	xref	rt_opl
	xref	rt_opl_index
	xref	rt_opl_keyon
	xref	rt_irq0_enter
	xref	rt_irq0_leave
	xref	rt_irq_saved
	xref	rt_irq0_running
	xref	rt_irq_mask
	xref	rt_opl_pair
	xref	rt_irq_interrupting
	xref	rt_ems_es_c
	xref	rt_ems_ds_c
	xref	rt_ems_ds_left
	xref	rt_ems_fast
	xref	rt_ems_cache_es
	xref	rt_ems_cache_ds
	xref	rt_ems_segments

	section	.text,code

; guest registers -> rt_r (SP and BP as offsets)
save_regs:
	move.l	a0,-(a7)
	lea	rt_r,a0
	movem.w	d0-d5/a4-a5,(a0)
	eori.w	#$7fff,8(a0)
	eori.w	#$7fff,10(a0)
	movea.l	(a7)+,a0
	rts

; rt_r and the state-block segments -> guest registers (upper words
; undefined: sign-extended) and segment bases. A segment whose window
; reaches a self-modified region, smc_seg_lo <= seg < smc_seg_limit, drops
; the cell caches (translator/smc.py).
load_regs:
	lea	rt_r,a0
	movem.w	(a0),d0-d5/a4-a5
	eori.w	#$7fff,d4
	eori.w	#$7fff,d5
	moveq	#0,d7
	move.w	G_ES(a6),d7
	bsr.s	seg_check
	lsl.l	#4,d7
	lea	-$7fff(a6),a1
	suba.l	d7,a1
	moveq	#0,d7
	move.w	G_SS(a6),d7
	bsr.s	seg_check
	lsl.l	#4,d7
	lea	-$7fff(a6),a2
	suba.l	d7,a2
	moveq	#0,d7
	move.w	G_DS(a6),d7
	bsr.s	seg_check
	lsl.l	#4,d7
	lea	-$7fff(a6),a3
	suba.l	d7,a3
	rts
seg_check:
	cmp.w	smc_seg_limit,d7
	bcc.s	.ok
	cmp.w	smc_seg_lo,d7
	bcs.s	.ok
	jsr	smc_expose
.ok:	rts

; Software interrupt: d6 = CS << 16 | vector, d7 = next IP. A machine service
; runs in C; a vector the guest owns runs its handler on the frame C pushed.
rt_int:
	ifd XWING_REPLAY
	jsr	rt_replay_enter
	endif
	addq.b	#1,rt_irq_mask		; services hold the CIA tick (machine.c)
	bsr	save_regs
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_int_c
	addq.l	#8,a7
deliver_or_return:
	subq.b	#1,rt_irq_mask
	move.l	d0,-(a7)
	bsr	load_regs
	move.l	(a7)+,d7
	bne.s	deliver_guest
rt_exit:	; back to generated code (tests/host_run.py: service returns)
	ifd XWING_REPLAY
	jsr	rt_replay_return
	endif
	rts
deliver_guest:	; d7 = CS << 16 | IP of the pushed frame; the handler's IRET pops it
	move.l	d7,-(a7)
	moveq	#0,d6
	move.w	rt_deliver_cs,d6
	moveq	#0,d7
	move.w	rt_deliver_ip,d7
	movea.l	rt_deliver_code,a0	; rt_lookup's far entry (deliver)
	jsr	(a0)
	cmp.l	(a7),d7
	bne	rt_ret_far_mismatch
	addq.l	#4,a7
rt_exit_guest:
	ifd XWING_REPLAY
	jsr	rt_replay_return
	endif
	rts

; Poll point with G_IRQ set (D8): d6 = CS << 16 (| 1 at a loop head), d7 = its IP.
; Posted interrupts run in order: IRQ0's guest handler through rt_irq_async,
; another guest handler on the frame C pushed, then the next; BIOS handlers
; in C.
; rt_irq_c changes no guest register but SP (the frame it pushes) and no
; segment, so only C's d0/d1/a1 are kept around it and SP reloaded (rt_r
; stays current for a stop's register dump).
rt_irq:
	addq.b	#1,rt_irq_mask
	bsr	save_regs
	movem.l	d0-d1/a1,-(a7)
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_irq_c
	addq.l	#8,a7
	movea.l	d0,a0
	movem.l	(a7)+,d0-d1/a1
	cmpa.w	#0,a0
	beq.s	irq_done
	movem.l	d6-d7,-(a7)
	cmpa.w	#1,a0
	bne.s	.guest
	bsr	rt_irq_async
	bra.s	rt_irq_back
.guest:	subq.b	#1,rt_irq_mask
	move.w	rt_r+8,d4		; SP below the frame, mirrored
	eori.w	#$7fff,d4
	move.l	a0,d7
	bsr	deliver_guest		; the guest handler, IRET checked
rt_irq_back:				; back at the poll point (host run: next interrupt)
	movem.l	(a7)+,d6-d7
	tst.b	G_IRQ(a6)
	bne.s	rt_irq			; more posted at this poll point
	rts
irq_done:
	subq.b	#1,rt_irq_mask
	rts

; IRQ0 (D8, Secret Weapons of the Luftwaffe's docs/irq-plan.md I4): the guest handler of IVT 08h on the private
; guest stack IRQ_SS:IRQ_SP (runtime.h RT_IRQ_SS/RT_IRQ_SP) below a frame whose
; CS:IP is the sentinel its IRET (or the BIOS chain's) must pop; the 68k
; registers, the state block and rt_r are saved around it and restored, so
; the interrupted stack is not touched. Sync mode: from rt_irq at a poll point
; (guest registers live, flags in the state block).
IRQ_SS	equ	$b000
IRQ_SP	equ	$8000
rt_irq_async:
	st	rt_irq0_running		; before anything is saved (the CIA tick)
	subq.b	#1,rt_irq_mask		; rt_irq's
	movem.l	d0-d7/a0-a5,-(a7)
	bsr	save_regs
	lea	rt_irq_saved,a0		; state block, then rt_r
	move.l	1(a6),(a0)+
	move.l	5(a6),(a0)+
	move.l	9(a6),(a0)+
	move.l	13(a6),(a0)+
	lea	rt_r,a1
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.w	#IRQ_SS,G_SS(a6)	; the private stack
	move.w	#IRQ_SP,rt_r+8
	jsr	rt_irq0_enter		; frame, IF = TF = 0, the handler at rt_deliver_*
	bsr	load_regs
	move.l	#IRQ_SS<<16|IRQ_SP,d7	; the sentinel
	bsr	deliver_guest		; the guest handler, IRET checked
rt_irq_async_back:			; (host run: the handler returned)
irq_restore:
	lea	rt_irq_saved,a0
	move.l	(a0)+,1(a6)
	move.l	(a0)+,5(a6)
	move.l	(a0)+,9(a6)
	move.l	(a0)+,13(a6)
	lea	rt_r,a1
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	jsr	rt_irq0_leave		; G_IRQ re-armed from what is posted
	movem.l	(a7)+,d0-d7/a0-a5
	rts

; Async mode (I6): the CIA tick's interrupt runs the handler at once when
; rt_irq0_ready allows it, over whatever ran (generated code, a native row,
; the field task): no guest registers are live in 68k registers to save
; into rt_r, which is kept as it is; the handler reads interrupted registers
; only to save them (I2). The SS base is the private stack's; the handler
; loads DS and ES before it uses them. C calling convention.
rt_irq_interrupt:
	movem.l	d2-d7/a2-a6,-(a7)
	movea.l	rt_guest,a6
	st	rt_irq0_running
	st	rt_irq_interrupting
	pea	irq_interrupt_back(pc)	; irq_restore returns here
	movem.l	d0-d7/a0-a5,-(a7)	; the frame irq_restore pops
	move.l	a7,irq_interrupt_sp
	lea	rt_irq_saved,a0
	move.l	1(a6),(a0)+
	move.l	5(a6),(a0)+
	move.l	9(a6),(a0)+
	move.l	13(a6),(a0)+
	lea	rt_r,a1
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.w	#IRQ_SS,G_SS(a6)
	move.w	#IRQ_SP,rt_r+8
	jsr	rt_irq0_enter
	lea	rt_r,a0
	movem.w	(a0),d0-d5/a4-a5
	eori.w	#$7fff,d4
	eori.w	#$7fff,d5
	lea	-$7fff-IRQ_SS*16(a6),a2
	move.l	#IRQ_SS<<16|IRQ_SP,d7
	bsr	deliver_guest
rt_irq_interrupt_back:			; (host run: the handler returned)
	bra	irq_restore
irq_interrupt_back:
	sf	rt_irq_interrupting
	movem.l	(a7)+,d2-d7/a2-a6
	rts

; A stop inside the interrupt's handler run (machine.c rt_stop): back to
; rt_irq_interrupt's frame, the interrupted state restored; the stop is raised
; again at the next poll.
rt_irq_abort:
	movea.l	irq_interrupt_sp,a7
	movea.l	rt_guest,a6
	bra	irq_restore

; The BIOS INT 08h handler, reached by a guest handler chaining to the vector
; it replaced (jmp far): the tick, then IRET; d7.l = popped CS:IP for the
; return check of the code that delivered the interrupt.
rt_bios_int08:
	bsr	save_regs
	jsr	rt_bios_int08_c
	move.l	d0,-(a7)
	bsr	load_regs
	move.l	(a7)+,d7
	rts

; Divide error: d6 = CS << 16 | 0, d7 = IP of the faulting instruction; the
; generated code re-executes it after the guest INT 00h handler returns.
rt_fault:
	addq.b	#1,rt_irq_mask
	bsr	save_regs
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_fault_c
	addq.l	#8,a7
	bra	deliver_or_return

; HLE copy_protection (annotations/hle.csv, protection.c): the protection
; screen's call is replaced by a correct first answer. NE skips the call.
; Clobbers d7 and a0; load_regs reloads the guest registers (AX = 1) and bases.
rt_hle_copy_protection:
	ifd	XWING_REPLAY_SCREEN
	moveq	#0,d7			; diagnostic replay --screen: EQ, the call runs
	rts
	endif
	bsr	save_regs
	jsr	rt_hle_copy_protection_c
	bsr	load_regs
	moveq	#1,d7
	rts

; HLE sfx_prerender (annotations/hle.csv, sfx.c): the return of FLIGHT's
; sound loader. The effect capture runs guest code: the 68k registers, the
; state block and rt_r are saved around it and restored (copied from Secret
; Weapons of the Luftwaffe's). Observe only: EQ.
rt_hle_sfx_prerender:
	movem.l	d0-d7/a0-a6,-(a7)
	bsr	save_regs
	lea	-32(a7),a7
	movea.l	a7,a0
	move.l	1(a6),(a0)+
	move.l	5(a6),(a0)+
	move.l	9(a6),(a0)+
	move.l	13(a6),(a0)+
	lea	rt_r,a1
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	jsr	rt_sfx_prerender
	movea.l	rt_guest,a6
	movea.l	a7,a0
	move.l	(a0)+,1(a6)
	move.l	(a0)+,5(a6)
	move.l	(a0)+,9(a6)
	move.l	(a0)+,13(a6)
	lea	rt_r,a1
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	32(a7),a7
	movem.l	(a7)+,d0-d7/a0-a6
rt_hle_sfx_prerender_done:		; tests/host_run.py: the capture's window ends
	cmp.w	d7,d7
	rts

; HLE sfx_start (annotations/hle.csv, sfx.c): the return of FLIGHT's effect
; start (command 08h), d7 its AX (0: the driver took it), d6 SI, the id:
; counted in rt_sfx_starts for the effect player (fx_play.c). Clobbers d7
; and a0. Observe only: EQ.
rt_hle_sfx_start:
	tst.w	d7
	bne.s	.sfx_start_done
	cmp.w	#48,d6			; runtime.h RT_SFX_IDS
	bhs.s	.sfx_start_done
	lea	rt_sfx_starts,a0
	addq.b	#1,(a0,d6.w)
.sfx_start_done:
	cmp.w	d7,d7
	rts

rt_halt:
	bsr	save_regs
	move.l	d7,-(a7)
	jsr	rt_halt_c

; A guest call from C: the translated far entry rt_deliver_code
; (rt_deliver_cs:ip) with the guest registers of rt_r and the state block;
; its far return (RETF or IRET) must pop the sentinel CS:IP, the argument.
; The guest registers back in rt_r. C calling convention.
rt_guest_call:
	movem.l	d2-d7/a2-a6,-(a7)
	movea.l	rt_guest,a6
	bsr	load_regs
	move.l	48(a7),d7		; the sentinel (load_regs clobbers d7)
	bsr	deliver_guest
	bsr	save_regs
	movem.l	(a7)+,d2-d7/a2-a6
	rts

; TF set by POPF/IRET: d7 = IP of the instruction.
rt_trap:
	bsr	save_regs
	move.l	d7,-(a7)
	jsr	rt_trap_c

; Ports: d7 port, d6 value (out) / result (in).
rt_in8:
	movem.l	d0-d1/a1,-(a7)
	pea	8.w
	bra.s	port_in
rt_in16:
	movem.l	d0-d1/a1,-(a7)
	pea	16.w
port_in:
	addq.b	#1,rt_irq_mask
	move.l	d7,-(a7)
	jsr	rt_port_in
	addq.l	#8,a7
	subq.b	#1,rt_irq_mask
	move.l	d0,d6
	movem.l	(a7)+,d0-d1/a1
	rts

; AdLib byte writes (and per channel the key-on edges, B0-B8 bit 5 rising)
; and the PIC's non-specific EOI here (ports.c); d7 and a0 clobbered.
rt_out8:
	cmp.w	#$389,d7
	beq.s	.opl_data
	cmp.w	#$388,d7
	beq.s	.opl_index
	cmp.w	#$20,d7
	bne.s	.port
	cmp.b	#$20,d6
	bne.s	.port
	rts
.opl_index:
	move.b	d6,rt_opl_index
	tst.b	rt_irq0_running
	bne.s	.opl_handler
	st	rt_opl_pair		; the main thread's pair holds the CIA tick
.opl_handler:
	rts
.opl_data:
	tst.b	rt_sfx_capturing
	bne	opl_capture
	tst.b	rt_irq0_running
	bne.s	.opl_pair_done
	sf	rt_opl_pair
.opl_pair_done:
	lea	rt_opl,a0
	moveq	#0,d7
	move.b	rt_opl_index,d7
	cmp.b	#$b0,d7
	blo.s	.opl_store
	cmp.b	#$b8,d7
	bhi.s	.opl_store
	btst	#5,d6
	beq.s	.opl_store
	btst	#5,(a0,d7.w)
	bne.s	.opl_store
	move.b	d6,(a0,d7.w)
	lea	rt_opl_keyon-$b0,a0
	addq.b	#1,(a0,d7.w)
	rts
.opl_store:
	move.b	d6,(a0,d7.w)
	rts
.port:	movem.l	d0-d1/a1,-(a7)
	pea	8.w
	bra.s	port_out
; The effect capture (sfx.c) runs: the data write goes to rt_sfx_write.
opl_capture:
	movem.l	d0-d1/a0-a1,-(a7)
	moveq	#0,d0
	move.b	d6,d0
	move.l	d0,-(a7)
	move.b	rt_opl_index,d0
	move.l	d0,-(a7)
	jsr	rt_sfx_write
	addq.l	#8,a7
	movem.l	(a7)+,d0-d1/a0-a1
	rts
rt_out16:
	movem.l	d0-d1/a1,-(a7)
	pea	16.w
port_out:
	addq.b	#1,rt_irq_mask
	move.l	d6,-(a7)
	move.l	d7,-(a7)
	jsr	rt_port_out
	lea	12(a7),a7
	subq.b	#1,rt_irq_mask
	movem.l	(a7)+,d0-d1/a1
	rts

; EMS model (ems.c, lower.py ems_guard; copied from Wing Commander 2): before an
; ES access, and a DS access in listed code (annotations/ems-ds.csv), with d7.w
; the offset and d6.l the bytes (0: the whole window), the segment's base
; register (a1, a3) = its plain base plus the C function's displacement (the
; access runs on the store page, or on the frame with its pages copied in);
; after a DS or SS load, the frame pages its window meets are copied in. Every
; other register kept; the callers keep d6, d7 and the CCR.
; An access within one frame page, or two whose displacements are equal,
; decides here from rt_ems_fast (ems.c): the store displacement, 0 (live or
; unmapped: the frame), or 1 (the C path, which copies it in). Whole windows,
; wraps, accesses that meet the frame from below or span pages that differ take
; the C path; an access above the frame runs plain.
EMS_GUARD	macro			; \1 segment slot, \2 base register, \3 C path, \4 cache
	; The cache (ems.c rt_ems_cache_es/ds): the same segment, an access within the
	; offsets of the frame page the last displaced access lay in: its base. d6 and d7
	; are the caller's to restore (lower.py ems_guard).
	movea.w	\1(a6),\2		; a segment of D001h or above: never the empty 0
	cmpa.w	\4,\2
	bne.s	.miss\@
	tst.l	d6			; the whole window: never cached
	beq.s	.miss\@
	and.l	#$ffff,d7
	cmp.w	\4+2,d7
	bcs.s	.miss\@
	add.l	d7,d6			; the access's end
	cmp.l	\4+4,d6
	bhi.s	.miss2\@
	movea.l	\4+8,\2
	rts
.miss2\@:
	sub.l	d7,d6
.miss\@:
	tst.l	d6			; the whole window
	beq	.slow\@
	movem.l	d0-d1/a0,-(a7)
	moveq	#0,d1
	move.w	d7,d1
	move.l	d1,d0
	add.l	d6,d0
	cmp.l	#$10000,d0		; the access wraps at FFFFh
	bhi	.slow2\@
	moveq	#0,d0
	move.w	\1(a6),d0
	lsl.l	#4,d0
	add.l	d1,d0
	sub.l	#$e0000,d0		; its first byte, frame-relative
	bcs	.slow2\@
	cmp.l	#$10000,d0
	bcc	.plain\@		; above the frame
	move.l	d0,d1
	add.l	d6,d1
	subq.l	#1,d1			; its last byte
	lsr.l	#8,d0			; page numbers (14 bits); d6 stays the
	lsr.l	#6,d0			; byte count for the C path
	lsr.l	#8,d1
	lsr.l	#6,d1
	cmp.l	#4,d1
	bcc	.slow2\@		; past the frame's end
	sub.l	d0,d1
	beq	.one\@
	subq.l	#1,d1
	bne	.slow2\@		; three pages or more: the C path
	lsl.w	#2,d0			; two pages: one displacement (ems.c store)
	lea	rt_ems_fast,a0
	move.l	4(a0,d0.w),d1
	move.l	(a0,d0.w),d0
	cmp.l	d0,d1
	bne	.slow2\@
	bra	.test\@
.one\@:
	lsl.w	#2,d0
	addq.b	#1,rt_irq_mask		; no refresh between the table and the cache
	lea	rt_ems_fast,a0
	move.l	(a0,d0.w),d1
	btst	#0,d1
	bne	.unmask\@
	; fill the cache: the offsets of frame page k (d0 = 4k) within the segment
	lsl.l	#8,d0
	lsl.l	#4,d0			; 4000h * k
	add.l	#$e0000,d0		; the page's first byte
	moveq	#0,d6
	move.w	\1(a6),d6
	lsl.l	#4,d6
	sub.l	d6,d0			; its offset in the segment (negative: below it)
	move.l	d0,d6
	add.l	#$4000,d6		; the page's end
	cmp.l	#$10000,d6
	bls.s	.end\@
	move.l	#$10000,d6
.end\@:
	move.l	d6,\4+4
	tst.l	d0
	bpl.s	.low\@
	moveq	#0,d0
.low\@:
	move.w	d0,\4+2
	move.l	d1,d6			; the displacement
	movem.l	(a7)+,d0-d1/a0
	moveq	#0,d7
	move.w	\1(a6),d7
	lsl.l	#4,d7
	lea	-$7fff(a6),\2
	suba.l	d7,\2
	adda.l	d6,\2
	move.l	\2,\4+8
	move.w	\1(a6),\4		; valid from here
	subq.b	#1,rt_irq_mask
	rts
.unmask\@:
	subq.b	#1,rt_irq_mask
	bra	.slow2\@
.test\@:
	btst	#0,d0
	bne	.slow2\@
	move.l	d0,d6			; the displacement
	movem.l	(a7)+,d0-d1/a0
	bra	.base\@
.plain\@:
	movem.l	(a7)+,d0-d1/a0
	moveq	#0,d6
	bra	.base\@
.slow2\@:
	movem.l	(a7)+,d0-d1/a0
.slow\@:
	movem.l	d0-d1/a0-a1,-(a7)
	addq.b	#1,rt_irq_mask		; the CIA tick waits (machine.c)
	move.l	d6,-(a7)
	move.l	d7,-(a7)
	jsr	\3
	addq.l	#8,a7
	subq.b	#1,rt_irq_mask
	move.l	d0,d6
	movem.l	(a7)+,d0-d1/a0-a1
.base\@:
	moveq	#0,d7
	move.w	\1(a6),d7
	lsl.l	#4,d7
	lea	-$7fff(a6),\2
	suba.l	d7,\2
	adda.l	d6,\2
	rts
	endm
rt_ems_es:
	EMS_GUARD	G_ES,a1,rt_ems_es_c,rt_ems_cache_es
rt_ems_ds:
	EMS_GUARD	G_DS,a3,rt_ems_ds_c,rt_ems_cache_ds
; Listed code left with DS at D001h or above (lower.py ems_exit): its frame
; pages copied in, a3 the plain DS base. Every other register kept.
rt_ems_ds_leave:
	movem.l	d0-d1/d7/a0-a1,-(a7)
	addq.b	#1,rt_irq_mask
	jsr	rt_ems_ds_left
	subq.b	#1,rt_irq_mask
	moveq	#0,d7
	move.w	G_DS(a6),d7
	lsl.l	#4,d7
	lea	-$7fff(a6),a3
	suba.l	d7,a3
	movem.l	(a7)+,d0-d1/d7/a0-a1
	rts
rt_ems_seg:
	movem.l	d0-d1/a0-a1,-(a7)
	addq.b	#1,rt_irq_mask
	jsr	rt_ems_segments
	subq.b	#1,rt_irq_mask
	movem.l	(a7)+,d0-d1/a0-a1
	rts

; Indirect transfer outside the compiled compare chain: d6 CS, d7 IP. Jumps to
; the translated entry (a jsr caller's return address stays on a7).
rt_dispatch_near:
	movem.l	d0-d1/a1,-(a7)
	moveq	#0,d0
	bra.s	dispatch
rt_dispatch_far:	; stops at a row no far transfer may enter
	movem.l	d0-d1/a1,-(a7)
	moveq	#1,d0
dispatch:
	addq.b	#1,rt_irq_mask		; rt_lookup's cache
	move.l	d0,-(a7)
	move.l	d7,-(a7)
	move.l	d6,-(a7)
	jsr	rt_lookup
	lea	12(a7),a7
	subq.b	#1,rt_irq_mask
	movea.l	d0,a0
	movem.l	(a7)+,d0-d1/a1
	jmp	(a0)

; Return site reached with another guest IP (d7) / CS (d6).
; R33 far returns carry both words in d7; normalize only the failure path.
rt_ret_far_mismatch:
	move.l	d7,d6
	swap	d6
rt_ret_mismatch:
	bsr	save_regs
	move.l	d6,-(a7)
	move.l	d7,-(a7)
	jsr	rt_ret_mismatch_c

; Transfer into code that is not translated: d7 IP, d6 CS (when known).
rt_stop_unknown:
	bsr	save_regs
	move.l	d6,-(a7)
	move.l	d7,-(a7)
	jsr	rt_stop_unknown_c

; Enter the guest at rt_entry_cs:rt_entry_ip with the registers in rt_r and
; the state block. Returns only if the guest's outermost frame returns.
rt_run_guest:
	movem.l	d2-d7/a2-a6,-(a7)
	movea.l	rt_guest,a6
	bsr	load_regs
	moveq	#0,d6
	move.w	rt_entry_cs,d6
	moveq	#0,d7
	move.w	rt_entry_ip,d7
	jsr	rt_dispatch_far
	movem.l	(a7)+,d2-d7/a2-a6
	rts

; D9 display. Before a FRONTEND or FLIGHT store through a segment whose
; 64 KiB window meets the frame (X-Wing has no graphics driver; the game
; draws the lower half through segments above A000h): bytes [d7.w, d7.w +
; d6.l) of the segment (the offset wraps at 64 KiB), a0 = the segment's
; signed byte distance from A0000h, widen the changed rows, clipped to the
; 320x200 frame. Per row (rt_vram_rows) the changed columns [lo, hi), hi = 0
; for none; a store spanning rows marks them whole. d6/d7/a0 clobbered.
rt_vram_mark:
	movem.l	d0-d2,-(a7)
	move.l	a0,d2			; segment distance
	and.l	#$ffff,d7
	move.l	d7,d0
	add.l	d6,d0			; end, exclusive
	cmp.l	#$10000,d0
	bls.s	.last
	sub.l	#$10000,d0		; wrapped: [d7, 64 KiB), then [0, d0)
	move.l	d0,-(a7)
	move.l	#$10000,d0
	bsr.s	vram_seg
	moveq	#0,d7
	move.l	(a7)+,d0
.last:	bsr.s	vram_seg
	movem.l	(a7)+,d0-d2
	rts

; Segment bytes [d7, d0), d2 the segment's distance: frame bytes [d7 + d2,
; d0 + d2), the part from 0 on (vram_span clips the end); d2 kept.
vram_seg:
	move.l	d2,-(a7)
	add.l	d2,d7
	add.l	d2,d0
	ble.s	.none			; wholly below the frame
	tst.l	d7
	bpl.s	.from
	moveq	#0,d7
.from:	bsr.s	vram_span
.none:	move.l	(a7)+,d2
	rts

; [d7, d0) with d0 <= 64 KiB
vram_span:
	cmp.l	#64000,d0
	bls.s	.clip
	move.l	#64000,d0
.clip:	cmp.l	d0,d7
	bhs.s	.done
	subq.l	#1,d0			; last byte
	lea	vram_row(pc),a0		; offset / 320 = (offset >> 6) / 5
	move.w	d7,d1
	lsr.w	#6,d1
	moveq	#0,d2
	move.b	(a0,d1.w),d2		; first row
	move.w	d2,d1
	lsl.w	#6,d1
	sub.w	d1,d7
	lsl.w	#2,d1
	sub.w	d1,d7			; first column
	move.w	d0,d1
	lsr.w	#6,d1
	moveq	#0,d6
	move.b	(a0,d1.w),d6		; last row
	move.w	d6,d1
	lsl.w	#6,d1
	sub.w	d1,d0
	lsl.w	#2,d1
	sub.w	d1,d0			; last column
	cmp.w	rt_vram_top,d2
	bhs.s	.top
	move.w	d2,rt_vram_top
.top:	cmp.w	rt_vram_bottom,d6
	blo.s	.bottom
	move.w	d6,d1
	addq.w	#1,d1
	move.w	d1,rt_vram_bottom
.bottom:
	lea	rt_vram_rows,a0
	lea	(a0,d2.l*4),a0		; row entry: lo.w, hi.w
	cmp.w	d2,d6
	bne.s	.rows
	addq.w	#1,d0			; column end
	tst.w	2(a0)
	beq.s	.new
	cmp.w	(a0),d7
	bhs.s	.lo
	move.w	d7,(a0)
.lo:	cmp.w	2(a0),d0
	bls.s	.done
	move.w	d0,2(a0)
.done:	rts
.new:	move.w	d7,(a0)+
	move.w	d0,(a0)
	rts
.rows:	sub.w	d2,d6			; rows - 1
.row:	move.l	#320,(a0)+		; lo 0, hi 320
	dbf	d6,.row
	rts

vram_row:	; row of each 64-byte block of the frame: k / 5
	dc.b	0,0,0,0,0,1,1,1,1,1,2,2,2,2,2,3,3,3,3,3
	dc.b	4,4,4,4,4,5,5,5,5,5,6,6,6,6,6,7,7,7,7,7
	dc.b	8,8,8,8,8,9,9,9,9,9,10,10,10,10,10,11,11,11,11,11
	dc.b	12,12,12,12,12,13,13,13,13,13,14,14,14,14,14,15,15,15,15,15
	dc.b	16,16,16,16,16,17,17,17,17,17,18,18,18,18,18,19,19,19,19,19
	dc.b	20,20,20,20,20,21,21,21,21,21,22,22,22,22,22,23,23,23,23,23
	dc.b	24,24,24,24,24,25,25,25,25,25,26,26,26,26,26,27,27,27,27,27
	dc.b	28,28,28,28,28,29,29,29,29,29,30,30,30,30,30,31,31,31,31,31
	dc.b	32,32,32,32,32,33,33,33,33,33,34,34,34,34,34,35,35,35,35,35
	dc.b	36,36,36,36,36,37,37,37,37,37,38,38,38,38,38,39,39,39,39,39
	dc.b	40,40,40,40,40,41,41,41,41,41,42,42,42,42,42,43,43,43,43,43
	dc.b	44,44,44,44,44,45,45,45,45,45,46,46,46,46,46,47,47,47,47,47
	dc.b	48,48,48,48,48,49,49,49,49,49,50,50,50,50,50,51,51,51,51,51
	dc.b	52,52,52,52,52,53,53,53,53,53,54,54,54,54,54,55,55,55,55,55
	dc.b	56,56,56,56,56,57,57,57,57,57,58,58,58,58,58,59,59,59,59,59
	dc.b	60,60,60,60,60,61,61,61,61,61,62,62,62,62,62,63,63,63,63,63
	dc.b	64,64,64,64,64,65,65,65,65,65,66,66,66,66,66,67,67,67,67,67
	dc.b	68,68,68,68,68,69,69,69,69,69,70,70,70,70,70,71,71,71,71,71
	dc.b	72,72,72,72,72,73,73,73,73,73,74,74,74,74,74,75,75,75,75,75
	dc.b	76,76,76,76,76,77,77,77,77,77,78,78,78,78,78,79,79,79,79,79
	dc.b	80,80,80,80,80,81,81,81,81,81,82,82,82,82,82,83,83,83,83,83
	dc.b	84,84,84,84,84,85,85,85,85,85,86,86,86,86,86,87,87,87,87,87
	dc.b	88,88,88,88,88,89,89,89,89,89,90,90,90,90,90,91,91,91,91,91
	dc.b	92,92,92,92,92,93,93,93,93,93,94,94,94,94,94,95,95,95,95,95
	dc.b	96,96,96,96,96,97,97,97,97,97,98,98,98,98,98,99,99,99,99,99
	dc.b	100,100,100,100,100,101,101,101,101,101,102,102,102,102,102,103,103,103,103,103
	dc.b	104,104,104,104,104,105,105,105,105,105,106,106,106,106,106,107,107,107,107,107
	dc.b	108,108,108,108,108,109,109,109,109,109,110,110,110,110,110,111,111,111,111,111
	dc.b	112,112,112,112,112,113,113,113,113,113,114,114,114,114,114,115,115,115,115,115
	dc.b	116,116,116,116,116,117,117,117,117,117,118,118,118,118,118,119,119,119,119,119
	dc.b	120,120,120,120,120,121,121,121,121,121,122,122,122,122,122,123,123,123,123,123
	dc.b	124,124,124,124,124,125,125,125,125,125,126,126,126,126,126,127,127,127,127,127
	dc.b	128,128,128,128,128,129,129,129,129,129,130,130,130,130,130,131,131,131,131,131
	dc.b	132,132,132,132,132,133,133,133,133,133,134,134,134,134,134,135,135,135,135,135
	dc.b	136,136,136,136,136,137,137,137,137,137,138,138,138,138,138,139,139,139,139,139
	dc.b	140,140,140,140,140,141,141,141,141,141,142,142,142,142,142,143,143,143,143,143
	dc.b	144,144,144,144,144,145,145,145,145,145,146,146,146,146,146,147,147,147,147,147
	dc.b	148,148,148,148,148,149,149,149,149,149,150,150,150,150,150,151,151,151,151,151
	dc.b	152,152,152,152,152,153,153,153,153,153,154,154,154,154,154,155,155,155,155,155
	dc.b	156,156,156,156,156,157,157,157,157,157,158,158,158,158,158,159,159,159,159,159
	dc.b	160,160,160,160,160,161,161,161,161,161,162,162,162,162,162,163,163,163,163,163
	dc.b	164,164,164,164,164,165,165,165,165,165,166,166,166,166,166,167,167,167,167,167
	dc.b	168,168,168,168,168,169,169,169,169,169,170,170,170,170,170,171,171,171,171,171
	dc.b	172,172,172,172,172,173,173,173,173,173,174,174,174,174,174,175,175,175,175,175
	dc.b	176,176,176,176,176,177,177,177,177,177,178,178,178,178,178,179,179,179,179,179
	dc.b	180,180,180,180,180,181,181,181,181,181,182,182,182,182,182,183,183,183,183,183
	dc.b	184,184,184,184,184,185,185,185,185,185,186,186,186,186,186,187,187,187,187,187
	dc.b	188,188,188,188,188,189,189,189,189,189,190,190,190,190,190,191,191,191,191,191
	dc.b	192,192,192,192,192,193,193,193,193,193,194,194,194,194,194,195,195,195,195,195
	dc.b	196,196,196,196,196,197,197,197,197,197,198,198,198,198,198,199,199,199,199,199
	even

; Video stores through DS (owner decision 2026-11-23): a DS load of a
; segment whose window meets the frame outside listed code
; (annotations/vram-ds.csv; lower.py putseg), or listed code left with DS there
; (vram_exit). Stores through DS go unmarked there, so the whole frame is
; changed at each present until one finds DS off the frame (video.c present).
; The flag first, then every row whole (video.c vram_all): a present
; between them still sees the flag. Keeps every register; the CCR is
; clobbered. Safe at interrupt level.
rt_vram_ds:
	st	rt_vram_ds_on
	movem.l	d0/a0,-(a7)
	lea	rt_vram_rows,a0
	move.w	#199,d0
.all:	move.l	#320,(a0)+		; lo 0, hi 320
	dbf	d0,.all
	movem.l	(a7)+,d0/a0
	clr.w	rt_vram_top
	move.w	#200,rt_vram_bottom
	addq.l	#1,rt_vram_ds_falls
	rts

; D9 contract (SWOTL's graphics driver thunk; none in X-Wing, video.c stops):
; the driver's retf returns here (d7.l = the popped CS:IP for the caller's
; return check). The outermost return publishes what the driver drew.
rt_vdrv_return:
	subq.w	#1,rt_vdrv_depth
	bne.s	.inner
	tst.w	rt_vram_bottom
	beq.s	.inner
	movem.l	d0-d1/a0-a1,-(a7)
	jsr	rt_video_publish
	movem.l	(a7)+,d0-d1/a0-a1
.inner:	rts

	section	.bss,bss
	cnop	0,4
irq_interrupt_sp:
	ds.l	1
