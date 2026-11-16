#include <proto/exec.h>
#include <proto/dos.h>
#include <exec/memory.h>
#include <dos/dos.h>
#include <hardware/dmabits.h>
extern "C" {
#include "runtime.h"
#include "fm_paula.h"
#include "fx_play.h"
#include "amiga_platform.h"
}
#include "Audio.h"
#include "AmigaHardware.h"

// AdLib FM on Paula and the prerendered effects, copied from Secret Weapons of
// the Luftwaffe's Audio.cpp (commit pinned in manifest/references.tsv)
// without its TFH samples. Voice v plays on Paula channel v: 0 and 3 left, 1
// and 2 right; an effect takes the voice fx_play gives it.
#define POOL_BYTES (FM_POOL_BYTES)
#define SILENCE_BYTES 4
#define AUDIO_DMA (DMAF_AUD0 | DMAF_AUD1 | DMAF_AUD2 | DMAF_AUD3)
#define PERIOD_FLOOR 124
// A restart's DMA-off window: Paula goes idle only at the end of a period in
// its second-byte state, up to two outgoing periods (AUDxPER does not cut a
// countdown short; Revs, Rescue on Fractalus, Vette), capped; a loop
// restarted late still plays valid samples (fm_paula.c keeps the last
// field's loops).
#define RESTART_LINES_MAX 16

// AUDxLC, LEN, PER, VOL, DAT, 16 bytes a channel
struct Channel {
    const int8_t* volatile lc;
    volatile uint16_t len, per, vol, dat;
    uint16_t pad[2];
};
#define PAULA ((volatile Channel*)aud0ptrPointer)

static int8_t* effectChip[RT_SFX_IDS];
static uint32_t effectBytes[RT_SFX_IDS];
static uint8_t effectVolume[RT_SFX_IDS];
static uint32_t effectKey = 0;
static volatile bool effects = false;
static int8_t* pool = 0;
static const int8_t* silence = 0;
static struct fm_voice pending[FM_VOICES];
static volatile bool fresh = false;
static volatile bool muted = false;
static bool running = false;
static const int8_t* shownLoop[FM_VOICES];
static uint16_t shownBytes[FM_VOICES], shownPeriod[FM_VOICES];

extern "C" {
volatile uint32_t amiga_audio_restarts = 0;   // channel restarts (diagnostics)
volatile uint32_t amiga_audio_effect_fields = 0;  // fields the prerender took (diagnostics)
volatile uint32_t amiga_audio_effect_bytes = 0;   // its Chip bytes (diagnostics)
volatile uint8_t amiga_audio_effect_cached = 0;   // 1 loaded from the cache, 2 written to it (diagnostics)
}

static_assert(sizeof(struct rt_sfx_write) == sizeof(struct fm_write), "capture and fm_effect write layouts");
static_assert(RT_SFX_IDS == FX_IDS && RT_SFX_PLAYERS == FX_PLAYERS, "runtime and fx_play sizes");

bool Audio::begin()
{
    pool = (int8_t*)AllocMem(POOL_BYTES + SILENCE_BYTES, MEMF_CHIP | MEMF_CLEAR);
    if (!pool) return false;
    silence = pool + POOL_BYTES;
    fm_init(pool, POOL_BYTES);
    return true;
}

// A one-shot effect the capture holds is prerendered; the loops (no end in the
// capture) stay on the FM re-hoster.
static bool wanted(uint8_t id)
{
    return rt_sfx_writes[id] && rt_sfx_ticks[id];
}

// The effect cache: the rendered samples in the game drawer, keyed by
// everything they come from (fm_effect's version, PAL/NTSC, the wanted ids,
// the capture). Big-endian: "XWFX", version, key, count; count entries (id,
// volume, 2 bytes 0, bytes); the samples in that order.
#define CACHE_NAME "sfx.cache"
#define CACHE_MAGIC 0x58574658u     // "XWFX"
struct CacheEntry {
    uint8_t id, volume, pad[2];
    uint32_t bytes;
};

static uint32_t fnv(uint32_t h, const void* data, uint32_t n)
{
    const uint8_t* p = (const uint8_t*)data;
    while (n--) h = (h ^ *p++) * 16777619u;
    return h;
}

