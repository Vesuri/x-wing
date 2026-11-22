/* Sound Blaster speech player (sb_play.h). A block plays as fx_play.c plays
 * an effect: in equal chunks of at most one Paula loop, the first restarted,
 * each next latched a field after the one before it starts; the samples a
 * field advance it (24.8) from the rate's Paula period, PAL (313 lines of 227
 * colour clocks) or NTSC (263 of 227.5). A pause keeps the samples played and
 * a continue restarts the voice at the next one. */
#include "sb_play.h"

#define SILENCE_BYTES 4
#define LOOP_BYTES 65534u           /* Paula's 16-bit word count */
#define CLOCK_PAL 3546895u
#define CLOCK_NTSC 3579545u
#define PERIOD_FLOOR 124

enum { IDLE, PLAY, PAUSED };
static struct {
    const int8_t *pcm;
    uint32_t bytes, rate;
    uint32_t base;                  /* the sample the voice restarted at */
    uint32_t elapsed;               /* samples since then, 24.8 */
    uint32_t chunk;                 /* bytes a chunk from base, even */
    uint8_t chunks, segment, phase;
} b;
static const int8_t *silence;
uint32_t sb_started, sb_ended;

static void restart_at(uint32_t base)
{
    uint32_t left = b.bytes - base;
    b.base = base;
    b.elapsed = 0;
    b.segment = 0;
    b.chunks = (uint8_t)((left + LOOP_BYTES - 1) / LOOP_BYTES);
    b.chunk = ((left + b.chunks - 1) / b.chunks + 1) & ~1u;
}

void sb_block(const int8_t *pcm, uint32_t bytes, uint32_t rate, const int8_t *zero)
{
    silence = zero;
    b.pcm = pcm;
    b.bytes = (bytes + 1) & ~1u;
    b.rate = rate;
    restart_at(0);
    b.phase = PLAY;
    ++sb_started;
}

void sb_pause(uint32_t paused)
{
    if (paused && b.phase == PLAY) {
        b.phase = PAUSED;
    } else if (!paused && b.phase == PAUSED) {
        uint32_t at = b.base + (b.elapsed >> 8);
        if (at + 2 > b.bytes) {
            at = b.bytes - 2;
        }
        restart_at(at & ~1u);
        b.phase = PLAY;
    }
}

void sb_clear(void)
{
    b.phase = IDLE;
}

uint16_t sb_field(uint8_t speaker, struct fm_voice *voice, uint8_t *ended)
{
    struct fm_voice *v = &voice[SB_VOICE];
    uint32_t clock = fm_ntsc ? CLOCK_NTSC : CLOCK_PAL;
    uint32_t period = (clock + b.rate / 2) / (b.rate ? b.rate : 1);
    uint32_t field, at;
    *ended = 0;
    if (b.phase == IDLE) {
        return 0;
    }
    if (period < PERIOD_FLOOR) {
        period = PERIOD_FLOOR;
    }
    field = fm_ntsc ? 128u * 119665u / period : 256u * 71051u / period;
    v->channel = -1;
    v->period = (uint16_t)period;
    v->restart = b.phase == PLAY && b.segment == 0;
    if (b.phase == PAUSED) {
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
        v->volume = 0;
        return FM_RESERVE(SB_VOICE);
    }
    if (b.segment) {
        b.elapsed += field;
        at = b.elapsed >> 8;
        /* the latched chunk has played a field: latch the next */
        if (b.segment <= b.chunks && at >= (uint32_t)(b.segment - 1) * b.chunk + (field >> 8)) {
            ++b.segment;
        }
        if (b.base + at >= b.bytes) {
            b.phase = IDLE;
            *ended = 1;
            ++sb_ended;
            v->loop = silence;
            v->bytes = SILENCE_BYTES;
            v->volume = 0;
            return FM_RESERVE(SB_VOICE);
        }
    } else {
        b.segment = 1;
    }
    if (b.segment <= b.chunks) {
        uint32_t off = (uint32_t)(b.segment - 1) * b.chunk;
        uint32_t left = b.bytes - b.base - off;
        v->loop = b.pcm + b.base + off;
        v->bytes = (uint16_t)(left < b.chunk ? left : b.chunk);
    } else {
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
    }
    v->volume = speaker ? SB_VOLUME : 0;
    return FM_RESERVE(SB_VOICE);
}
