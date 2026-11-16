/* Prerendered effect player (fx_play.h): the effect half of Secret Weapons of
 * the Luftwaffe's tfh_paula.c (commit pinned in manifest/references.tsv), its
 * fixed SPAZ slots replaced by the iMUSE driver's players. A player that
 * starts an effect with a sample gets a play: its sample once at its level,
 * in equal chunks of at most one Paula loop, each latched a field after the
 * one before it starts, on a Paula voice the FM re-hoster gives up; its OPL
 * channels are muted while the player plays it. The player's volume scales
 * the sample's; a stop before the driver's end of it fades out over
 * FX_FADE_FIELDS; at most FX_PLAYS play, the oldest giving way. A start that
 * reuses a player within one field is seen in the start counts. */
#include "fx_play.h"

#define SILENCE_BYTES 4
#define VOLUME_FULL 64
/* Paula period and samples a field (24.8) for FM_EFFECT_RATE, PAL (313 lines
 * of 227 colour clocks) and NTSC (263 of 227.5). */
#define EFFECT_PERIOD_PAL 214
#define EFFECT_PERIOD_NTSC 216
#define EFFECT_FIELD_PAL (256u * 71051u / EFFECT_PERIOD_PAL)
#define EFFECT_FIELD_NTSC (128u * 119665u / EFFECT_PERIOD_NTSC)
#define EFFECT_LOOP_BYTES 65534u    /* Paula's 16-bit word count */

/* Per player volume / 4 (the driver's step): the sample's gain, 1/256. The
 * driver lowers its carriers' total level about 14 units (10.5 dB) for each
 * halving of the volume, so the gain is ((4k + 1.5) / 127)^1.75, k 31 whole:
 * within 1.1 dB of the driver's carrier offsets for volume 16 up
 * (tools/sfx_capture.py --volume). */
static const uint16_t gain_of[32] = {
    0, 1, 3, 5, 8, 11, 15, 20, 25, 30, 36, 42, 49, 56, 64, 72,
    80, 89, 98, 108, 118, 128, 139, 150, 161, 173, 185, 197, 210, 223, 237, 256,
};

struct effect {
    const int8_t *pcm;
    uint32_t bytes, end;
    uint16_t chunk;                 /* bytes a chunk, even; the last may be shorter */
    uint8_t chunks, volume;
};
enum { IDLE, PLAY, FADE };
struct play {
    const struct effect *e;
    uint32_t elapsed;               /* samples since the start, 24.8 */
    uint32_t order;                 /* its start's: the oldest gives way */
    uint8_t phase, segment, fade;
    uint8_t player;                 /* FX_NONE once the player stopped it */
    uint16_t gain;                  /* the player's volume's, 1/256 */
    uint8_t voice;
};

static struct effect effects[FX_IDS];
static struct play plays[FX_PLAYS];
static uint8_t tracked[FX_PLAYERS] = {FX_NONE, FX_NONE, FX_NONE, FX_NONE, FX_NONE, FX_NONE, FX_NONE, FX_NONE};
static uint8_t seen[FX_IDS];
static uint32_t order;
static const int8_t *silence;
uint32_t fx_started;
uint16_t fx_mask;

void fx_effect(uint8_t id, const int8_t *pcm, uint32_t bytes, uint8_t volume, uint32_t end,
               const int8_t *zero)
{
    struct effect *e = &effects[id];
    if (id >= FX_IDS || bytes < 2 || bytes > FX_EFFECT_BYTES) {
        return;
    }
    if (!silence) {
        silence = zero;
    }
    e->bytes = bytes;
    e->end = end;
    e->chunks = (uint8_t)((bytes + EFFECT_LOOP_BYTES - 1) / EFFECT_LOOP_BYTES);
    e->chunk = (uint16_t)(((bytes + e->chunks - 1) / e->chunks + 1) & ~1u);
    e->volume = volume;
    e->pcm = pcm;                   /* last: the field task may be reading */
}

void fx_clear(void)
{
    uint8_t k;
    for (k = 0; k < FX_IDS; ++k) {
        effects[k].pcm = 0;
    }
    for (k = 0; k < FX_PLAYS; ++k) {
        plays[k].phase = IDLE;
    }
    for (k = 0; k < FX_PLAYERS; ++k) {
        tracked[k] = FX_NONE;
    }
}

uint8_t fx_effect_volume(uint32_t level)
{
    uint32_t v = (level * VOLUME_FULL + FM_EFFECT_FULL / 2) / FM_EFFECT_FULL;
    return (uint8_t)(v > VOLUME_FULL ? VOLUME_FULL : v ? v : 1);
}

static struct play *play_of(uint8_t player)
{
    uint8_t k;
    for (k = 0; k < FX_PLAYS; ++k) {
        if (plays[k].phase != IDLE && plays[k].player == player) {
            return &plays[k];
        }
    }
    return 0;
}

/* Player p stopped its effect (or plays another sound): before the driver's
 * end of it the play fades, else its tail plays out. */
