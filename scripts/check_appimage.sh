#!/bin/sh
# Check that the AppImage runs on a distribution with nothing extra installed.
#
#   docker run --rm -v "$PWD:/src:ro" ubuntu:22.04 sh /src/scripts/check_appimage.sh \
#       /src/build/Stickle-x86_64.AppImage
#
# Only the libraries in packaging/linux/excludelist (glibc, graphics drivers,
# X11/Wayland client basics, fontconfig, ...) are installed first, because every
# desktop has them and the AppImage deliberately does not bundle them.
set -eu

APPIMAGE="$1"
EXPECTED_VERSION="${2:-}"

if command -v apt-get >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends \
        libgl1 libegl1 libgbm1 libdrm2 libx11-6 libx11-xcb1 libxcb1 \
        libwayland-client0 libfontconfig1 libfreetype6 libharfbuzz0b >/dev/null
elif command -v dnf >/dev/null; then
    dnf install -y -q \
        mesa-libGL mesa-libEGL mesa-libgbm libdrm libX11 libX11-xcb libxcb \
        libwayland-client fontconfig freetype harfbuzz >/dev/null
fi

WORK="$(mktemp -d)"
cp "$APPIMAGE" "$WORK/Stickle.AppImage"
chmod +x "$WORK/Stickle.AppImage"
cd "$WORK"
# Containers have no FUSE; desktops do. Extracting tests the same contents.
export APPIMAGE_EXTRACT_AND_RUN=1

echo "== --version"
version="$(./Stickle.AppImage --version)"
echo "$version"
if [ -n "$EXPECTED_VERSION" ] && [ "$version" != "Stickle $EXPECTED_VERSION" ]; then
    echo "unexpected version output" >&2
    exit 1
fi

echo "== missing libraries"
./Stickle.AppImage --appimage-extract >/dev/null
missing="$(find squashfs-root -type f \( -name '*.so*' -o -name 'stickle.bin' \) \
    -exec ldd {} \; 2>/dev/null | grep 'not found' | sort -u || true)"
if [ -n "$missing" ]; then
    echo "$missing" >&2
    exit 1
fi
echo "none"

echo "== starts and keeps running"
QT_QPA_PLATFORM=offscreen ./Stickle.AppImage &
pid=$!
sleep 5
if ! kill -0 "$pid" 2>/dev/null; then
    wait "$pid" || true
    echo "exited early" >&2
    exit 1
fi
kill "$pid"
echo "ok"
