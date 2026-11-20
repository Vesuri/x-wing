/* INT 67h EMS 4.0 as the reference machine answers it
 * (docs/external-surface.md). Copied from Secret Weapons of the Luftwaffe's
 * (manifest/references.tsv) and adapted: X-Wing's machine reports 932 pages,
 * of which the store backs RT_EMS_STORE (runtime.h). The lazy frame pages are
 * Wing Commander 2's (docs/port-plan.md, its bfaebe3 and c31004f). */
#include "runtime.h"

#define EMS_FRAME 0xe000
#define EMS_HANDLES 16
#define EMS_PHYS 4

/* Store pages live after the state block (RT_EMS_BYTES), reversed (store()):
 * they are the truth while no frame page holds a copy. A frame page holds its
 * mapped page's bytes only while it is live (EMS model,
 * docs/translator-design.md): a map leaves the new page in the store and copies
 * nothing in; it writes a live page back. An ES access, and a DS access in
 * listed code (annotations/ems-ds.csv), within frame pages whose pages have no
 * live copy and share one store displacement runs on the store itself (guard:
 * the translator's guards rt_ems_es and rt_ems_ds); any other access copies the
 * pages in first: the runtime's own accessors (rt_ems_touch, runtime.h), a
 * guarded access across other pages or with DF set, and DS or SS while they
 * address the frame outside listed code (their accesses are not guarded:
 * rt_ems_segments, rt_ems_ds_left). DOSBox-X maps a page at two frame pages as
 * one memory. Here the store is that memory until a copy is made; copies of one
 * page are equal to the store when the second is made, merged against it at the
 * next map call (reconcile). A byte written differently through two of them is
 * a stop; a read through one of a byte written through another before that call
 * is not modelled (checked in tests/host_run.py, ems_alias; the guard's routing
 * in ems_guard_problems). Handles take store pages as DOSBox-X's
 * MEM_AllocatePages does, so after a release a handle's pages can be split
 * across free runs; a release leaves the frame mapped (as Wing Commander 2's
 * tests/test_ems.py checks for its copy). */
static uint16_t ems_free = RT_EMS_PAGES;
static uint16_t pages[EMS_HANDLES];   /* 0: free; handle 0 is the operating system's */
static uint16_t page_of[EMS_HANDLES][RT_EMS_STORE];
static uint8_t used[RT_EMS_PAGES];
uint16_t rt_ems_mapped[EMS_PHYS];     /* store page + 1, 0: none */
uint8_t rt_ems_live[EMS_PHYS];        /* the frame page holds the mapped page's bytes */
int32_t rt_ems_fast[EMS_PHYS];        /* rt_entry.s rt_ems_es: displacement, or 1 (refresh) */
/* rt_entry.s EMS_GUARD's one-entry caches (ES, DS): the segment (0: empty), the
 * lowest offset and the end of the offsets within the frame page the last
 * displaced access lay in, and the base register's value for them. Emptied by every
 * change of rt_ems_fast (refresh). */
uint32_t rt_ems_cache_es[3], rt_ems_cache_ds[3];

/* Separate and not inlined: host_run.py's sabotage "ems-cache" returns at once. */
void __attribute__((noinline)) rt_ems_cache_clear(void)
{
    rt_ems_cache_es[0] = 0;
    rt_ems_cache_ds[0] = 0;
}

/* IRQ0's handler (machine.c rt_irq0_enter, rt_irq0_leave) may fill the caches
 * between an interrupted guard's reads of them (production delivers it at the
 * CIA tick); it maps no EMS page (rt_int67 stops), so the caches it found are
 * still right when it leaves, and are put back. Separate and not inlined:
 * host_run.py's sabotage "ems-cache-irq" returns at once from the restore. */
static uint32_t cache_held[6];

void rt_ems_cache_hold(void)
{
    for (int i = 0; i < 3; ++i) {
        cache_held[i] = rt_ems_cache_es[i];
        cache_held[3 + i] = rt_ems_cache_ds[i];
    }
}

void __attribute__((noinline)) rt_ems_cache_restore(void)
{
    for (int i = 0; i < 3; ++i) {
        rt_ems_cache_es[i] = cache_held[i];
        rt_ems_cache_ds[i] = cache_held[3 + i];
    }
}
#define mapped rt_ems_mapped
#define live rt_ems_live

/* Store slot s at RT_EMS_STORE - s pages after the state block: reversed, as
 * guest memory is, so consecutive store pages mapped at consecutive frame
 * pages lie as those frame pages do and share one displacement (refresh). */