static void stop(uint8_t player, uint32_t field)
{
    struct play *p = play_of(player);
    if (!p) {
        return;
    }
    p->player = FX_NONE;
    if (p->phase == PLAY && (p->elapsed >> 8) + 2 * (field >> 8) < p->e->end) {
        p->phase = FADE;
        p->fade = FX_FADE_FIELDS;
    }
}

/* Player p starts effect e: its play from the first sample, on the voice it
 * had, else a free one, else the oldest play's. */
static void start(uint8_t player, const struct effect *e)
{
    struct play *p = play_of(player), *oldest = 0;
    uint8_t k, used = 0;
    if (!p) {
        for (k = 0; k < FX_PLAYS; ++k) {
            if (plays[k].phase == IDLE) {
                if (!p) {
                    p = &plays[k];
                }
            } else {
                used = (uint8_t)(used | 1u << plays[k].voice);
                if (!oldest || plays[k].order < oldest->order) {
                    oldest = &plays[k];
                }
            }
        }
        if (p) {
            for (k = 0; used >> k & 1; ++k) {
            }
            p->voice = k;
        } else {
            p = oldest;
        }
    }
    p->e = e;
    p->player = player;
    p->phase = PLAY;
    p->segment = 0;
    p->elapsed = 0;
    p->order = ++order;
    ++fx_started;
}

/* One field of play p on its voice v. */
static void play_field(struct play *p, struct fm_voice *v, uint32_t field)
{
    const struct effect *e = p->e;
    uint32_t at, volume;
    v->channel = -1;
    v->restart = p->segment == 0;
    v->period = fm_ntsc ? EFFECT_PERIOD_NTSC : EFFECT_PERIOD_PAL;
    if (p->segment) {
        p->elapsed += field;
        at = p->elapsed >> 8;
        /* the latched chunk has played a field: latch the next */
        if (p->segment <= e->chunks && at >= (uint32_t)(p->segment - 1) * e->chunk + (field >> 8)) {
            ++p->segment;
        }
        if (p->segment > e->chunks && at >= e->bytes + (field >> 8)) {
            p->phase = IDLE;
        }
    }
    volume = (e->volume * (uint32_t)p->gain + 128) >> 8;
    if (p->phase == FADE) {
        if (!p->fade) {
            p->phase = IDLE;
        } else {
            volume = volume * p->fade-- / (FX_FADE_FIELDS + 1);
        }
    }
    if (p->phase == IDLE) {
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
        v->volume = 0;
        return;
    }
    if (p->segment == 0) {
        p->segment = 1;
    }
    if (p->segment <= e->chunks) {
        uint32_t off = (uint32_t)(p->segment - 1) * e->chunk;
        v->loop = e->pcm + off;
        v->bytes = (uint16_t)(e->bytes - off < e->chunk ? e->bytes - off : e->chunk);
    } else {
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
    }
    v->volume = (uint8_t)volume;
}

uint16_t fx_field(const struct fx_driver *d, const uint8_t *starts, struct fm_voice *voice)
{
    uint32_t field = fm_ntsc ? EFFECT_FIELD_NTSC : EFFECT_FIELD_PAL;
    uint8_t fresh[FX_IDS], appeared[FX_PLAYERS], k;
    uint16_t mask = 0;
    for (k = 0; k < FX_IDS; ++k) {
        fresh[k] = (uint8_t)(starts[k] - seen[k]);
        seen[k] = starts[k];
    }
    /* A player that now plays another effect, or none, stopped its own; one
     * that newly plays an effect started it. */
    for (k = 0; k < FX_PLAYERS; ++k) {
        uint8_t id = d->active[k] && d->id[k] < FX_IDS && effects[d->id[k]].pcm ? d->id[k] : FX_NONE;
        appeared[k] = id != FX_NONE && id != tracked[k];
        if (tracked[k] != FX_NONE && id != tracked[k]) {
            stop(k, field);
        }
        if (appeared[k] && fresh[id]) {
            --fresh[id];
        }
        tracked[k] = id;
    }
    /* A start left over: a player that stopped and started the same effect
     * within the field (the driver took a start no new player shows). */
    for (k = 0; k < FX_PLAYERS; ++k) {
        if (tracked[k] != FX_NONE && !appeared[k] && fresh[tracked[k]]) {
            --fresh[tracked[k]];
            appeared[k] = 1;
        }
    }
    for (k = 0; k < FX_PLAYERS; ++k) {
        if (appeared[k]) {
            start(k, &effects[tracked[k]]);
        }
    }
    for (k = 0; k < 9; ++k) {
        if (d->owner[k] < FX_PLAYERS && tracked[d->owner[k]] != FX_NONE) {
            mask = (uint16_t)(mask | 1u << k);
        }
    }
    for (k = 0; k < FX_PLAYS; ++k) {
        struct play *p = &plays[k];
        if (p->phase == IDLE) {
            continue;
        }
        if (p->player != FX_NONE) {
            p->gain = gain_of[(d->volume[p->player] & 127) >> 2];
        }
        play_field(p, &voice[p->voice], field);
        if (p->phase != IDLE) {
            mask = (uint16_t)(mask | FM_RESERVE(p->voice));
        }
    }
    fx_mask = mask;
    return mask;
}
