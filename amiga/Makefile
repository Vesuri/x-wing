# X-Wing — Amiga cross-build (m68k-amiga-elf-gcc), A1200 68020/AGA.
# Copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and adapted.
#
#   . ./env.sh && make   — build out/XWing.exe (SYNC=1: the sync image)
#   make clean           — remove obj/ and out/
#   ./run.sh             — boot in FS-UAE (A1200, Kickstart 3.1)
#   ./debug.sh [ROM] [fixture.gdb] — source-level debug via the FS-UAE GDB stub
#
# Code lives under $(REPO)/src; this directory holds only build infrastructure.

OUT      = out/XWing
CC       = m68k-amiga-elf-gcc
AS       = m68k-amiga-elf-as
VASM     = vasmm68k_mot
OBJDUMP  = m68k-amiga-elf-objdump
PYTHON   = python3
SDKDIR   = $(abspath $(dir $(shell which $(CC)))../m68k-amiga-elf/sys-include)
SUPPORT  = $(abspath $(dir $(shell which $(CC)))../../support)
REPO      = ..
AMIGA_PYLIB ?= $(HOME)/.local/share/amiga/pylib
AMIGA_SRC = $(REPO)/src/platform/amiga
FRAMEWORK = $(AMIGA_SRC)/framework
RUNTIME   = $(REPO)/src/runtime
GEN       = $(REPO)/build/gen

CCFLAGS  = -g -MP -MMD -m68020 -msoft-float -O2 -nostdlib \
	-fomit-frame-pointer -fno-tree-loop-distribution \
	-ffunction-sections -fdata-sections -Wall -Wextra -Werror \
	-Wno-volatile-register-var
CPPFLAGS = $(CCFLAGS) -fno-rtti -fno-exceptions -fno-use-cxa-atexit -fcheck-new \
	-std=gnu++17 -fpermissive -Wno-write-strings -Wno-pointer-arith \
	-Wno-ignored-qualifiers -Wno-sign-compare \
	-Wno-parentheses -Wno-unused-parameter \
	-include "$(FRAMEWORK)/SASCCompat.h" \
	-I"$(FRAMEWORK)" -I"$(FRAMEWORK)/compat-include" -I"$(AMIGA_SRC)" -I"$(RUNTIME)"
ASFLAGS  = -mcpu=68020 -g --register-prefix-optional -I"$(SDKDIR)"
VASMFLAGS = -m68020 -Felf -quiet -x -no-opt -nowarn=62 -I"$(SDKDIR)" -Iobj
# Generated code: vasm picks branch sizes (translator/emit.py output, never edited).
VASMGEN  = -m68020 -Felf -quiet -x -nowarn=62
LDFLAGS  = -Wl,--emit-relocs,--gc-sections,-Ttext=0,-Map=$(OUT).map

