# Specification: Build and Test Nginx ECH (arm64)

## Goal
Build an arm64 Nginx binary with OpenSSL ECH and built-in Brotli (static modules; glibc dynamic), then run an end-to-end ECH smoke test in CI using the OpenSSL ECH tooling. Produce a release-ready tarball that can be deployed to a Raspberry Pi.

## CI Strategy
- **Trigger**: GitHub Actions on push to `main`, `develop`, or `release`.
- **Runner**:
  - Cache jobs run on `ubuntu-24.04` (x86_64) to maximize runner availability.
  - Build and test jobs run on `ubuntu-24.04-arm` for native arm64 builds and runtime smoke tests (no container).
- **Outputs**: A tarball containing the install prefix (default `/opt/nginx-ech`) plus a `BUILDINFO.txt`.
- **Parallel input acquisition**: Each build input has its own cache and working directory. Use separate jobs per input (`cache-nginx`, `cache-pcre2`, `cache-zlib`, `cache-openssl`, `cache-ngx-brotli`) on `ubuntu-24.04` and have build jobs depend only on the caches they need. Each cache job restores, validates, and saves its cache only when `CACHE_CHANGED=1`; build jobs restore their required caches again before compiling.
- **Parallel builds**:
  - `build-nginx` depends on `cache-nginx`, `cache-pcre2`, `cache-zlib`, `cache-openssl`, and `cache-ngx-brotli`.
  - `build-openssl-cli` depends only on `cache-openssl`.
  - `test-ech` depends on both `build-nginx` and `build-openssl-cli`.

## Build Inputs (Pinned)
- **Nginx**: 1.29.4.
  - Tarball (primary): `https://github.com/nginx/nginx/archive/refs/tags/release-1.29.4.tar.gz`
  - Fallback (canonical): `https://nginx.org/download/nginx-1.29.4.tar.gz` (only if the GitHub URL fails)
- **OpenSSL (ECH)**:
  - Repo: `https://github.com/openssl/openssl.git`
  - Base tag: `openssl-3.6.0`
  - Base pin: `7b371d80d959ec9ab4139d09d78e83c090de9779`
  - ECH ref: `feature/ech`
  - ECH pin: `ac3b44faf3bb51592e5d7904168801bc72ae3556`
  - Merge strategy: checkout the base tag commit and merge the ECH commit; fail the job on any merge conflict.
- **Brotli module (ngx_brotli)**:
  - Repo: `https://github.com/google/ngx_brotli.git`
  - Ref: `master`
  - Pin: `a71f9312c2deb28875acc7bacfdd5695a111aa53`
- **PCRE2**: 10.47.
  - Tarball: `https://github.com/PCRE2Project/pcre2/releases/download/pcre2-10.47/pcre2-10.47.tar.gz`
- **zlib**: 1.3.1.
  - Tarball (primary): `https://github.com/madler/zlib/archive/refs/tags/v1.3.1.tar.gz`
  - Fallback (canonical): `https://zlib.net/zlib-1.3.1.tar.gz` (only if the GitHub URL fails)

## Build Configuration
### Nginx
- Build Nginx from source with:
  - `--with-openssl=...` to build OpenSSL ECH in-tree (static libssl/libcrypto).
  - `--add-module=.../ngx_brotli` to compile Brotli support into the binary.
  - `--with-pcre=...` and `--with-zlib=...` from local tarballs.
  - `--with-http_ssl_module` to enable TLS.
  - `--with-http_v2_module` to enable HTTP/2.
  - `--with-http_v3_module` to enable HTTP/3 (requires OpenSSL QUIC support on the pinned ECH ref).
  - `--with-http_gzip_static_module` for precompressed assets.
  - `--with-http_stub_status_module` for basic status/health.
  - `--with-http_realip_module` for trusted proxy headers.
  - `--with-http_slice_module` for large file ranges.
- Use install prefix `/opt/nginx-ech` and stage with `DESTDIR` into a workspace `dist/` folder before packaging.
- Build is native (no cross-compile flags).
- Nginx OpenSSL source tree:
  - Copy cached OpenSSL repo into `build/openssl-nginx`.
  - Run the same merge step as the CLI build:
    - `git checkout 7b371d80d959ec9ab4139d09d78e83c090de9779`
    - `git config user.name "CI Merge"`
    - `git config user.email "ci@example.invalid"`
    - `git merge --no-ff --no-commit ac3b44faf3bb51592e5d7904168801bc72ae3556`
    - If the merge command exits non-zero, fail the job immediately.
  - Pass `--with-openssl=build/openssl-nginx` to `./configure`.

