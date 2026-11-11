#!/usr/bin/env bash
# Boot the Amiga build on the A1200 chipset. Left mouse button quits.
#   ./run.sh [path-to-kickstart-rom]
# Run a different binary with $XWING_EXE, arguments with $XWING_ARGS; extra fs-uae args via $EXTRA_ARGS (they win);
# AMIGA_CPU picks the CPU (68030: the minimum target model); DEBUG=1 adds the gdb stub.
set -euo pipefail
cd "$(dirname "$0")"
. ./env.sh
. "$FSUAE_COMMON"

ROM="${1:-$KICKSTART}"
EXE="${XWING_EXE:-out/XWing.exe}"
# The game directory as installed and configured (docs/dos-reference.md): the
# guest's C:\XWING, the current directory of the run.
GAME=../tmp/dos/configured/XWING
[ -f "$ROM" ] || { echo "Kickstart ROM not found: $ROM"; exit 1; }
[ -f "$EXE" ] || { echo "not found: $EXE  (build first: make)"; exit 1; }
[ -f "$GAME/XWING.EXE" ] || { echo "game directory not found: $GAME  (make dos-reference)"; exit 1; }

# KS 3.1 sets the AGA bits in GfxBase only after SetPatch (Secret Weapons of the Luftwaffe's docs/amiga-lessons.md L8).
[ -f "$SETPATCH" ] || { echo "SetPatch not found: $SETPATCH"; exit 1; }
RUN="$FSUAE_RUN"; DH0="$RUN/dh0"; DH1="$RUN/dh1"
mkdir -p "$DH0/c" "$DH0/s" "$DH1" "$RUN/state"
# The `cd` form is load-bearing for the GDB harnesses; keep both scripts alike.
printf 'C:SetPatch QUIET\ncd dh1:\nXWing %s\n' "${XWING_ARGS:-}" > "$DH0/s/startup-sequence"
cp -f "$SETPATCH" "$DH0/c/SetPatch"
rsync -a --delete "$GAME/" "$DH1/"
# The program goes on the boot volume's C:, run by name as before: the game
# directory stays the guest's C:\XWING entry for entry (its find-first scans
# count the entries).
cp -f "$EXE" "$DH0/c/XWing"
# A resumed .uss saved by a halted GDB session makes any build look frozen.
rm -f "$RUN"/state/*.uss

fsuae_prepare
# Model, memory, sound and window: fsuae_options in $FSUAE_COMMON.
KICKSTART="$ROM" AMIGA_MODEL=A1200 CPU="${CPU:-${AMIGA_CPU:-}}"
CHIP_KB=2048 FAST_KB="${FAST_KB:-${FAST_MEMORY:-8192}}"
fsuae_options
fsuae_exec \
  --hard_drive_0="$DH0" --hard_drive_1="$DH1" \
  --joystick_port_0=mouse --joystick_port_1=nothing \
  --window_width=720 --window_height=568 --state_dir="$RUN/state"
