/* I/O ports the game touches (docs/external-surface.md), as devices of the
 * reference machine: PIC, PIT, AdLib, the absent joystick and the VGA DAC and
 * input status, and with ADLIB_W.IMS (P10) the Sound Blaster's DSP and DMA
 * channel 1. Any other port stops. Copied from Secret Weapons of the
 * Luftwaffe's (manifest/references.tsv) and adapted; the Sound Blaster from
 * Wing Commander 2's. */
#include "runtime.h"
#include "platform.h"

/* PIC: the mask register (reference mask F8h: IRQ 0-2 enabled); the
 * non-specific EOI is answered in rt_out8 (rt_entry.s). */
static uint8_t pic_mask = 0xf8;

uint8_t rt_pic_masked(uint8_t irq)
{
    return (uint8_t)(pic_mask >> irq & 1);
}

/* PIT: per channel the access mode of its control word (1 lo, 2 hi, 3 lo/hi)
 * and the lo/hi toggle; channel 0's reload (0 = 65536) sets the tick rate.
 * BIOS start state: all channels lo/hi. ADLIB.IMS programs channel 2's mode
 * (43h = B6h) and then writes channel 0's reload (1000h) as lo/hi. */
static uint8_t pit_access[3] = {3, 3, 3}, pit_high[3];
static uint16_t pit_reload[3];
uint32_t rt_pit_divisor = 0x10000;

/* AdLib: index register, the written OPL2 register file (D10) and the key-on
 * edges per channel; rt_out8 (rt_entry.s) answers its byte writes. */
uint8_t rt_opl_index;
uint8_t rt_opl[256];
uint8_t rt_opl_keyon[9];

/* Sound Blaster 2.0 DSP at 220h (reference/dosbox-x-sb.conf: IRQ 7, DMA 1) and
 * its DMA channel 1, as far as ADLIB_W.IMS drives them (every sbms milestone,
 * MEASURED: trace/sound.csv). Its detection writes C6h to the reset port
 * (bit 0 clear: no reset) and reads the data port before any reset (the last
 * value, AAh), resets the DSP (226h 1, then 0 after four reads of 226h, which
 * answer FFh) and waits for AAh; E0h answers its argument inverted, E1h the
 * version 2.01, E4h/E8h store and read back a test byte, E2h writes an
 * identification byte by DMA (mode 45h) and F2h raises IRQ 7. Playback: the
 * time constant (40h), channel 1 programmed (mode 49h), one 8-bit single-cycle
 * block (14h, length - 1), speaker on (D1h) and off (D3h), DMA paused (D0h)
 * and continued (D4h); the DSP raises IRQ 7 when the block has played, and
 * ADLIB_W.IMS's INT 0Fh handler acknowledges it (22Eh) and starts the next.
 * Status reads answer as the model stands; plat_dsp_status adds the device's
 * timing. */
static uint8_t dsp_reset, dsp_last = 0xaa;         /* reset high; the last byte read */
static uint8_t dsp_out_q[2], dsp_out_n;             /* bytes awaiting a data read */
static uint8_t dsp_command, dsp_args, dsp_arg[2];   /* a command awaiting argument bytes */
static uint8_t dsp_time_constant, dsp_test, dsp_e2_count;
uint8_t rt_sb_playing;      /* a block started and its IRQ 7 not yet taken (machine.c) */
uint8_t rt_sb_f2;           /* F2h's IRQ 7 raised and not yet taken (machine.c) */
uint8_t rt_sb_speaker;      /* D1h on, D3h off */
uint8_t rt_sb_paused;       /* D0h paused, D4h continued */

/* The card's OPL2 at base + 8 (228h index and status, 229h data), as far as
 * ADLIB_W.IMS's detection drives it (+05180, MEASURED: trace/ports.csv): the
 * test register (1), timer 1's count (2) and the timer control (4: bit 7
 * resets the flags, bit 6 masks timer 1, bit 0 starts it). The status reads
 * 06h (the OPL2's low bits on the reference card) with timer 1's flags (C0h)
 * once it has expired; the model answers expired as soon as it runs and
 * plat_dsp_status may report it still counting, as the device's timing does.
 * The music writes the OPL at 388h/389h (rt_entry.s rt_out8). */
static uint8_t opl_sb_index, opl_sb_control, opl_sb_flags;

static uint8_t opl_sb_in(void)
{
    if ((opl_sb_control & 0x41) == 0x01) {
        opl_sb_flags = 0xc0;            /* timer 1 expired, its IRQ flag */
    }
    return plat_dsp_status(0x228, 0x06 | opl_sb_flags);
}

