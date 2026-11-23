/* X-Wing runtime, copied from Secret Weapons of the Luftwaffe's (commit pinned
 * in manifest/references.tsv) and adapted: the machine the generated code runs
 * on (DOS 5 / BIOS / EMS / ports as the DOSBox-X reference presents them) and
 * the rt_* entries of the generated-code contract (docs/translator-design.md).
 * Platform services (files, log, exit) come from platform.h. */
#ifndef XWING_RUNTIME_H
#define XWING_RUNTIME_H

#include <stdint.h>

/* Guest registers in the order rt_entry.s stores them (d0-d5, a4, a5). */
struct rt_regs {
    uint16_t ax, cx, dx, bx, sp, bp, si, di;
};

extern struct rt_regs rt_r;
extern uint8_t *rt_guest;          /* a6: TOP, guest linear 0 (reversed); state block above */

#define RT_GUEST_BYTES 0x110000u   /* 1 MiB + HMA (A20 on) */
#define RT_STATE_BYTES 16u
/* EMS (ems.c): the reference's 932 free 16 KiB pages (INT 67h AH=42h); the
 * store after guest RAM backs the first RT_EMS_STORE of them, the 64 pages the
 * game allocates (AH=43h BX=40h). A page outside the store is a stop. */
#define RT_EMS_PAGES 0x03a4u
#define RT_EMS_STORE 0x0040u
#define RT_EMS_PAGE 0x4000u
#define RT_EMS_BYTES (RT_EMS_STORE * RT_EMS_PAGE)

/* State block (translator/lower.py STATE_EQU), native big-endian. */
#define G_CCR  (rt_guest[16])      /* C=CF V=OF Z=ZF N=SF */
#define G_PF   (rt_guest[14])
#define G_AF   (rt_guest[13])
#define G_DF   (rt_guest[12])
#define G_IF   (rt_guest[11])
#define G_TF   (rt_guest[10])
#define G_IRQ  (rt_guest[9])       /* poll points call rt_irq (RT_RAISE_IRQ, machine.c) */
#define G_FX   (*(uint16_t *)(rt_guest + 7))
#define G_ES   (*(uint16_t *)(rt_guest + 5))
#define G_SS   (*(uint16_t *)(rt_guest + 3))
#define G_DS   (*(uint16_t *)(rt_guest + 1))

#define CCR_C 1
#define CCR_Z 4

static inline uint32_t lin(uint16_t seg, uint16_t off) { return ((uint32_t)seg << 4) + off; }

/* Guest memory: the runtime reaches it only through these (Secret Weapons of the Luftwaffe's docs/speed-plan.md
 * R1). It is reversed (translator/lower.py): the byte at linear a lives at
 * rt_guest - a. A span is the host bytes holding guest a..a+n-1 (in reverse),
 * for platform I/O and opaque page copies; rt_span_order puts a span in guest
 * order and back (the same call both ways). */
/* Self-modified regions (translator/smc.py): a store into one drops their
 * cell caches. smc_lo..smc_hi: the generated program's bounds, linear; a
 * segment in [smc_seg_lo, smc_seg_limit) reaches them (rt_entry.s load_regs). */
extern const uint32_t smc_lo, smc_hi;
extern const uint16_t smc_seg_lo, smc_seg_limit;
void smc_expose(void);
static inline void rt_wrote(uint32_t a, uint32_t n)
{
    if (n && a <= smc_hi && a + n - 1 >= smc_lo) {
        smc_expose();
    }
}
/* EMS frame pages are copied in on first access (ems.c): every runtime access
 * that meets the frame reports itself first. */
void rt_ems_touch(uint32_t a, uint32_t n);
void rt_ems_segments(void);
void rt_ems_cache_hold(void);       /* around IRQ0's handler (ems.c) */
void rt_ems_cache_restore(void);
extern uint32_t rt_ems_ds_exits;   /* listed code left with DS at the frame (ems.c) */
extern uint16_t rt_ems_mapped[4];
extern uint8_t rt_ems_live[4];
static inline void rt_frame(uint32_t a, uint32_t n)
{
    if (n && a <= 0xeffffu && a + n > 0xe0000u) {
        rt_ems_touch(a, n);
    }
}
static inline uint8_t rd8(uint32_t a) { rt_frame(a, 1); return *(rt_guest - a); }
static inline void wr8(uint32_t a, uint8_t v) { rt_frame(a, 1); rt_wrote(a, 1); *(rt_guest - a) = v; }
/* A guest word or dword is a native one ending at the guest address, at any
 * alignment (the 68020's; gcc would split it into bytes). */
