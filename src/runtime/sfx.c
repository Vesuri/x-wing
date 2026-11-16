/* Effect capture for prerendering (docs/translator-design.md, Sound: effects
 * R1), adapted from Secret Weapons of the Luftwaffe's src/runtime/sfx.c
 * (manifest/references.tsv). At the return of FLIGHT's sound loader (HLE
 * sfx_prerender, observe only), when every effect of SFXADL.LFD is in the
 * music driver's sound table, each effect's OPL writes are captured by
 * running ADLIB.IMS's own commands and INT 08h handler with the timer stepped
 * by hand: its request queue emptied, stop all (0Bh), start (08h), its group
 * (10h, as FLIGHT.OVL+18A3C), then a tick at a time until status (0Dh) reads
 * 0. Before each tick the handler's game-timer accumulator and BIOS countdown
 * are reset, so it runs only driver code (tools/sfx_capture.py checks that it
 * does). The driver's
 * memory is saved before and restored before each id and after the last, the
 * CIA tick held meanwhile (game time pauses). The writes go to
 * rt_sfx_capture, not rt_opl. tools/sfx_capture.py is the oracle.
 *
 * In play, rt_sfx_read gives the effect player (fx_play.c) the driver's
 * players and which of them each OPL channel's voice plays, and HLE
 * sfx_start (rt_entry.s) counts each id's starts in rt_sfx_starts. */
#include "platform.h"
#include "runtime.h"

/* ADLIB.IMS load-image offsets (docs/external-surface.md, Music driver interface). */
#define DRV_ENTRY 0x0000            /* the far command entry */
#define DRV_TIMER 0x0a1b            /* the INT 08h handler */
#define DRV_DATA 0x04d0             /* DS, paragraphs above CS (ADLIB.IMS+00BEF) */
#define DRV_BYTES 0x7760            /* image and minimum allocation (its MZ header) */
#define DRV_DS_SLOT 0x0911          /* CS word: the handler's DS */
#define DRV_BIOS_COUNT 0x0910       /* CS byte: ticks to the BIOS chain (ADLIB.IMS+00A2D) */
#define DRV_TIMER_ACC 0x0678        /* DS word: game-timer accumulator (ADLIB.IMS+00188) */
#define DRV_SOUNDS 0x06e2           /* DS far pointer: the game's sound table, id * 4 */
#define DRV_SHADOW 0x0342           /* DS: the driver's OPL register shadow (ADLIB.IMS+04BD2) */
#define DRV_QUEUE_HEAD 0x0ebe       /* DS words: the request queue's read and write index (+02B7D) */
#define DRV_QUEUE_TAIL 0x12c0
#define DRV_PLAYERS 0x06ea          /* DS: 8 players of 12h (ADLIB.IMS+00E8E) */
#define DRV_PLAYER_BYTES 0x12
#define PLAYER_ACTIVE 0x06           /* byte, 1 while it plays (ADLIB.IMS+01215) */
#define PLAYER_SOUND 0x08            /* word: the sound id */
#define PLAYER_VOLUME 0x0e           /* byte: its volume, 0-127 (command 102h) */
#define DRV_VOICES 0x1ed2           /* DS: 9 voices of 62h (ADLIB.IMS+03F1E) */
#define DRV_VOICE_BYTES 0x62
#define VOICE_PART 0x00             /* word: its part, 0 free; the part's word 0 its player */
#define VOICE_CHANNEL 0x07          /* byte: its OPL channel */
#define CMD_START 0x08
#define CMD_STOP_ALL 0x0b
#define CMD_STATUS 0x0d
#define CMD_GROUP 0x10
#define FIRST_EFFECT 4              /* ids from 4 are effects (FLIGHT.OVL+18A55) */
#define TICKS_MAX 2330              /* 8 s at 291.3 Hz */
#define SENTINEL_CS RT_IRQ_SS
#define SENTINEL_IP RT_IRQ_SP

uint8_t rt_sfx_prerender_on;
volatile uint8_t rt_sfx_capturing;
__attribute__((aligned(4))) struct rt_sfx_write rt_sfx_capture[RT_SFX_WRITES];
__attribute__((aligned(4))) uint16_t rt_sfx_first[RT_SFX_IDS], rt_sfx_writes[RT_SFX_IDS], rt_sfx_ticks[RT_SFX_IDS];
__attribute__((aligned(4))) uint8_t rt_sfx_opl[256];    /* the driver's OPL shadow after the stop */
uint32_t rt_sfx_captures;
__attribute__((aligned(4))) uint8_t rt_sfx_starts[RT_SFX_IDS];
static uint16_t capture_n, capture_tick, driver_cs;

