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
- **APT cache job**: Add `cache-apt` on `ubuntu-24.04-arm` to populate and cache `/var/cache/apt/archives` for arm64 packages. All build/test jobs depend on `cache-apt` and restore the APT cache before installing packages.
- **Parallel builds**:
  - `build-nginx` depends on `cache-apt`, `cache-nginx`, `cache-pcre2`, `cache-zlib`, `cache-openssl`, and `cache-ngx-brotli`.
  - `build-openssl-cli` depends on `cache-apt` and `cache-openssl`.
  - `test-ech` depends on `cache-apt`, `build-nginx`, and `build-openssl-cli`.

## Build Inputs (Pinned)
- **Nginx**: 1.29.4.
  - Tarball (primary): `https://github.com/nginx/nginx/archive/refs/tags/release-1.29.4.tar.gz`
  - Fallback (canonical): `https://nginx.org/download/nginx-1.29.4.tar.gz` (only if the GitHub URL fails)
- **OpenSSL (ECH)**:
  - Repo: `https://github.com/openssl/openssl.git`
  - Base tag: `openssl-3.6.0`
  - Base pin: `7b371d80d959ec9ab4139d09d78e83c090de9779`
  - Master ref: `master`
  - ECH ref: `feature/ech`
  - ECH pin: `ac3b44faf3bb51592e5d7904168801bc72ae3556`
  - Cherry-pick strategy:
    - Compute the common ancestor of `origin/master` and `origin/feature/ech` with `git merge-base`.
    - List commits in `feature/ech` after the common ancestor with `git rev-list --reverse`.
    - Checkout the base tag commit and cherry-pick the list in order.
    - Fail the job on any cherry-pick conflict.
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
- Configure invocation:
  - If `./configure` exists, use it.
  - Otherwise, run `./auto/configure` with the same flags.
- Nginx OpenSSL source tree:
  - Copy cached OpenSSL repo into `build/openssl-nginx`.
  - Run the same cherry-pick step as the CLI build:
    - `git checkout 7b371d80d959ec9ab4139d09d78e83c090de9779`
    - `git fetch origin master feature/ech`
    - `BASE_COMMIT=$(git merge-base origin/master origin/feature/ech)`
    - `COMMITS=$(git rev-list --reverse "$BASE_COMMIT..ac3b44faf3bb51592e5d7904168801bc72ae3556")`
    - `git config user.name "CI Merge"`
    - `git config user.email "ci@example.invalid"`
    - `for c in $COMMITS; do git cherry-pick -X theirs "$c"; done`
    - If any cherry-pick exits non-zero, fail the job immediately.
  - Pass `--with-openssl=build/openssl-nginx` to `./configure`.
- Brotli build step:
  - After `git submodule update --init --recursive`, build the Brotli static libs:
    - `cd build/ngx_brotli/deps/brotli`
    - `cmake -S . -B out -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF`
    - `cmake --build out`

### OpenSSL CLI (for tests)
- Build the OpenSSL ECH CLI separately from the Nginx build to avoid configure artifacts clobbering the Nginx build.
- Source directory: copy the cached OpenSSL repo into `build/openssl-cli`.
- Merge step (performed inside `build/openssl-cli`):
  - `git checkout 7b371d80d959ec9ab4139d09d78e83c090de9779`
  - `git fetch origin master feature/ech`
  - `BASE_COMMIT=$(git merge-base origin/master origin/feature/ech)`
  - `COMMITS=$(git rev-list --reverse "$BASE_COMMIT..ac3b44faf3bb51592e5d7904168801bc72ae3556")`
  - `git config user.name "CI Merge"`
  - `git config user.email "ci@example.invalid"`
  - `for c in $COMMITS; do git cherry-pick -X theirs "$c"; done`
  - If any cherry-pick exits non-zero, fail the job immediately.
- Configure and install:
  - `cd build/openssl-cli`
  - `./Configure linux-aarch64 --prefix="$PWD/../../test-openssl" --openssldir="$PWD/../../test-openssl/ssl" --libdir=lib no-tests`
  - `make -j"$(nproc)"`
  - `make install_sw`
  - Package to a workspace-root tarball: `tar -C "$GITHUB_WORKSPACE/test-openssl" -czf "$GITHUB_WORKSPACE/openssl-cli.tar.gz" .`
- Use the CLI at `test-openssl/bin/openssl` with `LD_LIBRARY_PATH` set to `test-openssl/lib` for all ECH test commands:
  - `export OPENSSL_BIN="$PWD/test-openssl/bin/openssl"`
  - `export LD_LIBRARY_PATH="$PWD/test-openssl/lib"`
- The `test-ech` job does not install the distro `openssl` package; it uses the built CLI for all certificate and ECH operations.

### Static vs Dynamic
- Static link for OpenSSL and Brotli.
- Keep glibc dynamic (avoid full static glibc to reduce compatibility risk).

## Caching
- **Strategy**: Treat caches as best-effort scratch space with per-input rolling caches. Each input gets its own cache namespace with a timestamp key, and cache creation is conditional on a detected change.
- **Per-input rolling keys**: Use keys with this pattern: `nginx-<timestamp>`, `pcre2-<timestamp>`, `zlib-<timestamp>`, `openssl-<timestamp>`, `ngx-brotli-<timestamp>`, `ccache-<timestamp>`, and `ccache-openssl-<timestamp>`. Always use `restore-keys: <name>-` to load the most recent cache.
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
    - If either command fails, run `git fetch origin openssl-3.6.0 master feature/ech` and set `CACHE_CHANGED=1`.
  - ngx_brotli cache validation:
    - Run `git cat-file -e a71f9312c2deb28875acc7bacfdd5695a111aa53^{commit}`.
    - If it fails, run `git fetch origin master` and set `CACHE_CHANGED=1`.