typedef uint16_t __attribute__((may_alias)) rt_u16;
typedef uint32_t __attribute__((may_alias)) rt_u32;
static inline uint16_t rd16(uint32_t a)
{
    uint16_t v;
    rt_frame(a, 2);
    __asm__("move.w %1,%0" : "=d"(v) : "m"(*(const rt_u16 *)(rt_guest - a - 1)));
    return v;
}
static inline void wr16(uint32_t a, uint16_t v)
{
    rt_frame(a, 2);
    rt_wrote(a, 2);
    __asm__("move.w %1,%0" : "=m"(*(rt_u16 *)(rt_guest - a - 1)) : "d"(v));
}
static inline uint32_t rd32(uint32_t a)
{
    uint32_t v;
    rt_frame(a, 4);
    __asm__("move.l %1,%0" : "=d"(v) : "m"(*(const rt_u32 *)(rt_guest - a - 3)));
    return v;
}
static inline void wr32(uint32_t a, uint32_t v)
{
    rt_frame(a, 4);
    rt_wrote(a, 4);
    __asm__("move.l %1,%0" : "=m"(*(rt_u32 *)(rt_guest - a - 3)) : "d"(v));
}
static inline uint8_t *rt_span(uint32_t a, uint32_t n) { rt_frame(a, n); return rt_guest - a - n + 1; }
/* A span the runtime stores into. */
static inline uint8_t *rt_span_w(uint32_t a, uint32_t n) { rt_wrote(a, n); return rt_span(a, n); }
static inline void rt_span_order(uint8_t *span, uint32_t n)
{
    for (uint8_t *lo = span, *hi = span + n; hi - lo > 1; ) {
        uint8_t t = *lo;
        *lo++ = *--hi;
        *hi = t;
    }
}
static inline void rt_fill(uint32_t a, uint8_t v, uint32_t n)
{
    for (uint8_t *p = rt_span_w(a, n); n--; ) {
        *p++ = v;
    }
}

static inline void set_cf(int on) { G_CCR = on ? (G_CCR | CCR_C) : (G_CCR & ~CCR_C); }
static inline void set_zf(int on) { G_CCR = on ? (G_CCR | CCR_Z) : (G_CCR & ~CCR_Z); }
#define AL(r) ((uint8_t)(r))
#define AH(r) ((uint8_t)((r) >> 8))
#define SET_AL(r, v) ((r) = ((r) & 0xff00) | (uint8_t)(v))
#define SET_AH(r, v) ((r) = ((r) & 0x00ff) | (uint16_t)((uint8_t)(v)) << 8)

/* Generated program (build/gen/program.s). */
struct rt_dispatch_row {
    uint16_t cs, ip, overlay, far;    /* far: a far transfer may enter (R14e) */
    void *code;
};
extern const uint32_t dispatch_count;
extern const struct rt_dispatch_row dispatch_table[];
extern const uint32_t load_segment;
extern const uint32_t driver_segment;  /* the music driver (dos.c AX=4B03h) */
extern const char driver_name[];       /* its file: ADLIB.IMS or ADLIB_W.IMS (translator image.DRIVER) */
/* Its layout for the effect capture (sfx.c), read from its own code by the translator
 * (translator/driver.py CAPTURE, in this order) */
enum { RT_DRV_TIMER, RT_DRV_DATA, RT_DRV_DS_SLOT, RT_DRV_BIOS_COUNT, RT_DRV_TIMER_ACC, RT_DRV_SOUNDS,
       RT_DRV_SHADOW, RT_DRV_QUEUE_HEAD, RT_DRV_QUEUE_TAIL, RT_DRV_PLAYERS, RT_DRV_VOICES, RT_DRV_BYTES };
