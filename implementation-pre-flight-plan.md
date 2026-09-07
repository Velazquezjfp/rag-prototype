# Implementation plan: `preflight` — deep endpoint verification for docling-graph-service

Status: agreed with the user on 2026-08-31, not yet implemented. Context: the remote deployment (CentOS,
Docker `--profile local`, models behind per-session SSH tunnels on the host loopback, LLM =
qwen3-coder-30B-A3B, VLM = gemma4:latest, corporate proxy for https only) failed in ways a one-minute probe
would have caught: VLM answered without seeing images ("blind hallucination" — endpoint probe said ok because
it only pings `/models`), served context window smaller than configured (silent prompt truncation → zero-yield
chunks → coverage-pass batches timing out at `timeout_s=300`), shell proxy intercepting client HTTP.

**Goal:** `dgs preflight` (CLI) + `POST /v1/preflight` (API) that truly test the three endpoints and the
configured variables before a batch run, with expected outcomes, clear PASS/WARN/FAIL and suggested `.env`
values — so models can be swapped and trusted. Report + suggest, **never** silently auto-adapt at runtime.
`/healthz` stays cheap and unchanged; preflight never runs inside `/v1/process`.

## Where the code goes (all inside `docling-graph/`)

| File | Change |
|---|---|
| `src/docling_graph_service/preflight.py` | NEW — all probes + report model |
| `src/docling_graph_service/describe.py` | reuse `describe_picture()` for the VLM probe (no change needed unless a helper hook is cleaner) |
| `src/docling_graph_service/api.py` | `POST /v1/preflight` → runs probes in `anyio.to_thread`, returns the report JSON; not behind the CapacityLimiter (but refuse while a process job runs? — no: probes are cheap, allow always) |
| `src/docling_graph_service/cli.py` | `dgs preflight` → same report, human-readable table + suggested `.env` block, exit code 1 on any FAIL |
| `src/docling_graph_service/pipeline.py` | production hardening: WARN (in `warnings[]`) when a stored picture description shares zero content tokens with the figure caption/context |
| `tests/unit/test_preflight.py` | NEW — every probe against `httpx.MockTransport` (success, blind-VLM, truncation, dim mismatch, slow endpoint) |
| `tests/integration/test_vlm_quality.py` | NEW — real-diagram quality check (see below), `DGS_INTEGRATION=1` + skip when `vlm.enabled` false |
| `DEPLOY.md` | new §: "run `dgs preflight` (or POST /v1/preflight) before every batch"; troubleshooting rows map probe FAILs to fixes |
| `README.md` | one paragraph + endpoint row in the API table |

## Report shape

```json
{"status": "pass|warn|fail",
 "checks": [{"name": "llm.completion", "status": "pass", "detail": "...", "measured": {...}}, ...],
 "suggested_env": {"DGS__LLM__CONTEXT_LIMIT": 26000, "DGS__LLM__TIMEOUT_S": 900, ...}}
```

## Probes (each: expected outcome → PASS/WARN/FAIL + reason; all via the existing `llm_http.LLMClient`
with `trust_env` semantics already in place; every probe individually try/excepted — one failure never stops the rest)

1. **llm.models** — `GET /models`; configured `llm.model` id in the list. Missing id → FAIL (names the ids found).
2. **llm.completion** — 1 tiny chat call, `max_tokens=16`. Round-trip + non-empty content → PASS.
3. **llm.structured_output** — one call with `response_format={"type":"json_schema", ...}` (trivial schema),
   fallback try `json_object`. Result: which modes the endpoint accepts → WARN if `llm.structured_output=true`
   but json_schema rejected (suggest `DGS__LLM__STRUCTURED_OUTPUT=false`; docling-graph falls back anyway, but
   the operator should know).
4. **llm.context** — measure the EFFECTIVE window via `usage.prompt_tokens` (works on vLLM, Ollama, LiteLLM):
   send filler prompts (`"wort " * N`), `max_tokens=1`, at ~2k → 8k → 32k → (config value) tokens, stop
   ascending when `usage.prompt_tokens` caps below what was sent (= truncation) or the call errors
   ("context length exceeded" = the honest kind of endpoint). Measured window M. Checks:
   - `llm.context_limit > M` → FAIL "configured limit exceeds served window: prompts get truncated".
   - suggestion: `CONTEXT_LIMIT = min(0.8*M, M - llm.max_output_tokens)` (the 80% rule with output headroom;
     docling-graph sizes dense batches from context_limit).
