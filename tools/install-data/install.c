/* Native, bounded installer for X-Wing (LucasArts, 1993, DOS floppy release
 * 1.0): the game directory from the user's five floppies, given as a drawer
 * with disk1.img..disk5.img (1.44M FAT12 images) or the files XWING.001..005,
 * INSTALL.EXE, DETECT.EXE and READ.ME copied from them.
 *
 * The five volumes are one archive: the data, then on disk 1 the catalog. A
 * file is stored or compressed (xwunpack.c). Every volume is checked by size
 * and SHA-256 first; each file by its catalog size and an exact end of its
 * stream. The configuration is the one the original installer writes for
 * AdLib (docs/dos-reference.md). Destination must be new; on any failure the
 * files created are removed. Adapted from Secret Weapons of the Luftwaffe's
 * (manifest/references.tsv). LGPL-2.1-or-later. */
#include "io.h"
#include "sha256.h"
#include "xwunpack.h"
#include <string.h>

#define VOLUMES 5
#define CATALOG 1256066UL       /* XWING.001: archive data, then the catalog */
#define RECORD 47
#define RECORDS 279
#define COPIES 3                /* disk 1's own files the installer copies */
#define FILES (RECORDS+COPIES+2)

static const uint32_t volume_size[VOLUMES]={1270992UL,1457152UL,1457152UL,1457152UL,1176599UL};
/* SHA-256 of XWING.001..005 (shasum -a 256). */
static const unsigned char volume_sha[VOLUMES][32]={
    {0x86,0xa2,0x3c,0x47,0xaa,0xdc,0x03,0x14,0x0e,0x00,0x35,0x5a,0x4d,0x73,0xf3,0x8c,
     0x64,0x8f,0x26,0xf2,0x82,0x49,0x0b,0xa9,0x72,0x15,0x64,0x52,0x57,0x4a,0x52,0xb2},
    {0x68,0xa5,0x32,0xc3,0x53,0x80,0x86,0x18,0xfa,0xd1,0x6c,0x82,0x79,0x2d,0x4d,0x8e,
     0x79,0x7b,0x33,0x31,0xd8,0x93,0xd8,0xbf,0xc1,0x36,0x88,0x27,0x5f,0xa7,0x8a,0x29},
    {0xd8,0xb1,0xb8,0x11,0xfb,0xa1,0xc8,0xe2,0x0a,0xdd,0xf3,0x2e,0x5a,0x6b,0xc2,0x88,
     0x97,0xdf,0xb8,0x1a,0xad,0xb5,0xbd,0xce,0x62,0xf3,0x4d,0x2b,0xf7,0x2d,0xb0,0xed},
    {0xf0,0x09,0xaf,0x11,0x4f,0x7e,0x7b,0x56,0xf5,0x05,0x3f,0x0b,0xc0,0xdd,0xcf,0x59,
     0x12,0x7f,0x68,0x6f,0x8d,0x93,0x89,0x1a,0xcc,0x92,0x67,0x29,0xf3,0x60,0xf9,0xab},
    {0x1e,0x0e,0xd4,0xc7,0xaf,0x56,0x29,0x1f,0x7f,0xfd,0xce,0x06,0x54,0x9c,0x7d,0x8b,
     0xa1,0x0b,0xe1,0x7d,0x3d,0x20,0x6d,0xd1,0xee,0x84,0xf6,0x78,0x15,0x60,0x7c,0x19}};