extern const uint16_t driver_layout[];
extern const uint16_t irq0_async_handler[2];  /* CS, IP: the proved INT 08h handler */
extern const uint32_t overlay_table;   /* descriptors, root image offset (machine.c) */

/* Reference: environment block; its MCB is the first one DOS gives programs. */
#define RT_ENV_SEG 0x07ca

/* Reference: INT 21h AH=1Bh returns DS:BX here, at the media descriptor byte. */
#define MEDIA_SEG 0x0410
#define MEDIA_OFF 0x0059

/* machine.c */
uint16_t rt_flags_word(void);
void rt_set_flags_word(uint16_t f);
/* Machine model, EXEC of XWING.EXE. `mem`: RT_GUEST_BYTES + RT_STATE_BYTES +
 * RT_EMS_BYTES (guest RAM reversed, the state block, the EMS store). */
void rt_start(uint8_t *mem);
extern uint16_t rt_entry_cs, rt_entry_ip;

/* services */
void rt_int21(uint16_t cs, uint16_t ip);
void rt_int10(void);
extern uint8_t rt_dac[768];      /* video.c: 6-bit R, G, B */
/* video.c: set to 1 (with RT_RAISE_IRQ) at each vertical blank by a platform
 * without a field task (rt_video_refresh at the next poll point; the host);
 * the changed rows are presented at the game's mouse poll, or at a blank
 * while the game does not poll (D9); 2: due, the platform's per-blank work
 * done */
extern volatile uint8_t rt_present_due;
void rt_video_refresh(void);
void rt_video_frame(void);      /* INT 33h AX=3: the game's frame boundary */
void rt_dac_out(uint16_t port, uint8_t v);   /* ports 3C8h/3C9h (video.c) */
extern volatile uint32_t rt_fields;   /* vertical blanks, counted by the platform */
/* Vertical mickeys per platform count (input.c): 2 as DOSBox-X, the
 * reference; production platforms with a real mouse set 1 (a PC driver's
 * AX=0Bh counts are equal per inch on both axes). */
extern uint8_t rt_mickeys_y;
/* Where a field task may interrupt the display path: empty; a test seam
 * (tests/test_display_queue.py runs the field task there). */
#define RT_FIELD_POINT() ((void)0)
void rt_int67(void);
void rt_dos_init(void);
void rt_dos_close(void);
uint16_t rt_psp(void);

/* hardware interrupts (machine.c): the platform appends a vector (08h tick,
 * 09h key make, 89h key break) at rt_irq_tail, then RT_RAISE_IRQ. While the
 * guest has IF = 0, rt_irq clears G_IRQ but keeps rt_irq_pending; every path
 * that sets IF copies rt_irq_pending into G_IRQ (sti, __set_flags,
 * rt_set_flags_word), so G_IRQ is never set without rt_irq_pending. */
#define RT_IRQ_RING 32
extern volatile uint8_t rt_irq_ring[RT_IRQ_RING];
extern volatile uint8_t rt_irq_tail;
extern volatile uint8_t rt_irq_pending;
#define RT_RAISE_IRQ() (rt_irq_pending = 1, *(volatile uint8_t *)&G_IRQ = 1)
/* The platform's post (machine.c): the vector appended at rt_irq_tail, then
 * RT_RAISE_IRQ; a full ring is a stop at the next poll point, never an
 * overwrite. At interrupt level, or with interrupts disabled. */
void rt_irq_post(uint8_t vector);
/* IRQ 7 (the DSP: platform.h plat_sb_block, plat_sb_irq), posted outside the
 * ring by counting rt_irq7_tail, then RT_RAISE_IRQ: a pending IRQ 7 holds no
 * CIA tick (rt_irq0_ready, rt_irq0_take look at the ring only), and a poll
 * point takes it after the posted ring, IRQ0 and IRQ1 being the PIC's higher
 * priorities (MEASURED: in the ring, 33 ticks posted behind it in five fields
 * overwrote it, the intro's first speech block). */
