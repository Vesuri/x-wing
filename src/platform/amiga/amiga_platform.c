/* Platform services for the runtime on AmigaOS: the game's files through
 * dos.library (each call in an I/O window of the takeover, XWing.cpp), the
 * PIT on a CIA-B timer, the VGA input status from the beam, the diagnostic
 * key script and the run of the translated program on its own native stack.
 * Game files are read from the current directory, the guest's C:\XWING (the
 * game's own data files, supplied by the user; from Workbench, the icon's
 * drawer). Copied from Secret Weapons of the Luftwaffe's
 * (manifest/references.tsv) and adapted. */
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/cia.h>
#include <proto/icon.h>
#include <exec/memory.h>
#include <dos/dos.h>
#include <workbench/startup.h>
#include <hardware/cia.h>
#include <hardware/intbits.h>
#include <resources/cia.h>
#include "runtime.h"
#include "platform.h"
#include "amiga_platform.h"
#include "FileDate.h"
#ifdef XWING_REPLAY
#include "replay_clocks.h"
uint8_t replay_vga_status(void);
#endif

struct DosLibrary *DOSBase = 0;
struct Library *IconBase = 0;

#define MAX_FILES 16
#define PATH_BYTES 128
#define GUEST_STACK_BYTES 0x10000

static BPTR files[MAX_FILES];
static char file_paths[MAX_FILES][PATH_BYTES];
static uint8_t file_stamped[MAX_FILES], file_modified[MAX_FILES];
static struct DateStamp file_stamps[MAX_FILES];

int32_t amiga_guest_call(void *stack_top);
static void key_script_step(void);
static uint8_t *guest_block = 0;
static uint8_t *guest_stack = 0;

void *plat_alloc(uint32_t bytes)
{
    amiga_io_begin();
    void *p = AllocVec(bytes, MEMF_ANY);
    amiga_io_end();
    return p;
}

void plat_free(void *p)
{
    amiga_io_begin();
    FreeVec(p);
    amiga_io_end();
}

/* WHDLoad's kickfs has no ACTION_CHANGE_MODE or ACTION_SET_FILE_SIZE and
 * crashes on a packet it does not know (Secret Weapons of the Luftwaffe's docs/whdload.md). A new or emptied
 * file is therefore made with MODE_NEWFILE, closed and opened again with
 * MODE_OLDFILE: DOS permits another open (including an attribute query)
 * while a created file is live, and MODE_NEWFILE starts exclusive. */
static BPTR open_new(const char *path)
{
    BPTR f = Open((CONST_STRPTR)path, MODE_NEWFILE);
    if (!f) {
        return 0;
    }
    Close(f);
    return Open((CONST_STRPTR)path, MODE_OLDFILE);
}

static int32_t open_as(const char *path, LONG mode)
{
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (!files[k]) {
            int n = 0;
            while (path[n] && n < PATH_BYTES - 1) {
                file_paths[k][n] = path[n];
                ++n;
            }
            if (path[n]) {
                return -1;
            }
            file_paths[k][n] = 0;
            BPTR f = mode == MODE_NEWFILE ? open_new(path) : Open((CONST_STRPTR)path, mode);
            if (!f) {
                return -1;
            }
            files[k] = f;
            file_stamped[k] = 0;
            file_modified[k] = mode == MODE_NEWFILE;
            return k;
        }
    }
    return -1;
}

/* DOS write of 0 bytes: truncate at the position. The game's C library opens
 * for writing with O_TRUNC so (AX=3D01h, then 40h with CX=0 at position 0):
 * the file is made anew in place, no temporary file or rename. MODE_NEWFILE
 * fails while another handle holds the file on a disk filesystem, which has
 * SetFileSize; kickfs grants it always. Elsewhere only SetFileSize, which
 * kickfs lacks and no reference run needs. */
static int32_t truncate_at(int32_t handle)
{
    if (Seek(files[handle], 0, OFFSET_CURRENT) != 0) {
        return SetFileSize(files[handle], 0, OFFSET_CURRENT) < 0 ? -1 : 0;
    }
    Close(files[handle]);
    files[handle] = open_new(file_paths[handle]);
    if (files[handle]) {
        return 0;
    }
    files[handle] = Open((CONST_STRPTR)file_paths[handle], MODE_OLDFILE);
    return !files[handle] ? -1 : SetFileSize(files[handle], 0, OFFSET_CURRENT) < 0 ? -1 : 0;
}

