#!/usr/bin/env bash
# Runs the ground-truth questions of REPORT.md in fast and slow mode (and, with ANSWER=1, with the model)
# and stores the output under out/questions/. Usage: bash scripts/run_questions.sh   |   ANSWER=1 bash scripts/run_questions.sh
set -euo pipefail
cd "$(dirname "$0")/.."
RAG=${RAG:-.venv/bin/rag-retrieve}
OUT=${OUT:-out/questions}
mkdir -p "$OUT"
QUESTIONS=(
  "Wer ist für IAM/Keycloak zuständig und wie eskaliere ich?"
  "Was passiert, wenn Vault versiegelt ist?"
  "Was war bei ZSDSUP-0247?"
  "In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?"
  "Auf welchen Servern und Ports läuft ZSD?"
  "Wer darf Vault entsiegeln und wie?"
  "Ich will den Dispatcher neu starten – was hängt daran?"
  "Wie erneuere ich ein TLS-Zertifikat?"
  "Wie backe ich einen Apfelkuchen?"
)
i=0
for q in "${QUESTIONS[@]}"; do
  i=$((i + 1))
  echo "== $i: $q"
  "$RAG" ask "$q" --no-graph > "$OUT/$i-fast.txt" 2>&1 || true
  "$RAG" ask "$q" --show-context > "$OUT/$i-slow.txt" 2>&1 || true
  if [ "${ANSWER:-0}" = "1" ]; then
    "$RAG" ask "$q" --answer > "$OUT/$i-answer.txt" 2>&1 || echo "   (exit $? — guardrail or error, see $OUT/$i-answer.txt)"
  fi
  grep -E "^(Modus|Kanäle|Guardrail)" "$OUT/$i-slow.txt" | sed 's/^/   /'
done
echo "written to $OUT/"