static void opl_sb_out(uint16_t port, uint8_t v)
{
    if (port == 0x228) {
        opl_sb_index = v;
        return;
    }
    switch (opl_sb_index) {
    case 1: case 2: return;             /* test register, timer 1's count */
    case 4:
        if (v & 0x80) {
            opl_sb_flags = 0;
        } else {
            opl_sb_control = v;
        }
        return;
    }
    rt_stop("OPL register at 229h outside the detection's (index, value)", opl_sb_index, v);
}

/* 8237 channel 1: base address and count (lo, hi through the flip-flop),
 * page (83h), mode (0Bh), single mask (0Ah; masked at reset). */
static uint8_t dma_flip, dma_masked = 1, dma_mode;
static uint16_t dma_address, dma_count;
static uint8_t dma_page;

/* E2h's identification bytes by argument in order (MEASURED: dma.csv write rows
 * of every sbms milestone, the bytes from their hashes: 3Ah, then 08h). */
static const uint8_t e2_answer[2][2] = {{0x06, 0x3a}, {0x6b, 0x08}};

static void dsp_queue(uint8_t v)
{
    if (dsp_out_n == sizeof dsp_out_q) {
        rt_stop("DSP output beyond its queue", v, 0);
    }
    dsp_out_q[dsp_out_n++] = v;
}

static uint8_t dsp_in(uint16_t port)
{
    uint8_t v;
    switch (port) {
    case 0x226: return 0xff;                         /* the reset port reads FFh */
    case 0x22a:
        if (dsp_out_n) {
            dsp_last = dsp_out_q[0];
            dsp_out_q[0] = dsp_out_q[1];
            --dsp_out_n;
        }
        return dsp_last;
    case 0x22c: v = 0x2a; break;                     /* bit 7 clear: ready for a byte */
    case 0x22e:                                      /* bit 7: data available; acks IRQ 7 */
        rt_irq7_ack();
        v = dsp_out_n ? 0xaa : 0x2a;
        break;
    default: rt_stop("unsupported DSP port in", port, 0);
    }
    return plat_dsp_status(port, v);
}

static void dma_ready(uint8_t mode, uint32_t length)
{
    if (dma_masked || dma_mode != mode) {
        rt_stop("DSP transfer without DMA channel 1 ready (mask, mode)", dma_masked, dma_mode);
    }
    if ((uint32_t)dma_count + 1 < length || (uint32_t)dma_address + length > 0x10000) {
        rt_stop("DSP transfer beyond DMA channel 1's count or page (count, length)", dma_count, length);
    }
}

/* The 8237 after `length` bytes: address and count advanced (count FFFFh at TC). */
static void dma_advance(uint32_t length)
{
    dma_address = (uint16_t)(dma_address + length);
    dma_count = (uint16_t)(dma_count - length);
}

/* 14h's length is complete: the block from channel 1's address. */
static void dsp_dma_block(uint32_t length)
{
    dma_ready(0x49, length);
    /* A 14h replaces the block before it, paused or playing: its IRQ 7 is
     * never raised, one already posted is still taken. CT-VOICE's stop pauses
     * the block (D0h) and the next clip's 14h replaces it (MEASURED: m02i,
     * blocks 9 to 12); over a playing block, the reference's DOSBox-X restarts
     * the count with the new length and drops the old end (DERIVED: its
     * sblaster.cpp, 14h through DSP_PrepareDMA_Old to DSP_DoDMATransfer;
     * reached on the 68030, where the intro's lines overlap). */
    rt_sb_paused = 0;
    if (dsp_time_constant == 0) {
        rt_stop("DSP block without a time constant", length, 0);
    }
    rt_sb_playing = 1;
    uint32_t linear = (uint32_t)dma_page << 16 | dma_address;
    dma_advance(length);
    plat_sb_block(linear, length, 1000000u / (256u - dsp_time_constant));
}

static void dsp_command_done(void)
{
    switch (dsp_command) {
    case 0x40: dsp_time_constant = dsp_arg[0]; return;
    case 0x14: dsp_dma_block((uint32_t)(dsp_arg[1] | dsp_arg[0] << 8) + 1); return;
    case 0xe0: dsp_queue((uint8_t)~dsp_arg[0]); return;
    case 0xe4: dsp_test = dsp_arg[0]; return;
    case 0xe2:
        if (dsp_e2_count == 2 || dsp_arg[0] != e2_answer[dsp_e2_count][0]) {
            rt_stop("DSP E2h identification not measured (call, argument)", dsp_e2_count, dsp_arg[0]);
        }
        dma_ready(0x45, 1);
        wr8((uint32_t)dma_page << 16 | dma_address, e2_answer[dsp_e2_count++][1]);
        dma_advance(1);
        return;
    }
}