/* MODE_OLDFILE reads and writes an existing file. */
int32_t plat_open(const char *path, int32_t mode)
{
    (void)mode;
    amiga_io_begin();
    int32_t handle = open_as(path, MODE_OLDFILE);
    amiga_io_end();
    return handle;
}

int32_t plat_create(const char *path)
{
    amiga_io_begin();
    int32_t handle = open_as(path, MODE_NEWFILE);
    amiga_io_end();
    return handle;
}

int32_t plat_write(int32_t handle, const void *buffer, uint32_t length)
{
    amiga_io_begin();
    int32_t n = length ? Write(files[handle], (APTR)buffer, (LONG)length) : truncate_at(handle);
    if (n >= 0) file_modified[handle] = 1;
    amiga_io_end();
    if (!files[handle]) rt_stop("cannot reopen a truncated file", handle, 0);
    return n;
}

int32_t plat_delete(const char *path)
{
    amiga_io_begin();
    int32_t result = DeleteFile((CONST_STRPTR)path) ? 0 : -1;
    amiga_io_end();
    return result;
}

int32_t plat_read(int32_t handle, void *buffer, uint32_t length)
{
    amiga_io_begin();
    int32_t n = Read(files[handle], buffer, (LONG)length);
    amiga_io_end();
    return n;
}

int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence)
{
    static const LONG mode[3] = {OFFSET_BEGINNING, OFFSET_CURRENT, OFFSET_END};
    int32_t position = -1;
    amiga_io_begin();
    if (whence >= 0 && whence <= 2 && Seek(files[handle], offset, mode[whence]) >= 0) {
        position = Seek(files[handle], 0, OFFSET_CURRENT);  /* Seek returns the old position */
    }
    amiga_io_end();
    return position;
}

uint32_t plat_calendar_date(void)
{
#ifdef XWING_REPLAY
    if (REPLAY_CALENDAR_DATE) return REPLAY_CALENDAR_DATE;
#endif
    struct DateStamp stamp;
    uint16_t time, date;
    amiga_io_begin();
    DateStamp(&stamp);
    amiga_io_end();
    amiga_file_date(stamp.ds_Days, stamp.ds_Minute, stamp.ds_Tick, &time, &date);
    return (uint32_t)(1980 + (date >> 9)) << 16 |
           (uint32_t)((date >> 5) & 15) << 8 | (date & 31);
}

void plat_file_stamp(int32_t handle, uint32_t time, uint32_t date)
{
    amiga_date_stamp((uint16_t)time, (uint16_t)date,
                     &file_stamps[handle].ds_Days, &file_stamps[handle].ds_Minute,
                     &file_stamps[handle].ds_Tick);
    file_stamped[handle] = 1;
}

void plat_close(int32_t handle)
{
#ifdef XWING_REPLAY
    if (REPLAY_FILE_DATE && file_modified[handle] && !file_stamped[handle])
        plat_file_stamp(handle, REPLAY_FILE_TIME, REPLAY_FILE_DATE);
#endif
    amiga_io_begin();
    /* After Close, so its filesystem stamp cannot overwrite the DOS timestamp.
     * By the opened path: NameFromFH needs ACTION_PARENT_FH, which kickfs
     * lacks; the current directory changes only around the run. kickfs
     * accepts SetFileDate without setting the date. */
    int closed = Close(files[handle]);
    int stamped = !file_stamped[handle] ||
                  (closed && SetFileDate((CONST_STRPTR)file_paths[handle], &file_stamps[handle]));
    amiga_io_end();
    files[handle] = 0;
    if (!stamped) rt_stop("cannot set file timestamp", handle, 0);
}

int32_t plat_dir_names(const char *dir, char *buffer, uint32_t size)
{
    int32_t bytes = 0;
    amiga_io_begin();
    BPTR lock = Lock((CONST_STRPTR)dir, ACCESS_READ);
    struct FileInfoBlock *fib = AllocDosObject(DOS_FIB, 0);
    if (lock && fib && Examine(lock, fib)) {
        while (ExNext(lock, fib)) {
            int k = 0;
            while (fib->fib_FileName[k] && k <= 12) {
                ++k;
            }
            int dir = fib->fib_DirEntryType > 0 && fib->fib_DirEntryType != ST_SOFTLINK;
            if ((fib->fib_DirEntryType >= 0 && !dir) || k > 12) {  /* longer: not 8.3 */
                continue;
            }
            if ((uint32_t)bytes + k + 1 + dir <= size) {
                for (int c = 0; c < k; ++c) {
                    buffer[bytes + c] = fib->fib_FileName[c];
                }
                if (dir) buffer[bytes + k] = '/';
                buffer[bytes + k + dir] = 0;
            }
            bytes += k + 1 + dir;
        }
    }
    if (fib) {
        FreeDosObject(DOS_FIB, fib);
    }
    if (lock) {
        UnLock(lock);
    }
    amiga_io_end();
    return bytes;
}

