#!/usr/bin/env bash
set -euxo pipefail

PACKAGE_NAME="nginx-ech"
VERSION="${NGINX_VERSION}+ech"
ARCH="arm64"

WORK_ROOT="$PWD/deb-build"
EXTRACT_DIR="$WORK_ROOT/extract"
PKG_ROOT="$WORK_ROOT/pkgroot"
DEBIAN_DIR="$PKG_ROOT/DEBIAN"

rm -rf "$WORK_ROOT"
mkdir -p "$EXTRACT_DIR" "$PKG_ROOT" "$DEBIAN_DIR"

tarball="nginx-${NGINX_VERSION}-ech-linux-arm64.tar.gz"
if [ ! -f "$tarball" ]; then
  echo "Missing nginx artifact: $tarball" >&2
  exit 1
fi

tar -xzf "$tarball" -C "$EXTRACT_DIR"

mkdir -p \
  "$PKG_ROOT/usr/sbin" \
  "$PKG_ROOT/etc/nginx-ech" \
  "$PKG_ROOT/etc/nginx-ech/conf.d" \
  "$PKG_ROOT/var/lib/nginx-ech" \
  "$PKG_ROOT/var/cache/nginx-ech" \
  "$PKG_ROOT/var/log/nginx-ech" \
  "$PKG_ROOT/usr/lib/systemd/system" \
  "$PKG_ROOT/usr/share/doc/nginx-ech"

cp -a "$EXTRACT_DIR/opt/nginx-ech/sbin/nginx" "$PKG_ROOT/usr/sbin/nginx-ech"
cp -a "$EXTRACT_DIR/opt/nginx-ech/conf/nginx.conf" "$PKG_ROOT/etc/nginx-ech/nginx.conf"
cp -a "$GITHUB_WORKSPACE/debian/logs.conf" "$PKG_ROOT/etc/nginx-ech/conf.d/00-logs.conf"

for conf in "$EXTRACT_DIR/opt/nginx-ech/conf/"*; do
  name=$(basename "$conf")
  if [ "$name" = "nginx.conf" ]; then
    continue
  fi
  cp -a "$conf" "$PKG_ROOT/var/lib/nginx-ech/$name"
done

if [ -d "$EXTRACT_DIR/opt/nginx-ech/html" ]; then
  cp -a "$EXTRACT_DIR/opt/nginx-ech/html" "$PKG_ROOT/var/lib/nginx-ech/html"
fi

if [ -d "$EXTRACT_DIR/LICENSES" ]; then
  cp -a "$EXTRACT_DIR/LICENSES" "$PKG_ROOT/usr/share/doc/nginx-ech/"
fi

cp -a "$GITHUB_WORKSPACE/debian/nginx-ech.service" \
  "$PKG_ROOT/usr/lib/systemd/system/nginx-ech.service"
cp -a "$GITHUB_WORKSPACE/debian/conffiles" "$DEBIAN_DIR/conffiles"

sed \
  -e "s/@PACKAGE_NAME@/${PACKAGE_NAME}/g" \
  -e "s/@VERSION@/${VERSION}/g" \
  -e "s/@ARCH@/${ARCH}/g" \
  "$GITHUB_WORKSPACE/debian/control" > "$DEBIAN_DIR/control"

dpkg-deb --root-owner-group -b "$PKG_ROOT" "$WORK_ROOT/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

cp -a "$WORK_ROOT/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb" "$PWD/"
