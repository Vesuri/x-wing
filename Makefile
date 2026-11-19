SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV := . amiga/env.sh &&

.PHONY: help verify-input extract-original-data reference check dos-emulator dos-disks dos-install dos-configure dos-reference dos-run dos-play map ghidra test-x86 dos-oracle gen gen-check gen-fresh test-m68k host test-host amiga amiga-sync test-amiga test-amiga-live test-amiga-audio t-sfx-capture t-sab-sfx-capture t-amiga-sfx t-resume-plants t-sab-resume sound-reference sound-fm gates-audio
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
	@echo 'make gen-fresh              G1 headers and digests only (what make host and make amiga run)'
	@echo 'make test-m68k              gate 4: gen-check, then 68020 differential, blocks, guards, sabotage'
	@echo 'make host                   link generated program + runtime for Unicorn 68020 -> build/host/xwing.elf'
	@echo 'make test-host              gate 5 host: lockstep to m01 against its host reference (tests/host_run.py)'
	@echo 'make t-resume-M             host lockstep to flight milestone M from its save at the flight start (else from boot, saving)'
	@echo 'make t-resume-plants        a resume refuses changes to what ran before its save (no host run)'
	@echo 'make t-sab-resume           a resume with an EMS mapping or a file position left out must diverge'
	@echo 'make amiga                  the A1200 image -> amiga/out/XWing.exe (SYNC=1: amiga-sync)'
	@echo 'make test-amiga             gate 5: m01 replayed on the 68030 model (A1200 chipset, FS-UAE + GDB capture; AMIGA_CPU)'
	@echo 'make test-amiga-live        the production image runs to the m01 label in real time (no compare)'
	@echo 'make test-amiga-audio       the production image plays music past the m01 label (key-ons, renders, restarts)'
	@echo 'make sound-reference        milestone runs with the OPL log; Nuked OPL WAVs in tmp/sound'
	@echo 'make sound-fm               the FM re-hoster's Paula WAVs beside them'
	@echo 'make t-amiga-sfx            the effects in flight: the m12 Amiga replay with capture and player (no host check)'
	@echo 'make gates-audio            every sound check and its sabotage'

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
# The image builds need only fresh, unedited build/gen (G1 headers and digests);
# the byte-identical regeneration is gen-check's, run by test-m68k.
gen-fresh:
	@$(ENV) python3 -m translator.check gen
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
# XWING_RESUME and one section per function and object: the resume's fingerprints
# (tests/host_resume.py) compare what ran before a save by input section.
RT_CFLAGS = -m68020 -O2 -ffreestanding -nostdlib -fomit-frame-pointer \
	-fno-tree-loop-distribute-patterns -Wall -Wextra -Werror -Isrc/runtime -DXWING_SYNC \
	-DXWING_RESUME -ffunction-sections -fdata-sections
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
	@$(ENV) $(CROSS)ld -Ttext=0x10000 -e _start -Map=$(@:.elf=.map) -o $@ $(HOST_OBJ)
host: gen-fresh build/host/xwing.elf

HOST_MILESTONES = m01-logo
t-host-%:
	$(call RUN,host-$*,python3 tests/host_run.py --milestone $*)
test-host: host
	@$(MAKE) -s -k -j$(JOBS) $(HOST_MILESTONES:%=t-host-%)
# The effect capture (src/runtime/sfx.c): host lockstep to its return in the m12
# flight, compared with tools/sfx_capture.py and the guest as before it; saved for
# its plants, which run on the saved capture in seconds.
SFX_MILESTONE = m12-training-flight
SFX_TIMEOUT   = 10000
t-sfx-capture: host
	$(call RUN,sfx-capture,python3 tests/host_run.py --milestone $(SFX_MILESTONE) --bypass --sfx-capture --resume --timeout $(SFX_TIMEOUT))
t-sab-sfx-capture:
	$(call RUN,sabotage-sfx-capture,python3 tests/host_run.py --sfx-plants)