int32_t plat_file_info(const char *path, struct plat_file_info *info)
{
    int32_t found = -1;
    amiga_io_begin();
    BPTR lock = Lock((CONST_STRPTR)path, ACCESS_READ);
    struct FileInfoBlock *fib = AllocDosObject(DOS_FIB, 0);
    if (lock && fib && Examine(lock, fib) && fib->fib_DirEntryType != ST_SOFTLINK) {
        info->size = (uint32_t)fib->fib_Size;
        amiga_file_date(fib->fib_Date.ds_Days, fib->fib_Date.ds_Minute,
                        fib->fib_Date.ds_Tick, &info->dos_time, &info->dos_date);
        found = fib->fib_DirEntryType > 0;
    }
    if (fib) {
        FreeDosObject(DOS_FIB, fib);
    }
    if (lock) {
        UnLock(lock);
    }
    amiga_io_end();
    return found;
}

/* PIT channel 0 on a CIA-B timer (D8): one CIA period per PIT period, the
 * latch scaled from the PIT clock (1193182 Hz) to the E-clock: PAL 709379 Hz,
 * 35469/59659 within 1e-5; NTSC 715909 Hz, 3/5 (both colour clock / 5). The
 * interrupt runs the guest handler at once when the runtime allows it
 * (Secret Weapons of the Luftwaffe's docs/irq-plan.md I6), with EXTER acknowledged and the mask lowered to 2 so
 * the vertical blank preempts a long tick (a nested tick is posted); else it
 * posts vector 08h for the next poll point. */
#define CIAB ((volatile struct CIA *)0xbfd000)
static struct Library *cia_base = 0;
static struct Interrupt cia_interrupt;
static WORD cia_bit = -1;

/* CIA ticks, and of them those run at once (fixtures: amiga/display_audit.gdb). */
volatile ULONG amiga_ticks = 0, amiga_ticks_async = 0;

static ULONG cia_tick(void)
{
    ++amiga_ticks;
    if (rt_sfx_capturing) {
        return 0;               /* the effect capture holds the tick: game time pauses */
    }
#ifndef XWING_SYNC
    /* Production has no poll checks (Secret Weapons of the Luftwaffe's docs/irq-plan.md I8): ticks posted while
     * IRQ0 could not run go first, then this one. */
    if (rt_irq0_bios_tick()) {      /* IVT 08h the BIOS's: counted now, as DOS does */
        return 0;
    }
    int current = rt_irq0_ready();  /* else this tick waits behind posted ones */
    if (current || rt_irq0_take()) {
        UWORD sr;
        *(volatile UWORD *)0xdff09c = INTF_EXTER;
        __asm__ volatile("move.w %%sr,%0" : "=d"(sr) : : "memory");
        __asm__ volatile("move.w %0,%%sr" : : "d"((UWORD)((sr & ~0x0700) | 0x0200)) : "memory");
        for (;;) {
            rt_irq0_running = 1;
            ++amiga_ticks_async;
            rt_irq_interrupt();
            if (rt_irq0_take()) {
                continue;
            }
            if (!current && rt_irq0_ready()) {
                current = 1;
                continue;
            }
            break;
        }
        __asm__ volatile("move.w %0,%%sr" : : "d"(sr) : "memory");
        if (current) {
            return 0;
        }
    }
#endif
    rt_irq_post(8);
    return 0;
}

static void cia_load(uint32_t divisor)
{
    uint32_t latch = amiga_ntsc ? (divisor * 3u + 2u) / 5u : (divisor * 35469u + 29829u) / 59659u;
    volatile UBYTE *cr = cia_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb;
    volatile UBYTE *lo = cia_bit == CIAICRB_TA ? &CIAB->ciatalo : &CIAB->ciatblo;
    volatile UBYTE *hi = cia_bit == CIAICRB_TA ? &CIAB->ciatahi : &CIAB->ciatbhi;
    *cr &= cia_bit == CIAICRB_TA ? 0xc0 : 0x80;    /* stop; keep TOD/serial bits */
    *lo = (UBYTE)latch;
    *hi = (UBYTE)(latch >> 8);
    *cr |= CIACRAF_LOAD | CIACRAF_START;          /* continuous */
}

