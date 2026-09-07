#!/usr/bin/env bash
# Wait until the compose Postgres accepts connections (replaces `up --wait`, which podman-compose lacks).
#   bash scripts/wait_db.sh            WAIT_TIMEOUT=120 COMPOSE="podman-compose" bash scripts/wait_db.sh
set -u
cd "$(dirname "$0")/.."
COMPOSE="${COMPOSE:-docker compose}"
TIMEOUT="${WAIT_TIMEOUT:-90}"
start=$(date +%s)
while :; do
  if $COMPOSE --profile postgres exec -T postgres pg_isready -U chat -d chat >/dev/null 2>&1; then
    echo "postgres ready ($(( $(date +%s) - start ))s)"; exit 0
  fi
  if [ $(( $(date +%s) - start )) -ge "$TIMEOUT" ]; then
    echo "postgres not ready after ${TIMEOUT}s" >&2
    $COMPOSE --profile postgres ps 2>&1 | sed 's/^/  /' >&2
    $COMPOSE --profile postgres logs --tail 30 postgres 2>&1 | sed 's/^/  /' >&2
    exit 1
  fi
  sleep 2
done
