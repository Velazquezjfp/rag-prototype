# Retrieval report — the ground-truth questions against both indexed manuals (2026-09-04)

Stack: OpenSearch 3.8.0 on `http://localhost:9200` with `BHB-PLT-0001` (CaaS, 120 chunks / 210 nodes / 127 edges)
and `BHB-PLT-0007` (ZSD, 112 / 250 / 154) indexed; union graph 400 node ids (60 shared across the books), 281 edges
(8 negative); query embeddings `bge-m3` (1024, no prefix) and answers `gemini-dev` (gemini-3.7-flash) through the
LiteLLM proxy on `:4000`. Everything below is reproducible with `make questions` (retrieval only) and
`ANSWER=1 make questions` (plus model answers); the outputs land in `out/questions/`.

Settings: defaults of `config.yaml` (k 20 per channel, final 10, RRF constant 60, 30 start nodes, 40 facts, 15 entity
cards, 15 graph chunks with 2 guaranteed slots, context budget 6000, 25 facts in the prompt, `max_tokens` 4000).

## Results per question

Pages are those of the top-10 sources; "expected" is the ground truth of `3-modules-plan.md` (verified in the PDFs).
Fast = four search channels; slow = plus the 1-hop graph expansion.

| # | Question | Expected | Fast (top sources) | Slow (sources · facts · entities) | Verdict |
|---|---|---|---|---|---|
| 1 | Wer ist für IAM/Keycloak zuständig und wie eskaliere ich? | ZSD S. 1–2 (Ostermann, 1315), S. 26 (Eskalation); fact `Kai Ostermann —ESCALATES_TO→ Dr. Annika Reuß (level=2)` | ZSD S. 6 (IAM), S. 14 (SOP-ZSD-02), **S. 26 Tabelle 13 Eskalationsstufen**, S. 4 | labels `IAM`, `Keycloak` → 30 start nodes; S. 26 ranks #1; 40 facts (`IAM —OPERATED_BY→ ZSD`, `Kai Ostermann —RESPONSIBLE_FOR→ SOP-ZSD-02/-03/-06`, `Kai Ostermann —ESCALATES_TO→ Dr. Annika Reuß (level=2)`); entity card Kai Ostermann with role, phone 1315 from both books | ✅ pages and fact present; the "wer/zuständig/eskal" cues put RESPONSIBLE_FOR/ESCALATES_TO before DEPENDS_ON |
| 2 | Was passiert, wenn Vault versiegelt ist? | CaaS S. 19 (Tabelle 12, VPP "keine"), S. 12, 15; ZSD S. 19, 15; negative `Vault —DEPENDS_ON→ PKI/Keycloak NICHT`; entity `Vault versiegelt \| VPP` severity keine | CaaS S. 15 (Sonderfall Vault), S. 22, **S. 12**, ZSD S. 11, S. 22 | label `Vault` + 8 partial matches (`Vault versiegelt \| VPP/Mars/Event-System/CaaS/Observability`, `Vault nach Knotenwartung versiegelt`); facts #1/#2 = **`Vault —DEPENDS_ON→ Keycloak: NICHT (für Vault-Unseal)`** and **`…→ PKI: NICHT`** with the quote from ZSD S. 19; then the DEPENDS_ON chain (dd-ingest-worker, CaaS, Event-System …); entities = all eight `Vault versiegelt \| X` cards incl. **`Vault versiegelt \| VPP — severity: keine`** (both books); ZSD S. 19 guaranteed as graph source | ✅ the deliberate non-couplings come out as negations; without the partial-label matcher the degree-0 ImpactStatements were unreachable |
| 3 | Was war bei ZSDSUP-0247? | identifier channel; ZSD S. 22–23; CaaS S. 21, 23; PARTNER_TICKET → CAASUP-0351, DDSUP-1201 | identifier channel 7 hits; **CaaS S. 21, S. 23 (Tabelle 14)**, **ZSD S. 23 (Tabelle 9, 2 parts grouped)**, S. 12, **S. 22** | same sources; 40 facts led by `CAASUP-0351 ⇄ ZSDSUP-0247 ⇄ DDSUP-1201 PARTNER_TICKET` (both books), `ZSDSUP-0247 —RESULTED_IN_CHANGE→ VaultSealed / OP-ZSD-02`; entity card `ZSDSUP-0247 (Incident)` with both books' attributes side by side (38 min vs 48 min) | ✅ |
| 4 | In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an? | CaaS S. 20 (Tabelle 13); ≥ 8 PRECEDES facts; ZSD S. 17/19 | **CaaS S. 20** (text), S. 15, ZSD S. 25, CaaS S. 22, S. 24 | no label; seeds include Tabelle 13 (kNN#2) through the per-channel seeding; `StartupStep` boosted by the "Reihenfolge" cue → **16 PRECEDES facts** from both books (`Virtualisierung → Firewall → AD/IAM → PKI → Control Plane → Worker → Vault entsiegeln → Kafka → Event-System → Mars → VPP`), StartupStep cards with `order`, `duration`, `precondition` | ✅ (ZSD's cold-start table is S. 19 in the index, not S. 17) |
| 5 | Auf welchen Servern und Ports läuft ZSD? | ZSD S. 8–9 (Tabelle 4), S. 9–10 (Tabelle 5) | **ZSD S. 9–10 Tabelle 5 (3 parts → one source, header once)** #1, S. 8 Abbildung 1, S. 10, S. 9 | Tabelle 5 drops to #4: the alias `ZSD` sits on 18 chunks (title page twice) and the graph channel adds dependency facts | ⚠️ fast mode is the better mode for this table question; Tabelle 4 (hosts) is not in the top 10 in either mode — see observations |
| 6 | Wer darf Vault entsiegeln und wie? | ZSD S. 15 (SOP-ZSD-05, Marcel Ebert), S. 17; CaaS S. 15, 19–20 | **CaaS S. 15**, **ZSD S. 15 (5.3.3 Vault entsiegeln)**, CaaS S. 12, ZSD S. 29, **CaaS S. 19–20** | labels `Vault entsiegeln` (+ `Vault` from inside the bigram); fact #1 **`Marcel Ebert —RESPONSIBLE_FOR→ SOP-ZSD-05`**, #2 `Marcel Ebert —RESPONSIBLE_FOR→ Vault`; Marcel Ebert card (phone 1352, both books) | ✅ |
| 7 | Ich will den Dispatcher neu starten – was hängt daran? | ZSD S. 11–12, 19; CaaS S. 14–15; partial until BHB-PLT-0042 is indexed | CaaS S. 12, ZSD S. 13–14, **ZSD S. 11–12 (Event-System 2.0)**, CaaS S. 21, **CaaS S. 19 Tabelle 12** | label `Dispatcher`; **no** partial matches (the "neu starten" pair is rejected without an anchor word); facts `Event-System —DEPENDS_ON→ Vault (failure_effect=Neustart des Dispatchers scheitert …)`, `kafka-broker-dispatcher —RUNS_ON→ eventing-kafka-broker`, `—READS_SECRET→ kv/event-system/kafka/scram`; **ZSD S. 19 Tabelle 8** #4 | ✅ for what the two books contain; the Event-System manual itself is not indexed |
| 8 | Wie erneuere ich ein TLS-Zertifikat? | ZSD S. 15–17; CaaS S. 16 | **CaaS S. 16 (SOP-CAAS-04)** #1, glossary entries, **ZSD S. 16** | no label (no node is called "TLS-Zertifikat"); graph via seeds: `cert-manager/ingress-wildcard —GOVERNED_BY→ SOP-CAAS-04`; **ZSD S. 16–17 (Zertifikatslebenszyklus)** #3 | ✅ |
| G | Wie backe ich einen Apfelkuchen? | weak evidence, no model call | kNN returns 20 chunks (it always does), **BM25 0** → `weak_evidence` "no lexical overlap with the corpus" | graph expansion skipped | ✅ `--answer` prints "Dazu steht nichts in den Handbüchern." and exits 2 without calling the model |
| R | history "Wer ist für Vault zuständig?" + "und bei Keycloak?" | rewritten question names Keycloak + zuständig | `rewrite_question` → "Wer ist für Keycloak zuständig?" (gemini-dev, one call) | — | ✅ (the model wraps its output over two lines; the parser joins them and cuts at the first `?`) |

Timings (slow mode, warm): analyze 0 ms · embed 210–270 ms (LiteLLM → Ollama bge-m3 on CPU) · msearch 7–9 ms ·
fuse 0 ms · graph 8–80 ms (expansion + `mget`) · **total 230–330 ms**. Fast mode saves only the graph step; the
embedding call dominates either way.

## Model answers (gemini-dev, `--answer`, default prompt and budget)

All answers cite `[BHB-PLT-… S. n]` on every statement, stay inside the context, and render the negations as negations.
Full texts in `out/questions/<n>-answer.txt` after `ANSWER=1 make questions`.

| # | Answer (condensed) | Correct? |
|---|---|---|
| 1 | Bereich IT-S 1 / ZSD; Kai Ostermann (iam-betrieb@…, 1315) [CaaS S. 6; ZSD S. 1–2, 17]; three escalation levels from Tabelle 13 with triggers and reaction times [ZSD S. 26] | ✅ |
| 2 | Vault data unreadable, three of five key shares to unseal [ZSD S. 22, 29; CaaS S. 12]; per consumer: CaaS deployments blocked / ArgoCD fails, running pods unaffected; Mars: `dd-ingest-worker` does not start, spool fills; Event-System: dispatcher restart fails, delivery continues; Observability: restart fails; **VPP: keine Auswirkungen, Keystores und Wallet liegen lokal** [CaaS S. 12; ZSD S. 19] | ✅ the "VPP unaffected" finding is stated explicitly with its reason |
| 3 | ZSDSUP-0247 (partner CAASUP-0351, follow-up DDSUP-1201), 02.07.2026, Sev-1; cause (unannounced node maintenance, two of three Vault pods rescheduled sealed, Raft quorum lost); impact; **both durations with their different measurement points (38 vs 48 min)**; resolution per SOP-ZSD-05 (Ostermann, Ebert, Wehrle); process changes (24 h notice, VaultSealed alarm, OP-ZSD-02) | ✅ the cross-book discrepancy is explained, not averaged |
| 4 | Eleven numbered steps from Virtualisierung to VPP with the responsible person per step [CaaS S. 20; ZSD S. 19] | ✅ |
| 5 | Target systems/IPs and ports from Tabelle 5 (10.20.6.20:443 OIDC, .40:443 ACME, .45:80 OCSP, .11/12:636 LDAPS, .31/32:5432, .21-23:7800, 10.30.8.7:443 Vault …) plus the hosts of the entity cards (iam-p01…03, vault-0…2 in `vault-system`) [ZSD S. 9–10] | ✅ (with `max_tokens` 1500 this answer was cut after the first bullet — see below) |
| 6 | Marcel Ebert with three of five share holders; shares from the IT-S 1 vault, no IAM/PKI needed; the five SOP-ZSD-05 steps (status, call holders via 0800 1180 100, unseal vault-0 then vault-1/-2, restart consumers, close the case and inform Andreas Wehrle) [ZSD S. 15, 17, 19, 22, 29] | ✅ |
| 7 | `kafka-broker-dispatcher` StatefulSet with PDB `minAvailable=2` → one replica at a time [CaaS S. 11–12; ZSD S. 15]; delivery delayed ≤ 3 min, nothing lost (Kafka); needs SASL/SCRAM secrets from Vault → restart fails while Vault is sealed [ZSD S. 11–12, 19] | ✅ |
| 8 | Two paths: cert-manager renews console/API/ingress-wildcard/tenant routes automatically 30 days before expiry via ACME with ClusterIssuer `bavd-issuing-ca-3` (needs `FW-CAAS-004` and the egress pool), immediate renewal with `cmctl renew ingress-wildcard -n openshift-ingress`; non-automated certificates (archive-adapter keystores, Kafka brokers) via the application procedure SOP-ZSD-01 [CaaS S. 16; ZSD S. 15–17, 20, 23, 28] | ✅ |
| G | "Dazu steht nichts in den Handbüchern." — printed by the guardrail, model not called | ✅ |

## Observations and what they changed during the implementation

1. **`finish_reason: length` at `max_tokens` 1500.** gemini-3.7-flash spent 1322 *reasoning* tokens of the 1500 and
   returned 174 tokens of text: answers 5, 7 and 8 were cut mid-sentence. `ChatClient.complete_full()` now reports
   `finish_reason`/usage, the default is 4000, and `.env.example` documents it. Ollama/vLLM models without thinking
   are unaffected.
2. **Degree-0 entities.** "VPP unaffected by a sealed Vault" is an `ImpactStatement` node with `severity: keine` and no
   edges. Only the label-token matcher reaches it (labels containing ≥ 2 question words). Anchoring that matcher to an
   exactly resolved label was necessary: unanchored, "Dispatcher neu starten" pulled in every "API-Server/Ingress-Router
   neu starten" statement.
3. **Guardrail vs. graph channel.** The first version counted graph facts as evidence — the off-topic question then
   passed, because the expansion had been seeded from kNN-only hits. The verdict now looks at the search channels only
   and the expansion is skipped when the verdict is weak.
4. **Seeds.** The Kaltstart table (11 StartupSteps) was kNN#2 but not in the fused top 5; the top two hits of every
   channel are seeds now, and node types the question asks about are boosted (`StartupStep` for "Reihenfolge").
   PRECEDES facts went from 3 to 16.
5. **Graph-only hits lose in RRF** (1/61 against ≥ 2/70 for any two-channel hit), so the S. 19 paragraph that carries
   the negative dependencies fell out of the top 10 while the facts quoted it. The provenance chunks of the two best
   facts are guaranteed a slot (`graph_min_sources`).
6. **Generic aliases dilute.** `ZSD` is an alias on 18 chunks (both title-page chunks among them): for the port
   question the label channel and the graph channel push the Portmatrix from #1 (fast) to #4 (slow). Candidates for
   later: an IDF-like damping of labels that sit on many chunks, or excluding page-1 chunks from the label channel.
7. **Tabelle 4 (hosts, ZSD S. 8–9)** does not reach the top 10 for "Servern und Ports": its caption is "Instanzen der
   Produktionsumgebung" and its rows carry host names and IPs, not the word "Server". The hosts do reach the prompt
   through the entity cards (`iam-p01…03`, `vault-0…2` with hostname/IP), which is how answer 5 lists them.
8. **Prompt size.** 19,120 characters of context were 7,336 Gemini tokens (2.6 chars/token, tables and identifiers are
   token-dense) — `estimate_tokens` uses that ratio; the 6000 budget is ~7,000 real tokens. For 4k-context Ollama
   models set `RAG__RETRIEVAL__CONTEXT_TOKEN_BUDGET=2500` and `RAG__LLM__CONTEXT_LIMIT_TOKENS=4096`.
9. **Two person nodes for one person** ("Kai Ostermann" and "Ostermann" with alias "Kai Ostermann") are merged into
   one entity card through the alias; attributes from the two books stay side by side (ZSD: IAM-Betrieb, 1315; CaaS:
   IAM (Keycloak)).

## Not covered yet

- Only two of the five manuals are indexed; questions about the Event-System (BHB-PLT-0042), VPP (BHB-VRF-0207) or
  Mars (BHB-VRF-0118) manuals themselves are answered from what the CaaS and ZSD books say about them.
- No relevance evaluation beyond this table (no recall@k over a labelled set); the `eval/` module of the roadmap is
  still open.
- Intent routing (ADR-0004) is replaced by the question-cue ordering; a router could later narrow `expand()`.
