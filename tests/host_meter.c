/* Unicorn block hook for tools/cost_meter.py: per translated block (first
 * address and size) its executions, and per taken transfer (a block that does
 * not start where the previous one ended) its source block and target, while
 * meter_on is set. Built on demand by cost_meter.hook_library(); no Unicorn
 * headers (the hook's C signature only), as tests/host_cov.c. */
#include <stdint.h>

#define BLOCKS (1u << 20)          /* open addressing, power of two */
#define EDGES (1u << 21)

uint8_t meter_on;
uint32_t meter_lost;               /* a table filled up: the result is refused */
uint32_t blk_addr[BLOCKS], blk_size[BLOCKS];
uint64_t blk_n[BLOCKS], blk_taken[BLOCKS];
uint32_t edge_from[EDGES], edge_to[EDGES];
uint64_t edge_n[EDGES];

static uint32_t prev = UINT32_MAX;  /* slot of the previous block */

static uint32_t mix(uint64_t k)
{
    k ^= k >> 33;
    k *= 0xff51afd7ed558ccdULL;
    k ^= k >> 33;
    return (uint32_t)k;
}

static uint32_t block_slot(uint32_t address, uint32_t size)
{
    uint32_t i = mix((uint64_t)address << 16 ^ size) & (BLOCKS - 1);
    for (uint32_t probes = 0; probes < BLOCKS; ++probes, i = (i + 1) & (BLOCKS - 1)) {
        if (blk_size[i] == 0) {
            blk_addr[i] = address;
            blk_size[i] = size;
            return i;
        }
        if (blk_addr[i] == address && blk_size[i] == size) {
            return i;
        }
    }
    ++meter_lost;
    return UINT32_MAX;
}

static void edge(uint32_t from, uint32_t to)
{
    uint32_t i = mix((uint64_t)from << 32 | to) & (EDGES - 1);
    for (uint32_t probes = 0; probes < EDGES; ++probes, i = (i + 1) & (EDGES - 1)) {
        if (edge_n[i] == 0) {
            edge_from[i] = from;
            edge_to[i] = to;
            edge_n[i] = 1;
            return;
        }
        if (edge_from[i] == from && edge_to[i] == to) {
            ++edge_n[i];
            return;
        }
    }
    ++meter_lost;
}

void meter_block(void *uc, uint64_t address, uint32_t size, void *user)
{
    (void)uc;
    (void)user;
    if (!meter_on) {
        prev = UINT32_MAX;
        return;
    }
    if (size == 0) {
        size = 2;
    }
    uint32_t s = block_slot((uint32_t)address, size);
    if (s == UINT32_MAX) {
        return;
    }
    if (prev != UINT32_MAX && blk_addr[prev] + blk_size[prev] != (uint32_t)address) {
        ++blk_taken[prev];
        edge(prev, s);
    }
    ++blk_n[s];
    prev = s;
}

void meter_reset(void)
{
    for (uint32_t i = 0; i < BLOCKS; ++i) {
        blk_addr[i] = blk_size[i] = 0;
        blk_n[i] = blk_taken[i] = 0;
    }
    for (uint32_t i = 0; i < EDGES; ++i) {
        edge_from[i] = edge_to[i] = 0;
        edge_n[i] = 0;
    }
    meter_on = 0;
    meter_lost = 0;
    prev = UINT32_MAX;
}
