#!/bin/bash
# Build the unpatched heavy-debug DOSBox-X that tests/dosbox_retf.py single-steps, as
# Secret Weapons of the Luftwaffe's oracle build (its build_dosbox_x.sh configures
# --enable-debug=heavy). The reference emulator (tools/build_dosbox_x.sh) stays a release
# build. The tree is $XWING_DOSBOX_X_DEBUG_SRC (default ~/.local/src/xwing-dosbox-x-debug),
# a worktree of the reference tree at the same pinned tag without the patch series. The
# binary is $XWING_DOSBOX_X_DEBUG_SRC/src/dosbox-x.
set -eu
COMMIT=4f19017c5f565dc40d01fede0f1382892e7243d7
SRC=${XWING_DOSBOX_X_SRC:-$HOME/.local/src/xwing-dosbox-x}
DBG=${XWING_DOSBOX_X_DEBUG_SRC:-$HOME/.local/src/xwing-dosbox-x-debug}

if [ ! -d "$DBG" ]; then
	git -C "$SRC" worktree add -q --detach "$DBG" "$COMMIT"
fi
cd "$DBG"
if [ "$(git rev-parse HEAD)" != "$COMMIT" ] || ! git diff --quiet HEAD -- . ':!*.in'; then
	echo "BUILD / DEBUG DOSBOX-X IS NOT THE CLEAN PINNED TAG ($COMMIT)" >&2
	exit 1
fi
[ -f configure ] || ./autogen.sh
[ -f Makefile ] || ./configure --enable-debug=heavy --enable-sdl2 --disable-sdl2test \
	--disable-sdl --disable-sdltest --prefix="$DBG/local"
n=$(sysctl -n hw.ncpu 2>/dev/null || nproc)
make -j"$(( n > 1 ? n / 2 : 1 ))"   # half the cores (AGENTS.md)
echo "BUILD PASS: $DBG/src/dosbox-x"