static void dsp_out(uint16_t port, uint8_t v)
{
    if (port == 0x226) {
        if (v & 1) {
            dsp_reset = 1;
        } else if (dsp_reset) {       /* reset ends: AAh to read, playback stopped */
            dsp_reset = 0;
            dsp_out_n = 0;
            dsp_command = dsp_args = 0;
            rt_sb_speaker = 0;
            rt_sb_paused = 0;
            dsp_queue(0xaa);
        }                             /* bit 0 clear without a reset: none (C6h) */
        return;
    }
    if (port == 0x22a) {              /* the detection's write of the data port: ignored */
        return;
    }
    if (port != 0x22c) {
        rt_stop("unsupported DSP port out (port, value)", port, v);
    }
    if (dsp_args) {
        dsp_arg[--dsp_args] = v;
        if (!dsp_args) {
            dsp_command_done();
        }
        return;
    }
    dsp_command = v;
    switch (v) {
    case 0x40: case 0xe0: case 0xe2: case 0xe4: dsp_args = 1; return;
    case 0x14: dsp_args = 2; return;                     /* 8-bit single-cycle DMA output */
    case 0xd0: rt_sb_paused = 1; plat_sb_pause(1); return;
    case 0xd4: rt_sb_paused = 0; plat_sb_pause(0); return;
    case 0xd1: rt_sb_speaker = 1; return;
    case 0xd3: rt_sb_speaker = 0; return;
    case 0xe1: dsp_queue(0x02); dsp_queue(0x01); return; /* version 2.01 */
    case 0xe8: dsp_queue(dsp_test); return;
    case 0xf2: rt_sb_f2 = 1; plat_sb_irq(); return;      /* IRQ 7 at once */
    }
    rt_stop("unsupported DSP command", v, 0);
}

static void dma_out(uint16_t port, uint8_t v)
{
    switch (port) {
    case 0x02:
        dma_address = dma_flip ? (uint16_t)((dma_address & 0xff) | v << 8)
                               : (uint16_t)((dma_address & 0xff00) | v);
        dma_flip ^= 1;
        return;
    case 0x03:
        dma_count = dma_flip ? (uint16_t)((dma_count & 0xff) | v << 8)
                             : (uint16_t)((dma_count & 0xff00) | v);
        dma_flip ^= 1;
        return;
    case 0x0a:
        if ((v & 3) == 1) {
            dma_masked = (v & 4) != 0;
            return;
        }
        break;
    case 0x0b:
        if ((v & 3) == 1) {
            dma_mode = v;
            return;
        }
        break;
    case 0x0c: dma_flip = 0; return;
    case 0x83: dma_page = v; return;
    }
    rt_stop("unsupported DMA write (port, value)", port, v);
}

static void pit_control(uint8_t v)
{
    uint8_t ch = v >> 6, access = (v >> 4) & 3;
    if (ch == 3 || access == 0) {
        rt_stop("PIT read-back or latch command", v, 0);
    }
    pit_access[ch] = access;
    pit_high[ch] = 0;
}

static void pit_data(uint8_t ch, uint8_t v)
{
    uint8_t access = pit_access[ch];
    int high = access == 2 || (access == 3 && pit_high[ch]);
    pit_reload[ch] = high ? (uint16_t)((pit_reload[ch] & 0x00ff) | v << 8)
                          : (uint16_t)((pit_reload[ch] & 0xff00) | v);
    if (access == 3) {
        pit_high[ch] ^= 1;
    }
    if (ch == 0 && (access != 3 || !pit_high[ch])) {
        rt_pit_divisor = pit_reload[0] ? pit_reload[0] : 0x10000;
        plat_timer_rate(rt_pit_divisor);
    }
}

uint32_t rt_port_in(uint32_t port, uint32_t width)
{
    port &= 0xffff;
    if (width == 8) {
        switch (port) {
        case 0x21: return pic_mask;
        case 0x201: return 0xff;    /* reference: no joystick, axes never time out */
        case 0x3da: return plat_vga_status();
        case 0x226: case 0x22a: case 0x22c: case 0x22e: return dsp_in((uint16_t)port);
        case 0x228: return opl_sb_in();
        }
    }
    rt_stop("unsupported port in (port, width)", port, width);
}

