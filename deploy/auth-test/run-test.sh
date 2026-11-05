#!/usr/bin/env bash
# Logs in through oauth2-proxy + Dex with curl and prints what the app behind the proxy receives.
# Usage: ./run-test.sh            (starts the stack if needed; `docker compose down` to stop it)
set -euo pipefail
cd "$(dirname "$0")"

PROXY=http://localhost:4180
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
c() { curl -sS --noproxy '*' "$@"; }

docker compose up -d >/dev/null
c -f -o /dev/null --retry 30 --retry-delay 1 --retry-all-errors "$PROXY/ping"

echo "== 1. without login: the proxy answers, the app is not reached"
c -o /dev/null -w 'HTTP %{http_code} -> %{redirect_url}\n' "$PROXY/"

echo
echo "== 2. login as max.muster@example.org: headers the app receives"
login_url=$(c -c "$jar" -b "$jar" -L -o /dev/null -w '%{url_effective}' "$PROXY/")
c -c "$jar" -b "$jar" -L --data-urlencode login=max.muster@example.org --data-urlencode password=password "$login_url" \
  | grep -iE '^(x-|authorization|cookie)' | sed 's/^/   /'

echo
echo "== 3. forged header from the client: does it reach the app?"
c -b "$jar" -H 'X-Forwarded-User: intruder' -H 'X-Forwarded-Email: intruder@example.org' "$PROXY/" \
  | grep -iE '^x-forwarded-(user|email)' | sed 's/^/   /'
