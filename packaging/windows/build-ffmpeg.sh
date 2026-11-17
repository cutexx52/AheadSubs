#!/usr/bin/env bash
set -euo pipefail

archive=$(cygpath -u "$1")
output=$(cygpath -u "$2")
jobs=$3

# Build with the Windows UCRT64 MinGW toolchain and FFmpeg's own codecs.
# Disable host library discovery so installing a new build tool cannot add codecs.
[[ "$MSYSTEM" == UCRT64 ]]
mkdir -p "$output"
tar -xf "$archive" --strip-components=1
./configure --prefix=/aheadsubs-ffmpeg --target-os=mingw32 --arch=x86_64 \
    --enable-shared --disable-static --enable-version3 --disable-autodetect \
    --disable-ffplay --disable-network --disable-pthreads --enable-w32threads \
    --disable-debug --disable-doc --extra-ldflags=-static-libgcc
make -j"$jobs" V=0 > make.log 2>&1 || { tail -n 80 make.log >&2; exit 1; }
make install DESTDIR="$output" > install.log 2>&1 || { tail -n 80 install.log >&2; exit 1; }