void rt_port_out(uint32_t port, uint32_t value, uint32_t width)
{
    port &= 0xffff;
    uint8_t v = (uint8_t)value;
    if (width == 16 && port == 0x3c8) {     /* index, then the first component */
        rt_dac_out(0x3c8, v);
        rt_dac_out(0x3c9, (uint8_t)(value >> 8));
        return;
    }
    if (width == 8) {
        switch (port) {
        case 0x21:
            pic_mask = v;
            if (!(v & 0x80)) {
                rt_irq7_unmasked();     /* a latched IRQ 7 (runtime.h rt_irq7_ack) */
            }
            return;
        case 0x40: case 0x41: case 0x42: pit_data((uint8_t)(port - 0x40), v); return;
        case 0x43: pit_control(v); return;
        case 0x201: return;         /* joystick one-shots: none to fire */
        case 0x3c8: case 0x3c9: rt_dac_out((uint16_t)port, v); return;
        case 0x226: case 0x22a: case 0x22c: dsp_out((uint16_t)port, v); return;
        case 0x228: case 0x229: opl_sb_out((uint16_t)port, v); return;
        case 0x02: case 0x03: case 0x0a: case 0x0b: case 0x0c: case 0x83: dma_out((uint16_t)port, v); return;
        }
    }
    rt_stop("unsupported port out (port, width)", port, width);
}

#ifdef XWING_RESUME
int rt_ports_fields(rt_field_fn *f, void *ctx, int saving)
{
    (void)saving;
    f(ctx, "ports.pic_mask", &pic_mask, sizeof pic_mask);
    f(ctx, "ports.pit_access", pit_access, sizeof pit_access);
    f(ctx, "ports.pit_high", pit_high, sizeof pit_high);
    f(ctx, "ports.pit_reload", pit_reload, sizeof pit_reload);
    f(ctx, "ports.pit_divisor", &rt_pit_divisor, sizeof rt_pit_divisor);
    f(ctx, "ports.opl_index", &rt_opl_index, sizeof rt_opl_index);
    f(ctx, "ports.opl", rt_opl, sizeof rt_opl);
    f(ctx, "ports.opl_keyon", rt_opl_keyon, sizeof rt_opl_keyon);
    f(ctx, "ports.dsp_reset", &dsp_reset, sizeof dsp_reset);
    f(ctx, "ports.dsp_last", &dsp_last, sizeof dsp_last);
    f(ctx, "ports.dsp_out_q", dsp_out_q, sizeof dsp_out_q);
    f(ctx, "ports.dsp_out_n", &dsp_out_n, sizeof dsp_out_n);
    f(ctx, "ports.dsp_command", &dsp_command, sizeof dsp_command);
    f(ctx, "ports.dsp_args", &dsp_args, sizeof dsp_args);
    f(ctx, "ports.dsp_arg", dsp_arg, sizeof dsp_arg);
    f(ctx, "ports.dsp_time_constant", &dsp_time_constant, sizeof dsp_time_constant);
    f(ctx, "ports.dsp_test", &dsp_test, sizeof dsp_test);
    f(ctx, "ports.dsp_e2_count", &dsp_e2_count, sizeof dsp_e2_count);
    f(ctx, "ports.sb_playing", &rt_sb_playing, sizeof rt_sb_playing);
    f(ctx, "ports.sb_f2", &rt_sb_f2, sizeof rt_sb_f2);
    f(ctx, "ports.opl_sb_index", &opl_sb_index, sizeof opl_sb_index);
    f(ctx, "ports.opl_sb_control", &opl_sb_control, sizeof opl_sb_control);
    f(ctx, "ports.opl_sb_flags", &opl_sb_flags, sizeof opl_sb_flags);
    f(ctx, "ports.sb_speaker", &rt_sb_speaker, sizeof rt_sb_speaker);
    f(ctx, "ports.sb_paused", &rt_sb_paused, sizeof rt_sb_paused);
    f(ctx, "ports.dma_flip", &dma_flip, sizeof dma_flip);
    f(ctx, "ports.dma_masked", &dma_masked, sizeof dma_masked);
    f(ctx, "ports.dma_mode", &dma_mode, sizeof dma_mode);
    f(ctx, "ports.dma_address", &dma_address, sizeof dma_address);
    f(ctx, "ports.dma_count", &dma_count, sizeof dma_count);
    f(ctx, "ports.dma_page", &dma_page, sizeof dma_page);
    return 0;
}
#endif
