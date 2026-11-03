#!/bin/bash
set -euo pipefail
for tool in wayland-scanner pkg-config cc g++; do
    command -v "$tool" >/dev/null || { echo "Missing build dependency: $tool (see README.md)" >&2; exit 1; }
done
pkg-config --exists wayland-client wayland-egl egl glesv2 libpng wayland-protocols || {
    echo "Missing development libraries; see README.md for distro packages." >&2; exit 1;
}
cd -- "$(dirname -- "$0")"
mkdir -p build
wayland-scanner client-header protocol/wlr-layer-shell-unstable-v1.xml build/layer-shell.h
# Older protocol XML uses a C++ keyword for a C argument; wire format is unchanged.
sed -i 's/\bnamespace\b/namespace_/g' build/layer-shell.h
wayland-scanner private-code protocol/wlr-layer-shell-unstable-v1.xml build/layer-shell.c
wayland-scanner private-code "$(pkg-config --variable=pkgdatadir wayland-protocols)/stable/xdg-shell/xdg-shell.xml" build/xdg-shell.c
cc -O2 -c build/layer-shell.c -o build/layer-shell.o $(pkg-config --cflags wayland-client)
cc -O2 -c build/xdg-shell.c -o build/xdg-shell.o $(pkg-config --cflags wayland-client)
g++ -O2 -std=c++17 -Wall -Wextra -Ibuild main.cpp build/layer-shell.o build/xdg-shell.o -o build/creation-ascii $(pkg-config --cflags --libs wayland-client wayland-egl egl glesv2 libpng)
