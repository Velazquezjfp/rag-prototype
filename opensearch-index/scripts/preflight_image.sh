#!/usr/bin/env bash
# Can this machine get the OpenSearch image? Decide BEFORE building anything on a server behind a proxy.
#
#   bash scripts/preflight_image.sh                       # opensearchproject/opensearch:3.8.0 (or $OPENSEARCH_IMAGE / .env)
#   bash scripts/preflight_image.sh <registry>/<repo>/opensearchproject/opensearch:3.8.0
#
# Checks, in order: image already present locally -> registry manifest reachable (downloads only KBs) -> one-time
# look inside the image (uid, curl for the compose healthcheck). On failure it prints the three fixes in order.
set -u
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
IMG="${1:-${OPENSEARCH_IMAGE:-opensearchproject/opensearch:3.8.0}}"
DASH="${DASHBOARDS_IMAGE:-opensearchproject/opensearch-dashboards:${IMG##*:}}"
BASE="${BASE_IMAGE:-python:3.12-slim}"
rc=0

say() { printf '%s\n' "$*"; }
check_image() {
  local img="$1" what="$2"
  say "== $what: $img"
  if docker image inspect "$img" >/dev/null 2>&1; then
    say "   present locally -> nothing to pull"
    return 0
  fi
  if out=$(docker manifest inspect "$img" 2>&1); then
    say "   registry reachable, tag exists (manifest inspect ok) -> 'docker compose pull' should work"
    say "   note: manifest inspect used the CLI's proxy settings (HTTPS_PROXY in this shell); the actual pull runs"
    say "         inside dockerd, which needs its OWN proxy config if the shell needs one (fix b below)."
    return 0
  fi
  say "   NOT reachable: ${out%%$'\n'*}"
  return 1
}

check_image "$IMG" "OpenSearch node image" || rc=1
check_image "$DASH" "Dashboards image (optional, profile dashboards)" || true
check_image "$BASE" "indexer base image (optional, profile tools)" || true

if [ "$rc" -ne 0 ]; then
  cat <<TXT

The node image cannot be pulled from here. Fixes, cheapest first:

 a) Internal registry mirror (the channel that already delivered python:3.12 on the server). In .env:
      OPENSEARCH_IMAGE=<artifactory-host>/<docker-remote-repo>/opensearchproject/opensearch:${IMG##*:}
    then re-run this script with no arguments.

 b) Daemon proxy. 'docker pull' / 'docker compose pull' run inside dockerd, which ignores the shell's proxy variables.
      sudo mkdir -p /etc/docker && sudo tee /etc/docker/daemon.json <<'JSON'
      {"proxies": {"http-proxy": "http://<proxy>:<port>", "https-proxy": "http://<proxy>:<port>",
                   "no-proxy": "localhost,127.0.0.1,<artifactory-host>,<registry-host>,.<internal-domain>"}}
JSON
      sudo systemctl daemon-reload && sudo systemctl restart docker
    (or a systemd drop-in /etc/systemd/system/docker.service.d/http-proxy.conf with Environment="HTTPS_PROXY=...").

 c) Offline transfer (proven with dgs:local). On a machine that can pull:
      docker pull $IMG && docker save $IMG | gzip > opensearch-${IMG##*:}.tar.gz      # ~2 GB image
    copy it over, then on the server:
      gunzip -c opensearch-${IMG##*:}.tar.gz | docker load
TXT
  exit 1
fi

if docker image inspect "$IMG" >/dev/null 2>&1; then
  say "== inside the image (one-time check for the compose healthcheck)"
  docker run --rm --entrypoint sh "$IMG" -c 'echo "   uid=$(id -u) gid=$(id -g) ($(id -un))"; if command -v curl >/dev/null; then echo "   curl: $(curl --version | head -1)"; else echo "   curl: MISSING -> replace the healthcheck with: bash -c \"exec 3<>/dev/tcp/127.0.0.1/9200\""; fi' 2>&1 || say "   (could not run the image)"
fi
say "== host: vm.max_map_count=$(sysctl -n vm.max_map_count 2>/dev/null || echo '?') (need >= 262144)"
say "OK"