static int timer_open(void)
{
    cia_base = (struct Library *)OpenResource((CONST_STRPTR)CIABNAME);
    if (!cia_base) {
        return 0;
    }
    cia_interrupt.is_Node.ln_Type = NT_INTERRUPT;
    cia_interrupt.is_Node.ln_Name = (char *)"X-Wing PIT";
    cia_interrupt.is_Code = (void (*)(void))cia_tick;
    for (WORD bit = CIAICRB_TA; bit <= CIAICRB_TB; ++bit) {
        if (!AddICRVector(cia_base, bit, &cia_interrupt)) {
            cia_bit = bit;
            cia_load(0x10000);
            return 1;
        }
    }
    return 0;
}

/* The DSP's block time (P10): the card ends a single-cycle block, and posts
 * IRQ 7, length / rate after its 14h, held while D0h pauses the DMA; Paula
 * plays the samples from the next field (sb_play.c), so the end is timed
 * here, on the other CIA-B timer, one-shot in 16-bit slices of E-clocks, not
 * by the player's fields (CT-VOICE's interrupt test waits 2000h loop passes
 * for a one-byte block's IRQ: MEASURED, the Amiga image's init failed). */
#define ECLOCK_PAL 709379u
#define ECLOCK_NTSC 715909u
static struct Interrupt dsp_interrupt;
static WORD dsp_bit = -1;
static ULONG dsp_left;              /* E-clocks after the loaded slice */
static ULONG dsp_held;              /* a paused block's E-clocks */
static UWORD dsp_slice;             /* the loaded slice; 0: not running */

static volatile UBYTE *dsp_cr(void) { return dsp_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb; }

static void dsp_load(void)
{
    ULONG n = dsp_left > 0xffff ? 0xffff : (dsp_left ? dsp_left : 1);
    volatile UBYTE *cr = dsp_cr();
    dsp_left -= n < dsp_left ? n : dsp_left;
    dsp_slice = (UWORD)n;
    *cr &= dsp_bit == CIAICRB_TA ? 0xc0 : 0x80;    /* stop; keep TOD/serial bits */
    *(dsp_bit == CIAICRB_TA ? &CIAB->ciatalo : &CIAB->ciatblo) = (UBYTE)n;
    *(dsp_bit == CIAICRB_TA ? &CIAB->ciatahi : &CIAB->ciatbhi) = (UBYTE)(n >> 8);
    *cr |= CIACRAF_LOAD | CIACRAF_RUNMODE | CIACRAF_START;   /* one-shot */
}

#ifdef XWING_SB
static ULONG dsp_tick(void)
{
    if (!dsp_slice) {
        return 0;
    }
    if (dsp_left) {
        dsp_load();
    } else {
        dsp_slice = 0;
        amiga_post_irq7();          /* the card's terminal count */
    }
    return 0;
}
#endif

/* E-clocks still to run, the timer stopped. */
static ULONG dsp_stop(void)
{
    volatile UBYTE *cr = dsp_cr();
    *cr &= (UBYTE)~CIACRAF_START;
    UWORD at = dsp_bit == CIAICRB_TA ? (UWORD)(CIAB->ciatahi << 8 | CIAB->ciatalo)
                                     : (UWORD)(CIAB->ciatbhi << 8 | CIAB->ciatblo);
    ULONG left = dsp_slice ? dsp_left + at : 0;
    dsp_slice = 0;
    return left;
}

#ifdef XWING_SB
static void dsp_open(void)
{
    WORD bit = cia_bit == CIAICRB_TA ? CIAICRB_TB : CIAICRB_TA;
    dsp_interrupt.is_Node.ln_Type = NT_INTERRUPT;
    dsp_interrupt.is_Node.ln_Name = (char *)"X-Wing DSP";
    dsp_interrupt.is_Code = (void (*)(void))dsp_tick;
    if (cia_bit >= 0 && !AddICRVector(cia_base, bit, &dsp_interrupt)) {
        dsp_bit = bit;
        *dsp_cr() &= (UBYTE)~CIACRAF_START;
    }
}
#endif

