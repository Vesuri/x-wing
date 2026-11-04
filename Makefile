SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV := . amiga/env.sh &&

.PHONY: help verify-input extract-original-data reference check dos-emulator dos-disks dos-install dos-configure dos-reference dos-run dos-play map ghidra
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
