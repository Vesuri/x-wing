/* Prerendered effect player (docs/translator-design.md, Sound: effects): the
 * effects the runtime captured (sfx.c) and fm_effect rendered, played on
 * Paula where the music driver plays them, their OPL channels muted from the
 * FM re-hoster. Plain C, no Amiga headers, as fm_paula.c. */
#ifndef XWING_FX_PLAY_H
#define XWING_FX_PLAY_H

#include <stdint.h>
#include "fm_paula.h"

#define FX_IDS 48                   /* runtime.h RT_SFX_IDS */
#define FX_PLAYERS 8                /* runtime.h RT_SFX_PLAYERS */
#define FX_PLAYS 3                  /* effects at once: the music keeps a Paula voice */
#define FX_FADE_FIELDS 3            /* an early stop's fade */
#define FX_NONE 0xff

/* The music driver's state in one field (runtime.h rt_sfx_read): per player
 * active, its sound id (FX_NONE past FX_IDS), its volume 0-127; per OPL
 * channel the player its voice plays, FX_NONE none. */
struct fx_driver {
    uint8_t active[FX_PLAYERS], id[FX_PLAYERS], volume[FX_PLAYERS], owner[9];
};

/* Effect id's sample: fm_effect's output in Chip (even length, at most
 * FX_EFFECT_BYTES: two Paula loops), played at FM_EFFECT_RATE with Paula
 * volume `volume` at the driver's full volume; `end` the samples to the
 * driver's end of it (its capture's ticks, 512/9 samples each); `silence` 4
 * zero Chip bytes. An id with no sample stays on the FM re-hoster. */
#define FX_EFFECT_BYTES 131068
void fx_effect(uint8_t id, const int8_t *pcm, uint32_t bytes, uint8_t volume, uint32_t end,
               const int8_t *silence);
/* Every sample dropped and every play stopped (before the samples are freed). */
void fx_clear(void);
/* The Paula volume of fm_effect's peak: a full-scale voice is one channel
 * at 0 dB, louder mixes at full volume. */
uint8_t fx_effect_volume(uint32_t level);
/* One field: `d` the driver now, `starts` per id the starts the driver took
 * (runtime.h rt_sfx_starts), wrapping. Fills voice[v] of each Paula voice an
 * effect holds; returns fm_field's mask: the OPL channels of the players
 * whose effect has a sample, and FM_RESERVE of the voices held. */
uint16_t fx_field(const struct fx_driver *d, const uint8_t *starts, struct fm_voice *voice);
/* Diagnostics: plays started; the last field's mask. */
extern uint32_t fx_started;
extern uint16_t fx_mask;

#endif