- **ccache (nginx)**:
  - Cache directory: `~/.cache/nginx-ech/ccache`.
  - In `build-nginx`, restore ccache at the start of the job.
  - Export `CCACHE_DIR="$HOME/.cache/nginx-ech/ccache"` before invoking any build commands so `ccache` writes to the tracked directory.
  - Record the ccache tree hash in a dedicated step before the build:
    - `HASH_DIR="$HOME/.cache/nginx-ech/ccache-hash"`
    - `find "$CCACHE_DIR" -type f -print0 | sort -z | xargs -0 -r sha256sum | sha256sum > "$HASH_DIR/ccache.hash.before"`
  - After the build, compute the tree hash again into `"$HASH_DIR/ccache.hash.after"` and compare to the before value. If different, save a new cache.
  - The compare/save steps run with `if: always()` so they execute even when the build step fails.
- **ccache (openssl-cli)**:
  - Cache directory: `~/.cache/nginx-ech/ccache-openssl`.
  - In `build-openssl-cli`, restore ccache at the start of the job.
  - Export `CCACHE_DIR="$HOME/.cache/nginx-ech/ccache-openssl"` before invoking any build commands so `ccache` writes to the tracked directory.
  - Record the ccache tree hash before and after the build using the same hashing scheme as Nginx, but store hashes under `~/.cache/nginx-ech/ccache-openssl-hash`.
  - Save the cache only when the hash changes, with `if: always()` so it runs even if the build step fails.
- **Scope**: Nginx and OpenSSL CLI use separate ccache directories to avoid cross-contamination.
- **Note**: Avoid caching full build directories (fragile); rely on validated sources and `ccache` for speedups.
- **APT packages (arm64)**:
  - Cache job: `cache-apt` on `ubuntu-24.04-arm`.
  - Cache directory: `/var/cache/apt/archives`.
  - Restore the cache before installing packages in `build-nginx`, `build-openssl-cli`, and `test-ech`.
  - Before cache restore, `sudo chown -R "$USER:$USER" /var/cache/apt/archives` so the cache action can write; after restore, `sudo chown -R root:root /var/cache/apt/archives` before `apt-get`.
  - Use a union package list across all jobs:
    - `build-essential`, `ca-certificates`, `ccache`, `cmake`, `git`, `ninja-build`, `perl`, `pkg-config`, `binutils`.
  - In `cache-apt`, compute a hash of `/var/cache/apt/archives` before and after a `sudo apt-get install -y --download-only` for the union list; `sudo chown -R "$USER:$USER" /var/cache/apt/archives` after the download so the hash and cache save can read files. Set `CACHE_CHANGED=1` if the hash changes, and save the cache only then.

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

Commands used in the workflow (certs, stored under a `test-certs/` directory, using the built OpenSSL CLI):
- Ensure the OpenSSL config exists for the CLI:
  - `mkdir -p test-openssl/ssl`
  - `cat > test-openssl/ssl/openssl.cnf <<'EOF'`
  - `openssl_conf = openssl_init`
  - `[openssl_init]`
  - `providers = provider_sect`
  - `[provider_sect]`
  - `default = default_sect`
  - `[default_sect]`
  - `activate = 1`
  - `EOF`
  - `export OPENSSL_CONF="$PWD/test-openssl/ssl/openssl.cnf"`
- CA key and cert:
  - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out test-certs/ca.key`
  - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN req -x509 -new -key test-certs/ca.key -sha256 -days 30 -subj "/CN=Test CA" -out test-certs/ca.crt`
- Leaf certs (loop per domain in the list above, with `NAME` derived by replacing dots with underscores):
  - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "test-certs/${NAME}.key"`
  - `printf 'subjectAltName=DNS:%s\n' "$DOMAIN" > test-certs/san.cnf`
  - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN req -new -key "test-certs/${NAME}.key" -subj "/CN=${DOMAIN}" -out "test-certs/${NAME}.csr"`
  - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN x509 -req -in "test-certs/${NAME}.csr" -CA test-certs/ca.crt -CAkey test-certs/ca.key -CAcreateserial -days 30 -sha256 -extfile test-certs/san.cnf -out "test-certs/${NAME}.crt"`

### ECH Config
- Use the OpenSSL ECH branch tooling to generate:
  - ECH key material for the server.
  - An ECHConfigList blob for the client.
- Store files under `test-ech/` in the workflow workspace.
- Commands used in the workflow:
  - List ECH-related subcommands and options for debugging:
    - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN list -commands | grep -i ech`
    - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN help ech`
  - Produce a PEM bundle with the ECH key and config:
    - `LD_LIBRARY_PATH="$PWD/test-openssl/lib" $OPENSSL_BIN ech -public_name outer.example.test -out test-ech/echconfig.pem`
  - Extract the ECHConfigList for the client:
    - `awk 'BEGIN{in_block=0} /BEGIN ECH/{in_block=1; next} /END ECH/{in_block=0} in_block{print}' test-ech/echconfig.pem | tr -d '\n' > test-ech/echconfig.b64`
    - `base64 -d test-ech/echconfig.b64 > test-ech/echconfig.bin`

### Nginx Test Config
- Use the repo file `conf/nginx.conf` (static file, no templating).
- The `http` block sets shared defaults:
  - `ssl_protocols TLSv1.3;`
  - `add_header Alt-Svc 'h3=":8443"; ma=86400';`
  - `add_header QUIC-Status $http3;`
- Each `server` block includes `snippets/server_defaults.conf` for shared server directives:
  - `listen 127.0.0.1:8443 ssl;`
  - `listen 127.0.0.1:8443 quic;`
  - `http2 on;`
  - `http3 on;`
  - `ssl_ech_file test-ech/echconfig.pem;`
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