static void timer_close(void)
{
    if (dsp_bit >= 0) {
        *dsp_cr() &= (UBYTE)~CIACRAF_START;
        RemICRVector(cia_base, dsp_bit, &dsp_interrupt);
        dsp_bit = -1;
        dsp_slice = 0;
    }
    if (cia_bit >= 0) {
        *(cia_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb) &= ~CIACRAF_START;
        RemICRVector(cia_base, cia_bit, &cia_interrupt);
        cia_bit = -1;
    }
}

void plat_timer_rate(uint32_t divisor)
{
    if (cia_bit >= 0) {
        Disable();
        cia_load(divisor);
        Enable();
    }
}

/* Diagnostic key script (argument KEYS=when:key,...; when is a frame from
 * the start, or pN: N guest mouse reads after the previous step, which waits
 * for a screen that is polling rather than for a time the host load moves;
 * keys a-z 0-9 enter esc space or $hex raw codes, mouse buttons lmb rmb,
 * mouse motion mx+N mx-N my+N my-N counts; shot and quit call
 * amiga_script_mark for a debugger fixture; unknown names are logged at the
 * start and skipped): fed from the field task at each vertical blank into
 * the keyboard and mouse paths of Input.cpp; a key
 * is released 5 frames after it is pressed, a button once the guest has
 * also read the mouse twice (buttons are polled levels, keys reach the BIOS
 * buffer). */
#define SCRIPT_LMB 0x100
#define SCRIPT_RMB 0x101
static const char *key_script = 0;
static ULONG key_up_frame = 0;
static ULONG key_up_reads = 0;
static ULONG step_reads = 0;    /* amiga_mouse_reads at the previous step */
static ULONG step_presents = 0; /* amiga_presents at the previous step */
extern volatile uint32_t amiga_presents;
static int key_up = -1;         /* the held raw key or SCRIPT_LMB/RMB */

void __attribute__((noinline)) amiga_script_mark(int quit)
{
    __asm__ volatile("" : : "r"(quit) : "memory");
}

static void script_event(int code, int up)
{
    if (code == SCRIPT_LMB || code == SCRIPT_RMB) {
        amiga_mouse_script_buttons(up ? 0 : code == SCRIPT_LMB ? 1 : 2);
    } else {
        amiga_key(code, up);
    }
}

static int named(const char *name, int n, const char *word)
{
    int k = 0;
    while (k < n && word[k] == name[k]) {
        ++k;
    }
    return k == n && !word[k];
}

static int raw_of(const char *name, int n)
{
    static const char rows[4][11] = {"1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"};
    static const UBYTE base[4] = {0x01, 0x10, 0x20, 0x31};
    if (n == 1) {
        for (int r = 0; r < 4; ++r) {
            for (int k = 0; rows[r][k]; ++k) {
                if (rows[r][k] == name[0]) {
                    return base[r] + k;
                }
            }
        }
    }
    if (named(name, n, "enter")) return 0x44;
    if (named(name, n, "esc")) return 0x45;
    if (named(name, n, "space")) return 0x40;
    if (named(name, n, "up")) return 0x4C;      /* the cursor keys ($ is the Shell's) */
    if (named(name, n, "down")) return 0x4D;
    if (named(name, n, "right")) return 0x4E;
    if (named(name, n, "left")) return 0x4F;
    if (named(name, n, "lmb")) return SCRIPT_LMB;
    if (named(name, n, "rmb")) return SCRIPT_RMB;
    if (n == 3 && name[0] == '$') {
        int v = 0;
        for (int k = 1; k < 3; ++k) {
            char c = name[k];
            v = v * 16 + (c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10);
        }
        return v;
    }
    return -1;
}

static int motion(const char *name, int n)
{
    return n > 3 && name[0] == 'm' && (name[1] == 'x' || name[1] == 'y') &&
           (name[2] == '+' || name[2] == '-');
}

static int known(const char *name, int n)
{
    return motion(name, n) || named(name, n, "shot") || named(name, n, "quit") ||
           raw_of(name, n) >= 0;
}

/* At the start (main program): the field task cannot log. */
static void key_script_check(void)
{
    for (const char *p = key_script; p && *p > ' ';) {
        while (*p > ' ' && *p != ',' && *p != ':') {
            ++p;
        }
        const char *name = *p == ':' ? ++p : p;
        while (*p > ' ' && *p != ',') {
            ++p;
        }
        if (!known(name, (int)(p - name))) {
            plat_log("X-Wing KEYS: unknown key");
        }
        p += *p == ',';
    }
}

