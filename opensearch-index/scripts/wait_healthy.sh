#!/usr/bin/env bash
# Wait until the OpenSearch node answers with cluster status yellow or green (the final state of a single node).
# Replaces `docker compose up --wait`, which podman-compose does not implement; works with any engine because it
# only talks to the published port on the host. On timeout it prints the container state and the last log lines.
#
#   bash scripts/wait_healthy.sh                   # OPENSEARCH_BIND / OPENSEARCH_PORT from .env, default 127.0.0.1:9200
#   WAIT_TIMEOUT=600 bash scripts/wait_healthy.sh
#   COMPOSE="podman-compose" bash scripts/wait_healthy.sh
set -u
cd "$(dirname "$0")/.."

# Read only the two values we need. .env is deliberately NOT sourced: it may carry build-time proxy variables
# (HTTP_PROXY, http_proxy) that would send curl's loopback request to a corporate proxy.
envval() { [ -f .env ] && sed -n "s/^[[:space:]]*$1=//p" .env | tail -1 | tr -d "\"'" | sed 's/[[:space:]]*#.*$//'; }
HOST="${OPENSEARCH_BIND:-$(envval OPENSEARCH_BIND)}"; HOST="${HOST:-127.0.0.1}"
[ "$HOST" = "0.0.0.0" ] && HOST=127.0.0.1
PORT="${OPENSEARCH_PORT:-$(envval OPENSEARCH_PORT)}"; PORT="${PORT:-9200}"
TIMEOUT="${WAIT_TIMEOUT:-300}"
COMPOSE="${COMPOSE:-docker compose}"
URL="http://${HOST}:${PORT}/_cluster/health?wait_for_status=yellow&timeout=5s"

start=$(date +%s); last=0
while :; do
  if out=$(curl -fsS --noproxy '*' --max-time 8 "$URL" 2>/dev/null); then
    status=$(printf '%s' "$out" | sed -n 's/.*"status":"\([a-z]*\)".*/\1/p')
    printf 'opensearch ready at http://%s:%s (cluster status %s, %ss)\n' "$HOST" "$PORT" "${status:-?}" "$(( $(date +%s) - start ))"
    exit 0
  fi
  now=$(( $(date +%s) - start ))
  if [ "$now" -ge "$TIMEOUT" ]; then
    {
      echo "opensearch not ready after ${TIMEOUT}s at http://${HOST}:${PORT}"
      echo "--- $COMPOSE ps ---"
      $COMPOSE ps 2>&1 | sed 's/^/  /'
      echo "--- $COMPOSE logs --tail 40 opensearch ---"
      $COMPOSE logs --tail 40 opensearch 2>&1 | grep -v '^[[:space:]]*$' | tail -40 | sed 's/^/  /'
      echo "--- known causes (DEPLOY.md §5/§6) ---"
      echo "  'vm.max_map_count [65530] is too low'            -> sysctl vm.max_map_count=262144"
      echo "  'AccessDeniedException ... /data/nodes'          -> ownership: rootless podman => podman unshare chown -R 1000:1000 data/opensearch (make init does it);"
      echo "                                                      or SELinux => SELINUX_LABEL=,Z in .env, check getenforce"
      echo "  'memory locking requested ... not locked'         -> OPENSEARCH_MEMORY_LOCK=false in .env"
      echo "  container Up but no answer                       -> still booting on a slow host: WAIT_TIMEOUT=600 make wait"
    } >&2
    exit 1
  fi
  if [ $(( now - last )) -ge 30 ]; then echo "waiting for opensearch at http://${HOST}:${PORT} (${now}s) ..."; last=$now; fi
  sleep 3
done
