/* Decoders for the compressed files of X-Wing's installer archive (LucasArts,
 * 1993; format: docs/release.md, Original data). LGPL-2.1-or-later. Bits are
 * read least significant first in both.
 *
 * Method 0xd0: a stream starts with N (LE16) and W (byte), then N tree entries of W bits:
 * an entry below N is a node base, else a leaf with symbol entry-N. A symbol is found from node N-2 by
 * node = tree[node + bit] until a leaf: below 256 a literal, 256 the end,
 * else a match of symbol-254 bytes. A match's distance has a high part from
 * the fixed 64-value prefix code below and 0..7 low bits, as many as the
 * output position allows; the 8 KiB window starts as spaces. */
#include "xwunpack.h"
#include <string.h>

#define WINDOW 8192U
#define TREE 0x275U

/* The position code: lengths 1x3, 3x4, 8x5, 12x6, 24x7, 16x8 bits (as
 * LZHUF's), and each value's code as read, least significant bit first. The
 * assignment of codes to values is the original installer's own, needed to
 * read its archive (owner decision 2026-11-19, docs/design.md). */
static const unsigned char code[64]={
    0x00,0x02,0x04,0x0c,0x01,0x06,0x0a,0x0e,0x11,0x16,0x1a,0x1e,0x05,0x09,0x0d,0x15,
    0x19,0x1d,0x25,0x29,0x2d,0x35,0x39,0x3d,0x03,0x07,0x0b,0x13,0x17,0x1b,0x23,0x27,
    0x2b,0x33,0x37,0x3b,0x43,0x47,0x4b,0x53,0x57,0x5b,0x63,0x67,0x6b,0x73,0x77,0x7b,
    0x0f,0x1f,0x2f,0x3f,0x4f,0x5f,0x6f,0x7f,0x8f,0x9f,0xaf,0xbf,0xcf,0xdf,0xef,0xff};
static unsigned length(unsigned v)
{ return v<1?3:v<4?4:v<12?5:v<24?6:v<48?7:8; }

typedef struct {
    xw_in in; void *how; unsigned char *next; unsigned avail;
    uint32_t buf; unsigned bits, pad;
} Bits;
static unsigned char window[WINDOW], lookup[256];
static uint16_t tree[TREE];

/* At least k (<=16) bits buffered; past the input's end zero bytes, counted. */
static void fill(Bits *b,unsigned k)
{
    while(b->bits<k) {
        unsigned v=0;
        if(!b->avail && !b->pad) b->avail=b->in(b->how,&b->next);
        if(b->avail) { v=*b->next++; b->avail--; } else b->pad++;
        b->buf|=(uint32_t)v<<b->bits; b->bits+=8;
    }
}
/* k bits; nonzero *bad once a bit past the input's end is taken. */
static unsigned get(Bits *b,unsigned k,int *bad)
{
    unsigned v;
    fill(b,k);
    v=(unsigned)(b->buf&((1UL<<k)-1));
    b->buf>>=k; b->bits-=k;
    if(b->bits<b->pad*8) *bad=1;
    return v;
}

static int tree_lz(xw_in in,void *inhow,xw_out out,void *outhow,uint32_t size)
{
    Bits b; unsigned n,w,i,v; uint32_t done=0; unsigned at=0; int bad=0;
    b.in=in; b.how=inhow; b.avail=0; b.buf=0; b.bits=0; b.pad=0;
    for(v=0;v<64;v++)
        for(i=code[v];i<256;i+=1U<<length(v)) lookup[i]=(unsigned char)v;
    n=get(&b,16,&bad); w=get(&b,8,&bad);
    if(n<2 || n>TREE || !w || w>16) return 1;
    for(i=0;i<n;i++) tree[i]=(uint16_t)get(&b,w,&bad);
    memset(window,0x20,WINDOW);
    while(!bad) {
        unsigned node=n-2,steps=0,sym;
        for(;;) {
            if(++steps>n || node+1>=n) return 1;
            node=tree[node+get(&b,1,&bad)];
            if(node>=n) break;
        }
        sym=node-n;
        if(sym==256) break;
        if(sym<256) {
            if(done==size) return 1;
            window[at++]=(unsigned char)sym; done++;
            if(at==WINDOW) { if(out(outhow,window,WINDOW)) return 1; at=0; }
        } else {
            uint32_t pos=done+0x3c,low=0; unsigned high,lb=0,len=sym-0xfe,from;
            fill(&b,8);
            high=lookup[b.buf&255]; get(&b,length(high),&bad);
            if(pos>=0x2000) lb=7;
            else for(v=(unsigned)(pos>>5);v>1;v>>=1) lb++;
            if(lb) low=get(&b,lb,&bad);
            from=(unsigned)(at-(((uint32_t)high<<lb|low)+1))&(WINDOW-1);
            if(len>size-done) return 1;
            while(len--) {
                window[at++]=window[from++]; from&=WINDOW-1; done++;
                if(at==WINDOW) { if(out(outhow,window,WINDOW)) return 1; at=0; }
            }
        }
    }
    if(bad || done!=size || b.avail || b.bits-b.pad*8>=8) return 1;
    if(!b.pad && in(inhow,&b.next)) return 1;
    return at && out(outhow,window,at) ? 1 : 0;
}