static uint32_t effectsKey()
{
    uint32_t h = 2166136261u, v = FM_EFFECT_VERSION;
    h = fnv(h, &v, sizeof v);
    h = fnv(h, &fm_ntsc, 1);
    h = fnv(h, rt_sfx_opl, 256);
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        uint8_t w = wanted(id);
        h = fnv(h, &w, 1);
        if (!w) continue;
        h = fnv(h, &rt_sfx_writes[id], sizeof rt_sfx_writes[id]);
        h = fnv(h, &rt_sfx_ticks[id], sizeof rt_sfx_ticks[id]);
        h = fnv(h, &rt_sfx_capture[rt_sfx_first[id]], rt_sfx_writes[id] * sizeof(struct rt_sfx_write));
    }
    return h | 1;   // 0: none loaded
}

// Stops every play first: the field task may be reading the samples.
static void freeEffects()
{
    Disable();
    effects = false;
    fx_clear();
    Enable();
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        if (effectChip[id]) FreeMem(effectChip[id], effectBytes[id]);
        effectChip[id] = 0;
    }
    effectKey = 0;
    amiga_audio_effect_bytes = 0;
}

static void registerEffects(uint32_t key)
{
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        if (!effectChip[id]) continue;
        amiga_audio_effect_bytes += effectBytes[id];
        fx_effect(id, effectChip[id], effectBytes[id], effectVolume[id], rt_sfx_ticks[id] * 512u / 9u, silence);
    }
    effectKey = key;
    effects = true;
}

// The cache's samples straight into Chip, in one I/O window; false (nothing
// kept) unless every wanted id comes back whole under this key.
static bool loadCache(uint32_t key)
{
    uint32_t head[4], count = 0;
    struct CacheEntry entry[RT_SFX_IDS];
    bool ok = false;
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) count += wanted(id);
    amiga_io_begin();
    BPTR f = Open((CONST_STRPTR)CACHE_NAME, MODE_OLDFILE);
    if (f) {
        ok = Read(f, head, sizeof head) == sizeof head && head[0] == CACHE_MAGIC &&
             head[1] == FM_EFFECT_VERSION && head[2] == key && head[3] == count &&
             Read(f, entry, count * sizeof entry[0]) == (LONG)(count * sizeof entry[0]);
        for (uint32_t k = 0; ok && k < count; ++k) {
            const struct CacheEntry& e = entry[k];
            ok = e.id < RT_SFX_IDS && !effectChip[e.id] && wanted(e.id) && e.bytes >= 2 &&
                 e.bytes <= FX_EFFECT_BYTES && !(e.bytes & 1) &&
                 (effectChip[e.id] = (int8_t*)AllocMem(e.bytes, MEMF_CHIP)) != 0;
            if (!ok) break;
            effectBytes[e.id] = e.bytes;
            effectVolume[e.id] = e.volume;
            ok = Read(f, effectChip[e.id], e.bytes) == (LONG)e.bytes;
        }
        Close(f);
    }
    amiga_io_end();
    if (!ok) freeEffects();
    return ok;
}

// The rendered samples to the cache in one I/O window and one Write, the file
// made as the game's are: MODE_NEWFILE, Close, MODE_OLDFILE. Without memory
// for the file's image nothing is written; a failed write leaves a file the
// next load refuses.
static void saveCache(uint32_t key)
{
    uint32_t head[4] = {CACHE_MAGIC, FM_EFFECT_VERSION, key, 0}, total = sizeof head;
    struct CacheEntry entry[RT_SFX_IDS];
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        if (!effectChip[id]) continue;
        struct CacheEntry& e = entry[head[3]++];
        e.id = id;
        e.volume = effectVolume[id];
        e.pad[0] = e.pad[1] = 0;
        e.bytes = effectBytes[id];
        total += sizeof e + e.bytes;
    }
    amiga_io_begin();
    uint8_t* image = (uint8_t*)AllocMem(total, MEMF_ANY);
    amiga_io_end();
    if (!image) return;
    uint8_t* p = image;
    CopyMem(head, p, sizeof head);
    p += sizeof head;
    CopyMem(entry, p, head[3] * sizeof entry[0]);
    p += head[3] * sizeof entry[0];
    for (uint32_t k = 0; k < head[3]; ++k) {
        CopyMem(effectChip[entry[k].id], p, entry[k].bytes);
        p += entry[k].bytes;
    }
    amiga_io_begin();
    BPTR f = Open((CONST_STRPTR)CACHE_NAME, MODE_NEWFILE);
    if (f) {
        Close(f);
        f = Open((CONST_STRPTR)CACHE_NAME, MODE_OLDFILE);
    }
    if (f) {
        if (Write(f, image, total) == (LONG)total) amiga_audio_effect_cached = 2;
        Close(f);
    }
    FreeMem(image, total);
    amiga_io_end();
}

