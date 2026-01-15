# Specification: Build and Test NGINX for Linux/arm64 with ECH Support

## Goal

Configure CI to build an arm64 NGINX binary with "Encrypted ClientHello" support and run an end-to-end ECH smoke test. Produce a release-ready tarball that can be deployed to any arm64 machine that is running a reasonably recent version of Linux and glibc 2.39 or later, for example, Ubuntu 24.04 LTS.

## Build Configuration

### NGINX
- Build NGINX from source with:
  - `--with-openssl=...` to build OpenSSL ECH in-tree (static libssl/libcrypto).
  - `--add-module=.../ngx_brotli` for built-in Brotli support.
  - `--with-pcre=...` and `--with-zlib=...` to specify the paths to PCRE2 and zlib source.
  - `--with-http_ssl_module` for TLS.
  - `--with-http_v2_module` for HTTP/2.
  - `--with-http_v3_module` for HTTP/3 (note: requires OpenSSL QUIC support).
  - `--with-http_gzip_static_module` for precompressed assets.
  - `--with-http_stub_status_module` for basic status/health.
  - `--with-http_realip_module` for trusted proxy headers.
  - `--with-http_slice_module` for large file ranges.
- Use install prefix `/opt/nginx-ech` and stage with `DESTDIR` into a workspace `dist/` folder before packaging.
- Configure invocation:
  - If `./configure` exists, use it.
  - Otherwise, run `./auto/configure` with the same flags.
- NGINX OpenSSL source tree:
  - Use the OpenSSL source tree in `build/openssl-nginx` and configure NGINX with `--with-openssl=build/openssl-nginx` so it builds against that tree.
- Brotli build step:
  - After `git submodule update --init --recursive`, build the Brotli static libs.

### OpenSSL CLI (for tests)
- Build the OpenSSL ECH CLI separately from the NGINX build to avoid configure artifacts clobbering the NGINX build.
- Source directory: use the OpenSSL source tree in `build/openssl-cli`.
- Configure for `linux-aarch64`, install under `test-openssl/` (bin, lib, ssl), skip tests, and package the install tree into `openssl-cli.tar.gz`.
- Use the CLI at `test-openssl/bin/openssl`, with `LD_LIBRARY_PATH` pointing at `test-openssl/lib`, for all ECH test commands.
- The `test-ech` job does not install the distro `openssl` package; it uses the built CLI for all certificate and ECH operations.

### Static vs Dynamic

- Static link for OpenSSL and Brotli.
- Keep glibc dynamic (avoid full static glibc to reduce compatibility risk).

## Build Inputs (Pinned)

- **NGINX**: 1.29.4.
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
    - Check out the base tag commit and cherry-pick the list in order.
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

## CI Strategy

- **Trigger**: GitHub Actions on push to `main`, `develop`, `release`, or `ci/test-only`. Tag pushes matching `r*` also trigger the workflow for release asset uploads. Manual runs use `workflow_dispatch`.
- **Test-only branch**: `ci/test-only` runs the test job only (does not build) and pulls binaries from the latest non-draft, non-prerelease release.
- **Runner**:
  - Cache jobs run on `ubuntu-24.04` (x86_64) to maximize runner availability.
  - Build and test jobs run on `ubuntu-24.04-arm` for native arm64 builds and runtime smoke tests.
- **Outputs**: A tarball containing the install prefix (default `/opt/nginx-ech`) plus a `BUILDINFO.txt`. On `r*` tag pushes, CI uploads the NGINX and OpenSSL CLI tarballs as release assets on that tag.
- **Parallel acquisition of the sources**: Each build input has its own cache and working directory. Use separate jobs per input (`cache-nginx`, `cache-pcre2`, `cache-zlib`, `cache-openssl`, `cache-ngx-brotli`) on `ubuntu-24.04` (x64) and have build jobs depend only on the caches they need. Each cache job restores, validates, and saves its cache only when `CACHE_CHANGED=1`; build jobs restore their required caches again before compiling. Skip these cache jobs when `skip_builds=true`.
- **APT cache job**: Add `cache-apt` on `ubuntu-24.04-arm` to populate and cache `/var/cache/apt/archives` for arm64 packages. All build/test jobs depend on `cache-apt` and restore the APT cache before installing packages.
- **Parallel builds**:
  - `build-nginx` depends on `cache-apt`, `cache-nginx`, `cache-pcre2`, `cache-zlib`, `cache-openssl`, and `cache-ngx-brotli`.
  - `build-openssl-cli` depends on `cache-apt` and `cache-openssl`.
  - `test-ech` depends on `cache-apt`, `build-nginx`, and `build-openssl-cli`, but is gated to run only when the build jobs succeeded or were skipped.

