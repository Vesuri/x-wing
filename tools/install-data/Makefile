# Run from anywhere: make -C tools/install-data [amiga|test]
# Source amiga/env.sh before building the Amiga binary.
# io*, sha256*, start.s, COPYING.LIB: AmigaXDev install-data as vendored by Secret
# Weapons of the Luftwaffe, unchanged and pinned in vendored.sha256.
ROOT := ../..
BUILD ?= $(ROOT)/build/install-data
CC ?= cc
CFLAGS ?= -O2 -g
WARN = -std=c99 -Wall -Wextra -Werror
SOURCES = install.c sha256.c xwunpack.c
HEADERS = io.h sha256.h xwunpack.h install_config.h
AMIGA_CC = m68k-amiga-elf-gcc
AMIGA_NM = $(dir $(shell command -v $(AMIGA_CC)))../m68k-amiga-elf/bin/nm
# 68020 like the game: 32-bit divide in the FAT12 reader, no libgcc.
AMIGA_FLAGS = -std=c99 -O2 -g -m68020 -msoft-float -nostdlib -fno-builtin -fno-tree-loop-distribute-patterns -fstack-usage -Wall -Wextra -Wno-volatile-register-var -DINSTALL_AMIGA
AMIGA_OBJECTS = $(BUILD)/start.o $(BUILD)/install.o $(BUILD)/xwunpack.o $(BUILD)/sha256.o $(BUILD)/io_amiga.o
.PHONY: all amiga test pinned
all: pinned $(BUILD)/XWingInstallData
pinned:
	@shasum -a 256 -c --quiet vendored.sha256
$(BUILD):
	mkdir -p $@
$(BUILD)/XWingInstallData: $(SOURCES) io_unix.c $(HEADERS) | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) $(SOURCES) io_unix.c -o $@
amiga: pinned $(BUILD)/XWingInstallData.exe
$(BUILD)/%.o: %.c $(HEADERS) Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -c $< -o $@
$(BUILD)/start.o: start.s | $(BUILD)
	$(AMIGA_CC) -m68020 -c $< -o $@
$(BUILD)/XWingInstallData.elf: $(AMIGA_OBJECTS)
	$(AMIGA_CC) -nostdlib -m68020 -Wl,--emit-relocs,-Ttext=0,-e,_start,-Map=$(BUILD)/XWingInstallData.map $^ -o $@
	$(AMIGA_NM) -u $@ > $(BUILD)/undefined.txt
	@test ! -s $(BUILD)/undefined.txt
$(BUILD)/XWingInstallData.exe: $(BUILD)/XWingInstallData.elf
	elf2hunk $< $@ -s
test: all
	python3 test_install.py $(BUILD)/XWingInstallData