uint32_t rt_guest_call(uint32_t sentinel);
void *rt_lookup(uint32_t cs, uint32_t ip, uint32_t far);

/* rt_out8 (rt_entry.s) while capturing: one OPL data write. */
void rt_sfx_write(uint32_t reg, uint32_t value)
{
    if (capture_n < RT_SFX_WRITES) {
        rt_sfx_capture[capture_n].tick = capture_tick;
        rt_sfx_capture[capture_n].reg = (uint8_t)reg;
        rt_sfx_capture[capture_n].value = (uint8_t)value;
        ++capture_n;
    }
}

static void push(uint16_t v)
{
    rt_r.sp = (uint16_t)(rt_r.sp - 2);
    wr16(lin(G_SS, rt_r.sp), v);
}

/* The driver at cs:ip on the private stack below the sentinel return: a far
 * C call with n arguments, or (iret) the INT 08h handler's frame. AX after. */
static uint16_t driver(uint16_t cs, uint16_t ip, int iret, const uint16_t *arg, int n)
{
    G_SS = RT_IRQ_SS;
    rt_r.sp = RT_IRQ_SP;
    if (iret) {
        push(0x0202);
        G_IF = 0;
    } else {
        while (n--) {
            push(arg[n]);
        }
        G_IF = 1;
    }
    G_TF = 0;
    push(SENTINEL_CS);
    push(SENTINEL_IP);
    rt_deliver_cs = cs;
    rt_deliver_ip = ip;
    rt_deliver_code = rt_lookup(cs, ip, 1);
    rt_guest_call((uint32_t)SENTINEL_CS << 16 | SENTINEL_IP);
    return rt_r.ax;
}

static uint16_t command(uint16_t cs, uint16_t a, uint16_t b, uint16_t c, int n)
{
    const uint16_t arg[3] = {a, b, c};
    return driver(cs, DRV_ENTRY, 0, arg, n);
}

/* The driver's memory, its bytes as rt_span holds them. */
static void memory(uint16_t cs, uint8_t *save, int restore)
{
    uint8_t *span = restore ? rt_span_w(lin(cs, 0), DRV_BYTES) : rt_span(lin(cs, 0), DRV_BYTES);
    for (uint32_t i = 0; i < DRV_BYTES; ++i) {
        if (restore) {
            span[i] = save[i];
        } else {
            save[i] = span[i];
        }
    }
}

/* HLE sfx_prerender (rt_entry.s saves and restores the guest's registers and
 * state block around it). IVT 08h is the driver's handler. */
void rt_sfx_prerender(void)
{
    if (!rt_sfx_prerender_on) {
        return;
    }
    uint16_t cs = rd16(8 * 4 + 2), ds = (uint16_t)(cs + DRV_DATA);
    if (rd16(8 * 4) != DRV_TIMER || rd16(lin(cs, DRV_DS_SLOT)) != ds) {
        rt_stop("effect capture: IVT 08h is not the music driver's handler", cs, rd16(8 * 4));
    }
    uint8_t *save = plat_alloc(DRV_BYTES);
    if (!save) {
        rt_log("effect capture: no memory for the driver's state; effects stay live");
        return;
    }
    uint32_t table = lin(rd16(lin(ds, DRV_SOUNDS + 2)), rd16(lin(ds, DRV_SOUNDS)));
    uint32_t effects = rt_r.ax;    /* the loader's return: effects registered from id 4 */
    uint8_t index = rt_opl_index, pair = rt_opl_pair;
    memory(cs, save, 0);
    rt_irq0_running = 1;            /* no tick delivered; the CIA's held */
    rt_sfx_capturing = 1;
    capture_n = 0;
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        rt_sfx_first[id] = capture_n;
        rt_sfx_writes[id] = rt_sfx_ticks[id] = 0;
        uint32_t far = id < FIRST_EFFECT || id >= FIRST_EFFECT + effects ? 0 : rd32(table + 4u * id);
        uint32_t sound = lin((uint16_t)(far >> 16), (uint16_t)far);
        if (!far || rd32(sound) != 0x204c4441u || !plat_sfx_wanted(id)) {   /* "ADL ", little-endian */
            continue;
        }
        memory(cs, save, 1);
        wr16(lin(ds, DRV_QUEUE_HEAD), rd16(lin(ds, DRV_QUEUE_TAIL)));  /* no queued request runs */
        capture_tick = 0;
        command(cs, CMD_STOP_ALL, 0, 0, 1);
        for (unsigned r = 0; r < 256; ++r) {
            rt_sfx_opl[r] = rd8(lin(ds, (uint16_t)(DRV_SHADOW + r)));
        }
        uint16_t first = capture_n, end = 0;
        rt_sfx_first[id] = first;
        command(cs, CMD_START, id, 0, 2);
        command(cs, CMD_GROUP, id, 1, 3);
        for (capture_tick = 1; capture_tick <= TICKS_MAX; ++capture_tick) {
            wr16(lin(ds, DRV_TIMER_ACC), 0);
            wr8(lin(cs, DRV_BIOS_COUNT), 0x10);
            driver(cs, DRV_TIMER, 1, 0, 0);
            if (!command(cs, CMD_STATUS, id, 0, 2)) {
                end = capture_tick;
                break;
            }
        }
        if (capture_n >= RT_SFX_WRITES) {
            rt_log("effect capture: the write buffer is full");
            break;
        }
        rt_sfx_writes[id] = (uint16_t)(capture_n - first);
        rt_sfx_ticks[id] = end;     /* 0: it did not end (a loop the game stops) */
    }
    memory(cs, save, 1);
    rt_opl_index = index;
    rt_opl_pair = pair;
    plat_free(save);
    driver_cs = cs;
    ++rt_sfx_captures;
    plat_sfx_captured();            /* the prerender, game time still paused */
    rt_sfx_capturing = 0;
    rt_irq0_running = 0;
}