static uint8_t *store(uint16_t slot)
{
    return rt_guest + 1 + RT_STATE_BYTES + (uint32_t)(RT_EMS_STORE - slot) * RT_EMS_PAGE;
}

/* DOSBox-X BestMatch(1): the first free run of one page, else the first of
 * the shortest; RT_EMS_PAGES when none. *largest: the longest run. */
static uint16_t free_run(uint16_t *largest)
{
    uint16_t at = RT_EMS_PAGES, best = 0xffff, k = 0;
    *largest = 0;
    while (k < RT_EMS_PAGES) {
        uint16_t first = k;
        while (k < RT_EMS_PAGES && !used[k]) {
            ++k;
        }
        uint16_t n = k - first;
        if (n > *largest) {
            *largest = n;
        }
        if (n && n < best) {
            best = n;
            at = first;
        }
        k += k < RT_EMS_PAGES;
    }
    return at;
}

/* (rt_span itself: the frame is reached here without rt_ems_touch) */
static uint8_t *frame_page(uint8_t phys)
{
    return rt_guest - (lin(EMS_FRAME, 0) + (uint32_t)(phys + 1) * RT_EMS_PAGE) + 1;
}

/* One page. Frame pages and the store share their address mod 4 (both are
 * rt_guest + 1 mod 4), so after the head bytes both run long-aligned. */
static void copy(uint8_t *d, const uint8_t *s)
{
    uint32_t n = RT_EMS_PAGE;
    while (n && ((uintptr_t)d & 3)) {
        *d++ = *s++;
        --n;
    }
    if (n >= 32) {
        uint16_t k = n / 32 - 1;    /* dbra count, at most 511 */
        __asm__ volatile(
            "1:\tmove.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "dbra %2,1b"
            : "+a"(s), "+a"(d), "+d"(k) : : "memory");
    }
    for (n &= 31; n; --n) {
        *d++ = *s++;
    }
}

/* The frame pages holding live copies of slot; their number. */
static uint8_t copies(uint16_t slot, uint8_t *at)
{
    uint8_t n = 0;
    for (uint8_t k = 0; k < EMS_PHYS; ++k) {
        if (slot && mapped[k] == slot && live[k]) {
            at[n++] = k;
        }
    }
    return n;
}

/* The store page takes what its live copies hold: one copy's bytes; for
 * several, where one differs from the store, that copy's byte (they equalled
 * the store when the second was made). The copies stay live and equal. */
static void merge(uint16_t slot)
{
    uint8_t at[EMS_PHYS], n = copies(slot, at);
    if (n == 1) {
        copy(store(slot), frame_page(at[0]));
    }
    if (n < 2) {
        return;
    }
    uint8_t *b = store(slot), *f[EMS_PHYS];
    for (uint8_t c = 0; c < n; ++c) {
        f[c] = frame_page(at[c]);
    }
    for (uint32_t j = 0; j < RT_EMS_PAGE; ++j) {
        uint8_t v = b[j];
        for (uint8_t c = 0; c < n; ++c) {
            uint8_t x = f[c][j];
            if (x != b[j]) {
                if (v != b[j] && v != x) {
                    /* rt_span is reversed: guest offset in the page */
                    rt_stop("EMS page written differently through two frame pages (page, offset)",
                            slot - 1, RT_EMS_PAGE - 1 - j);
                }
                v = x;
            }
        }
        if (v != b[j]) {
            b[j] = v;
            for (uint8_t c = 0; c < n; ++c) {
                f[c][j] = v;
            }
        }
    }
}

/* Every page with two or more live copies is merged (at each map call). */
static void reconcile(void)
{
    for (uint8_t p = 0; p < EMS_PHYS; ++p) {
        uint8_t at[EMS_PHYS];
        if (live[p] && copies(mapped[p], at) > 1 && at[0] == p) {
            merge(mapped[p]);
        }
    }
}

/* rt_ems_fast after a change of mapped or live: an ES access within frame page
 * k adds 0 to its base (live or unmapped: the frame), the store displacement (a
 * page with no live copy), or takes the C path (1: a live alias copies it in). */
static void refresh(void)
{
    rt_ems_cache_clear();
    for (uint8_t k = 0; k < EMS_PHYS; ++k) {
        uint8_t at[EMS_PHYS];
        rt_ems_fast[k] = live[k] || !mapped[k] ? 0
                         : copies(mapped[k], at) ? 1
                         : (int32_t)(store(mapped[k]) - frame_page(k));
    }
}

/* The frame page shows its mapped page's bytes from now on: the store,
 * brought up to date from the page's live copies first. */
