#!/usr/bin/env bash
set -euo pipefail

project="clipflow-smoke-$$"
scratch=$(mktemp -d)
compose() { docker compose -p "$project" "$@"; }
cleanup() {
    compose down --volumes >/dev/null 2>&1 || true
    rm -rf "$scratch"
}
trap cleanup EXIT
export CLIPFLOW_SITE=http://:80 CLIPFLOW_BIND_IP=127.0.0.1
export CLIPFLOW_HTTP_PORT=34880 CLIPFLOW_HTTPS_PORT=34843 CLIPFLOW_OWNER=owner
fixture_password=$(openssl rand -hex 24)
export CLIPFLOW_OWNER_HASH
CLIPFLOW_OWNER_HASH=$(docker run --rm caddy:2.10-alpine caddy hash-password --plaintext "$fixture_password")
export CLIPFLOW_SUPABASE_URL=https://example.supabase.co CLIPFLOW_SUPABASE_KEY=fixture
export CLIPFLOW_OWNER_ID=6c2ee342-0886-4e58-8f2e-cc35f9d8bc2c
export CLIPFLOW_SESSION_SECRET=fixture-configuration-does-not-contact-any-provider
export CLIPFLOW_R2_ACCOUNT_ID=11111111111111111111111111111111 CLIPFLOW_R2_BUCKET=fixture
export CLIPFLOW_R2_ACCESS_KEY_ID=fixture CLIPFLOW_R2_SECRET_ACCESS_KEY=fixture
compose -f compose.yaml -f compose.integrations.yaml config --quiet
unset CLIPFLOW_SUPABASE_URL CLIPFLOW_SUPABASE_KEY CLIPFLOW_OWNER_ID CLIPFLOW_SESSION_SECRET
unset CLIPFLOW_R2_ACCOUNT_ID CLIPFLOW_R2_BUCKET CLIPFLOW_R2_ACCESS_KEY_ID CLIPFLOW_R2_SECRET_ACCESS_KEY
if [[ -n "${CODEX_PROXY_CERT:-}" && -r /etc/ssl/certs/ca-certificates.crt ]]; then
    docker build --secret id=build-ca,src=/etc/ssl/certs/ca-certificates.crt -t clipflow-owner:preview .
    compose up -d --no-build
else
    compose up -d --build
fi
base=http://127.0.0.1:34880
request() {
    curl --noproxy '*' -sS --max-time 7 -u "$CLIPFLOW_OWNER:$fixture_password" "$@"
}
wait_status() {
    local actual
    for _ in {1..20}; do
        actual=$(request -o "$scratch/response" -w '%{http_code}' -r 0-31 "$base$1" 2>/dev/null || true)
        if [ "$actual" = "$2" ]; then
            return 0
        fi
        sleep 1
    done
    echo "Expected HTTP $2 on $1, received $actual"
    compose logs --tail=12 web worker gateway
    return 1
}
wait_status /api/jobs 200
test "$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' "$base/api/jobs")" = 401
ffmpeg -nostdin -v error -f lavfi -i 'color=c=black:s=320x180:r=30' -t 3 -c:v libx264 "$scratch/source.mp4"
job=$(request --fail -H 'Content-Type: video/mp4' -H "Idempotency-Key: $(cat /proc/sys/kernel/random/uuid)" \
    -H 'X-Clip-Start: 0' -H 'X-Clip-End: 2' --data-binary "@$scratch/source.mp4" "$base/api/jobs" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
wait_status "/media/$job" 206
test "$(wc -c < "$scratch/response")" -eq 32
compose restart web worker
wait_status "/media/$job" 206
echo 'Passed: gateway auth, video upload, FFmpeg worker, byte-range playback, and restart persistence.'