/* Disk 1's files copied as they are (manifest/dos-installed.sha256). */
static const char *const copy_name[COPIES]={"INSTALL.EXE","DETECT.EXE","READ.ME"};
static const uint32_t copy_size[COPIES]={138041UL,32238UL,13201UL};
static const unsigned char copy_sha[COPIES][32]={
    {0x9c,0xf6,0x73,0x44,0xee,0x10,0x77,0x78,0xca,0x08,0x18,0x53,0xad,0x2e,0xdb,0x29,
     0x57,0xef,0xe5,0xd5,0x7b,0x1d,0x90,0xc5,0x17,0xe5,0x5a,0xb9,0x64,0xf3,0xed,0xfa},
    {0xd7,0x24,0x49,0x55,0xeb,0x4a,0xe7,0x2d,0x79,0x09,0x9d,0xa6,0xcf,0x71,0xa2,0x41,
     0xe9,0x1f,0x2e,0x59,0x6d,0xc7,0x86,0x68,0xf0,0x44,0xc5,0x48,0xd5,0x49,0xa5,0xff},
    {0xfb,0x6c,0xb0,0x92,0xae,0x01,0x6a,0x29,0x2d,0xa4,0x1f,0x76,0x20,0x61,0xc9,0xf1,
     0xd7,0x9e,0x76,0x05,0x5a,0x67,0x5f,0x94,0x6a,0x84,0xe9,0xbd,0x0b,0xcc,0x5a,0x6a}};
/* The catalog's directory indexes 1..4; "" is the game drawer itself. */
static const char *const directory[5]={0,"","RESOURCE","MISSION","CP"};
/* The configuration the original installer writes for AdLib with its fast
 * detail (docs/dos-reference.md): LANDRU.CFG, and OPTIONS.CFG as a copy of
 * the installed FASTYES.CFG. */
static const char landru[]="adlib\r\nFAST\r\nems\r\ndiff\r\n";

typedef struct {
    File f; int image; uint32_t size, data, cluster;
    unsigned clusters; uint16_t chain[2880];
} Volume;
static Volume volume[VOLUMES], loose;
static unsigned char catalog[RECORDS*RECORD], buffer[4096], sector[7168];
static char created[FILES+8][24];
static unsigned count;