static void expose(uint8_t phys)
{
    if (live[phys] || !mapped[phys]) {
        return;
    }
    merge(mapped[phys]);
    rt_wrote(lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE, RT_EMS_PAGE);
    copy(frame_page(phys), store(mapped[phys]));
    live[phys] = 1;
    refresh();
}

static int addresses(uint16_t seg, uint8_t phys)
{
    uint32_t first = lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE;
    return lin(seg, 0) <= first + RT_EMS_PAGE - 1 && first <= lin(seg, 0xffff);
}

/* Frame page phys shows store slot (0: unmapped). */
static uint8_t map_slot(uint8_t phys, uint16_t slot)
{
    reconcile();
    if (slot && mapped[phys] == slot) {
        return 0;   /* the copies are merged: the frame page shows the page already */
    }
    uint16_t old = mapped[phys];
    if (old) {
        if (!slot) {
            expose(phys);   /* an unmapped frame page keeps the bytes it showed */
        }
        if (live[phys]) {
            uint8_t at[EMS_PHYS];
            if (copies(old, at) == 1) {
                copy(store(old), frame_page(phys));
            }       /* else merged by reconcile: the store holds them */
        }
    }
    live[phys] = 0;
    mapped[phys] = slot;
    refresh();
    if (slot && (addresses(G_DS, phys) || addresses(G_SS, phys))) {
        expose(phys);
    }
    return 0;
}

static uint8_t map(uint8_t phys, uint16_t page, uint16_t handle)
{
    if (phys >= EMS_PHYS) {
        reconcile();
        return 0x8b;
    }
    if (page != 0xffff && (handle == 0 || handle >= EMS_HANDLES || !pages[handle])) {
        reconcile();
        return 0x83;
    }
    if (page != 0xffff && page >= pages[handle]) {
        reconcile();
        return 0x8a;
    }
    return map_slot(phys, page == 0xffff ? 0 : page_of[handle][page] + 1);
}

/* The runtime is about to touch guest a..a+n-1: the frame pages it meets are
 * copied in (none when it misses the frame: a guarded ES access below or above
 * it, n 0). */
void rt_ems_touch(uint32_t a, uint32_t n)
{
    uint32_t first = lin(EMS_FRAME, 0), last = first + EMS_PHYS * RT_EMS_PAGE - 1;
    if (!n || a > last || a + n - 1 < first) {
        return;
    }
    uint32_t lo = a < first ? first : a, hi = a + n - 1 > last ? last : a + n - 1;
    for (uint32_t p = (lo - first) / RT_EMS_PAGE; p <= (hi - first) / RT_EMS_PAGE; ++p) {
        expose((uint8_t)p);
    }
}

/* Translator guard (lower.py ems_guard): the segment >= D001h before an access
 * of `bytes` at segment:offset; bytes 0: the whole window (a string with DF
 * set). Returns the displacement the access adds to the segment's base
 * (rt_entry.s rt_ems_es, rt_ems_ds): an access that lies within one frame page
 * whose mapped page has no live copy goes to the store page itself, without a
 * copy; anything else has its frame pages copied in and runs on the frame (0). */
static int32_t guard(uint16_t seg, uint32_t offset, uint32_t bytes)
{
    uint32_t base = lin(seg, 0), first = lin(EMS_FRAME, 0);
    offset &= 0xffff;
    if (bytes && offset + bytes <= 0x10000) {
        uint32_t a = base + offset, z = a + bytes - 1;
        if (a >= first && z < first + EMS_PHYS * RT_EMS_PAGE) {
            /* frame pages whose pages have no live copy and lie as their store
             * pages do (one displacement: consecutive slots, store()) */
            uint8_t k = (uint8_t)((a - first) / RT_EMS_PAGE), last = (uint8_t)((z - first) / RT_EMS_PAGE);
            int32_t d = rt_ems_fast[k];
            int same = mapped[k] && !(d & 1);
            for (uint8_t p = k + 1; same && p <= last; ++p) {
                same = mapped[p] && rt_ems_fast[p] == d;
            }
            if (same) {
                return d;
            }
        }
    }
    if (!bytes) {
        rt_ems_touch(base, 0x10000);
    } else if (offset + bytes > 0x10000) {        /* the word at FFFFh wraps to 0 */
        rt_ems_touch(base + offset, 0x10000 - offset);
        rt_ems_touch(base, offset + bytes - 0x10000);
    } else {
        rt_ems_touch(base + offset, bytes);
    }
    return 0;
}

int32_t rt_ems_es_c(uint32_t offset, uint32_t bytes)
{
    return guard(G_ES, offset, bytes);
}

/* DS in listed code (annotations/ems-ds.csv), whose DS loads copy nothing in */
int32_t rt_ems_ds_c(uint32_t offset, uint32_t bytes)
{
    return guard(G_DS, offset, bytes);
}

