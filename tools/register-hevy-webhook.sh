#!/usr/bin/env bash
# Register (or rotate) the htb webhook with Hevy.
#
# Reads HEVY_API_KEY from env (or .env in repo root). Generates a fresh
# HEVY_WEBHOOK_SECRET if one isn't already in the .env. Posts the webhook
# config to Hevy and writes the secret back to .env on success.
#
# Run from repo root:  tools/register-hevy-webhook.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
WEBHOOK_URL="${WEBHOOK_URL:-https://htb.home.vogelcc.com/webhooks/hevy}"

if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

if [[ -z "${HEVY_API_KEY:-}" ]]; then
  echo "abort: HEVY_API_KEY not set (env or $ENV_FILE)" >&2
  exit 1
fi

if [[ -z "${HEVY_WEBHOOK_SECRET:-}" ]]; then
  HEVY_WEBHOOK_SECRET="$(openssl rand -hex 32)"
  echo "generated new HEVY_WEBHOOK_SECRET"
fi

echo "registering webhook -> $WEBHOOK_URL"
http_status=$(curl -s -o /tmp/hevy-webhook.json -w "%{http_code}" \
  -X POST "https://api.hevyapp.com/v1/webhook-subscription" \
  -H "api-key: $HEVY_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$WEBHOOK_URL\",\"authToken\":\"$HEVY_WEBHOOK_SECRET\"}")

if [[ "$http_status" -lt 200 || "$http_status" -ge 300 ]]; then
  echo "abort: hevy returned HTTP $http_status" >&2
  cat /tmp/hevy-webhook.json >&2 || true
  exit 1
fi

if grep -q '^HEVY_WEBHOOK_SECRET=' "$ENV_FILE" 2>/dev/null; then
  awk -v k="$HEVY_WEBHOOK_SECRET" '/^HEVY_WEBHOOK_SECRET=/ { print "HEVY_WEBHOOK_SECRET=" k; next } { print }' "$ENV_FILE" > "$ENV_FILE.new"
  mv "$ENV_FILE.new" "$ENV_FILE"
else
  echo "HEVY_WEBHOOK_SECRET=$HEVY_WEBHOOK_SECRET" >> "$ENV_FILE"
fi

echo "ok. webhook registered. response:"
cat /tmp/hevy-webhook.json
echo
echo
echo "next: copy HEVY_WEBHOOK_SECRET to host .env and restart the API:"
echo "  ssh hd 'cd ~/compose/hack-the-body && (grep -q ^HEVY_WEBHOOK_SECRET= .env && sed -i \"s|^HEVY_WEBHOOK_SECRET=.*|HEVY_WEBHOOK_SECRET=$HEVY_WEBHOOK_SECRET|\" .env || echo HEVY_WEBHOOK_SECRET=$HEVY_WEBHOOK_SECRET >> .env) && docker compose up -d app'"
