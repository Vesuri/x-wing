SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV := . amiga/env.sh &&

.PHONY: help verify-input extract-original-data reference check dos-emulator dos-disks dos-install dos-configure dos-reference dos-run dos-play map ghidra test-x86 dos-oracle
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
