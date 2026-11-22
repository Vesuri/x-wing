/* Platform services the runtime needs: the game's files and their directory, the timer, the
 * mouse, the VGA status, the display of the mode 13h frame (changed rectangles, DAC), a log
 * line and exit. Copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and
 * adapted. Implemented by src/platform/host (Unicorn harness) and src/platform/amiga
 * (dos.library). */
#ifndef XWING_PLATFORM_H
#define XWING_PLATFORM_H

#include <stdint.h>

/* Native runtime storage; allocation failure returns null. */
void *plat_alloc(uint32_t bytes);
void plat_free(void *memory);

/* path: game-relative, upper case, '/' separated ("RESOURCE/XWING.LFD"). mode 0 read,
 * 1 write, 2 read/write (existing file). < 0 if missing. */
int32_t plat_open(const char *path, int32_t mode);
/* New empty file (an existing one is truncated), open read/write; < 0 on error. */
int32_t plat_create(const char *path);
int32_t plat_read(int32_t handle, void *buffer, uint32_t length);
/* Bytes written, < 0 on error; length 0 truncates the file at the position. */
int32_t plat_write(int32_t handle, const void *buffer, uint32_t length);
/* < 0 if missing. */
int32_t plat_delete(const char *path);
/* whence 0 start, 1 current, 2 end; returns the new position, < 0 on error */
int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence);
void plat_close(int32_t handle);
/* DOS caches the local calendar at startup: year:16, month:8, day:8. */
uint32_t plat_calendar_date(void);
/* Retain this explicit DOS timestamp when the open file is closed. */
void plat_file_stamp(int32_t handle, uint32_t dos_time, uint32_t dos_date);
/* The names of the files and directories in directory `dir` (game-relative as
 * above, "" the game directory), up to 12 chars each, case as stored, a
 * directory's followed by '/', NUL-terminated and packed, in one directory
 * pass: the bytes they need (0 for none or a missing directory); only names
 * that fit completely are written to buffer[size]. */
int32_t plat_dir_names(const char *dir, char *buffer, uint32_t size);
/* Metadata of file or directory `path` (local calendar, DOS packed time/date;
 * the size the filesystem gives): 0 a file, 1 a directory, < 0 missing. */
struct plat_file_info { uint32_t size; uint16_t dos_time, dos_date; };
int32_t plat_file_info(const char *path, struct plat_file_info *info);
/* PIT channel 0 now fires every `divisor` input clocks (1..65536, 1193182 Hz):
 * per period the platform posts vector 08h (runtime.h rt_irq_ring). */
void plat_timer_rate(uint32_t divisor);
/* Mouse counts since the last call (right and down positive) and the
 * buttons held (bit 0 left, 1 right, 2 middle). */
uint32_t plat_mouse(int32_t *dx, int32_t *dy);
/* Publish rectangles of the 320x200 chunky frame (pixels, ends exclusive, x0
 * and x1 multiples of 32); the rest of the frame is unchanged. The platform
 * may queue the completed image for its next safe display handoff. */
struct plat_rect { uint16_t x0, y0, x1, y1; };
void plat_present(const uint8_t *frame, const struct plat_rect *rects, int32_t n);
/* The DAC changed (256 x 6-bit R, G, B). */
void plat_palette(const uint8_t *dac);
/* VGA input status 1 (port 3DAh) now: bit 3 vertical retrace, bit 0 display
 * disabled (the host replays the reference's reads, trace/retrace.csv). */
uint8_t plat_vga_status(void);

/* Sound Blaster DSP status read (port 22Ch write status, 22Eh data status):
 * `value` is the DSP model's answer (ports.c); the platform may report the
 * device still busy (22Ch bit 7 set) or its data not yet there (22Eh bit 7
 * clear), as the reference DSP's timing does, and the OPL's timer 1 still
 * counting (228h flags C0h clear). Returns the byte read. */
uint8_t plat_dsp_status(uint32_t port, uint32_t value);
/* Sound Blaster block: `length` 8-bit unsigned mono samples at guest linear
 * `linear` (guest RAM order, runtime.h rd8) played at `rate` Hz; when the last
 * has played the platform posts vector 0Fh (IRQ 7, rt_irq_ring). */
void plat_sb_block(uint32_t linear, uint32_t length, uint32_t rate);
/* DSP D0h (1) and D4h (0): the playing block paused and continued. */
void plat_sb_pause(uint32_t paused);
/* DSP F2h: the platform posts vector 0Fh (IRQ 7). */
void plat_sb_irq(void);
/* Effect capture (runtime.h rt_sfx_*): whether to capture effect id; the
 * capture is complete (called once after the last id, the guest state restored). */
int plat_sfx_wanted(uint8_t id);
void plat_sfx_captured(void);
/* The platform's own work from the main program at a vertical blank. */
void plat_service(void);
void plat_log(const char *line);
/* The game's console output (DOS writes to CON), as written. */
void plat_console(const void *buffer, uint32_t length);
void plat_exit(int32_t code) __attribute__((noreturn));

#endif