static void key_script_step(void)
{
    if (key_up >= 0 && amiga_frames >= key_up_frame && amiga_mouse_reads >= key_up_reads) {
        script_event(key_up, 1);
        key_up = -1;
    }
    if (!key_script || *key_script <= ' ' || key_up >= 0) {
        return;
    }
    ULONG when = 0;
    const char *p = key_script;
    int reads = *p == 'p', presents = *p == 'f';
    p += reads | presents;
    while (*p >= '0' && *p <= '9') {
        when = when * 10 + (ULONG)(*p++ - '0');
    }
    if (reads ? amiga_mouse_reads - step_reads < when :
        presents ? amiga_presents - step_presents < when : amiga_frames < when) {
        return;
    }
    step_reads = amiga_mouse_reads;
    step_presents = amiga_presents;
    const char *name = *p == ':' ? ++p : p;
    while (*p > ' ' && *p != ',') {
        ++p;
    }
    int n = (int)(p - name);
    key_script = *p == ',' ? p + 1 : p;
    if (motion(name, n)) {
        WORD v = 0;
        for (int k = 3; k < n; ++k) {
            v = (WORD)(v * 10 + name[k] - '0');
        }
        v = name[2] == '-' ? (WORD)-v : v;
        amiga_mouse_move(name[1] == 'x' ? v : 0, name[1] == 'y' ? v : 0);
        return;
    }
    if (named(name, n, "shot") || named(name, n, "quit")) {
        amiga_script_mark(name[0] == 'q');
        return;
    }
    int code = raw_of(name, n);
    if (code < 0) {
        return;
    }
    script_event(code, 0);
    key_up = code;
    key_up_frame = amiga_frames + 5;
    key_up_reads = amiga_mouse_reads + (code >= SCRIPT_LMB ? 2 : 0);
}

/* Effect capture (runtime.h rt_sfx_*): every effect when Audio has its
 * Chip; the prerender follows in Audio (docs/translator-design.md Sound:
 * effects). */
extern int amiga_audio_effect_wanted(uint8_t id);
extern void amiga_audio_effects(void);
__attribute__((aligned(4))) volatile uint32_t amiga_sfx_capture_fields;  /* the capture's fields (diagnostics) */
int plat_sfx_wanted(uint8_t id)
{
    if (id == 4) {
        amiga_sfx_capture_fields = amiga_frames;
    }
    return amiga_audio_effect_wanted(id);
}

void plat_sfx_captured(void)
{
    amiga_sfx_capture_fields = amiga_frames - amiga_sfx_capture_fields;
    amiga_audio_effects();
}

void plat_service(void)
{
    key_script_step();
    amiga_audio_service();
}

/* VGA input status (port 3DAh) from the beam: bit 3 vertical retrace while
 * the beam is outside the 200 display lines (AMIGA_TOP_LINE on), bit 0
 * display disabled then and outside the low-resolution data fetch of a line
 * (horizontal positions $38-$D7). The game polls it to wait for a retrace. */
uint8_t plat_vga_status(void)
{
#ifdef XWING_REPLAY
    return replay_vga_status();     /* the reference's reads (tests/amiga_replay.c) */
#else
    ULONG beam = *(volatile ULONG *)0xdff004;       /* VPOSR:VHPOSR */
    UWORD v = (UWORD)((beam >> 8) & 0x1ff), h = (UWORD)(beam & 0xff);
    UWORD top = AMIGA_TOP_LINE;
    int vblank = v < top || v >= top + 200;
    return (uint8_t)((vblank ? 0x09 : 0) | (h < 0x38 || h >= 0xd8 ? 0x01 : 0));
#endif
}

/* The DSP and the OPL timer answer at once: the model's status (ports.c).
 * The diagnostic replay has no DSP reads recorded. */
uint8_t plat_dsp_status(uint32_t port, uint32_t value)
{
#ifdef XWING_REPLAY
    rt_stop("DSP status read in a replay: none recorded (port, value)", port, value);
#else
    (void)port;
    return (uint8_t)value;
#endif
}

/* IRQ 7 posted from the main program (F2h) or the DSP timer, outside the
 * ring (runtime.h rt_irq7_tail): all interrupts masked around the post. Disable(), not SR: the main program runs in user
 * mode, where a move to or from SR is a privilege violation (MEASURED: the
 * detection's F2h stopped the Amiga image in Exec's alert). */