### OpenSSL CLI (for tests)
- Build the OpenSSL ECH CLI separately from the Nginx build to avoid configure artifacts clobbering the Nginx build.
- Source directory: copy the cached OpenSSL repo into `build/openssl-cli`.
- Merge step (performed inside `build/openssl-cli`):
  - `git checkout 7b371d80d959ec9ab4139d09d78e83c090de9779`
  - `git config user.name "CI Merge"`
  - `git config user.email "ci@example.invalid"`
  - `git merge --no-ff --no-commit ac3b44faf3bb51592e5d7904168801bc72ae3556`
  - If the merge command exits non-zero, fail the job immediately.
- Configure and install:
  - `cd build/openssl-cli`
  - `./Configure linux-aarch64 --prefix="$PWD/../../test-openssl" --openssldir="$PWD/../../test-openssl/ssl" --libdir=lib no-tests`
  - `make -j"$(nproc)"`
  - `make install_sw`
- Use the CLI at `test-openssl/bin/openssl` with `LD_LIBRARY_PATH` set to `test-openssl/lib` for all ECH test commands:
  - `export OPENSSL_BIN="$PWD/test-openssl/bin/openssl"`
  - `export LD_LIBRARY_PATH="$PWD/test-openssl/lib"`

### Static vs Dynamic
- Static link for OpenSSL and Brotli.
- Keep glibc dynamic (avoid full static glibc to reduce compatibility risk).

## Caching
- **Strategy**: Treat caches as best-effort scratch space with per-input rolling caches. Each input gets its own cache namespace with a timestamp key, and cache creation is conditional on a detected change.
- **Per-input rolling keys**: Use keys with this pattern: `nginx-<timestamp>`, `pcre2-<timestamp>`, `zlib-<timestamp>`, `openssl-<timestamp>`, `ngx-brotli-<timestamp>`, plus `ccache-<timestamp>`. Always use `restore-keys: <name>-` to load the most recent cache.
  - Define `CACHE_TS=$(date -u +%Y%m%dT%H%M%SZ)` once per workflow run and pass it to all jobs.
  - Each cache job sets `CACHE_CHANGED=1` only if it modifies its cache contents; save the cache only when `CACHE_CHANGED=1`.
- **Tarball caches (nginx/pcre2/zlib)**:
  - Cache directories: `~/.cache/nginx-ech/nginx`, `~/.cache/nginx-ech/pcre2`, `~/.cache/nginx-ech/zlib`.
  - Normalize tarball names in cache:
    - `~/.cache/nginx-ech/nginx/nginx-1.29.4.tar.gz`
    - `~/.cache/nginx-ech/pcre2/pcre2-10.47.tar.gz`
    - `~/.cache/nginx-ech/zlib/zlib-1.3.1.tar.gz`
  - Validate by checking for the exact tarball filename.
  - If the tarball is missing, download it to the normalized filename with `curl -L <url> -o <normalized>`, then set `CACHE_CHANGED=1`.
- **Git caches (OpenSSL, ngx_brotli)**:
  - Cache directories: `~/.cache/nginx-ech/openssl`, `~/.cache/nginx-ech/ngx_brotli`.
  - OpenSSL cache validation:
    - Run `git cat-file -e 7b371d80d959ec9ab4139d09d78e83c090de9779^{commit}` and `git cat-file -e ac3b44faf3bb51592e5d7904168801bc72ae3556^{commit}`.
    - If either command fails, run `git fetch origin openssl-3.6.0 feature/ech` and set `CACHE_CHANGED=1`.
  - ngx_brotli cache validation:
    - Run `git cat-file -e a71f9312c2deb28875acc7bacfdd5695a111aa53^{commit}`.
    - If it fails, run `git fetch origin master` and set `CACHE_CHANGED=1`.
- **ccache**:
  - Cache directory: `~/.cache/nginx-ech/ccache`.
  - In `build-nginx`, restore ccache at the start of the job.
  - Record the ccache tree hash in a dedicated step before the build:
    - `HASH_DIR="$HOME/.cache/nginx-ech/ccache-hash"`
    - `find "$CCACHE_DIR" -type f -print0 | sort -z | xargs -0 -r sha256sum | sha256sum > "$HASH_DIR/ccache.hash.before"`
  - After the build, compute the tree hash again into `"$HASH_DIR/ccache.hash.after"` and compare to the before value. If different, save a new cache.
  - The compare/save steps run with `if: always()` so they execute even when the build step fails.
- **Scope**: ccache is used by the Nginx build only; the OpenSSL CLI build does not use ccache.
- **Note**: Avoid caching full build directories (fragile); rely on validated sources and `ccache` for speedups.