/* Listed code left with DS at D001h or above (lower.py ems_exit): the pages
 * its window meets are copied in, as at an unlisted load (a counted fallback). */
uint32_t rt_ems_ds_exits;

void rt_ems_ds_left(void)
{
    ++rt_ems_ds_exits;
    rt_ems_segments();
}

/* DS or SS may address the frame (a load of D001h or above, a service, an
 * interrupt's return): their pages are live while they do. */
void rt_ems_segments(void)
{
    for (uint8_t k = 0; k < EMS_PHYS; ++k) {
        if (addresses(G_DS, k) || addresses(G_SS, k)) {
            expose(k);
        }
    }
}

void rt_int67(void)
{
    if (rt_irq0_running) {
        /* A map there would change the pages of a DS restored without a check
         * (annotations/ems-ds.csv restore), so rt_irq0_leave copies nothing. */
        rt_stop("EMS call at interrupt level (function)", AH(rt_r.ax), 0);
    }
    switch (AH(rt_r.ax)) {
    case 0x40:  /* status */
        break;
    case 0x41:  /* page frame segment */
        rt_r.bx = EMS_FRAME;
        break;
    case 0x42:  /* free pages, and in DX the longest free run (DOSBox-X's "total") */
        rt_r.bx = ems_free;
        free_run(&rt_r.dx);
        break;
    case 0x43: {  /* allocate BX pages; 16 handles (DOSBox-X 200, the game opens 3) */
        uint16_t h = 1, n = rt_r.bx, largest;
        while (h < EMS_HANDLES && pages[h]) {
            ++h;
        }
        if (!n || n > ems_free || h == EMS_HANDLES) {
            SET_AH(rt_r.ax, !n ? 0x89 : n > ems_free ? 0x88 : 0x85);
            return;
        }
        if (n > RT_EMS_STORE) {
            rt_stop("EMS allocation larger than the store (pages, store)", n, RT_EMS_STORE);
        }
        for (uint16_t p = 0; p < n;) {
            for (uint16_t k = free_run(&largest); p < n && k < RT_EMS_PAGES && !used[k]; ++k) {
                if (k >= RT_EMS_STORE) {
                    rt_stop("EMS page outside the store (page, store)", k, RT_EMS_STORE);
                }
                used[k] = 1;
                page_of[h][p++] = k;
            }
        }
        pages[h] = n;
        ems_free -= n;
        rt_r.dx = h;
        break;
    }
    case 0x44:  /* map logical page BX of handle DX at frame page AL */
        SET_AH(rt_r.ax, map(AL(rt_r.ax), rt_r.bx, rt_r.dx));
        return;
    case 0x4c:  /* pages of handle DX */
        if (rt_r.dx >= EMS_HANDLES || !pages[rt_r.dx]) {
            SET_AH(rt_r.ax, 0x83);
            return;
        }
        rt_r.bx = pages[rt_r.dx];
        break;
    case 0x45:  /* release handle DX; its frame pages stay mapped */
        if (rt_r.dx == 0) {     /* DOSBox-X frees the OS's pages, outside the store */
            rt_unsupported("EMS release of handle 0", 0x67, 0, 0);
            return;
        }
        if (rt_r.dx >= EMS_HANDLES || !pages[rt_r.dx]) {
            SET_AH(rt_r.ax, 0x83);
            return;
        }
        for (uint16_t p = 0; p < pages[rt_r.dx]; ++p) {
            used[page_of[rt_r.dx][p]] = 0;
        }
        ems_free += pages[rt_r.dx];
        pages[rt_r.dx] = 0;
        break;
    default:
        rt_unsupported("EMS function", 0x67, 0, 0);
    }
    SET_AH(rt_r.ax, 0);
}

#ifdef XWING_RESUME
int rt_ems_fields(rt_field_fn *f, void *ctx, int saving)
{
    (void)saving;
    f(ctx, "ems.free", &ems_free, sizeof ems_free);
    f(ctx, "ems.pages", pages, sizeof pages);
    f(ctx, "ems.page_of", page_of, sizeof page_of);
    f(ctx, "ems.used", used, sizeof used);
    f(ctx, "ems.mapped", rt_ems_mapped, sizeof rt_ems_mapped);
    f(ctx, "ems.live", rt_ems_live, sizeof rt_ems_live);
    f(ctx, "ems.fast", rt_ems_fast, sizeof rt_ems_fast);
    f(ctx, "ems.ds_exits", &rt_ems_ds_exits, sizeof rt_ems_ds_exits);
    return 0;
}
#endif
