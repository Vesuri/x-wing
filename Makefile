SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV := . amiga/env.sh &&

.PHONY: help verify-input extract-original-data reference check dos-emulator dos-disks dos-install dos-configure dos-reference dos-run dos-play map ghidra test-x86 dos-oracle gen gen-check test-m68k host test-host amiga amiga-sync test-amiga test-amiga-live
help:
	@echo 'make verify-input           verify the staged demo archive'
	@echo 'make extract-original-data  extract both forks into tmp/runtime-data'
	@echo 'make reference              boot System 7.5.5 on a Quadra 700 and run the demo'
	@echo 'make check                  verify the inputs and shared compiler access'
	@echo 'make dos-emulator           build the scripted DOSBox-X (tools/patches)'
	@echo 'make dos-disks              extract the five DOS floppy images into tmp/dos/disks'
	@echo 'make dos-install            run the original installer into tmp/dos/installed'
	@echo 'make dos-configure          select AdLib in the installer; tmp/dos/configured/XWING'
	@echo 'make dos-reference          run and check every milestone (reference/milestones.csv)'
	@echo 'make dos-run RUN=n ARGS=..  one traced run (tools/pc_run.py) in ref/dosbox/runs/n'
	@echo 'make dos-play               play on a period 386, copy protection answered'
	@echo 'make map                    static and live map of the newest milestone set (tmp/sweep)'
	@echo 'make ghidra                 Ghidra project per code unit in tmp/ghidra-proj'
	@echo 'make dos-oracle             build the unpatched debug DOSBox-X for the RETF oracle'
	@echo 'make test-x86               gate 3: decoder cross-check, Unicorn differential, sabotage'
	@echo 'make gen                    translate the in-scope modules -> build/gen (audit, coverage)'
	@echo 'make gen-check              G1: headers, digests and byte-identical regeneration of build/gen'
	@echo 'make test-m68k              gate 4: gen-check, then 68020 differential, blocks, guards, sabotage'
	@echo 'make host                   link generated program + runtime for Unicorn 68020 -> build/host/xwing.elf'
	@echo 'make test-host              gate 5 host: lockstep to m01 against its host reference (tests/host_run.py)'
	@echo 'make amiga                  the A1200 image -> amiga/out/XWing.exe (SYNC=1: amiga-sync)'
	@echo 'make test-amiga             gate 5: m01 replayed on the 68030 model (A1200 chipset, FS-UAE + GDB capture; AMIGA_CPU)'
	@echo 'make test-amiga-live        the production image runs to the m01 label in real time (no compare)'

verify-input:
	@shasum -a 256 -c manifest/originals.sha256

extract-original-data: verify-input
	@$(ENV) python3 tools/extract_original_data.py

reference:
	@$(ENV) python3 tools/run_reference.py

check: verify-input
	@$(ENV) m68k-amiga-elf-gcc --version | head -1

dos-emulator:
	@tools/build_dosbox_x.sh

dos-disks: verify-input
	@$(ENV) python3 tools/dos_reference.py disks

dos-install: dos-disks
	@$(ENV) python3 tools/dos_reference.py install

dos-configure:
	@$(ENV) python3 tools/dos_reference.py configure

dos-reference:
	@$(ENV) python3 tools/reference.py

dos-run:
	@$(ENV) python3 tools/pc_run.py $(RUN) $(ARGS)

dos-play:
	@$(ENV) python3 tools/dos_reference.py play

map:
	@$(ENV) python3 tools/overlay_check.py $(MAP_ARGS)
	@$(ENV) python3 tools/sweep.py --annotations $(MAP_ARGS)
	@$(ENV) python3 tools/code_writes.py $(MAP_ARGS)
	@$(ENV) python3 tools/surface.py $(MAP_ARGS) > tmp/sweep/surface.md
	@$(ENV) python3 tools/census.py $(MAP_ARGS) > tmp/sweep/census.md
	@echo 'MAP PASS: tmp/sweep/surface.md, tmp/sweep/census.md'

ghidra:
	@$(ENV) python3 tools/ghidra_import.py