## Smoke Test Strategy (ECH End-to-End)
### Overview
Perform a real TLS ECH handshake using OpenSSL’s ECH-enabled `openssl` CLI, then send an HTTP request over that handshake to confirm the server is reachable and routing by the inner SNI. Use multiple test domains to prove that the inner name is hidden from plaintext SNI.

### glibc Check
- Log the runner glibc version with `ldd --version`.
- Log the Nginx binary’s required glibc symbols with `readelf --version-info /opt/nginx-ech/sbin/nginx | grep -o 'GLIBC_[0-9.]*' | sort -u`.

### Certificates (Generated Per Run)
- Generate a test CA (ECDSA P-256) valid for 30 days.
- Generate multiple ECDSA P-256 leaf certs (distinct SANs), signed by the test CA (valid for 30 days).
- No caching of certs; generation is fast and avoids expiration issues.

Domains used:
- CA: `Test CA`
- Leaf certs: `outer.example.test`, `this.doesnt.exist`, `whats.going.on`, `bananas.arent.real`, `blue.seaglass`
- Each leaf uses SANs and a unique `server_name` in Nginx.

Commands used in the workflow (certs, stored under a `test-certs/` directory):
- CA key and cert:
  - `openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out test-certs/ca.key`
  - `openssl req -x509 -new -key test-certs/ca.key -sha256 -days 30 -subj "/CN=Test CA" -out test-certs/ca.crt`
- Leaf certs (loop per domain in the list above, with `NAME` derived by replacing dots with underscores):
  - `openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "test-certs/${NAME}.key"`
  - `printf 'subjectAltName=DNS:%s\n' "$DOMAIN" > test-certs/san.cnf`
  - `openssl req -new -key "test-certs/${NAME}.key" -subj "/CN=${DOMAIN}" -out "test-certs/${NAME}.csr"`
  - `openssl x509 -req -in "test-certs/${NAME}.csr" -CA test-certs/ca.crt -CAkey test-certs/ca.key -CAcreateserial -days 30 -sha256 -extfile test-certs/san.cnf -out "test-certs/${NAME}.crt"`

### ECH Config
- Use the OpenSSL ECH branch tooling to generate:
  - ECH key material for the server.
  - An ECHConfigList blob for the client.
- Store files under `test-ech/` in the workflow workspace.
- Commands used in the workflow:
  - List ECH-related subcommands and options for debugging:
    - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN list -commands | grep -i ech`
    - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN help ech`
  - Generate the ECH key pair (HPKE):
    - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN genpkey -algorithm X25519 -out test-ech/ech.key`
  - Produce an ECHConfigList (binary + base64):
    - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN ech -public_name outer.example.test -key test-ech/ech.key -out test-ech/echconfig.bin -out_b64 test-ech/echconfig.b64`

### Nginx Test Config
- Use the repo file `conf/nginx.conf` (static file, no templating).
- The `http` block sets shared defaults:
  - `ssl_protocols TLSv1.3;`
  - `add_header Alt-Svc 'h3=":8443"; ma=86400';`
  - `add_header QUIC-Status $http3;`
- Each `server` block includes `conf/snippets/server_defaults.conf` for shared server directives:
  - `listen 127.0.0.1:8443 ssl http2;`
  - `listen 127.0.0.1:8443 quic reuseport;`
  - `http3 on;`
  - `ssl_ech on;`
  - `ssl_ech_config test-ech/echconfig.b64;`
  - `ssl_ech_key test-ech/ech.key;`
- Each `server` block defines a unique `server_name`, leaf cert/key pair, and a unique response body.
- All certificate and ECH file paths are relative (`test-certs/...`, `test-ech/...`), so tests must launch Nginx with the workspace as the prefix:
  - `nginx -p "$PWD" -c conf/nginx.conf -g 'daemon off;'`

### Client Validation
Use the ECH-enabled OpenSSL client to:
- Provide the ECHConfigList directly (no DNS/SVCB required).
- Set `-servername` to the *inner* SNI.
- Trust the test CA.
- Send an HTTP request over the TLS session and verify the response body.

Client validation commands (run once per inner domain: `this.doesnt.exist`, `whats.going.on`, `bananas.arent.real`, `blue.seaglass`):
```
printf 'GET / HTTP/1.1\r\nHost: this.doesnt.exist\r\nConnection: close\r\n\r\n' | \
  LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN s_client \
    -connect 127.0.0.1:8443 \
    -servername this.doesnt.exist \
    -CAfile "$PWD/test-certs/ca.crt" \
    -ech_config "$PWD/test-ech/echconfig.bin" \
    -quiet
```

Pass criteria:
- For each inner domain, `openssl s_client` exits 0 and the HTTP response body matches the requested host.
