#!/usr/bin/env bash
# Pulls the org auth chart (read-only: nothing is installed anywhere) and collects what decides the headers our app
# receives: oauth2-proxy flags, header/claim settings, mesh authz objects, Vault and ServiceAccount wiring.
#
# Usage: ./inspect-auth-chart.sh oci://<artifactory>/<path>/cc-r444-core-auth <version>
#   REG_USER=<user> ./inspect-auth-chart.sh …   asks for the password and logs in to the registry first
#   OUT=<dir>                                   output folder (default ./auth-chart)
#   HELM_IMAGE=<mirror>/alpine/helm:3.19.0      used when helm is not installed (default docker.io/alpine/helm:3.19.0)
# Result: <out>/<chart>/ (the chart), <out>/rendered.yaml (helm template with defaults), <out>/summary.txt
set -euo pipefail

chart=${1:?usage: $0 oci://<host>/<path>/<chart> <version>}
version=${2:?usage: $0 oci://<host>/<path>/<chart> <version>}
[[ $chart == oci://* ]] || { echo "expects an oci:// reference, got: $chart" >&2; exit 2; }
host=${chart#oci://}
host=${host%%/*}
name=$(basename "$chart")
out=${OUT:-./auth-chart}
mkdir -p "$out"
out=$(cd "$out" && pwd)

REG_USER=${REG_USER:-}
REG_PASS=
if [[ -n $REG_USER ]]; then
  read -rsp "registry password for $REG_USER@$host: " REG_PASS
  echo
fi
export REG_USER REG_PASS REG_HOST=$host CHART=$chart VERSION=$version NAME=$name

# runs in the host shell or in the helm container; OUTDIR differs between the two
# shellcheck disable=SC2016
steps='
set -e
if [ -n "$REG_USER" ]; then printf %s "$REG_PASS" | helm registry login "$REG_HOST" -u "$REG_USER" --password-stdin; fi
rm -rf "$OUTDIR/$NAME"
helm pull "$CHART" --version "$VERSION" --untar --untardir "$OUTDIR"
helm template auth "$OUTDIR/$NAME" > "$OUTDIR/rendered.yaml" 2> "$OUTDIR/rendered.err" \
  || echo "helm template needs values (see rendered.err); the raw templates are still in $NAME/templates"
'

if command -v helm >/dev/null; then
  OUTDIR=$out sh -c "$steps"
else
  # a shell alias docker=podman is invisible to scripts, so look for either binary
  ctr=$(command -v docker || command -v podman) || { echo "neither helm nor docker/podman found" >&2; exit 1; }
  # rootless podman maps the container's root to you; docker needs --user to avoid root-owned files
  user_opt=(--user "$(id -u):$(id -g)")
  "$ctr" --version 2>/dev/null | grep -qi podman && user_opt=()
  z=
  command -v getenforce >/dev/null && [[ $(getenforce) == Enforcing ]] && z=:Z
  # fully qualified default: podman refuses short names without a TTY to ask
  "$ctr" run --rm "${user_opt[@]}" -e HOME=/tmp -e OUTDIR=/out \
    -e REG_USER -e REG_PASS -e REG_HOST -e CHART -e VERSION -e NAME \
    -v "$out:/out$z" --entrypoint sh "${HELM_IMAGE:-docker.io/alpine/helm:3.19.0}" -c "$steps"
fi

pattern='x-forwarded|x-auth-request|pass-user-headers|pass-basic-auth|pass-authorization-header|pass-access-token'
pattern+='|set-xauthrequest|prefer-email|injectRequestHeaders|claim|upstream|redirect.?ur[il]|callback|http-address'
pattern+='|AuthorizationPolicy|ext_?authz|extensionProvider|headersTo|RequestAuthentication|sidecar|inject'
pattern+='|vault|serviceAccount|redis|cookie|image:|repository:|tag:|port'
{
  echo "# $chart $version"
  echo
  echo "## Chart.yaml"
  cat "$out/$name/Chart.yaml"
  echo
  echo "## objects rendered with default values"
  grep -h '^kind:' "$out/rendered.yaml" 2>/dev/null | sort | uniq -c || echo "(none - helm template failed, see rendered.err)"
  echo
  echo "## files"
  (cd "$out/$name" && find . -type f | sort)
  echo
  echo "## lines about headers, claims, routing, mesh, Vault, images"
  grep -rniE "$pattern" "$out/$name" || true
} > "$out/summary.txt"

echo "done: $out/summary.txt  (chart in $out/$name, rendered objects in $out/rendered.yaml)"
