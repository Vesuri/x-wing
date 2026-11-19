#ifndef XWING_INSTALL_XWUNPACK_H
#define XWING_INSTALL_XWUNPACK_H
#include "io.h"
/* Input: point *buf at the next bytes and return their count, 0 at the end.
 * Output: take len bytes, return nonzero to stop. As zlib's blast(). */
typedef unsigned (*xw_in)(void *how, unsigned char **buf);
typedef int (*xw_out)(void *how, unsigned char *buf, unsigned len);
/* One compressed file of the X-Wing installer archive, method 0xd0 or 0xe0
 * (the catalog record's byte 5): exactly size bytes.
 * 0 when the stream decodes to them and ends with its end code, else nonzero. */
int xw_unpack(unsigned method, xw_in in, void *inhow, xw_out out, void *outhow, uint32_t size);
#endif