### Manual test mode

To allow manual runs (either in the GitHub Actions web UI or via the API), `workflow_dispatch` exposes:

  - `skip_builds` (boolean, default false) to skip build jobs and reuse artifacts.
  - `artifact_run_id` (string, optional) to download artifacts from a previous run.
  - `artifact_release_tag` (string, optional) to download artifacts from a release tag.
  - When `skip_builds=true`, cache jobs (`cache-nginx`, `cache-pcre2`, `cache-zlib`, `cache-openssl`, `cache-ngx-brotli`) and build jobs (`build-nginx`, `build-openssl-cli`) are skipped, and `test-ech` downloads artifacts from either a run ID or a release tag (exactly one).
  - If `skip_builds=true` and both inputs are empty (or both are set), fail `test-ech` with a clear message.

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
  - OpenSSL cache validation and patching:
    - Ensure the pinned base and ECH commits exist locally; fetch the required refs if they do not.
    - If the cached `.ech_patch_state` marker does not match the current pins, reapply the ECH commit range onto the pinned base and update the marker.
    - Fail the cache job if cherry-picking does not apply cleanly; do not save a partial cache.
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
  - Record the ccache tree hash before and after the build using the same hashing scheme as NGINX, but store hashes under `~/.cache/nginx-ech/ccache-openssl-hash`.
  - Save the cache only when the hash changes, with `if: always()` so it runs even if the build step fails.
- **Scope**: NGINX and OpenSSL CLI use separate ccache directories to avoid cross-contamination.
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
- Log the NGINX binary’s required glibc symbols with `readelf --version-info /opt/nginx-ech/sbin/nginx | grep -o 'GLIBC_[0-9.]*' | sort -u`.

### Certificates (Generated Per Run)

- Generate a test CA (ECDSA P-256) valid for 30 days.
- Generate multiple ECDSA P-256 leaf certs (distinct SANs), signed by the test CA (valid for 30 days).
- No caching of certs; ECDSA generation is fast enough, and avoids expiration issues.

Names:

- CA: `Test CA`
- Leaf certs: `outer.example.test`, `this.doesnt.exist`, `whats.going.on`, `bananas.arent.real`, `blue.seaglass`
- Each leaf uses SANs and a unique `server_name` in NGINX.

Files:

- Ensure the OpenSSL config exists for the CLI (`test-openssl/ssl/openssl.cnf`) so the default provider loads correctly.
- Create `conf/test-certs` and `conf/test-ech` and add `test-certs`/`test-ech` symlinks at the repo root so NGINX’s relative paths resolve.
- Generate a P-256 test CA (30‑day validity), then generate one P‑256 leaf cert per domain with a SAN matching the domain and sign them with the test CA.
- Store all certs and keys under `conf/test-certs` (the symlink keeps NGINX paths simple).

### ECH Config

- Use the OpenSSL ECH tooling to generate server ECH key material and a client-facing ECHConfigList.
- Store artifacts under `conf/test-ech/` with a `test-ech` symlink in the workspace.
- Record the ECHConfigList in base64 form (`echconfig.b64`) so the client can provide it directly, without DNS/SVCB.
- Keep a PEM bundle (`echconfig.pem`) for the server to load via `ssl_ech_file`.

### NGINX Test Config
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
- Certificate/ECH paths are relative in the config, so tests must launch NGINX with the workspace as the prefix, and the workflow creates `test-certs`/`test-ech` symlinks pointing at `conf/test-certs` and `conf/test-ech`:
  - `nginx -p "$PWD" -c conf/nginx.conf -g 'daemon off;'`

### Client Validation

Use the ECH-enabled OpenSSL client to:

- Provide the ECHConfigList directly (no DNS/SVCB required).
- Set `-servername` to the *inner* SNI.
- Trust the test CA.
- Send an HTTP request over the TLS session and verify the response body.
- Explicitly set the *outer* SNI (`outer.example.test`) so a non‑ECH handshake would route to the outer vhost and fail the response check.
- Run a traced handshake first and assert that the trace includes `encrypted_client_hello` (this confirms ECH was actually used).
- Run a second, quiet request to capture the HTTP response, extract the body into a file, and `diff` it against the expected single‑line body for that domain.

Pass criteria:

- Each inner domain handshake reports `encrypted_client_hello`.
- Each response body file matches the expected body for that domain.
