#!/usr/bin/env bash
# Boot the Amiga build on the A1200 chipset. Left mouse button quits.
#   ./run.sh [path-to-kickstart-rom]
# Run a different binary with $XWING_EXE, arguments with $XWING_ARGS; extra fs-uae args via $EXTRA_ARGS (they win);
# The machine is AmigaXDev's shared preset with the CPU caches on: a1200-030 (the minimum target
# model, 50 MHz 68030 with its data cache), or a1200-040 / a1200-060 for AMIGA_CPU=68040 / 68060.
# AMIGA_SETUP names another preset; Another AMIGA_CPU, or AMIGA_SETUP=none, boots the bare A1200 with that CPU as before.
# DEBUG=1 adds the gdb stub.
# Speech (P10): build with `XWING_DRIVER=ADLIB_W.IMS make amiga`; this script then boots
# the Sound Blaster setup.
set -euo pipefail
cd "$(dirname "$0")"
. ./env.sh
. "$FSUAE_COMMON"

ROM="${1:-$KICKSTART}"
EXE="${XWING_EXE:-out/XWing.exe}"
# The game directory as installed and configured (docs/dos-reference.md): the
# guest's C:\XWING, the current directory of the run.
# The Sound Blaster build (XWING_DRIVER=ADLIB_W.IMS, P10) runs on the Sound Blaster
# setup, whose configuration selects its driver; the AdLib build on the AdLib setup.
# XWING_GAME_DIR overrides. The SB build is told by its SB-only DSP timer message.
if LC_ALL=C grep -aq "X-Wing no second CIA-B timer for the DSP" "$EXE" 2>/dev/null; then
  GAME="${XWING_GAME_DIR:-../tmp/dos/configured-sb/XWING}"
else
  GAME="${XWING_GAME_DIR:-../tmp/dos/configured/XWING}"
fi
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

case "${AMIGA_SETUP:-}" in
  none) unset AMIGA_SETUP ;;
  "") case "${AMIGA_CPU:-68030}" in
        68040) AMIGA_SETUP=a1200-040 ;;
        68060) AMIGA_SETUP=a1200-060 ;;
        68030) AMIGA_SETUP=a1200-030 ;;
      esac
      [ -n "${AMIGA_SETUP:-}" ] && export AMIGA_SETUP ;;
esac

fsuae_prepare
# Model, memory, sound and window: fsuae_options in $FSUAE_COMMON; a preset's machine
# and memory come first and win.
KICKSTART="$ROM" AMIGA_MODEL=A1200 CPU="${CPU:-${AMIGA_CPU:-}}"
CHIP_KB=2048 FAST_KB="${FAST_KB:-${FAST_MEMORY:-8192}}"
fsuae_options
fsuae_exec \
  --hard_drive_0="$DH0" --hard_drive_1="$DH1" \
  --joystick_port_0=mouse --joystick_port_1=nothing \
  --window_width=720 --window_height=568 --state_dir="$RUN/state"