void amiga_post_irq7(void)
{
    Disable();
    ++rt_irq7_tail;                 /* outside the ring (runtime.h) */
    RT_RAISE_IRQ();
    Enable();
}

/* Speech (Audio.cpp, sb_play.c): the block on Paula, IRQ 7 at its end. */
extern void amiga_audio_sb_block(uint32_t linear, uint32_t length, uint32_t rate);
extern void amiga_audio_sb_pause(uint32_t paused);
void plat_sb_block(uint32_t linear, uint32_t length, uint32_t rate)
{
#ifdef XWING_REPLAY
    rt_stop("Sound Blaster block in a replay: none recorded (linear, length)", linear, length);
#else
    if (dsp_bit < 0) {
        rt_stop("DSP block without a CIA-B timer for its end (linear, length)", linear, length);
    }
    amiga_audio_sb_block(linear, length, rate);
    /* length * E-clock / rate in 32 bits (no libgcc): exact up to 65535 Hz */
    uint32_t eclock = amiga_ntsc ? ECLOCK_NTSC : ECLOCK_PAL, div = rate ? rate : 1, shift = 0;
    uint32_t q = eclock / div, r = eclock % div;
    while ((div >> shift) > 0xffffu) {
        ++shift;
    }
    uint32_t ticks = length * q + length * (r >> shift) / (div >> shift);
    Disable();
    (void)dsp_stop();               /* a paused block's end never comes (ports.c) */
    dsp_held = 0;
    dsp_left = ticks;
    dsp_load();
    Enable();
#endif
}

void plat_sb_pause(uint32_t paused)
{
    amiga_audio_sb_pause(paused);
    Disable();
    if (paused) {
        dsp_held = dsp_stop();
    } else if (dsp_held) {
        dsp_left = dsp_held;
        dsp_held = 0;
        dsp_load();
    }
    Enable();
}

/* DSP F2h: IRQ 7 at once, at the next poll point. */
void plat_sb_irq(void)
{
    amiga_post_irq7();
}

/* Shell start: the Shell's output; Workbench start: none. */
void plat_console(const void *buffer, uint32_t length)
{
    amiga_io_begin();
    BPTR out = Output();
    if (out && length) {
        Write(out, (APTR)buffer, (LONG)length);
    }
    amiga_io_end();
}

void plat_log(const char *line)
{
    LONG n = 0;
    while (line[n]) {
        ++n;
    }
    amiga_io_begin();
    BPTR out = Output();
    if (out) {
        Write(out, (APTR)line, n);
        Write(out, (APTR)"\n", 1);
    }
    amiga_io_end();
}

/* Workbench start (L84): the program's own drawer becomes the current
 * directory (a Shell's is its own) and the tool icon's tool types are the
 * arguments, the same keywords; KEYS= is copied, the icon is freed before
 * the run. The release image reads none. The installed X-Wing.info is a
 * project icon whose default tool is data/X-Wing, so the tool's name may
 * hold a path relative to its lock: the drawer is the tool file's parent. */
static BPTR wb_old_dir = 0;
static BPTR wb_dir = 0;
static char *wb_keys = 0;
static ULONG wb_keys_bytes = 0;

static int wb_options(void)
{
    struct WBArg *tool = amiga_wb_startup->sm_ArgList;
    wb_old_dir = CurrentDir(tool->wa_Lock);
    BPTR file = Lock((CONST_STRPTR)tool->wa_Name, ACCESS_READ);
    if (file) {
        wb_dir = ParentDir(file);
        UnLock(file);
    }
    if (!wb_dir) {
        plat_log("X-Wing cannot find its drawer");
        return 0;
    }
    IconBase = OpenLibrary((CONST_STRPTR)"icon.library", 37);
    if (!IconBase) {
        CurrentDir(wb_dir);
        return 1;
    }
    struct DiskObject *icon = GetDiskObject((STRPTR)tool->wa_Name);
    int ok = 1;
    if (icon) {
#ifndef XWING_RELEASE
        STRPTR *types = (STRPTR *)icon->do_ToolTypes;
        const char *keys = (const char *)FindToolType(types, (STRPTR)"KEYS");
        if (keys) {
            ULONG n = 0;
            while (keys[n]) {
                ++n;
            }
            wb_keys_bytes = n + 1;
            wb_keys = (char *)AllocMem(wb_keys_bytes, MEMF_ANY);
            if (wb_keys) {
                for (ULONG k = 0; k < wb_keys_bytes; ++k) {
                    wb_keys[k] = keys[k];
                }
                key_script = wb_keys;
            } else {
                plat_log("X-Wing not enough memory");
                ok = 0;
            }
        }
#endif
        FreeDiskObject(icon);
    }
    CloseLibrary(IconBase);
    IconBase = 0;
    CurrentDir(wb_dir);
    return ok;
}

