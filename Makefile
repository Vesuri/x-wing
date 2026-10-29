SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV := . amiga/env.sh &&

.PHONY: help verify-input extract-original-data reference check dos-emulator dos-disks dos-install dos-reference dos-play
help:
	@echo 'make verify-input           verify the staged demo archive'
	@echo 'make extract-original-data  extract both forks into tmp/runtime-data'
	@echo 'make reference              boot System 7.5.5 on a Quadra 700 and run the demo'
	@echo 'make check                  verify the inputs and shared compiler access'
	@echo 'make dos-emulator           build the scripted DOSBox-X (tools/patches)'
	@echo 'make dos-disks              extract the five DOS floppy images into tmp/dos/disks'
	@echo 'make dos-install            run the original installer into tmp/dos/installed'
	@echo 'make dos-reference          intro, copy protection and its control'
	@echo 'make dos-play               open a DOSBox-X window on a fresh copy of the game'

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

dos-reference:
	@$(ENV) python3 tools/dos_reference.py reference

dos-play:
	@$(ENV) python3 tools/dos_reference.py play