// Prerendered effects, from the runtime's capture at FLIGHT's sound loader
// (plat_sfx_captured, game time paused): kept when the samples loaded hold
// this capture's, else from the cache when it holds them, else each id
// through fm_effect in Fast, then its own Chip block, and the cache written.
// Every wanted id or none: all render or none is kept (those effects then
// stay on FM).
void Audio::loadEffects()
{
    if (!pool) return;
    uint32_t start = amiga_frames, key = effectsKey();
    if (effects && key == effectKey) return;
    freeEffects();
    if (loadCache(key)) {
        amiga_audio_effect_cached = 1;
        registerEffects(key);
        amiga_audio_effect_fields = amiga_frames - start;
        return;
    }
    amiga_io_begin();
    int16_t* render = (int16_t*)AllocMem(FX_EFFECT_BYTES * 2, MEMF_ANY);
    amiga_io_end();
    if (!render) return;
    bool ok = true;
    for (uint8_t id = 0; ok && id < RT_SFX_IDS; ++id) {
        if (!wanted(id)) continue;
        uint32_t level = 0;
        uint32_t n = fm_effect(rt_sfx_opl, (const struct fm_write*)&rt_sfx_capture[rt_sfx_first[id]],
                               rt_sfx_writes[id], render, FX_EFFECT_BYTES, &level);
        int8_t* pcm = (int8_t*)render;
        uint32_t bytes = n < 2 ? 2 : (n + 1) & ~1u;
        for (uint32_t k = n; k < bytes; ++k) pcm[k] = 0;
        amiga_io_begin();
        int8_t* chip = (int8_t*)AllocMem(bytes, MEMF_CHIP);
        amiga_io_end();
        if (!chip) {
            ok = false;
            break;
        }
        CopyMem(pcm, chip, bytes);
        effectChip[id] = chip;
        effectBytes[id] = bytes;
        effectVolume[id] = fx_effect_volume(level);
    }
    amiga_io_begin();
    FreeMem(render, FX_EFFECT_BYTES * 2);
    amiga_io_end();
    if (!ok) {
        freeEffects();
        return;
    }
    registerEffects(key);
    saveCache(key);
    amiga_audio_effect_fields = amiga_frames - start;
}

extern "C" int amiga_audio_effect_wanted(uint8_t)
{
    return pool != 0;
}

extern "C" void amiga_audio_effects(void)
{
    Audio::loadEffects();
}

void Audio::end()
{
    freeEffects();
    if (pool) FreeMem(pool, POOL_BYTES + SILENCE_BYTES);
    pool = 0;
}

void Audio::takeOver()
{
    if (!pool) return;
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        PAULA[c].vol = 0;
        PAULA[c].lc = silence;
        PAULA[c].len = SILENCE_BYTES / 2;
        PAULA[c].per = PERIOD_FLOOR;
        shownLoop[c] = silence;
        shownBytes[c] = SILENCE_BYTES;
        shownPeriod[c] = PERIOD_FLOOR;
    }
    AmigaHardware::setDMAChannels(AUDIO_DMA, true);
    running = true;
}

void Audio::handBack()
{
    running = false;
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        PAULA[c].vol = 0;
    }
    AmigaHardware::setDMAChannels(AUDIO_DMA, false);
}