/* Shell start: ReadArgs, so the keywords are case-insensitive, `?` prompts
 * with the template and a bad line fails with the DOS error. ReadArgs reads
 * the line from Input()'s buffer, where the Shell and the WHDLoad slave's
 * RunCommand put it. KEYS points into the RDArgs until the close. */
static struct RDArgs *shell_args = 0;

#ifdef XWING_RELEASE
/* The release image: no options yet. */
#define SHELL_TEMPLATE ""
enum { ARG_COUNT = 1 };
#else
#define SHELL_TEMPLATE "KEYS/K"
enum { ARG_KEYS, ARG_COUNT };
#endif

static int shell_options(void)
{
    LONG values[ARG_COUNT] = {0};
    shell_args = ReadArgs((CONST_STRPTR)SHELL_TEMPLATE, values, 0);
    if (!shell_args) {
        amiga_io_begin();
        PrintFault(IoErr(), (CONST_STRPTR)"XWing");
        amiga_io_end();
        return 0;
    }
#ifndef XWING_RELEASE
    if (values[ARG_KEYS]) key_script = (const char *)values[ARG_KEYS];
#endif
    return 1;
}

int amiga_guest_open(void)
{
    DOSBase = (struct DosLibrary *)OpenLibrary((CONST_STRPTR)"dos.library", 39);
    if (!DOSBase) {
        return 0;
    }
    if (amiga_wb_startup && !wb_options()) {
        return 0;
    }
    if (!amiga_wb_startup && !shell_options()) {
        return 0;
    }
    key_script_check();
    rt_sfx_prerender_on = 1;    /* effects prerendered at FLIGHT's sound loader (runtime.h) */
#ifndef XWING_SYNC
    rt_mickeys_y = 1;       /* vertical counts 1:1, as a real PC mouse (runtime.h) */
#endif
    /* Guest RAM, the state block below it and the EMS store after it; Fast RAM
     * when present (D15). */
    guest_block = (uint8_t *)AllocMem(RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES, MEMF_ANY | MEMF_CLEAR);
    guest_stack = (uint8_t *)AllocMem(GUEST_STACK_BYTES, MEMF_ANY);
    if (!guest_block || !guest_stack) {
        plat_log("X-Wing not enough memory");
        return 0;
    }
    plat_log("X-Wing guest start");
    rt_start(guest_block);
#ifdef XWING_REPLAY
    /* The reference's interrupts arrive at their recorded poll points. */
    (void)timer_open;
    plat_log("X-Wing diagnostic reference replay");
#else
    if (!timer_open()) {
        plat_log("X-Wing no CIA-B timer");
    }
#ifdef XWING_SB
    dsp_open();
    if (dsp_bit < 0) {
        plat_log("X-Wing no second CIA-B timer for the DSP");
    }
#endif
#endif
    return 1;
}

long amiga_guest_run(void)
{
    return amiga_guest_call(guest_stack + GUEST_STACK_BYTES);
}

void amiga_guest_close(void)
{
    timer_close();
    rt_dos_close();
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (files[k]) {
            plat_close(k);
        }
    }
    if (guest_stack) {
        FreeMem(guest_stack, GUEST_STACK_BYTES);
        guest_stack = 0;
    }
    if (guest_block) {
        FreeMem(guest_block, RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES);
        guest_block = 0;
    }
    if (wb_keys) {
        FreeMem(wb_keys, wb_keys_bytes);
        wb_keys = 0;
    }
    if (shell_args) {
        FreeArgs(shell_args);
        shell_args = 0;
    }
    if (DOSBase && amiga_wb_startup) {
        CurrentDir(wb_old_dir);
        if (wb_dir) {
            UnLock(wb_dir);
            wb_dir = 0;
        }
    }
    if (DOSBase) {
        CloseLibrary((struct Library *)DOSBase);
        DOSBase = 0;
    }
}