static uint32_t le32(const unsigned char *p)
{ return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static unsigned le16(const unsigned char *p) { return p[0]|(unsigned)p[1]<<8; }
static int path(char *out,const char *dir,const char *name)
{
    unsigned n=strlen(dir),m=strlen(name);
    if(!n || n+m+2>512) return 0;
    memcpy(out,dir,n); if(out[n-1]!=':' && out[n-1]!='/') out[n++]='/';
    memcpy(out+n,name,m+1); return 1;
}
/* "NAME.EXT" as a FAT directory entry's 11 bytes. */
static void entry_name(char *out,const char *name)
{
    unsigned i=0;
    memset(out,' ',11);
    while(*name && *name!='.' && i<8) out[i++]=*name++;
    if(*name=='.') for(name++,i=8;*name && i<11;) out[i++]=*name++;
}

/* One file of disk n: itself in the source drawer, or its FAT12 chain inside
 * the drawer's diskn.img. */
static int open_image(Volume *v,const char *name)
{
    unsigned char *b=sector; char want[11];
    unsigned bps,spc,reserved,fats,roots,spf,i,c;
    entry_name(want,name);
    if(!io_read(&v->f,b,512)) return 0;
    bps=le16(b+11); spc=b[13]; reserved=le16(b+14); fats=b[16]; roots=le16(b+17); spf=le16(b+22);
    if(bps!=512 || !spc || spc>8 || !reserved || fats<1 || fats>2 || !roots || roots>224 || !spf || spf>12) return 0;
    v->cluster=spc*512UL;
    v->data=(reserved+fats*spf)*512UL+roots*32UL;
    if(v->data>=v->f.size || !io_seek(&v->f,(reserved+fats*spf)*512UL) || !io_read(&v->f,b,roots*32)) return 0;
    for(i=0;i<roots;i++) {
        unsigned char *e=b+32*i;
        if(!memcmp(e,want,11) && !(e[11]&0x18)) break;
    }
    if(i==roots) return 0;
    v->size=le32(b+32*i+28); c=le16(b+32*i+26);
    if(!io_seek(&v->f,reserved*512UL) || !io_read(&v->f,b,spf*512)) return 0;
    for(v->clusters=0;c>=2 && c<0xff8;) {
        uint32_t at=v->data+(c-2)*v->cluster,e=c+c/2;
        if(v->clusters>=2880 || at+v->cluster>v->f.size || e+1>=spf*512U) return 0;
        v->chain[v->clusters++]=(uint16_t)c;
        c=c&1?le16(b+e)>>4:le16(b+e)&0xfff;
    }
    return v->clusters==(v->size+v->cluster-1)/v->cluster;
}
static int open_file(Volume *v,const char *source,unsigned disk,const char *name)
{
    static char image[]="disk0.img",ima[]="disk0.ima";
    char target[512];
    image[4]=ima[4]=(char)('0'+disk);
    v->image=0;
    if(path(target,source,name) && io_open(&v->f,target,0)) { v->size=v->f.size; return 1; }
    if((path(target,source,image) && io_open(&v->f,target,0)) || (path(target,source,ima) && io_open(&v->f,target,0)))
        { v->image=1; if(open_image(v,name)) return 1; io_close(&v->f); }
    return 0;
}
static int read_volume(Volume *v,uint32_t off,unsigned char *out,uint32_t n)
{
    while(n) {
        uint32_t k=n,at=off;
        if(v->image) {
            uint32_t in=off%v->cluster;
            if(off/v->cluster>=v->clusters) return 0;
            at=v->data+(v->chain[off/v->cluster]-2)*v->cluster+in;
            if(k>v->cluster-in) k=v->cluster-in;
        }
        if(off+k>v->size || !io_seek(&v->f,at) || !io_read(&v->f,out,k)) return 0;
        off+=k; out+=k; n-=k;
    }
    return 1;
}
static int hash_volume(Volume *v,uint32_t size,const unsigned char *want)
{
    SHA256 sha; unsigned char hash[32]; uint32_t pos;
    if(v->size!=size) return 0;
    sha_init(&sha);
    for(pos=0;pos<v->size;) {
        uint32_t k=v->size-pos; if(k>sizeof buffer)k=sizeof buffer;
        if(io_cancelled() || !read_volume(v,pos,buffer,k)) return 0;
        sha_update(&sha,buffer,k); pos+=k;
    }
    sha_final(&sha,hash);
    return !memcmp(hash,want,32);
}

/* The archive data as one stream: XWING.001 up to its catalog, then 002..005. */
typedef struct { uint32_t pos, left; int error; } Input;
static unsigned input(void *how,unsigned char **buf)
{
    Input *in=how; uint32_t n=in->left,pos=in->pos; unsigned v=0;
    uint32_t end=CATALOG;
    if(!n || io_cancelled()) return 0;
    while(v<VOLUMES-1 && pos>=end) { pos-=end; end=volume_size[++v]; }
    if(n>sizeof buffer) n=sizeof buffer;
    if(n>end-pos) n=end-pos;
    if(!read_volume(&volume[v],pos,buffer,n)) { in->error=1; return 0; }
    in->pos+=n; in->left-=n; *buf=buffer; return (unsigned)n;
}
typedef struct { File *f; uint32_t size, limit; } Output;
static int output(void *how,unsigned char *buf,unsigned len)
{
    Output *out=how;
    if(len>out->limit-out->size) return 1;
    out->size+=len;
    return !io_write(out->f,buf,len);
}

static int create(File *out,const char *dest,const char *file)
{
    char target[512];
    if(!path(target,dest,file) || io_exists(target) || !io_open(out,target,1)) return 0;
    memcpy(created[count++],file,strlen(file)+1);
    return 1;
}
static int write_file(const char *dest,const char *file,const void *data,uint32_t n)
{
    File out={0};
    return create(&out,dest,file) && io_write(&out,data,n) && io_close(&out);
}

int install_data(const char *source,const char *dest,const char *temp)
{
    File out={0}; char target[512];
    unsigned v,r,files=0; int ok=0;
    (void)temp; count=0;
    if(io_exists(dest)) { io_message("Destination exists; refusing to replace files."); return 20; }
    io_message("Checking the X-Wing disks...");
    for(v=0;v<VOLUMES;v++) {
        static char name[]="XWING.000";
        name[8]=(char)('1'+v);
        if(!open_file(&volume[v],source,v+1,name)) {
            io_message("Disk image or XWING file missing. Need disk1.img..disk5.img or XWING.001-005 and disk 1's files.");
            goto done;
        }
        if(!hash_volume(&volume[v],volume_size[v],volume_sha[v])) { io_message("Unsupported or damaged disks. Use the X-Wing 1.0 floppies."); goto done; }
    }
    if(!read_volume(&volume[0],CATALOG+6,catalog,sizeof catalog)) goto done;
    if(!io_mkdir(dest)) goto done;
    memcpy(created[count++],"",1);
    for(v=2;v<5;v++) {
        if(!path(target,dest,directory[v]) || !io_mkdir(target)) goto done;
        memcpy(created[count++],directory[v],strlen(directory[v])+1);
    }
    io_message("Extracting X-Wing...");
    for(r=0;r<RECORDS;r++) {
        const unsigned char *e=catalog+r*RECORD;
        char name[14],file[24]; unsigned d,disk,dir; uint32_t start,comp,size;
        Input in; Output o; unsigned char *rest; int bad;
        if(e[0]!=0x1a || e[19]&0x18) goto done;
        memcpy(name,e+6,13); name[13]=0;
        disk=e[30]; dir=e[43]; comp=le32(e+20); size=le32(e+33);
        if(disk<1 || disk>VOLUMES || dir<1 || dir>4 || !strlen(name) || comp>size || (e[5]==0xc8)!=(comp==size)) goto done;
        for(d=0;name[d];d++) if(!((name[d]>='A' && name[d]<='Z') || (name[d]>='0' && name[d]<='9') || name[d]=='.' || name[d]=='-' || name[d]=='_')) goto done;
        start=le32(e+1);
        for(d=1;d<disk;d++) start+=d==1?CATALOG:volume_size[d-1];
        if(dir==1) memcpy(file,name,strlen(name)+1);
        else { unsigned k=strlen(directory[dir]); memcpy(file,directory[dir],k); file[k]='/'; memcpy(file+k+1,name,strlen(name)+1); }
        if(!create(&out,dest,file)) goto done;
        in.pos=start; in.left=comp; in.error=0;
        o.f=&out; o.size=0; o.limit=size;
        if(e[5]==0xc8) {                                 /* stored */
            unsigned n;
            bad=0;
            while(!bad && (n=input(&in,&rest))) bad=output(&o,rest,n);
        } else bad=xw_unpack(e[5],input,&in,output,&o,size);
        if(bad || in.error || in.left || o.size!=size || !io_close(&out)) {
            io_message("Damaged archive data. Use the X-Wing 1.0 floppies.");
            goto done;
        }
        files++;
    }
    for(v=0;v<COPIES;v++) {
        uint32_t pos;
        if(!open_file(&loose,source,1,copy_name[v]) || !hash_volume(&loose,copy_size[v],copy_sha[v])) {
            io_message("Disk 1's INSTALL.EXE, DETECT.EXE or READ.ME missing or unsupported.");
            goto done;
        }
        if(!create(&out,dest,copy_name[v])) goto done;
        for(pos=0;pos<loose.size;) {
            uint32_t k=loose.size-pos; if(k>sizeof buffer)k=sizeof buffer;
            if(!read_volume(&loose,pos,buffer,k) || !io_write(&out,buffer,k)) goto done;
            pos+=k;
        }
        if(!io_close(&out)) goto done;
        io_close(&loose.f); files++;
    }
    if(!path(target,dest,"FASTYES.CFG") || !io_open(&loose.f,target,0) || loose.f.size>sizeof buffer
       || !io_read(&loose.f,buffer,loose.f.size) || !io_close(&loose.f)) goto done;
    if(!write_file(dest,"LANDRU.CFG",landru,sizeof landru-1) || !write_file(dest,"OPTIONS.CFG",buffer,loose.f.size)) goto done;
    files+=2;
    if(files!=FILES) goto done;
    ok=1; io_message("Installed 284 X-Wing files.");
done:
    io_close(&out); io_close(&loose.f);
    for(v=0;v<VOLUMES;v++) io_close(&volume[v].f);
    if(!ok) {
        while(count) {
            --count;
            if(!created[count][0]) io_remove(dest);
            else if(path(target,dest,created[count])) io_remove(target);
        }
        io_message("Installation failed or cancelled; existing installations were not changed.");
    }
    return ok?0:20;
}
