#!/usr/bin/env bash
# Source-level debug the Amiga build via FS-UAE's GDB stub.
#   ./debug.sh [path-to-kickstart] [fixture.gdb] [executable]
# AMIGA_CPU picks the CPU (68030: the minimum target model). XWING_ARGS: the Shell
# arguments. Without a fixture: interactive gdb; `continue` runs the program.
# The stub serves memory reads but silently drops writes: inject inputs from C.
# Copied from Secret Weapons of the Luftwaffe's (manifest/references.tsv) and
# adapted: Shell start only.
set -uo pipefail
cd "$(dirname "$0")"
. ./env.sh
. "$FSUAE_COMMON"

GDB="${GDB:-m68k-amiga-elf-gdb}"
ROM="${1:-$KICKSTART}"
[ -f "$ROM" ] || { echo "Kickstart ROM not found: $ROM"; exit 1; }
ELF="${XWING_ELF:-out/XWing.elf}"
[ -f "$ELF" ] || { echo "build first: make"; exit 1; }
# The game directory as installed and configured (docs/dos-reference.md): the
# guest's C:\XWING, the current directory of the run (local only, never committed).
SOURCE=../tmp/dos/configured/XWING
[ -f "$SOURCE/XWING.EXE" ] || { echo "game directory not found: $SOURCE  (make dos-reference)"; exit 1; }

# KS 3.1 sets the AGA bits in GfxBase only after SetPatch (Secret Weapons of the
# Luftwaffe's docs/amiga-lessons.md L8).
[ -f "$SETPATCH" ] || { echo "SetPatch not found: $SETPATCH"; exit 1; }
RUN="$FSUAE_RUN"; DH0="$RUN/dh0"; DH1="$RUN/dh1"; GDBHOME="$RUN/gdbhome"
mkdir -p "$DH0/c" "$DH0/s" "$DH1" "$RUN/state" "$GDBHOME"
# Do not simplify to `dh1:XWing`: with the path form gdb resolves symbols
# against the wrong base and no breakpoint is ever hit (Rescue on Fractalus).
printf 'C:SetPatch QUIET\ncd dh1:\nXWing %s\n' "${XWING_ARGS:-}" > "$DH0/s/startup-sequence"
cp -f "$SETPATCH" "$DH0/c/SetPatch"
rsync -a --delete "$SOURCE/" "$DH1/"
# The program goes on the boot volume's C:, run by name as before (run.sh): the game
# directory stays the guest's C:\XWING entry for entry (its find-first scans
# count the entries).
cp -f "${3:-out/XWing.exe}" "$DH0/c/XWing" || exit 1
rm -f "$RUN"/state/*.uss

fsuae_claim_port || exit 1
# Quiet debug run (no sound, window behind the others): fsuae_options in $FSUAE_COMMON.
KICKSTART="$ROM" AMIGA_MODEL=A1200 CPU="${CPU:-${AMIGA_CPU:-}}" DEBUG=1
CHIP_KB=2048 FAST_KB="${FAST_KB:-${FAST_MEMORY:-8192}}"
fsuae_options
FSUAE_LOG="$RUN/fsuae-dbg.log" fsuae_launch \
  --hard_drive_0="$DH0" --hard_drive_1="$DH1" \
  --window_width=720 --window_height=568 \
  --remote_debugger_trigger=XWing --state_dir="$RUN/state"

for i in $(seq 1 60); do
  kill -0 "$FSUAE_PID" 2>/dev/null || { echo "FS-UAE exited early; see $RUN/fsuae-dbg.log"; exit 1; }
  lsof -nP -iTCP:"$DEBUG_PORT" -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 1
done

PREAMBLE="$RUN/connect.gdb"
printf 'set pagination off\nset confirm off\nset remotetimeout 90\ntarget remote 127.0.0.1:%s\n' \
  "$DEBUG_PORT" > "$PREAMBLE"

if [ -n "${2:-}" ]; then
  [ -f "$2" ] || { echo "fixture not found: $2"; fsuae_stop; exit 1; }
  env HOME="$GDBHOME" XDG_CACHE_HOME="$GDBHOME" \
    "$GDB" -q -l 10 -x "$PREAMBLE" -x "$2" "$ELF"
  STATUS=$?
  fsuae_stop
  exit $STATUS
fi
exec env HOME="$GDBHOME" XDG_CACHE_HOME="$GDBHOME" \
  "$GDB" -q -l 10 -x "$PREAMBLE" "$ELF"
