#!/usr/bin/env bash
set -euxo pipefail

mkdir -p conf/test-certs conf/test-ech logs
ln -sfn conf/test-certs test-certs
ln -sfn conf/test-ech test-ech

OPENSSL_BIN="$PWD/test-openssl/bin/openssl"
CERT_DIR="$PWD/conf/test-certs"
ECH_DIR="$PWD/conf/test-ech"
export LD_LIBRARY_PATH="$PWD/test-openssl/lib"
export OPENSSL_CONF="$PWD/test-openssl/ssl/openssl.cnf"
mkdir -p "$PWD/test-openssl/ssl"
cat > "$OPENSSL_CONF" <<'EOF_CONF'
openssl_conf = openssl_init

[openssl_init]
providers = provider_sect

[provider_sect]
default = default_sect

[default_sect]
activate = 1
EOF_CONF

"$OPENSSL_BIN" genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$CERT_DIR/ca.key"
"$OPENSSL_BIN" req -x509 -new -key "$CERT_DIR/ca.key" -sha256 -days 30 -subj "/CN=Test CA" -out "$CERT_DIR/ca.crt"

for DOMAIN in outer.example.test this.doesnt.exist whats.going.on bananas.arent.real blue.seaglass; do
  NAME=$(printf "%s" "$DOMAIN" | tr '.' '_')
  "$OPENSSL_BIN" genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$CERT_DIR/${NAME}.key"
  printf 'subjectAltName=DNS:%s\n' "$DOMAIN" > "$CERT_DIR/san.cnf"
  "$OPENSSL_BIN" req -new -key "$CERT_DIR/${NAME}.key" -subj "/CN=${DOMAIN}" -out "$CERT_DIR/${NAME}.csr"
  "$OPENSSL_BIN" x509 -req -in "$CERT_DIR/${NAME}.csr" -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial -days 30 -sha256 -extfile "$CERT_DIR/san.cnf" -out "$CERT_DIR/${NAME}.crt"
done

"$OPENSSL_BIN" list -commands | grep -i ech
"$OPENSSL_BIN" help ech
"$OPENSSL_BIN" ech -public_name outer.example.test -out "$ECH_DIR/echconfig.pem"
awk 'BEGIN{in_block=0} /BEGIN ECH/{in_block=1; next} /END ECH/{in_block=0} in_block{print}' \
  "$ECH_DIR/echconfig.pem" | tr -d '\n' > "$ECH_DIR/echconfig.b64"
base64 -d "$ECH_DIR/echconfig.b64" > "$ECH_DIR/echconfig.bin"

ECH_CONFIG_LIST="$(cat "$ECH_DIR/echconfig.b64")"

"$OPENSSL_BIN" s_client -help

./opt/nginx-ech/sbin/nginx -p "$PWD" -c conf/nginx.conf -t
./opt/nginx-ech/sbin/nginx -p "$PWD" -c conf/nginx.conf -g 'daemon off;' &
NGINX_PID=$!
sleep 1

for DOMAIN in this.doesnt.exist whats.going.on bananas.arent.real blue.seaglass; do
  RESPONSE_RAW="response-${DOMAIN}.raw"
  RESPONSE_BODY="response-${DOMAIN}.txt"
  EXPECTED_BODY="expected-${DOMAIN}.txt"
  TRACE_LOG="trace-${DOMAIN}.log"

  printf 'GET / HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n' "$DOMAIN" | \
    LD_LIBRARY_PATH="$PWD/test-openssl/lib" "$OPENSSL_BIN" s_client \
      -connect 127.0.0.1:8443 \
      -servername "$DOMAIN" \
      -CAfile "$CERT_DIR/ca.crt" \
      -ech_config_list "$ECH_CONFIG_LIST" \
      -ech_outer_sni outer.example.test \
      -trace \
      -quiet \
      >"$TRACE_LOG" 2>&1
  grep -q "encrypted_client_hello" "$TRACE_LOG"

  printf 'GET / HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n' "$DOMAIN" | \
    LD_LIBRARY_PATH="$PWD/test-openssl/lib" "$OPENSSL_BIN" s_client \
      -connect 127.0.0.1:8443 \
      -servername "$DOMAIN" \
      -CAfile "$CERT_DIR/ca.crt" \
      -ech_config_list "$ECH_CONFIG_LIST" \
      -ech_outer_sni outer.example.test \
      -quiet \
      >"$RESPONSE_RAW" 2>"$TRACE_LOG"

  awk 'BEGIN{body=0} /^\r?$/{body=1; next} {if(body) print}' \
    "$RESPONSE_RAW" >"$RESPONSE_BODY"
  printf "%s\n" "$DOMAIN" >"$EXPECTED_BODY"
  diff -u "$EXPECTED_BODY" "$RESPONSE_BODY"
done

./opt/nginx-ech/sbin/nginx -p "$PWD" -c conf/nginx.conf -s quit
wait "$NGINX_PID"
