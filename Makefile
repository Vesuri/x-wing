SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV := . amiga/env.sh &&

.PHONY: help verify-input extract-original-data reference check
help:
	@echo 'make verify-input           verify the staged demo archive'
	@echo 'make extract-original-data  extract both forks into tmp/runtime-data'
	@echo 'make reference              boot System 7.5.5 on a Quadra 700 and run the demo'
	@echo 'make check                  verify the inputs and shared compiler access'

verify-input:
	@shasum -a 256 -c manifest/originals.sha256

extract-original-data: verify-input
	@$(ENV) python3 tools/extract_original_data.py

reference:
	@$(ENV) python3 tools/run_reference.py

check: verify-input
	@$(ENV) m68k-amiga-elf-gcc --version | head -1
