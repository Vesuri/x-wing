#!/bin/bash
# Build the scripted DOSBox-X reference emulator, adapted from Secret Weapons of the
# Luftwaffe's build_dosbox_x.sh. The tree lives in $XWING_DOSBOX_X_SRC (default
# ~/.local/src/xwing-dosbox-x) at the pinned tag; tools/patches/ORDER applies on a clean
# checkout. The binary is $XWING_DOSBOX_X_SRC/src/dosbox-x.
set -eu
TAG=dosbox-x-v2026.08.31
COMMIT=4f19017c5f565dc40d01fede0f1382892e7243d7
REPO=$(cd "$(dirname "$0")/.." && pwd)
SRC=${XWING_DOSBOX_X_SRC:-$HOME/.local/src/xwing-dosbox-x}

if [ ! -d "$SRC/.git" ]; then
	git clone --branch "$TAG" --depth 1 https://github.com/joncampbell123/dosbox-x.git "$SRC"
fi
cd "$SRC"
if [ "$(git rev-parse HEAD)" != "$COMMIT" ]; then
	echo "BUILD / DOSBOX-X HEAD IS NOT $TAG ($COMMIT)" >&2
	exit 1
fi
if [ "${1:-}" = "--reset" ]; then
	git reset -q --hard "$COMMIT"
	git clean -fdxq
fi
if git diff --quiet HEAD -- . ':!*.in' && [ ! -e src/misc/xwing_script.cpp ]; then
	while read -r patch; do
		git apply "$REPO/tools/patches/$patch"
	done < "$REPO/tools/patches/ORDER"
fi
[ -f configure ] || ./autogen.sh
[ -f Makefile ] || ./configure --enable-sdl2 --disable-sdl2test --disable-sdl --disable-sdltest \
	--prefix="$SRC/local"
make -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
echo "BUILD PASS: $SRC/src/dosbox-x"
