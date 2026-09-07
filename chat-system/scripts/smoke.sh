#!/usr/bin/env bash
# Run the smoke questions through the headless CLI against the live stack (OpenSearch + LiteLLM from .env).
#   bash scripts/smoke.sh                    # -> out/smoke/<n>.txt and a summary line per question
set -u
cd "$(dirname "$0")/.."
mkdir -p out/smoke
n=0; fail=0
while IFS= read -r line; do
  [ -z "$line" ] && continue; case "$line" in \#*) continue;; esac
  n=$((n+1)); args=(); user=otto.ops
  case "$line" in fast:*) args+=(--no-graph); line="${line#fast:}";; esac
  case "$line" in user=*) user="${line%% *}"; user="${user#user=}"; line="${line#* }";; esac
  q="$(echo "$line" | sed 's/^[[:space:]]*//')"
  if .venv/bin/chat-ask "$q" --user "$user" "${args[@]}" > "out/smoke/$n.txt" 2>&1; then
    printf '%2d ok   [%s] %s\n' "$n" "$user" "$q"
  else
    rc=$?
    if [ "$rc" = 2 ]; then printf '%2d refused/guardrail [%s] %s -> %s\n' "$n" "$user" "$q" "$(tail -1 "out/smoke/$n.txt")"
    else printf '%2d FAIL (%s) [%s] %s -> %s\n' "$n" "$rc" "$user" "$q" "$(tail -1 "out/smoke/$n.txt")"; fail=$((fail+1)); fi
  fi
done < scripts/smoke_questions.txt
echo "answers in out/smoke/; failures: $fail"
[ "$fail" = 0 ]