5. **llm.speed** — one timed ~200-token generation → tokens/sec + time-to-first... (no streaming; just total).
   Estimate per-skeleton-call seconds ≈ (context_limit tokens prompt-eval + max_output gen) / measured rates —
   keep the formula rough and label it an estimate. WARN if estimate × safety(2) > `llm.timeout_s`, suggest
   `TIMEOUT_S` and note `PARALLEL_WORKERS=1` when the endpoint is a single-GPU server (can't detect; phrase as hint).
6. **vlm.vision** (only if `vlm.enabled`) — generate a PNG in-process with PIL: white canvas ~600×300, a random
   6-char code (e.g. `K7F3QX`) drawn large, two labeled boxes "IAM" → "VPP" with an arrow. Send through the
   PRODUCTION path `describe.describe_picture()` (same encoding, same client). PASS = response contains the
   random code (case-insensitive); code absent but labels present → WARN "partially read"; neither → FAIL
   "endpoint answers but does not see the image (text-only model or encoding ignored)". This catches the
   blind-hallucination case the `/models` ping cannot.
7. **embedding.roundtrip** — 3 short texts w/ configured prefix; checks: count 3, order (probe by distinct
   lengths is NOT reliable — instead verify index fields), dim == `embedding.dim` (mismatch → FAIL with the
   real dim as suggestion), latency noted.
8. **config crosschecks** (no network) — `max_output_tokens ≤ context_limit`, deadline vs. timeout×retries
   sanity, vlm.max_tokens ≥ 1000 hint for thinking models.

CLI output: aligned table (check, status, detail), then `# suggested .env` block printed verbatim, exit 1 iff
any FAIL. API returns the JSON; `scripts/process_via_api.py` gets `--preflight` flag: call the endpoint first,
abort before upload if FAIL (keeps the "test before batch" habit one flag away).

## Integration-tier VLM quality test (separate from preflight)

`tests/integration/test_vlm_quality.py`: downscale `user-manual-books/handbuch_daten/handbuch/diagramme-png/
zsd1-uebersicht.png` (4800px → ≤1600px, PIL), send via `describe_picture()` with the production prompt.
Assert deterministic **label coverage** (no LLM judge): description mentions ≥4 of
{IAM, PKI, Vault, VPP, CaaS, Dokumentendienste|Mars, Event-System}, length 200–3000 chars.
Purpose: acceptance test for whichever vision model is configured; also validates the probe criteria locally
(gemini-dev passes it — verify once here before shipping).

## Production hardening (small, same PR)

In `pipeline.py` after `describe_pictures`: for each stored description, tokenize crudely (words ≥4 chars,
casefold); if intersection with (caption + surrounding heading breadcrumb) is empty AND the description is
non-trivial → append warning `"vlm: description for #/pictures/N shares no terms with its caption — verify
the model actually sees images (run dgs preflight)"`. Never degrades, never blocks.

## Verification checklist (after implementing)

1. `pytest tests/unit -q` — new probe tests green (MockTransport scenarios incl. truncated-context server that
   caps `usage.prompt_tokens`, blind VLM returning fluent text without the code, wrong-dim embeddings).
2. Local live: `.venv/bin/dgs preflight` against LiteLLM (gemini-dev + bge-m3) → all PASS; context probe
   reports gemini's window ≥ configured; vision probe finds the random code.
3. `curl -X POST localhost:8080/v1/preflight` (native serve) → same JSON.
4. Negative check locally: `DGS__VLM__MODEL=granite4 dgs preflight` → vlm.vision FAIL (granite4 has no vision) —
   proves the blind-model detection.
5. Rebuild image (`docker compose --profile local build` — only the src layer changes, fast) and smoke
   `POST /v1/preflight` through the container.
6. Ship to server: rsync `src/`, `scripts/`, `tests/` → `docker compose --profile local build && up -d` there.

## Constraints / decisions already made (do not re-litigate)

- pip not uv; no new Python dependencies (PIL, httpx, PIL already present).
- Report+suggest only; no auto-tuning; `/healthz` untouched.
- No LLM-as-judge anywhere in preflight — deterministic checks only (random code, label coverage, usage counts).
- Probes go through the same client/code paths as production so a pass predicts pipeline behaviour.
- Remote context measured (num_ctx reality) beats model-card values; user's qwen endpoint likely serves a
  small window — the suggested CONTEXT_LIMIT/TIMEOUT_S values from probe 4/5 are the fix for the observed
  coverage-pass timeouts (`full_document_coverage_dense_skeleton_16+ timeout` pattern).