/* The driver's players and voices now (any time after a capture; the field
 * task calls it with the tick masked): per player active, its sound id (0xff
 * one past RT_SFX_IDS) and volume; per OPL channel the player its voice
 * plays, 0xff none. 0 before the first capture. */
int rt_sfx_read(uint8_t *active, uint8_t *id, uint8_t *volume, uint8_t *owner)
{
    if (!driver_cs) {
        return 0;
    }
    uint16_t ds = (uint16_t)(driver_cs + DRV_DATA);
    for (unsigned p = 0; p < RT_SFX_PLAYERS; ++p) {
        uint16_t at = (uint16_t)(DRV_PLAYERS + p * DRV_PLAYER_BYTES);
        uint16_t sound = rd16(lin(ds, (uint16_t)(at + PLAYER_SOUND)));
        active[p] = rd8(lin(ds, (uint16_t)(at + PLAYER_ACTIVE))) == 1;
        id[p] = sound < RT_SFX_IDS ? (uint8_t)sound : 0xff;
        volume[p] = rd8(lin(ds, (uint16_t)(at + PLAYER_VOLUME)));
    }
    for (unsigned c = 0; c < 9; ++c) {
        owner[c] = 0xff;
    }
    for (unsigned v = 0; v < 9; ++v) {
        uint16_t at = (uint16_t)(DRV_VOICES + v * DRV_VOICE_BYTES);
        uint16_t part = rd16(lin(ds, (uint16_t)(at + VOICE_PART)));
        uint8_t c = rd8(lin(ds, (uint16_t)(at + VOICE_CHANNEL)));
        if (!part || c >= 9) {
            continue;
        }
        uint16_t k = (uint16_t)(rd16(lin(ds, part)) - DRV_PLAYERS);
        if (k % DRV_PLAYER_BYTES == 0 && k / DRV_PLAYER_BYTES < RT_SFX_PLAYERS) {
            owner[c] = (uint8_t)(k / DRV_PLAYER_BYTES);
        }
    }
    return 1;
}

#ifdef XWING_RESUME
/* rt_sfx_prerender_on is the platform's choice, not state: the resumed run's own. */
int rt_sfx_fields(rt_field_fn *f, void *ctx, int saving)
{
    if (saving && rt_sfx_capturing) {
        return RT_UNSAVED_CAPTURE;
    }
    f(ctx, "sfx.captures", &rt_sfx_captures, sizeof rt_sfx_captures);
    f(ctx, "sfx.capture", rt_sfx_capture, sizeof rt_sfx_capture);
    f(ctx, "sfx.first", rt_sfx_first, sizeof rt_sfx_first);
    f(ctx, "sfx.writes", rt_sfx_writes, sizeof rt_sfx_writes);
    f(ctx, "sfx.ticks", rt_sfx_ticks, sizeof rt_sfx_ticks);
    f(ctx, "sfx.opl", rt_sfx_opl, sizeof rt_sfx_opl);
    f(ctx, "sfx.starts", rt_sfx_starts, sizeof rt_sfx_starts);
    f(ctx, "sfx.capture_n", &capture_n, sizeof capture_n);
    f(ctx, "sfx.capture_tick", &capture_tick, sizeof capture_tick);
    f(ctx, "sfx.driver_cs", &driver_cs, sizeof driver_cs);
    return 0;
}
#endif