# Host lockstep resume (tests/host_resume.py, docs/translator-design.md Resume): a
# flight milestone from its save at the flight's start (tmp/resume) when nothing that
# ran before the save changed, else from boot, saving anew. Its controls: changes to
# what ran before the save are refused and others are not (on the save, no host run);
# a resume with the handles' EMS mappings or an open file's position left out fails
# with a lockstep divergence (a timeout alone does not count): a planted run leaves
# the reference's path and need not reach the milestone, so it gets PLANT_TIMEOUT
# (seconds; an unplanted m12 resume runs in about 200).
RESUME_MILESTONE = m12-training-flight
RESUME_TIMEOUT   = 40000
PLANT_TIMEOUT    = 600
DIVERGED = ^(reference irq \#[0-9]+ .* not reached \(service events|service \#[0-9]+ |host: .*bytes differ|host: register |host: machine byte |frame: |EMS: guest read )
t-resume-%: host
	$(call RUN,resume-$*,python3 tests/host_run.py --milestone $* --bypass --resume --timeout $(RESUME_TIMEOUT))
t-resume-plants:
	$(call RUN,resume-plants,python3 tests/host_run.py --milestone $(RESUME_MILESTONE) --bypass --resume-plants)
t-sab-resume: host
	@mkdir -p tmp/test; for p in ems file; do \
		log=tmp/test/sabotage-resume-$$p.log; \
		if $(ENV) python3 tests/host_run.py --milestone $(RESUME_MILESTONE) --bypass --resume-plant $$p \
			--timeout $(PLANT_TIMEOUT) > $$log 2>&1; then echo "FAIL  plant $$p not caught ($$log)"; exit 1; \
		elif grep -q "^host run to .*: FAIL" $$log && grep -Eq '$(DIVERGED)' $$log; then \
			echo "ok    plant $$p caught: $$(grep -E '$(DIVERGED)' $$log | head -n 1)"; \
		else echo "FAIL  plant $$p: no lockstep divergence ($$log)"; tail -n 5 $$log; exit 1; fi; done

# The A1200 image (amiga/Makefile), copied from Secret Weapons of the Luftwaffe's.
# test-amiga (gate 5): the diagnostic replay image (tests/amiga_replay.py) replays
# the host reference's interrupts, REP slices, VGA status reads and clocks on the
# 68030 model; its capture at the milestone gets the host run's checks.
# AMIGA_ARGS: --screen (m03, m03c, m03p, m03q) or --bypass (later milestones);
# m10 and m15 also --exempt with tests/host_run.py --bypass --exempt-out of the same
# milestone; a later milestone needs a longer --timeout (AMIGA_ARGS) than the default hour.
# test-amiga-live: the production image runs to the milestone label in real time
# (amiga/milestone.gdb.in); its state is timing-dependent, so it is not compared.
AMIGA_MILESTONE ?= m01-logo
AMIGA_CPU       ?= 68030
AMIGA_CAPTURE    = tmp/amiga-capture/$(AMIGA_MILESTONE)
amiga: gen-fresh
	@$(ENV) $(MAKE) -C amiga
amiga-sync: gen-fresh
	mkdir -p build/amiga-sync && ln -sf ../../amiga/Makefile build/amiga-sync/Makefile
	@$(ENV) $(MAKE) -C build/amiga-sync REPO=../.. SYNC=1
test-amiga: host
	$(ENV) AMIGA_CPU=$(AMIGA_CPU) python3 tests/amiga_replay.py --milestone $(AMIGA_MILESTONE) $(AMIGA_ARGS)
test-amiga-live: amiga
	@mkdir -p $(AMIGA_CAPTURE)
	sed -e "s|@LABEL@|$$(python3 tests/host_run.py --label --milestone $(AMIGA_MILESTONE))|" \
		-e "s|@OUT@|../$(AMIGA_CAPTURE)|" amiga/milestone.gdb.in > $(AMIGA_CAPTURE)/fixture.gdb
	$(ENV) cd amiga && AMIGA_CPU=$(AMIGA_CPU) ./debug.sh "" "../$(AMIGA_CAPTURE)/fixture.gdb" 2>&1 | \
		tee ../$(AMIGA_CAPTURE)/gdb.log
	grep -q '^XWING_MILESTONE_OK$$' $(AMIGA_CAPTURE)/gdb.log
# Music on Paula: the production image past the label (amiga/audio.gdb.in); key-on
# edges, re-hoster renders and Paula restarts must all be above 0.
AUDIO_FIELDS ?= 500
test-amiga-audio: amiga
	@mkdir -p $(AMIGA_CAPTURE)
	sed -e "s|@LABEL@|$$(python3 tests/host_run.py --label --milestone $(AMIGA_MILESTONE))|" \
		-e "s|@FIELDS@|$(AUDIO_FIELDS)|" amiga/audio.gdb.in > $(AMIGA_CAPTURE)/audio.gdb
	$(ENV) cd amiga && AMIGA_CPU=$(AMIGA_CPU) ./debug.sh "" "../$(AMIGA_CAPTURE)/audio.gdb" 2>&1 | \
		tee ../$(AMIGA_CAPTURE)/audio.log
	grep -Eq '^XWING_AUDIO fields=[0-9]+ irq0=[0-9]+ keyons=[1-9][0-9]* renders=[1-9][0-9]* restarts=[1-9][0-9]*$$' \
		$(AMIGA_CAPTURE)/audio.log

# AdLib FM on Paula (P7), copied from Secret Weapons of the Luftwaffe's Makefile: the
# re-hoster (src/platform/amiga/fm_paula.c) on the OPL logs of milestone runs
# (tools/reference.py --opl, named sound-<milestone>), checked against Nuked OPL from the
# DOSBox-X tree (tools/build_dosbox_x.sh).
DOSBOX_X_SRC ?= $(or $(XWING_DOSBOX_X_SRC),$(HOME)/.local/src/xwing-dosbox-x)
NUKED = $(DOSBOX_X_SRC)/src/hardware
FM_RUNS = m01-logo m02-title m06-concourse-pilot-saved m13-mission-flight
FM_OPL = ref/dosbox/runs/sound-$(1)/trace/opl.csv
build/tools/opl_render: tools/opl_render.cpp
	mkdir -p build/tools
	c++ -O2 -std=c++17 -I$(NUKED) -o $@ $< $(NUKED)/nukedopl.cpp
build/tools/fm_check: tools/fm_check.cpp src/platform/amiga/fm_paula.c src/platform/amiga/fm_paula.h
	mkdir -p build/tools
	cc -O2 -std=c99 -Wall -Wextra -Werror -c -o build/tools/fm_paula.o src/platform/amiga/fm_paula.c
	c++ -O2 -std=c++17 -Isrc/platform/amiga -I$(NUKED) -o $@ $< build/tools/fm_paula.o $(NUKED)/nukedopl.cpp
sound-reference: build/tools/opl_render
	python3 tools/reference.py --opl --jobs 2 --name sound $(FM_RUNS)
	mkdir -p tmp/sound
	for r in $(FM_RUNS); do build/tools/opl_render $(call FM_OPL,$$r) tmp/sound/$$r-fm.wav || exit 1; done
build/tools/fm_effect_check: tools/fm_effect_check.cpp src/platform/amiga/fm_paula.c src/platform/amiga/fm_paula.h
	@mkdir -p build/tools
	cc -O2 -std=c99 -Wall -Wextra -Werror -c -o build/tools/fm_effect_paula.o src/platform/amiga/fm_paula.c
	c++ -O2 -std=c++17 -Isrc/platform/amiga -I$(NUKED) -o $@ $< build/tools/fm_effect_paula.o $(NUKED)/nukedopl.cpp
# Prerendered effects against Nuked OPL on the original driver's captures
# (tools/sfx_capture.py from the m13 reference snapshot); WAVs in tmp/sound/sfx-wav.
tmp/sound/sfx-writes.csv: tools/sfx_capture.py
	python3 tools/sfx_capture.py
t-fm-effect: build/tools/fm_effect_check tmp/sound/sfx-writes.csv
	$(call RUN,fm-effect,mkdir -p tmp/sound/sfx-wav && build/tools/fm_effect_check tmp/sound/sfx-writes.csv tmp/sound/sfx-wav)
t-sab-fm-effect: build/tools/fm_effect_check tmp/sound/sfx-writes.csv
	$(call RUN,sabotage-fm-effect,mkdir -p tmp/test/sfx-wav && for s in pitch level end fade; do \
		! build/tools/fm_effect_check tmp/sound/sfx-writes.csv tmp/test/sfx-wav --sabotage $$s || exit 1; done)
# The prerender's assembly loop (fm_effect_run.s) on the 68020 core against the C loop.
t-fm-effect-asm: tmp/sound/sfx-writes.csv
	$(call RUN,fm-effect-asm,. amiga/env.sh && python3 tests/test_fm_effect_asm.py)
t-sab-fm-effect-asm: tmp/sound/sfx-writes.csv
	$(call RUN,sabotage-fm-effect-asm,. amiga/env.sh && python3 tests/test_fm_effect_asm.py --sabotage)
sound-fm: build/tools/fm_check
	mkdir -p tmp/sound
	-for r in $(FM_RUNS); do build/tools/fm_check $(call FM_OPL,$$r) tmp/sound/$$r-paula.wav; done
t-fm: build/tools/fm_check
	$(call RUN,fm-paula,mkdir -p tmp/sound && for r in $(FM_RUNS); do \
		build/tools/fm_check $(call FM_OPL,$$r) tmp/sound/$$r-paula.wav || exit 1; done)
t-sab-fm: build/tools/fm_check
	$(call RUN,sabotage-fm-paula,for s in pitch level; do \
		! build/tools/fm_check $(call FM_OPL,m13-mission-flight) tmp/test/fm-sabotage.wav --sabotage $$s || exit 1; done)
FM_UNITS = quality render phase envelope allocation cache
t-fm-%:
	$(call RUN,fm-$*,python3 tests/test_fm_$*.py)
t-sab-fm-%:
	$(call RUN,sabotage-fm-$*,python3 tests/test_fm_$*.py --sabotage)
# The effect player (src/platform/amiga/fx_play.c) on synthetic driver states.
t-fx-play:
	$(call RUN,fx-play,python3 tests/test_fx_play.py)
t-sab-fx-play:
	$(call RUN,sabotage-fx-play,python3 tests/test_fx_play.py --sabotage)
# The effects in flight on the 68030 model: the Amiga replay to m12 with the capture,
# the prerender and the player running; no host check (tests/amiga_replay.py --sfx).
t-amiga-sfx: host
	$(ENV) AMIGA_CPU=$(AMIGA_CPU) python3 tests/amiga_replay.py --milestone $(SFX_MILESTONE) --screen --sfx
# Isolated audio changes: the sound checks and their plants.
gates-audio:
	@$(MAKE) -s -k -j$(JOBS) t-fm t-sab-fm $(FM_UNITS:%=t-fm-%) $(FM_UNITS:%=t-sab-fm-%) \
		t-fm-effect t-sab-fm-effect t-fm-effect-asm t-sab-fm-effect-asm t-fx-play t-sab-fx-play
