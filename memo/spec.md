# Specification: Build and Test Nginx ECH (arm64)

## Goal
Build an arm64 Nginx binary with OpenSSL ECH and built-in Brotli (static modules; glibc dynamic), then run an end-to-end ECH smoke test in CI using the OpenSSL ECH tooling. Produce a release-ready tarball that can be deployed to a Raspberry Pi.

## CI Strategy
- **Trigger**: GitHub Actions on push to `main`, `develop`, or `release`.
- **Runner**: `ubuntu-24.04-arm64` for native builds and runtime smoke tests.
- **Outputs**: A tarball containing the install prefix (default `/opt/nginx-ech`) plus a `BUILDINFO.txt`.

## Build Inputs (Pinned)
- **Nginx**: 1.29.4.
- **OpenSSL**: ECH feature branch, pinned to a specific commit/branch ref.
- **Brotli module**: `google/ngx_brotli`, pinned ref.
- **PCRE2** and **zlib**: pinned versions from upstream tarballs.

## Build Configuration
### Nginx
- Build Nginx from source with:
  - `--with-openssl=...` to build OpenSSL ECH in-tree (static libssl/libcrypto).
  - `--add-module=.../ngx_brotli` to compile Brotli support into the binary.
  - `--with-pcre=...` and `--with-zlib=...` from local tarballs.
- Use an install prefix like `/opt/nginx-ech` and stage with `DESTDIR` into a workspace `dist/` folder before packaging.
- Build is native (no cross-compile flags).

### Static vs Dynamic
- Static link for OpenSSL and Brotli.
- Keep glibc dynamic (avoid full static glibc to reduce compatibility risk).

## Caching
- **Tarball cache**: Store downloaded nginx/pcre2/zlib archives in `~/.cache/nginx-ech/archives`.
- **Git cache**: Cache OpenSSL and ngx_brotli repositories (with submodules).
- **Compiler cache**: Use `ccache` with `~/.cache/nginx-ech/ccache`.
- Cache keys must include all pinned version refs to ensure correct invalidation on upgrades.

## Smoke Test Strategy (ECH End-to-End)
### Overview
Perform a real TLS ECH handshake using OpenSSL’s ECH-enabled `openssl` CLI, then send an HTTP request over that handshake to confirm the server is reachable and routing by the inner SNI. Use multiple test domains to prove that the inner name is hidden from plaintext SNI.

### Certificates (Generated Per Run)
- Generate a short-lived test CA (ECDSA P-256).
- Generate multiple ECDSA P-256 leaf certs (distinct SANs), signed by the test CA.
- No caching of certs; generation is fast and avoids expiration issues.

Example intent:
- CA: `Test CA`
- Leaf certs: `outer.example.test`, `inner1.example.test`, `inner2.example.test`
- Each leaf uses SANs and a unique `server_name` in Nginx.

### ECH Config
- Use the OpenSSL ECH branch tooling to generate:
  - ECH key material for the server.
  - An ECHConfigList blob for the client.
- Store files under the workflow workspace for the test run.
- The exact OpenSSL command names can vary by ECH branch; pin the OpenSSL ref and update this step if upstream CLI flags change.

### Nginx Test Config
- Bind to loopback, e.g., `127.0.0.1:8443`.
- Multiple `server` blocks:
  - Distinct `server_name` values (e.g., `inner1.example.test`, `inner2.example.test`).
  - Unique response bodies per server for validation.
  - Shared CA-signed certs and ECH directives (per nginx ECH docs).

### Client Validation
Use the ECH-enabled OpenSSL client to:
- Provide the ECHConfigList directly (no DNS/SVCB required).
- Set `-servername` to the *inner* SNI.
- Trust the test CA.
- Send an HTTP request over the TLS session and verify the response body.

Example shape (exact flags may vary by OpenSSL ECH ref):
```
printf 'GET / HTTP/1.1\r\nHost: inner1.example.test\r\nConnection: close\r\n\r\n' | \
  /path/to/ech-openssl/openssl s_client \
    -connect 127.0.0.1:8443 \
    -servername inner1.example.test \
    -CAfile /path/to/test-ca.crt \
    -ech_config /path/to/echconfig.bin \
    -quiet
```

Pass criteria:
- TLS handshake completes with ECH enabled (s_client output indicates ECH success for the pinned ref).
- HTTP response body matches the expected server (e.g., `inner1` vs `inner2`).

## Non-Goals
- Packaging as a Debian `.deb` in CI.
- Producing a fully static (glibc-static) binary.
- ECH verification with stock curl (not ECH-capable).
