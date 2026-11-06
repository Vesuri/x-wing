/* Copy-protection bypass (owner decision 2026-11-01; annotations/hle.csv
 * copy_protection, rt_hle_copy_protection in rt_entry.s).
 *
 * The front end's protection screen (FRONTEND.OVL 3273:3470, called from
 * 3273:0AFF) shows three glyphs, asks for the code-name on a manual page and
 * returns AX = 1 when it was typed. The hook replaces the call: the screen is
 * never built or shown, and the guest is left as a correct first answer
 * leaves it (reference milestone m03p-protection-passed, the reference's
 * question 16, page 11, BRIGGIA):
 *   [6562h]:0000..0005  the question's glyph triple, from its table at +1222h
 *   [6562h]:000E        wrong tries: 0
 *   [6562h]:003A        the triple frozen: 1
 *   [6562h]:0E06        the question index
 *   AX                  1
 * The screen's own state (its windows, the RNG seed it advanced while the
 * glyphs cycled, the music and the BIOS tick that ran while it was shown) is
 * the dialog's and its duration's; tests/host_run.py --bypass lists it. */

#include "runtime.h"

#define PROTECTION_DS_SLOT 0x6562   /* DGROUP word: the screen's data segment */
#define QUESTION 16                 /* the reference's: page 16 / 2 + 3 = 11 */

void rt_hle_copy_protection_c(void)
{
    uint32_t seg = lin(rd16(lin(G_DS, PROTECTION_DS_SLOT)), 0);
    for (int i = 0; i < 3; i++) {
        wr16(seg + 2 * i, rd16(seg + 0x1222 + 2 * (QUESTION * 3 + i)));
    }
    wr16(seg + 0x0e, 0);
    wr16(seg + 0x3a, 1);
    wr16(seg + 0xe06, QUESTION);
    rt_r.ax = 1;
}