# start.o first: DOS enters the first hunk at offset 0, and the link check below
# holds _start there.
OBJECTS = obj/start.o obj/main.o obj/XWing.o obj/Input.o obj/Audio.o obj/GCCRuntime.o \
	obj/framework_amiga_hardware.o obj/framework_bitmap.o \
	obj/framework_copper_list.o obj/framework_palette24.o \
	obj/gcc8_c_support.o obj/gcc8_a_support.o obj/memory.o obj/version.o \
	obj/amiga_platform.o obj/fm_paula.o obj/amiga_run.o obj/c2p1x1_8_c5_bm.o obj/rt_entry.o \
	$(patsubst $(RUNTIME)/%.c,obj/rt_%.o,$(wildcard $(RUNTIME)/*.c)) obj/program.o

# Sync image (Secret Weapons of the Luftwaffe's docs/irq-plan.md I8): the
# generated sync-point checks and the runtime's sync mode (no tick at the CIA
# interrupt, keys as IRQ1), for make amiga-sync and every replay image.
# Production has neither.
ifneq ($(SYNC)$(REPLAY),)
CCFLAGS += -DXWING_SYNC
VASMGEN += -DXWING_SYNC=1
VASMFLAGS += -DXWING_SYNC=1
endif

# Diagnostic replay image (tests/amiga_replay.py), built in its own working
# directory from the reference's recorded inputs in $(REPLAY); never a release.
ifneq ($(REPLAY),)
CCFLAGS += -DXWING_REPLAY -I"$(REPLAY)"
VASMFLAGS += -DXWING_REPLAY=1
# --screen: the copy-protection hook declines, so the translated screen runs
ifneq ($(REPLAY_SCREEN),)
VASMFLAGS += -DXWING_REPLAY_SCREEN=1
endif
OBJECTS += obj/replay_c.o obj/replay_s.o
obj/replay_c.o: $(REPO)/tests/amiga_replay.c $(REPLAY)/replay_data.h | obj
	$(CC) $(CCFLAGS) -ffreestanding -I"$(RUNTIME)" -c -o $@ $<
obj/replay_s.o: $(REPO)/tests/amiga_replay.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<
endif

# Release image: no diagnostic arguments or tool types (amiga_platform.c).
ifneq ($(RELEASE),)
CCFLAGS += -DXWING_RELEASE
endif

.DEFAULT_GOAL := all
.PHONY: all clean verify-runtime
# Never leave a truncated executable that looks up to date after elf2hunk fails.
.DELETE_ON_ERROR:

all: $(OUT).exe

obj out:
	mkdir -p $@

verify-runtime: obj/gcc8_c_support.o
	PYTHONPATH='$(AMIGA_PYLIB)' $(PYTHON) -m amigaxdev.dos.verify_amiga_runtime $(OBJDUMP) $<

obj/start.o: $(AMIGA_SRC)/start.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -c -o $@ $<

obj/main.o: $(REPO)/src/main.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/XWing.o: $(AMIGA_SRC)/XWing.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/Audio.o: $(AMIGA_SRC)/Audio.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/Input.o: $(AMIGA_SRC)/Input.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/GCCRuntime.o: $(AMIGA_SRC)/GCCRuntime.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_amiga_hardware.o: $(FRAMEWORK)/AmigaHardware.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_bitmap.o: $(FRAMEWORK)/Bitmap.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_copper_list.o: $(FRAMEWORK)/CopperList.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_palette24.o: $(FRAMEWORK)/Palette24Bit.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/gcc8_c_support.o: $(SUPPORT)/gcc8_c_support.c Makefile | obj
	# Runtime implementations must not be folded into calls to themselves.
	# Its _start loses main's result and the Workbench message: start.c's runs.
	$(CC) $(CCFLAGS) -fno-builtin -Dmemcpy=xwing_support_memcpy -Dmemset=xwing_support_memset \
		-D_start=xwing_unused_shared_start -c -o $@ $<

obj/gcc8_a_support.o: $(SUPPORT)/gcc8_a_support.s | obj
	$(AS) $(ASFLAGS) -o $@ $<

obj/memory.o: $(AMIGA_SRC)/memory.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<

obj/amiga_platform.o: $(AMIGA_SRC)/amiga_platform.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -I"$(RUNTIME)" -I"$(AMIGA_SRC)" -c -o $@ $<

obj/fm_paula.o: $(AMIGA_SRC)/fm_paula.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -c -o $@ $<

obj/amiga_run.o: $(AMIGA_SRC)/amiga_run.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<

obj/c2p1x1_8_c5_bm.o: $(AMIGA_SRC)/c2p1x1_8_c5_bm.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<

obj/rt_%.o: $(RUNTIME)/%.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -I"$(RUNTIME)" -c -o $@ $<

obj/rt_entry.o: $(RUNTIME)/rt_entry.s | obj
	$(VASM) $(VASMFLAGS) -I"$(RUNTIME)" -o $@ $<

obj/program.o: $(GEN)/program.s $(wildcard $(GEN)/*.s) | obj
	$(VASM) $(VASMGEN) -I"$(GEN)" -o $@ $<

obj/version.o: $(AMIGA_SRC)/version.s | obj
	$(AS) $(ASFLAGS) -o $@ $<

$(OUT).elf: $(OBJECTS) | out verify-runtime
	$(CC) $(CCFLAGS) $(LDFLAGS) $(OBJECTS) -o $@
	@test "$$($(OBJDUMP) -t $@ | awk '$$NF == "_start" && $$4 == ".text" { print $$1 }')" = 00000000 || \
		{ echo "_start is not at the hunk start" >&2; rm -f $@; exit 1; }
	@# A restart's DMA-off window polls VHPOSR between the two DMACON writes
	@# (a non-volatile poll compiled to nothing: 0.91 on a 68040).
	@$(OBJDUMP) -d -C --no-show-raw-insn $@ | awk '/<Audio::verticalBlank\(\)>:/ { f = 1; next } \
		f && /^$$/ { exit } f && /dff096/ { d++ } f && d == 1 && /dff006/ { w = 1 } \
		END { exit !(d >= 2 && w) }' || \
		{ echo "Audio::verticalBlank: no VHPOSR wait between the DMACON writes" >&2; rm -f $@; exit 1; }
	$(OBJDUMP) --disassemble --no-show-raw-ins -S $@ > $(OUT).s 2>/dev/null || true

# Kickstart 3.1's LoadSeg reads at most 65535 offsets per RELOC32 block (tools/hunk_relocs.py).
$(OUT).exe: $(OUT).elf
	elf2hunk $< $@
	$(PYTHON) $(REPO)/tools/hunk_relocs.py $@

clean:
	$(RM) -r obj out

-include obj/*.d