void Audio::service()
{
    if (!running) return;
    // The OPL state between two ticks' writes (Secret Weapons of the Luftwaffe's docs/irq-plan.md I5): the
    // field task runs at interrupt level, the tick masked for the copy.
    typedef uint32_t __attribute__((may_alias)) Long;
    static uint8_t opl[256] __attribute__((aligned(4)));
    static uint8_t keyon[9], starts[RT_SFX_IDS] __attribute__((aligned(4)));
    static struct fx_driver driver;
    Disable();
    for (uint16_t k = 0; k < 256; k += 4) *(Long*)(opl + k) = *(const Long*)(rt_opl + k);
    for (uint16_t k = 0; k < 9; ++k) keyon[k] = rt_opl_keyon[k];
    for (uint16_t k = 0; k < RT_SFX_IDS; k += 4) *(Long*)(starts + k) = *(const Long*)(rt_sfx_starts + k);
    bool play = effects && rt_sfx_read(driver.active, driver.id, driver.volume, driver.owner);
    Enable();
    // The effects first: they take their OPL channels and Paula voices.
    struct fm_voice v[FM_VOICES], t[FM_VOICES];
    uint16_t mask = play ? fx_field(&driver, starts, t) : 0;
    fm_field(opl, keyon, mask, v);
    for (uint16_t k = 0; k < FM_VOICES; ++k) {
        if (mask & FM_RESERVE(k)) v[k] = t[k];
    }
    Disable();
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        // a restart the vertical blank has not staged yet still happens
        if (fresh && pending[c].restart) v[c].restart = 1;
        pending[c] = v[c];
    }
    fresh = true;
    Enable();
}

static void waitLines(uint16_t lines)
{
    uint16_t line = *vhposrPointer >> 8;
    while (lines) {
        uint16_t now = *vhposrPointer >> 8;
        if (now != line) {
            line = now;
            --lines;
        }
    }
}

void Audio::verticalBlank()
{
    if (!running || !fresh) return;
    fresh = false;
    uint16_t restart = 0, outgoing = 0;
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        const struct fm_voice& v = pending[c];
        if (muted || !v.loop) {
            PAULA[c].vol = 0;   // silence: the loop plays on, unheard
            continue;
        }
        // A silent attack still starts its PCM and latches its repeat segment.
        if (v.restart) {
            restart |= DMAF_AUD0 << c;
            if (shownPeriod[c] > outgoing) outgoing = shownPeriod[c];
            PAULA[c].vol = 0;
            continue;
        }
        if (v.loop != shownLoop[c] || v.bytes != shownBytes[c]) {
            PAULA[c].lc = v.loop;   // latched at the running loop's end
            PAULA[c].len = v.bytes / 2;
        }
        PAULA[c].per = v.period;
        PAULA[c].vol = v.volume;
        shownLoop[c] = v.loop;
        shownBytes[c] = v.bytes;
        shownPeriod[c] = v.period;
    }
    if (!restart) return;
    *dmaconPointer = restart;
    uint16_t lines = (2u * outgoing + 226) / 227 + 2;
    waitLines(lines < RESTART_LINES_MAX ? lines : RESTART_LINES_MAX);
    for (uint16_t c = 0; c < FM_VOICES; ++c) {
        if (!(restart & (DMAF_AUD0 << c))) continue;
        const struct fm_voice& v = pending[c];
        PAULA[c].lc = v.loop;
        PAULA[c].len = v.bytes / 2;
        PAULA[c].per = v.period;
        PAULA[c].vol = v.volume;
        shownLoop[c] = v.loop;
        shownBytes[c] = v.bytes;
        shownPeriod[c] = v.period;
        ++amiga_audio_restarts;
    }
    *dmaconPointer = DMAF_SETCLR | restart;
}

void Audio::mute(bool on)
{
    muted = on;
    if (on) {
        for (uint16_t c = 0; c < FM_VOICES; ++c) {
            PAULA[c].vol = 0;
        }
    } else {
        fresh = true;   // the next vertical blank restores the volumes
    }
}

extern "C" void amiga_audio_service(void)
{
    Audio::service();
}