extern volatile uint8_t rt_irq7_tail;
/* The DSP's IRQ 7 as the reference's DOSBox-X raises it (DERIVED: sblaster.cpp
 * SB_RaiseIRQ, the 22Eh read; pic.cpp): a raise latches at the PIC while 21h
 * masks IRQ 7 and is taken once unmasked (ports.c rt_irq7_unmasked); reading
 * 22Eh lowers it, dropping a raise not yet taken (rt_irq7_ack). ADLIB_W.IMS's
 * clip stop (+0581C) masks DMA channel 1 and IRQ 7, then reads 22Eh: a block
 * that ends during it is never delivered (MEASURED on the 68030: the end posted
 * before the mask, still untaken at the next poll point). */
void rt_irq7_ack(void);
void rt_irq7_unmasked(void);
void rt_bios_int08(void);
/* Async IRQ0 (Secret Weapons of the Luftwaffe's docs/irq-plan.md I6): the platform's tick interrupt calls
 * rt_irq_interrupt (rt_entry.s) when rt_irq0_ready, else posts vector 08h;
 * production (I8) then runs the posted ticks it may take (rt_irq0_take).
 * rt_irq0_running: a handler runs (either entry); rt_irq_mask: runtime services
 * in progress; rt_opl_pair: the main thread's OPL index/data pair is open. */
extern volatile uint8_t rt_irq0_running, rt_irq_mask, rt_opl_pair, rt_irq_interrupting;
int rt_irq0_ready(void);
int rt_irq0_take(void);
int rt_irq0_bios_tick(void);   /* production: the BIOS INT 08h at the CIA tick */
void rt_irq_interrupt(void);
void rt_irq_abort(void) __attribute__((noreturn));
/* IRQ0 entry (rt_entry.s rt_irq_async, Secret Weapons of the Luftwaffe's docs/irq-plan.md I4): the guest handler
 * of IVT 08h runs on a private guest stack, below a frame whose CS:IP is this
 * sentinel (B000:8000 down: backed, outside the compared RAM, the monochrome
 * text area the VGA reference never shows); the interrupted registers, state
 * block and rt_r are restored after it. rt_entry.s IRQ_SS/IRQ_SP. */
#define RT_IRQ_SS 0xb000
#define RT_IRQ_SP 0x8000
extern uint8_t rt_irq_saved[RT_STATE_BYTES + sizeof(struct rt_regs)];

/* input.c: the platform appends keyboard events (PC set 1 scan code, bit 7
 * break, RT_KEY_E0 for E0-prefixed keys), in sync builds (XWING_SYNC: host,
 * replay, bench) one per 09h interrupt it posts; production posts none and
 * rt_int_c drains them at service entry with IF set (Secret Weapons of the Luftwaffe's docs/irq-plan.md I8) */
#define RT_KEY_RING 16
#define RT_KEY_E0 0x100
extern volatile uint16_t rt_key_ring[RT_KEY_RING];
extern volatile uint8_t rt_key_tail;
void rt_input_init(void);
void rt_keyboard_irq(void);
void rt_keyboard_drain(void);
int rt_key_available(void);
uint16_t rt_key_take(void);
void rt_key_wait(const char *what, uint8_t vector, uint16_t cs, uint16_t ip);
void rt_int16(void);
void rt_int33(void);

/* ports.c */
extern volatile uint32_t rt_irq0_runs, rt_irq0_bios;  /* machine.c: IRQ0 deliveries */
extern uint32_t rt_pit_divisor;    /* channel 0 reload, 1..65536 */
extern uint8_t rt_opl[256];         /* AdLib registers as written (rt_entry.s rt_out8) */
extern uint8_t rt_opl_index;
extern uint8_t rt_opl_keyon[9];     /* per channel: key-on edges, wrapping (FM re-hoster) */
extern uint16_t rt_deliver_cs, rt_deliver_ip;
extern void *rt_deliver_code;
extern uint8_t rt_sb_playing;       /* ports.c: a DSP block plays; its IRQ 7 clears it */
extern uint8_t rt_sb_f2;            /* ports.c: DSP F2h raised IRQ 7; its delivery clears it */
extern uint8_t rt_sb_speaker;       /* ports.c: DSP D1h on, D3h off (Paula speech volume) */
uint8_t rt_pic_masked(uint8_t irq); /* ports.c: the PIC's mask bit of an IRQ */

