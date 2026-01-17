#!/usr/bin/env bash
set -euxo pipefail

export CCACHE_DIR="$HOME/.cache/nginx-ech/ccache-openssl"
export PATH="/usr/lib/ccache:$PATH"
export CC="ccache gcc"

BUILD_ROOT="$PWD/build"
mkdir -p "$BUILD_ROOT"
rm -rf "$BUILD_ROOT/openssl-cli"
cp -a "$HOME/.cache/nginx-ech/openssl" "$BUILD_ROOT/openssl-cli"

PATCH_STATE="$BUILD_ROOT/openssl-cli/.ech_patch_state"
EXPECTED_STATE="${OPENSSL_BASE_COMMIT}:${OPENSSL_ECH_COMMIT}"
if [ ! -f "$PATCH_STATE" ] || [ "$(cat "$PATCH_STATE")" != "$EXPECTED_STATE" ]; then
  echo "OpenSSL cache is not patched to the expected state."
  exit 1
fi

cd "$BUILD_ROOT/openssl-cli"

./Configure linux-aarch64 \
  --prefix="$PWD/../../test-openssl" \
  --openssldir="$PWD/../../test-openssl/ssl" \
  --libdir=lib \
  no-tests
make -j"$(nproc)"
make install_sw

ROOT="$GITHUB_WORKSPACE"
tar -C "$ROOT/test-openssl" -czf "$ROOT/openssl-cli.tar.gz" .
echo "tar_path=$ROOT/openssl-cli.tar.gz" >> "$GITHUB_OUTPUT"
