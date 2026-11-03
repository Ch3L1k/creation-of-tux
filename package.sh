#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
mkdir -p dist
version=$(cat VERSION)
git archive --format=zip --prefix="creation-of-tux-$version/" -o "dist/creation-of-tux-$version-source.zip" HEAD
sha256sum "dist/creation-of-tux-$version-source.zip" > "dist/SHA256SUMS"
echo "Created dist/creation-of-tux-$version-source.zip"
