/* Unicorn block hook for tests/host_resume.py: the translated blocks a host run
 * executes, each recorded once (its first address and size), so a save knows
 * what ran before it at the cost of a C call per block. Built on demand by
 * host_resume.coverage(); no Unicorn headers (the hook's C signature only). */
#include <stdint.h>

#define UNITS (1u << 23)            /* 2-byte units from cov_base: 16 MiB */
#define CAP (1u << 21)

uint8_t cov_seen[UNITS];
uint64_t cov_base;
uint8_t cov_on;
uint32_t cov_n, cov_lost;
uint32_t cov_addr[CAP];
uint32_t cov_size[CAP];

void cov_block(void *uc, uint64_t address, uint32_t size, void *user)
{
    uint64_t k = (address - cov_base) >> 1;
    (void)uc;
    (void)user;
    if (!cov_on || k >= UNITS || cov_seen[k]) {
        return;
    }
    cov_seen[k] = 1;
    if (cov_n < CAP) {
        cov_addr[cov_n] = (uint32_t)address;
        cov_size[cov_n++] = size;
    } else {
        ++cov_lost;
    }
}