# Gate 3 (copied from Secret Weapons of the Luftwaffe's Makefile): each check logs to
# tmp/test/<name>.log and prints one status line; the differential runs in shards.
JOBS ?= $(shell sysctl -n hw.ncpu 2>/dev/null || nproc)
RUN = @mkdir -p tmp/test; if $(ENV) $(2) > tmp/test/$(1).log 2>&1; then echo "ok    $(1)"; \
	else echo "FAIL  $(1) (tmp/test/$(1).log)"; tail -n 15 tmp/test/$(1).log; exit 1; fi
SHARDS = forms.0/4 forms.1/4 forms.2/4 forms.3/4 space.0/1 boundary.0/1 blocks.0/1
X86_TESTS = t-decode $(subst /,-of-,$(SHARDS:%=t-x86-%)) t-sab-x86 t-oracle-boundary \
	t-sab-oracle-boundary t-oracle-exception-writes t-sab-oracle-exception-writes \
	t-dosbox-retf t-sab-dosbox-retf

# The boundary corpus and t-dosbox-retf need the debug DOSBox-X (make dos-oracle).
test-x86:
	@$(MAKE) -s -k -j$(JOBS) $(X86_TESTS)

t-decode:
	$(call RUN,decode,python3 tests/test_decode.py)
# t-x86-<corpus>.<k>-of-<n>: one shard of a differential corpus
CORPUS = $(word 1,$(subst ., ,$*))
SHARD = $(subst -of-,/,$(word 2,$(subst ., ,$*)))
t-x86-%:
	$(call RUN,x86-$*,python3 tests/x86_diff.py --only $(CORPUS) --shard $(SHARD))
t-sab-x86:
	$(call RUN,sabotage-x86,python3 tests/x86_sabotage.py)
t-oracle-boundary:
	$(call RUN,oracle-boundary,python3 tests/test_oracle_boundary.py)
t-sab-oracle-boundary:
	$(call RUN,sabotage-oracle-boundary,python3 tests/test_oracle_boundary.py --sabotage)
t-oracle-exception-writes:
	$(call RUN,oracle-exception-writes,python3 tests/test_oracle_exception_writes.py)
t-sab-oracle-exception-writes:
	$(call RUN,sabotage-oracle-exception-writes,python3 tests/test_oracle_exception_writes.py --sabotage)
t-dosbox-retf:
	$(call RUN,dosbox-retf,python3 tests/test_dosbox_retf.py)
t-sab-dosbox-retf:
	$(call RUN,sabotage-dosbox-retf,python3 tests/test_dosbox_retf.py --sabotage)

dos-oracle:
	@tools/build_dosbox_x_debug.sh

# Gate 4 (copied from Secret Weapons of the Luftwaffe's Makefile). The checks run in
# parallel after the one writer of build/gen (gen-check, which regenerates and
# compares). The boundary shard records its x86 side for the sabotage plants.
M68K_TESTS = $(subst /,-of-,$(SHARDS:%=t-m68k-%)) t-blocks t-guards t-sab-m68k
gen:
	@$(ENV) python3 -m translator.gen
gen-check:
	@$(ENV) python3 -m translator.check gen --regen
test-m68k: gen
	@$(MAKE) -s gen-check
	@$(MAKE) -s -k -j$(JOBS) $(M68K_TESTS)
t-m68k-%:
	$(call RUN,m68k-$*,python3 tests/m68k_diff.py --only $(CORPUS) --shard $(SHARD))
t-m68k-boundary.0-of-1:
	$(call RUN,m68k-boundary.0-of-1,python3 tests/m68k_diff.py --only boundary --shard 0/1 \
		--record tmp/test/x86-side-boundary.pkl)
t-blocks:
	$(call RUN,blocks,python3 tests/m68k_blocks.py)
t-guards:
	$(call RUN,guards,python3 tests/test_guards.py)
t-sab-m68k: t-m68k-boundary.0-of-1
	$(call RUN,sabotage-m68k,python3 tests/m68k_sabotage.py)