/* Method 0xe0: LZW over the entries 1..0x1eff, with run-length coding of the
 * output. Codes start 1 bit wide and widen when the next entry reaches 2^width.
 * Each code is preceded by a bit, 0 for an 8-bit literal instead. Entry 0
 * ends the stream. Each symbol after the first adds an entry: the previous
 * symbol plus its own first byte. In the output, 0x90 n repeats the previous
 * byte n-1 more times; 0x90 0 is 0x90 itself.
 * The original decoder also drops the flag bit once 375 of the last 500
 * symbols were entries, and reuses entries once the table is full. The
 * pinned archive's 0xe0 files reach neither (MEASURED: all 18 at most 1,428
 * bytes), so both are refused here rather than implemented untested. */
#define CODES 0x1f00U
#define HISTORY 500U
static int16_t prefix[CODES];
static unsigned char suffix[CODES], history[HISTORY], stack[CODES];

typedef struct { xw_out out; void *how; uint32_t done, size; unsigned at; } Sink;
static int put(Sink *s,unsigned char c)
{
    if(s->done==s->size) return 1;
    window[s->at++]=c; s->done++;
    if(s->at==WINDOW) { s->at=0; return s->out(s->how,window,WINDOW); }
    return 0;
}

static int lzw(xw_in in,void *inhow,xw_out out,void *outhow,uint32_t size)
{
    Bits b; Sink s; int bad=0, pending=0;
    unsigned width=1,last=0,entries=0,slot=0;
    int16_t prev=0; unsigned char first,byte=0;
    b.in=in; b.how=inhow; b.avail=0; b.buf=0; b.bits=0; b.pad=0;
    s.out=out; s.how=outhow; s.done=0; s.size=size; s.at=0;
    memset(history,0,sizeof history);
    for(;;) {
        int16_t code; int si; unsigned depth=0;
        code=get(&b,1,&bad) ? (int16_t)get(&b,width,&bad) : (int16_t)(-(int)get(&b,8,&bad)-1);
        if(bad) return 1;
        if(!code) break;
        if(code>0 && (unsigned)code>last) return 1;      /* not yet defined */
        for(si=code;si>0;si=prefix[si]) {
            if(depth>=CODES-1) return 1;
            stack[depth++]=suffix[si];
        }
        first=(unsigned char)(-si-1); stack[depth++]=first;
        while(depth) {
            unsigned char c=stack[--depth];
            if(pending) {
                pending=0;
                if(!c) { if(put(&s,0x90)) return 1; }
                else while(--c) if(put(&s,byte)) return 1;
            } else if(c==0x90) pending=1;
            else { byte=c; if(put(&s,c)) return 1; }
        }
        if(prev) {
            if(history[slot]) entries--;
            history[slot]=code>0; entries+=code>0;
            if(++slot==HISTORY) slot=0;
            if(entries>=375 || last==CODES-1) return 1;  /* refused, see above */
            if(++last>=1U<<width) width++;
            prefix[last]=prev; suffix[last]=first;
        }
        prev=code;
    }
    if(pending || s.done!=size || b.avail || b.bits-b.pad*8>=8) return 1;
    if(!b.pad && in(inhow,&b.next)) return 1;
    return s.at && out(outhow,window,s.at) ? 1 : 0;
}

int xw_unpack(unsigned method,xw_in in,void *inhow,xw_out out,void *outhow,uint32_t size)
{
    return method==0xd0 ? tree_lz(in,inhow,out,outhow,size)
         : method==0xe0 ? lzw(in,inhow,out,outhow,size) : 1;
}
