#!/usr/bin/env bash
set -euxo pipefail

export CCACHE_DIR="$HOME/.cache/nginx-ech/ccache"
export PATH="/usr/lib/ccache:$PATH"
export CC="ccache gcc"

BUILD_ROOT="$PWD/build"
DIST_ROOT="$PWD/dist"
mkdir -p "$BUILD_ROOT" "$DIST_ROOT"

mkdir -p "$BUILD_ROOT/nginx" "$BUILD_ROOT/pcre2" "$BUILD_ROOT/zlib"
tar -xf "$HOME/.cache/nginx-ech/nginx/nginx-${NGINX_VERSION}.tar.gz" -C "$BUILD_ROOT/nginx" --strip-components=1
tar -xf "$HOME/.cache/nginx-ech/pcre2/pcre2-${PCRE2_VERSION}.tar.gz" -C "$BUILD_ROOT/pcre2" --strip-components=1
tar -xf "$HOME/.cache/nginx-ech/zlib/zlib-${ZLIB_VERSION}.tar.gz" -C "$BUILD_ROOT/zlib" --strip-components=1

rm -rf "$BUILD_ROOT/openssl-nginx" "$BUILD_ROOT/ngx_brotli"
cp -a "$HOME/.cache/nginx-ech/openssl" "$BUILD_ROOT/openssl-nginx"
cp -a "$HOME/.cache/nginx-ech/ngx_brotli" "$BUILD_ROOT/ngx_brotli"

PATCH_STATE="$BUILD_ROOT/openssl-nginx/.ech_patch_state"
EXPECTED_STATE="${OPENSSL_BASE_COMMIT}:${OPENSSL_ECH_COMMIT}"
if [ ! -f "$PATCH_STATE" ] || [ "$(cat "$PATCH_STATE")" != "$EXPECTED_STATE" ]; then
  echo "OpenSSL cache is not patched to the expected state."
  exit 1
fi

cd "$BUILD_ROOT/ngx_brotli"
git submodule update --init --recursive
cd "$BUILD_ROOT/ngx_brotli/deps/brotli"
cmake -S . -B out -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF
cmake --build out

cd "$BUILD_ROOT/nginx"
if [ -x ./configure ]; then
  CONFIGURE=./configure
else
  CONFIGURE=./auto/configure
fi
"$CONFIGURE" \
  --prefix="$PREFIX" \
  --with-http_ssl_module \
  --with-http_v2_module \
  --with-http_v3_module \
  --with-http_gzip_static_module \
  --with-http_stub_status_module \
  --with-http_realip_module \
  --with-http_slice_module \
  --with-pcre="$BUILD_ROOT/pcre2" \
  --with-zlib="$BUILD_ROOT/zlib" \
  --with-openssl="$BUILD_ROOT/openssl-nginx" \
  --with-openssl-opt="no-shared no-tests" \
  --add-module="$BUILD_ROOT/ngx_brotli"

make -j"$(nproc)"
make install DESTDIR="$DIST_ROOT"

BUILDINFO="$DIST_ROOT$PREFIX/BUILDINFO.txt"
{
  echo "nginx_version=$NGINX_VERSION"
  echo "openssl_base_tag=$OPENSSL_BASE_TAG"
  echo "openssl_base_commit=$OPENSSL_BASE_COMMIT"
  echo "openssl_ech_ref=$OPENSSL_ECH_REF"
  echo "openssl_ech_commit=$OPENSSL_ECH_COMMIT"
  echo "ngx_brotli_commit=$NGX_BROTLI_COMMIT"
  echo "pcre2_version=$PCRE2_VERSION"
  echo "zlib_version=$ZLIB_VERSION"
} > "$BUILDINFO"

TAR_NAME="nginx-${NGINX_VERSION}-ech-linux-arm64.tar.gz"
tar -C "$DIST_ROOT" -czf "$PWD/$TAR_NAME" .
echo "tar_path=$PWD/$TAR_NAME" >> "$GITHUB_OUTPUT"