# P5: the generated program with the runtime for Unicorn 68020 (tests/host_run.py),
# copied from Secret Weapons of the Luftwaffe's host build. XWING_SYNC: poll checks
# at the sync points; interrupts are replayed there.
CROSS     = $${AMIGA_TOOLCHAIN}/bin/m68k-amiga-elf-
VASMELF   = $${VASM} -quiet -m68020 -Felf -x -nowarn=62
RT_CFLAGS = -m68020 -O2 -ffreestanding -nostdlib -fomit-frame-pointer \
	-fno-tree-loop-distribute-patterns -Wall -Wextra -Werror -Isrc/runtime -DXWING_SYNC
RUNTIME_C = $(wildcard src/runtime/*.c)
HOST_OBJ  = build/host/host_s.o build/host/host.o build/host/rt_entry.o \
	$(patsubst src/runtime/%.c,build/host/%.o,$(RUNTIME_C)) build/host/program.o

build/host/program.o: build/gen/program.s $(wildcard build/gen/*.s)
	@mkdir -p $(dir $@)
	@$(ENV) cd build/gen && $(VASMELF) -DXWING_SYNC=1 -o ../host/program.o program.s
build/host/rt_entry.o: src/runtime/rt_entry.s
	@mkdir -p $(dir $@)
	@$(ENV) $(VASMELF) -Isrc/runtime -o $@ $<
build/host/host_s.o: src/platform/host/host.s
	@mkdir -p $(dir $@)
	@$(ENV) $(VASMELF) -o $@ $<
build/host/host.o: src/platform/host/host.c src/runtime/runtime.h src/runtime/platform.h
	@mkdir -p $(dir $@)
	@$(ENV) $(CROSS)gcc $(RT_CFLAGS) -c -o $@ $<
build/host/%.o: src/runtime/%.c src/runtime/runtime.h src/runtime/platform.h
	@mkdir -p $(dir $@)
	@$(ENV) $(CROSS)gcc $(RT_CFLAGS) -c -o $@ $<
build/host/xwing.elf: $(HOST_OBJ)
	@$(ENV) $(CROSS)ld -Ttext=0x10000 -e _start -o $@ $(HOST_OBJ)
host: gen-check build/host/xwing.elf

HOST_MILESTONES = m01-logo
t-host-%:
	$(call RUN,host-$*,python3 tests/host_run.py --milestone $*)
test-host: host
	@$(MAKE) -s -k -j$(JOBS) $(HOST_MILESTONES:%=t-host-%)

# The A1200 image (amiga/Makefile), copied from Secret Weapons of the Luftwaffe's.
# test-amiga (gate 5): the diagnostic replay image (tests/amiga_replay.py) replays
# the host reference's interrupts, REP slices, VGA status reads and clocks on the
# 68030 model; its capture at the milestone gets the host run's checks.
# test-amiga-live: the production image runs to the milestone label in real time
# (amiga/milestone.gdb.in); its state is timing-dependent, so it is not compared.
AMIGA_MILESTONE ?= m01-logo
AMIGA_CPU       ?= 68030
AMIGA_CAPTURE    = tmp/amiga-capture/$(AMIGA_MILESTONE)
amiga: gen-check
	@$(ENV) $(MAKE) -C amiga
amiga-sync: gen-check
	mkdir -p build/amiga-sync && ln -sf ../../amiga/Makefile build/amiga-sync/Makefile
	@$(ENV) $(MAKE) -C build/amiga-sync REPO=../.. SYNC=1
test-amiga: host
	$(ENV) AMIGA_CPU=$(AMIGA_CPU) python3 tests/amiga_replay.py --milestone $(AMIGA_MILESTONE)
test-amiga-live: amiga
	@mkdir -p $(AMIGA_CAPTURE)
	sed -e "s|@LABEL@|$$(python3 tests/host_run.py --label --milestone $(AMIGA_MILESTONE))|" \
		-e "s|@OUT@|../$(AMIGA_CAPTURE)|" amiga/milestone.gdb.in > $(AMIGA_CAPTURE)/fixture.gdb
	$(ENV) cd amiga && AMIGA_CPU=$(AMIGA_CPU) ./debug.sh "" "../$(AMIGA_CAPTURE)/fixture.gdb" 2>&1 | \
		tee ../$(AMIGA_CAPTURE)/gdb.log
	grep -q '^XWING_MILESTONE_OK$$' $(AMIGA_CAPTURE)/gdb.log