/* Effect capture (sfx.c, docs/translator-design.md Sound: effects R1): at the
 * return of FLIGHT's sound loader, with rt_sfx_prerender_on, each effect id's
 * OPL writes in rt_sfx_capture[rt_sfx_first[id]..+rt_sfx_writes[id]), ticks of
 * the music driver's 291.3 Hz timer from its start (0); rt_sfx_ticks[id] the
 * tick its status read 0 (0: not within the capture's 8 s, a loop the game
 * stops); rt_sfx_opl the driver's OPL shadow the captures start from. While
 * rt_sfx_capturing, rt_out8's data writes go to rt_sfx_write, not rt_opl. */
#define RT_SFX_IDS 48
#define RT_SFX_WRITES 12288
struct rt_sfx_write { uint16_t tick; uint8_t reg, value; };
extern uint8_t rt_sfx_prerender_on;
extern volatile uint8_t rt_sfx_capturing;
extern struct rt_sfx_write rt_sfx_capture[RT_SFX_WRITES];
extern uint16_t rt_sfx_first[RT_SFX_IDS], rt_sfx_writes[RT_SFX_IDS], rt_sfx_ticks[RT_SFX_IDS];
extern uint8_t rt_sfx_opl[256];
extern uint32_t rt_sfx_captures;    /* completed captures */
void rt_sfx_write(uint32_t reg, uint32_t value);
void rt_sfx_prerender(void);
/* In play (fx_play.c): rt_sfx_starts[id] counts the starts the driver took
 * (HLE sfx_start), wrapping; rt_sfx_read the driver's RT_SFX_PLAYERS players
 * and each OPL channel's player (sfx.c). */
#define RT_SFX_PLAYERS 8
extern uint8_t rt_sfx_starts[RT_SFX_IDS];
int rt_sfx_read(uint8_t *active, uint8_t *id, uint8_t *volume, uint8_t *owner);

#ifdef XWING_RESUME
/* Host lockstep resume (snapshot.c, docs/translator-design.md Resume): the
 * runtime's state by field. Each module names its fields to `f`, saving or
 * loading; with `saving` it returns non-zero where its state cannot be saved
 * (RT_UNSAVED_*). Not saved: caches the load leaves empty (rt_lookup's, the
 * cell walk's) and pointers the new image keeps (rt_guest, rt_deliver_code). */
typedef void rt_field_fn(void *ctx, const char *name, volatile void *field, uint32_t bytes);
#define RT_UNSAVED_SEARCH 1     /* a directory search is open */
#define RT_UNSAVED_STOP 2       /* a stop raised at interrupt level is pending */
#define RT_UNSAVED_HANDLER 3    /* an IRQ0 handler or a runtime service runs */
#define RT_UNSAVED_CAPTURE 4    /* an effect capture runs */
#define RT_UNSAVED_IRQ7 5       /* an IRQ 7 is posted, not yet taken */
int rt_machine_fields(rt_field_fn *f, void *ctx, int saving);
int rt_dos_fields(rt_field_fn *f, void *ctx, int saving);
int rt_ems_fields(rt_field_fn *f, void *ctx, int saving);
int rt_input_fields(rt_field_fn *f, void *ctx, int saving);
int rt_ports_fields(rt_field_fn *f, void *ctx, int saving);
int rt_video_fields(rt_field_fn *f, void *ctx, int saving);
int rt_sfx_fields(rt_field_fn *f, void *ctx, int saving);
/* The fields into out[room]: the bytes used; 0 when they do not fit, else
 * -RT_UNSAVED_* (as uint32_t) when the state cannot be saved. */
uint32_t rt_snapshot_save(uint8_t *out, uint32_t room);
/* Back from in[bytes] (rt_snapshot_save's): 0, else the 1-based index of the
 * first field whose name or size differs from this runtime's (or that is
 * missing), or -1 for another version. */
int32_t rt_snapshot_load(const uint8_t *in, uint32_t bytes);
#endif

/* stop: report and halt, never resumes */
void rt_stop(const char *what, uint32_t a, uint32_t b) __attribute__((noreturn));
void rt_unsupported(const char *what, uint16_t vector, uint16_t cs, uint16_t ip) __attribute__((noreturn));
void rt_log(const char *s);
void rt_log_hex(const char *label, uint32_t v);

#endif
