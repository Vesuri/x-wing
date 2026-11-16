/* Host lockstep resume (runtime.h, docs/translator-design.md Resume): the
 * runtime's state as named fields in a versioned record, so a save made by one
 * image loads into another whose fields agree in name, order and size. The
 * record: "XWRS", the version (16 bits), then per field its name length
 * (8 bits), name, size (32 bits) and bytes; a 0 name length ends it. */
#include "runtime.h"

#ifdef XWING_RESUME

#define SNAPSHOT_VERSION 1

struct cursor {
    uint8_t *out;               /* saving */
    const uint8_t *in;          /* loading */
    uint32_t at, room;
    int32_t index, bad;
};

static uint32_t length(const char *s)
{
    uint32_t n = 0;
    while (s[n]) {
        ++n;
    }
    return n;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static void field(void *ctx, const char *name, volatile void *data, uint32_t bytes)
{
    struct cursor *c = ctx;
    volatile uint8_t *p = data;
    uint32_t n = length(name);
    ++c->index;
    if (c->bad) {
        return;
    }
    if (c->out) {
        if (c->at + 1 + n + 4 + bytes > c->room) {
            c->bad = c->index;
            return;
        }
        c->out[c->at++] = (uint8_t)n;
        for (uint32_t k = 0; k < n; ++k) {
            c->out[c->at++] = (uint8_t)name[k];
        }
        put32(c->out + c->at, bytes);
        c->at += 4;
        for (uint32_t k = 0; k < bytes; ++k) {
            c->out[c->at++] = p[k];
        }
        return;
    }
    if (c->at + 1 + n + 4 > c->room || c->in[c->at] != n) {
        c->bad = c->index;
        return;
    }
    for (uint32_t k = 0; k < n; ++k) {
        if (c->in[c->at + 1 + k] != (uint8_t)name[k]) {
            c->bad = c->index;
            return;
        }
    }
    if (get32(c->in + c->at + 1 + n) != bytes || c->at + 1 + n + 4 + bytes > c->room) {
        c->bad = c->index;
        return;
    }
    c->at += 1 + n + 4;
    for (uint32_t k = 0; k < bytes; ++k) {
        p[k] = c->in[c->at++];
    }
}

static int modules(struct cursor *c, int saving)
{
    int (*const each[])(rt_field_fn *, void *, int) = {
        rt_machine_fields, rt_dos_fields, rt_ems_fields, rt_input_fields,
        rt_ports_fields, rt_video_fields, rt_sfx_fields,
    };
    for (uint32_t k = 0; k < sizeof each / sizeof each[0]; ++k) {
        int why = each[k](field, c, saving);
        if (why) {
            return why;
        }
    }
    return 0;
}

uint32_t rt_snapshot_save(uint8_t *out, uint32_t room)
{
    struct cursor c = {out, 0, 6, room, 0, 0};
    if (room < 7) {
        return 0;
    }
    out[0] = 'X'; out[1] = 'W'; out[2] = 'R'; out[3] = 'S';
    out[4] = SNAPSHOT_VERSION >> 8;
    out[5] = SNAPSHOT_VERSION & 255;
    int why = modules(&c, 1);
    if (why) {
        return (uint32_t)-why;
    }
    if (c.bad || c.at >= room) {
        return 0;
    }
    out[c.at++] = 0;
    return c.at;
}

int32_t rt_snapshot_load(const uint8_t *in, uint32_t bytes)
{
    struct cursor c = {0, in, 6, bytes, 0, 0};
    if (bytes < 7 || in[0] != 'X' || in[1] != 'W' || in[2] != 'R' || in[3] != 'S' ||
            (in[4] << 8 | in[5]) != SNAPSHOT_VERSION) {
        return -1;
    }
    modules(&c, 0);
    if (!c.bad && (c.at >= bytes || in[c.at] != 0)) {
        c.bad = c.index + 1;    /* a field this runtime does not have */
    }
    return c.bad;
}

#endif
