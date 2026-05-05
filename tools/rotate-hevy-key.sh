#!/usr/bin/env bash
# Rotate the Hevy API key in local .env and on deployment hosts.
#
# Usage:  tools/rotate-hevy-key.sh
#
# Prereqs:
#   1. Generate a new key at https://hevy.com/settings?developer
#      (this also invalidates the old one).
#   2. Have it on your clipboard / ready to paste.
#
# What it does:
#   - Updates HEVY_API_KEY in repo-root .env (local dev).
#   - SSHes to each host in $HEVY_DEPLOY_HOSTS, rewrites
#     ~/compose/hack-the-body/.env, and restarts the ingestor.
#
# Configure hosts inline or via env:
#   HEVY_DEPLOY_HOSTS="hd remote-host"  tools/rotate-hevy-key.sh

set -euo pipefail

HOSTS="${HEVY_DEPLOY_HOSTS:-hd}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_ENV="$REPO_ROOT/.env"

read -rsp "New Hevy API key: " NEW_KEY
echo
if [[ -z "$NEW_KEY" ]]; then
  echo "abort: empty key" >&2
  exit 1
fi

# --- local .env ---
if [[ -f "$LOCAL_ENV" ]] && grep -q '^HEVY_API_KEY=' "$LOCAL_ENV"; then
  # Use a sed-safe delimiter since UUIDs are tame, but be defensive.
  tmp="$(mktemp)"
  awk -v k="$NEW_KEY" '
    /^HEVY_API_KEY=/ { print "HEVY_API_KEY=" k; next }
    { print }
  ' "$LOCAL_ENV" > "$tmp"
  mv "$tmp" "$LOCAL_ENV"
  echo "updated $LOCAL_ENV"
else
  echo "HEVY_API_KEY=$NEW_KEY" >> "$LOCAL_ENV"
  echo "appended HEVY_API_KEY to $LOCAL_ENV"
fi

# --- remote hosts ---
for host in $HOSTS; do
  echo "→ $host"
  ssh "$host" "bash -s" <<EOF
set -euo pipefail
cd ~/compose/hack-the-body
if grep -q '^HEVY_API_KEY=' .env; then
  awk -v k="$NEW_KEY" '/^HEVY_API_KEY=/ { print "HEVY_API_KEY=" k; next } { print }' .env > .env.new
  mv .env.new .env
else
  echo "HEVY_API_KEY=$NEW_KEY" >> .env
fi
docker compose up -d ingestor-hevy 2>/dev/null || docker compose restart ingestor-hevy 2>/dev/null || true
echo "  $host: .env updated"
EOF
done

echo "done. test with: curl -H \"api-key: \$NEW_KEY\" https://api.hevyapp.com/v1/workouts?page=1\&pageSize=1"
