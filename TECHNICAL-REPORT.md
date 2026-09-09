# From Manual to Answer

**How an ontology and a knowledge graph make retrieval over German operations manuals (almost) deterministic**

*Technical report of the RAG prototype — status 2026-09-04*

---

### About this report

This document explains one system end to end: a chat assistant that answers German questions about IT
operations manuals (*Betriebshandbücher*) and cites every statement down to the document, page and table.
It is written to be read front to back. The first chapters set the scene; the middle chapters go deep into
the three things that make the system what it is:

1. **the ontology** — what it contains, why it is shaped the way it is, and whether such a thing can be
   built for real data;
2. **the knowledge graph** — how a PDF becomes typed nodes and edges with provenance, which parts of that
   are done by a language model and which by plain code;
3. **the search mechanism** — how a question is turned into search requests and graph traversals *without*
   a language model, and how the pieces are fused into one cited context.

The storage layer (OpenSearch) is explained to the depth needed to understand the search. The user policy
and the chat application are described at surface level; their own README and REPORT files hold the rest.
Deployment topics (which machine, which container runtime, which network) are deliberately left out.

Every number in this report was measured on the two manuals that are indexed today (`BHB-PLT-0001`,
the container platform manual, and `BHB-PLT-0007`, the central security services manual). Where a
figure comes from a single extraction run it is marked as such, because extraction counts vary between
runs — that variation is itself a topic of this report.

---

## Table of contents

1. Introduction: the problem and the idea
2. The corpus: five manuals designed to be hard
3. The ontology: taxonomy, nature, and replicability
4. Building the knowledge graph with docling-graph
5. Storing chunks and graph in OpenSearch
6. From question to answer: the retrieval mechanism
7. Users, limits and the chat application (overview)
8. How deterministic is it, really?
9. The reader's questions, answered directly
10. Appendix: parameters, glossary, file map

---

## 1. Introduction: the problem and the idea

### 1.1 The problem

An operations team keeps its knowledge in manuals. In this project they are German *Betriebshandbücher*
of a (fictional) federal agency: one manual per IT system, each written from that system's point of view.
The questions the team asks are operational and precise:

- *Was passiert, wenn Vault versiegelt ist?* — what happens when the secret store is sealed?
- *Wer ist für IAM/Keycloak zuständig und wie eskaliere ich?* — who is responsible, how do I escalate?
- *Was war bei ZSDSUP-0247?* — what happened in ticket ZSDSUP-0247?
- *In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?* — in which order does everything
  restart after a total outage?

Three properties of these questions defeat ordinary "chunk it, embed it, retrieve the top 5" RAG:

| Property | Why plain vector search struggles |
|---|---|
| **Exact identifiers** (`ZSDSUP-0247`, `SOP-ZSD-05`, `FW-CAAS-004`, `kv/dd/prod`) | Text analyzers split `CAASUP-0342` into `caasup` and `0342`, so `caasup` matches every CaaS ticket; embeddings blur identifiers by design. |
| **Cross-document facts** | The answer to "what happens when Vault is sealed" is spread over the platform manual (impact table per tenant) and the security manual (the dependency chain and the manual unseal). No single chunk contains it. |
| **Negations and non-couplings** | "VPP is *not* affected because its keystores are local" is a deliberate statement. A similarity search finds chunks that *mention* VPP and Vault, and a model then confidently produces the wrong coupling. |

Add to this that roughly 70 % of the useful facts sit in tables (impact matrices, port matrices, escalation
tables, incident lists), and that every answer must carry a citation like `[BHB-PLT-0007 S. 19]`.

### 1.2 The idea

The system puts a **normative ontology** at the centre and builds everything around it:

```
                     ontology.yaml  (26 classes, 32 relations, identity rules, negation policy)
                            │
          ┌─────────────────┼──────────────────────────────┐
          ▼                 ▼                              ▼
   extraction schema    identity keys                 identifier regexes
   (what the LLM may    (what makes two               (what an exact
    extract, typed)      mentions the same)            match looks like)
          │                 │                              │
          ▼                 ▼                              ▼
 ┌──────────────┐    ┌──────────────┐               ┌──────────────┐
 │ PDF ─► chunks│    │ typed graph  │               │ chunk fields │
 │ (docling)    │    │ nodes+edges  │               │ identifiers[]│
 │              │    │ + provenance │               │ node_labels[]│
 └──────┬───────┘    └──────┬───────┘               └──────┬───────┘
        └───────────────────┴──────────────┬───────────────┘
                                           ▼
                                  OpenSearch (chunks, nodes, graph blob)
                                           │
              question ──► analyze ──► 4 search channels + 1-hop graph expansion ──► RRF ──► context ──► LLM answer
                            (regex + string match; no model)                          (cited)
```

Four design decisions follow from it, and they recur throughout this report:

1. **The graph is typed and carries provenance.** Every node and edge knows the document, pages, chunk ids
   and the literal quote it came from. A graph fact is therefore citable exactly like a text passage.
2. **Negation is data.** A statement like "Vault does not depend on the PKI for unsealing" becomes an edge
   with `polarity: negative`, not a missing edge. An impact of "keine" (none) becomes a node with
   `severity: keine`.
3. **Entity resolution is deterministic.** Which mentions are the same entity is decided by identity rules
   in the ontology (casefolded label, ticket id, hostname, …), not by a model. Two manuals that mention the
   same person produce the *same node id* without any merge step.
4. **Retrieval does not call a language model.** Identifiers are found by regular expressions, entities by
   string matching against the graph's labels, semantics by an embedding model, and the lists are fused by
   rank. The language model only writes the final answer (and, for follow-up questions, a standalone rewrite).

### 1.3 The modules

| Module | Folder | Role | State |
|---|---|---|---|
| 1 | `docling-graph/` | PDF → Markdown + chunks + embedded vectors + ontology-grounded graph (FastAPI service around docling and docling-graph) | done, verified |
| 2 | `opensearch-index/` | OpenSearch node + `osi` indexer: idempotent ingest of a run into four indices | done, verified |
| 3 | `retrieval/` | question → four search channels + graph expansion → fused, cited context; chat client with guardrail | done, verified |
| 4 | `users/` | mock identity and policy: daily cap, turn cap, allowed manuals | done, verified |
| 5 | `chat-system/` | Streamlit chat with conversation database, streaming, citations, diagnostics; headless CLI | done, verified |
| — | `integration/` | orchestration of process → index per manual; cross-book report | done |

---

## 2. The corpus: five manuals designed to be hard

The corpus is fictional and says so on every page (a header line *TESTDOKUMENT · DIESES DOKUMENT IST FIKTIV
· KEINE ECHTEN BETRIEBSDATEN*). It was derived from three anonymised Confluence exports of real operations
manuals; the two "hub" manuals were written from scratch so that the five documents close into one universe.

| Document id | Manual | Pages / figures / tables | Role |
|---|---|---|---|
| `BHB-PLT-0001` | CaaS — Container-Plattform als Dienst | 27 / 3 / 19 | **hub**: tenants, node maintenance, impact matrix, cold start |
| `BHB-PLT-0007` | ZSD — Zentrale Sicherheitsdienste (IAM, PKI, Vault) | 29 / 3 / 15 | **hub**: consumer matrix, impact matrix |
| `BHB-PLT-0042` | Event-System 2.0 | 49 / 7 / 45 | application (event distribution on OpenShift + Kafka) |
| `BHB-VRF-0118` | Mars Dokumentendienste | 50 / 7 / 42 | application (document intake, OCR, archive) |
| `BHB-VRF-0207` | VPP — Verfahrensportal Prüfprozesse | 50 / 7 / 37 | application (classic web app: Tomcat/Oracle/Keycloak) |

Two of the five (the hubs) are indexed today; the three application manuals are the next ingestion step.

What makes this a *test* corpus is that the traps are documented (in `README-Testdaten.md` and the
ontology's `negative_assertions`), so a pipeline can be graded against them:

- **Two hubs.** Every application manual refers to the platform (CaaS) and to the security services (ZSD).
  The hub manuals name every consumer with namespace, IAM client, certificate procedure and Vault path.
- **Two join tables.** ZSD Tabelle 6 (who uses which client, path, certificate mode) and CaaS Tabelle 12
  (impact of platform events per tenant) are the direct path from "I restart X" to "that hits Y and Z".
- **A documented ring dependency.** Vault runs on the platform; the platform gets its certificates from
  the PKI; the PKI keeps material in Vault. Both hub manuals explain how the ring is broken (IAM and PKI
  run on their own VMs; unsealing is manual with key shares).
- **Deliberate non-couplings.** VPP does not use the Event-System, is not a tenant of the platform and is
  unaffected by a sealed Vault. In CaaS Tabelle 12 the VPP column reads "keine" throughout, with the reason
  underneath. These are exactly the statements a similarity search gets wrong.
- **Partner tickets.** Seven incidents appear in two or three manuals, each side naming the other's ticket
  number (`CAASUP-0351 ⇄ ZSDSUP-0247 ⇄ DDSUP-1201` is the Vault incident of 02.07.2026).
- **One number, two truths.** For that incident the platform team reports 48 minutes and the security
  team 38 minutes — the text explains the different measurement points. A pipeline must keep both.
- **Shared people.** Kai Ostermann (IAM) and Sabine Wollmer (PKI) appear in all five manuals, others in
  three or four, always with role and phone extension — the check value for correct merging.
- **A startup chain across all documents.** CaaS Tabelle 13 lists eleven cold-start steps with owner,
  duration and precondition.

Identifiers are typeset non-breaking so that `CAASUP-0338` never splits across a line end. Diagrams are
embedded at three times the layout resolution (about 4 500 px wide) because labels become unreadable
below `images_scale 3.0`.

---

## 3. The ontology: taxonomy, nature, and replicability

### 3.1 What the ontology is for

`ontology.yaml` (873 lines) is the single source of truth for three generated things:

1. a **Pydantic model** (`ontology_model.py`, 477 lines, generated by `ontology_to_pydantic.py`);
2. the **extraction schema** handed to docling-graph — the language model may only produce instances of
   these classes, connected by these relations, with these attribute types;
3. the **edge vocabulary** of the graph, including polarity and provenance, which the retrieval module
   later renders as German facts.

It is *normative*, not descriptive (ADR-0002): it states what a manual written to the agency's template
*should* contain. That is what makes it usable as a documentation-quality yardstick later — a manual from
which few of the mandated facts can be extracted is an incomplete manual.

### 3.2 Anatomy of the file

| Section | Count | Content |
|---|---|---|
| `meta` | — | name, version, corpus language `de`, identifier language `en`, the five documents with file name and root system, design notes |
| `datatypes` | 27 | constrained base types with regex patterns (`doc_id`, `ticket_id`, `hostname`, `ipv4`, `cidr`, `port`, `vault_path`, `k8s_name`, `duration`, `percent`, …) |
| `enums` | 16 | controlled vocabularies (`Polarity`, `SystemKind`, `DependencyKind`, `ImpactSeverity`, `IncidentSeverity`, `Criticality`, `CertRenewalMode`, …) |
| `mixins` | 3 | `Provenance`, `NodeBase`, `EdgeBase` — applied to every node and edge |
| `classes` | 26 | the entity types, each with identity rule, German cue words, fields, table hints |
| `relations` | 32 | typed edges with domain, range, cardinality, German label, optional properties |
| `negative_assertions` | 7 | statements the corpus negates on purpose; they must become negative edges |
| `extraction_rule_negation` | — | the German trigger words for polarity `negative` and the conflict rule |
| `competency_questions` | 7 | the questions the graph must answer, each with the traversal path and key fields |
| `extraction` | — | chunking preferences, "tables first", 14 high-yield table patterns, 6 identifier regexes, normalisation and conflict policy |
| `expected_graph_shape` | — | sample expectations for the extraction (5 documents, 2 hubs, 7 partner tickets, the cycle, chain length 11, ≥7 negative edges) |

### 3.3 The mixins: provenance, node, edge

Everything inherits three small structures. They are the reason a graph fact is citable.

```
Provenance   document_id (doc_id, required) · chapter · page · table_ref ("Tabelle 12") · figure_ref · quote (≤300 chars) · confidence
NodeBase     id · label (as written in the document) · aliases[] · description · provenance[] (required)
EdgeBase     type (relation name) · source_id · target_id · polarity (positive|negative, default positive) · qualifier · provenance[] (required)
```

`qualifier` deserves a note: it is the free-text restriction or *reason* attached to an edge ("nur für
neue Sitzungen", "für Vault-Unseal"). For negative edges it holds *why* the relation does not exist — the
sentence the chat later shows as justification.

### 3.4 The class taxonomy

The 26 classes fall into five layers. The identity rule (what makes two mentions the same node) is the most
important column: it drives deduplication inside a document and the join across documents.

**Layer 1 — document and organisation**

| Class | Identity | Note |
|---|---|---|
| `Document` | `doc_id`, upper-cased | one per manual; also created for referenced manuals |
| `OrgUnit` | `label`, casefold | teams, departments, providers, data centres (kind enum) |
| `Person` | `label`, *strip titles then casefold* | "Dr. Annika Reuß" → key `annika reuss`, title kept in label; role and phone extension are the merge check |
| `Contract` | `contract_id` | framework contracts, service sheets |

**Layer 2 — system and architecture**

| Class | Identity | Note |
|---|---|---|
| `System` | `label` casefold, secondary `ci_id` | the top object; each manual describes exactly one; kind, protection level, availability target, RTO/RPO, `cert_renewal_mode` |
| `Component` | `label` casefold, **scope: system** | pods, deployments, adapters; `restart_note` (PDB, order) |
| `Host` | `hostname` | servers, VMs, VIPs; ip, role, fire section |
| `Environment` | `label` casefold | clusters/stages |
| `Namespace` | `label` (k8s name) | the tenant relation itself is an edge |
| `NetworkZone` | `zone_id` | `ZONE-…`, cidr, site |
| `FirewallRule` | `fw_id` | one row of a port matrix; carries the network edges |
| `DataStore` | `label` casefold | databases, topics, buckets, volumes |
| `EventChannel` | `label` | brokers, triggers, topics |

**Layer 3 — identity, certificates, secrets**

| Class | Identity | Note |
|---|---|---|
| `IdentityClient` | `label` | OIDC client (realm, flow, secret rotation) |
| `Certificate` | `label` casefold, secondary `keystore_path` | `renewal_mode` required (automatic ACME / mixed / manual) |
| `CertificateAuthority` | `label` | root/issuing CAs |
| `SecretStorePath` | `vault_path` | `kv/…` paths a system reads |

**Layer 4 — operating processes**

| Class | Identity | Note |
|---|---|---|
| `Procedure` | `sop_id` | SOPs with trigger, lead time, ordered steps, literal commands, rollback |
| `MaintenanceWindow` | `label`, scope: system | schedule, notice period |
| `StartupStep` | `order` + `label` | one step of the cold-start chain; linked by `PRECEDES` |

**Layer 5 — failures, impact, monitoring**

| Class | Identity | Note |
|---|---|---|
| `Incident` | `ticket_id` | date, severity, duration, root cause, resolution, process change; "Partnervorgang" column is the most valuable edge |
| `FailureMode` | `label`, scope: system | recurring failure picture: symptom, log evidence, check, remedy |
| `ImpactStatement` | `event` + `affected_system` | **reified** cell of an impact matrix: "event X at A affects B like so", `severity` required (`keine` is a statement, not missing data) |
| `Alert` | `label` | expression, threshold, reaction |
| `OpenItem` | `openitem_id` | planned items |
| `Term` | `label` casefold | glossary entry; `maps_to` a node — the designed bridge between user wording and graph labels |

Three things in this table shape the whole system. First, **every class has an identity rule** — the
graph never relies on a model to decide sameness. Second, three classes are scoped to their system
(`Component`, `MaintenanceWindow`, `FailureMode`): a "Dispatcher" in the Event-System and a "Dispatcher"
elsewhere must not merge, so their key is prefixed with the root system (`zentrale sicherheitsdienste::dispatcher`).
Third, `ImpactStatement` turns a *cell of a table* into a node. The statement "a sealed Vault has no impact
on VPP" is not a relation between Vault and VPP — it is an assertion with its own attributes (event,
affected system, severity, symptom, mitigation) and provenance. This is why later the retrieval module has
to include *entity cards*, not only edges: the most valuable negative finding in the corpus has degree zero.

### 3.5 Datatypes and enums: the constrained vocabulary

Datatypes carry regex patterns, so a value can be checked after extraction rather than trusted:

```
doc_id      ^BHB-(PLT|VRF)-\d{4}$            ticket_id   ^(ESSUP|DDSUP|VPPSUP|CAASUP|ZSDSUP)-\d{3,4}$
sop_id      ^SOP-(\d+|(CAAS|ZSD|DD|VPP)-\d{2})$   fw_id   ^FW-(ES|DD|VPP|CAAS|ZSD)-\d{3}$
zone_id     ^ZONE-[A-Z]+(-[A-Z]{2})?$         hostname    ^[a-z][a-z0-9-]{1,30}(\.[a-z0-9-]+)*$
vault_path  ^kv/[a-z0-9/_<>*-]+$              phone_ext   ^\d{3,4}$
```

Enums are the controlled vocabularies of the domain. Two of them matter for negation and impact:

- `Polarity: [positive, negative]`
- `ImpactSeverity: [keine, eingeschraenkt, ausfall, unbekannt]` — "keine" (none) is a legitimate value.
- `DependencyKind: [identitaet, zertifikat, geheimnis, netz, speicher, plattform, messaging, datenbank, monitoring, dienstleister]`
  — every `DEPENDS_ON` edge must say *what kind* of dependency it is.

### 3.6 The 32 relations

Relations are directed, typed, and each has a German label (`label_de`) that the chat renders. Domain and
range are class names; `NodeBase` means "any node". Five relations carry typed properties.

| Relation | Domain → Range | German label | Properties / notes |
|---|---|---|---|
| `DOCUMENTS` | Document → System | beschreibt | 1-1 |
| `MENTIONED_IN` | NodeBase → Document | belegt in | **not extracted**: derived from provenance |
| `RELATED_DOCUMENT` | Document → Document | verwandtes Dokument | `relation_note` |
| `OPERATED_BY` | System → OrgUnit | betrieben von | |
| `RESPONSIBLE_FOR` | Person → NodeBase | verantwortlich für | `raci`, `is_deputy` |
| `ESCALATES_TO` | Person → Person | eskaliert an | `level` |
| `CONTRACT_COVERS` | Contract → NodeBase | Vertrag deckt ab | |
| `HAS_COMPONENT` | System → Component | hat Komponente | |
| `RUNS_ON` | Component → Host / Namespace / Environment | läuft auf | negated in the corpus for IAM, PKI, Kafka |
| `LOCATED_IN` | Host / Environment / Component → NetworkZone | liegt in Zone | |
| `TENANT_OF` | System → System | Mandant von | `namespaces[]`, `quota`; negated for VPP |
| `USES_DATASTORE` | System / Component → DataStore | nutzt Datenhaltung | |
| `ALLOWS_TRAFFIC` | FirewallRule → NodeBase | erlaubt Verkehr | |
| `PUBLISHES_EVENT` | System → EventChannel | veröffentlicht Ereignis | |
| `CONSUMES_EVENT` | System → EventChannel | konsumiert Ereignis | negated for VPP |
| **`DEPENDS_ON`** | System / Component → System / Component / DataStore / CA / SecretStorePath / IdentityClient / OrgUnit | hängt ab von | `dependency_kind` (required), `criticality`, `failure_effect`, `bridging`; the ring dependency is deliberately cyclic |
| `AUTHENTICATES_VIA` | System → IdentityClient | authentisiert über | |
| `SECURED_BY` | Component / Host / System → Certificate | gesichert durch | |
| `ISSUED_BY` | Certificate → CertificateAuthority | ausgestellt von | |
| `READS_SECRET` | System / Component → SecretStorePath | liest Geheimnis | |
| `GOVERNED_BY` | System / Component / Certificate / Host → Procedure | geregelt durch | |
| `HAS_MAINTENANCE_WINDOW` | System → MaintenanceWindow | hat Wartungsfenster | |
| `PRECEDES` | StartupStep → StartupStep | geht voraus | the cold-start chain |
| `STEP_RESPONSIBILITY` | StartupStep → OrgUnit / Person | Schritt verantwortet von | |
| `AFFECTS` | Incident → System / Component / DataStore | betrifft | |
| `PARTNER_TICKET` | Incident → Incident | Partnervorgang | symmetric; both documents must produce the same edge |
| `INSTANCE_OF_FAILURE` | Incident → FailureMode | Ausprägung von Störungsbild | |
| `RESULTED_IN_CHANGE` | Incident → Procedure / MaintenanceWindow / Alert / OpenItem | führte zu Änderung | |
| `DETECTED_BY` | FailureMode / Incident → Alert | erkannt durch | |
| `MONITORS` | Alert → Component / System / Host | überwacht | |
| `IMPACT_OF` | ImpactStatement → System / Component | Auswirkung von | the matrix as a graph |
| `DEFINES_TERM` | Document → Term | definiert Begriff | |

`DEPENDS_ON` is called "the heart of the graph" in the file itself. Its `failure_effect` and `bridging`
properties are what turn "A depends on B" into an operational answer ("if B is down, new pods of A do not
start; running pods are unaffected").

### 3.7 Negation as data

The ontology commits to negation in four places:

1. `EdgeBase.polarity` — every edge is positive or negative.
2. `negative_assertions` — seven statements the corpus makes on purpose, each with its evidence document
   and reason: `VPP ⇸TENANT_OF⇸ CaaS-Plattform` ("runs on VMs"), `VPP ⇸CONSUMES_EVENT⇸ Event-System 2.0`,
   `VPP ⇸DEPENDS_ON⇸ Vault` ("keystores are local"), `Event-System ⇸DEPENDS_ON⇸ Oracle`,
   `Kafka-Broker ⇸RUNS_ON⇸ CaaS`, `IAM ⇸RUNS_ON⇸ CaaS`, `PKI ⇸RUNS_ON⇸ CaaS` (the last two are what
   break the ring dependency).
3. `extraction_rule_negation` — the German trigger words: *kein, keine, nicht, ohne, unberührt, bewusst
   nicht genutzt, nicht angebunden, kein Mandant, entfällt*; the qualifier records the reason; and the rule
   that **a negative edge must never overwrite a positive edge of the same type between the same nodes —
   conflicts are reported, not silently resolved**.
4. `ImpactStatement.severity = keine` with the explicit note: this is a statement, not missing information.

### 3.8 How the ontology steers extraction

Beyond types and relations the file carries extraction *hints* that the compiler turns into prompt text:

- `cues_de` per class and relation — German anchor words ("Verantwortlicher", "Durchwahl", "Partnervorgang",
  "hängt ab", "ohne … nicht").
- `table_hints` per class — the recurring table captions where instances live ("Portmatrix",
  "Eskalationsweg", "Halter der Unseal-Schlüsselanteile").
- `high_yield_tables` — 14 caption patterns mapped to the relations they yield ("Auswirkung" → `ImpactStatement`,
  "Kaltstartreihenfolge" → `StartupStep, PRECEDES, STEP_RESPONSIBILITY`, "Incident" → `Incident, PARTNER_TICKET,
  RESULTED_IN_CHANGE`), with the guidance "tables first: about 70 % of the edges are in recurring tables".
- `normalization` — decimal comma to point, `DD.MM.YYYY` to ISO, remove thousands separators, keep
  identifiers untouched, lowercase keys only.
- `conflict_policy` — keep contradicting values as a candidate list with provenance (the 48 vs 38 minutes).

### 3.9 Competency questions: the acceptance criteria

Seven questions define what the graph *must* be able to answer. Each names the traversal and the fields
that carry the answer. They are the origin of the retrieval design (chapter 6) and of the test questions
in chapter 6.11.

| Id | Question | Traversal in the ontology |
|---|---|---|
| Q1 | Wie erneuere ich das TLS-Zertifikat von System X? | System −SECURED_BY→ Certificate −ISSUED_BY→ CA; System −GOVERNED_BY→ Procedure |
| Q2 | Ich will Komponente Y neu starten — wen trifft es? | Component ←HAS_COMPONENT− System; ImpactStatement{event≈"Neustart"} → affected system; System ←DEPENDS_ON− dependants; Incident −AFFECTS→ Component |
| Q3 | Wer ist mein Ansprechpartner für System X und wie eskaliere ich? | System ←RESPONSIBLE_FOR− Person −ESCALATES_TO→ Person; System −OPERATED_BY→ OrgUnit |
| Q4 | Auf welchen Servern und Ports läuft System X? | System −HAS_COMPONENT→ Component −RUNS_ON→ Host −LOCATED_IN→ Zone; FirewallRule −ALLOWS_TRAFFIC→ … |
| Q5 | Was passiert, wenn der zentrale Dienst Z ausfällt? | ImpactStatement{causing_system=Z} → all affected; Z ←DEPENDS_ON− systems; **at least one answer must be "keine Auswirkung" with a reason** |
| Q6 | In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an? | StartupStep −PRECEDES→ StartupStep, topologically; STEP_RESPONSIBILITY per step |
| Q7 | Wurde dieses Problem schon einmal gelöst, und wer war beteiligt? | FailureMode ←INSTANCE_OF_FAILURE− Incident −PARTNER_TICKET→ Incident (other document) |

All seven are one- or two-hop patterns. That observation is what later justified expanding *all*
relations one hop instead of building an intent classifier.

### 3.10 Is an ontology at this level easy to replicate on real data?

Honest answer: the *shape* is easy to replicate, the *content* takes domain work, and the *payoff* depends
on how disciplined the real manuals are. Three considerations:

**What is generic and can be copied as is.** The mixins (provenance, polarity, qualifier), the identity-rule
mechanism (keys + normalisation + scope), the negation policy with trigger words, the competency-question
method, the `expected_graph_shape` idea, and the identifier-regex list. None of this is specific to this
corpus; it is the framework any operations ontology needs.

**What is domain-specific and must be written per organisation.** The 26 classes and 32 relations mirror
the sections a *Betriebshandbuch* template mandates (contacts and escalation, architecture, dependencies,
impact, procedures, incidents, glossary). Real manuals written to a template deliver most of this
structure for free — that is ADR-0001's argument: the edges come from mandated sections, so future manuals
will contain them. An organisation without a template gets a thinner graph. The file here is 873 lines and
was derived from three anonymised real exports; the effort is days of a domain expert plus an engineer,
iterating against an extraction run, not months.

**Where real data bites.**

| Risk | Effect on this design | Mitigation in the design |
|---|---|---|
| No identifier scheme (tickets, SOPs, rules named ad hoc) | the exact-match channel and the ticket/SOP identities lose their power | fall back to label identities; add regexes as conventions emerge |
| Inconsistent naming across manuals ("ZSD", "Zentrale Sicherheitsdienste", "ZSD – Zentrale …") | content-addressed node ids do **not** join; the entity exists twice | alias lists on nodes; retrieval merges cards by alias spelling; a later merge module for fuzzy joins |
| Facts in prose rather than tables | edge recall drops (already the known weak spot: one run had 13 relations with zero edges and 136 of 279 nodes isolated) | table-driven passes, `reference` attributes materialised as edges |
| Manuals that are incomplete | fewer facts, but visibly: the ontology is normative, so missing mandated content shows up as missing nodes | ADR-0013 plans a degradation study to quantify exactly this |

The pragmatic path is to start with roughly ten classes and ten relations that the template guarantees
(system, component, host, person, org unit, procedure, incident; depends-on, runs-on, responsible-for,
governed-by, partner-ticket), define identity keys and a negation policy on day one, and let the class
list grow from what the extractor keeps reporting as `unresolved_targets`.

---

## 4. Building the knowledge graph with docling-graph

Module `docling-graph/` wraps two open-source libraries in a FastAPI service: **docling** (PDF parsing,
layout, tables, OCR) and **docling-graph** (ontology-schema-driven extraction with a language model). One
call, `POST /v1/process`, turns a PDF into Markdown, chunks with vectors, and a graph. The service processes
one document at a time and answers `503` with a retry hint while busy.

### 4.1 The pipeline at a glance

```
PDF ──► 1 parse (docling) ──► 2 clean-up ──► 3 figures (VLM) ──► 4 markdown + chunks ──► 5 embeddings
                                                                                              │
        ┌─────────────────────────────────────────────────────────────────────────────────────┘
        ▼
   6 graph extraction (docling-graph, LLM) ──► 7 materialise (normalise · resolve · validate · provenance)
                                                                     │
                                                                     ▼
                       response: document · markdown · chunks[] · graph{nodes, edges, meta} · degraded · timings
```

Only the parse step is a hard failure. Figures, embeddings and graph each set a `degraded` flag and record
an error instead of failing the run, so a document without a graph is still indexed and searchable. A
result is cached (keyed by file hash, options, ontology schema hash, model names and versions) only when
nothing was degraded.

Reference run used throughout this chapter: the ZSD manual, 29 pages, 22 tables, 3 pictures →
112 chunks, 250 nodes, 154 edges; timings convert 359 s, describe 15 s, chunk 0.8 s, embed 105 s,
graph 337 s (about 13 minutes end to end).

### 4.2 Parsing and structural clean-up

docling runs with the accurate TableFormer table model (`do_table_structure=True`, `do_cell_matching=True`),
EasyOCR for German and English when OCR is requested, `images_scale = 3.0` (about 216 dpi, needed for the
diagram labels), page and picture images generated, heading hierarchy enabled, CPU accelerator.

Before chunking, the service repairs what PDF parsing leaves behind:

| Step | What it does | Why |
|---|---|---|
| `strip_page_furniture` | drops lines starting with `TESTDOKUMENT ·` (configurable prefixes) | the header line would otherwise appear in every chunk and dominate near-duplicate retrieval |
| `strip_repeated_furniture` | drops text repeated on ≥ 3 pages inside the top/bottom 12 % band of the page | running headers and footers |
| `normalize_heading_levels` | rebuilds a consistent heading hierarchy | breadcrumbs like `7 Troubleshooting › 7.2 Dokumentierte Störungsbilder › 7.2.4 …` |
| `dehyphenate_table_cells` | rejoins words hyphenated at cell line breaks | identifiers and compounds stay whole |
| `infer_captions` | a caption-less table right after a table with the same header row inherits its caption (page break); otherwise the nearest `Tabelle n:` / `Abbildung n:` line becomes the caption | the caption is the key that groups table parts later |

### 4.3 Chunking

The chunker is docling's `HybridChunker`, configured so that tables and pictures stay whole units and text
neighbours under one heading are merged by the service itself.

| Parameter | Value | Meaning |
|---|---|---|
| tokenizer | `intfloat/multilingual-e5-large` (XLM-RoBERTa vocabulary, shared with bge-m3) | token counting uses the *embedding model's* tokenizer |
| `max_tokens` | **512** | the embedding model's hard limit; a longer input would be truncated silently |
| budget per chunk | `512 − tokens(prefix) − 2` | the 2 are the model's special tokens; the embedding prefix ("passage: " for e5) counts against the budget |
| `merge_peers` | true | adjacent text items under the same heading become one chunk |
| table serialisation | Markdown table, compact, header repeated on every part | tables are searchable as text *and* readable by the model |
| caption on parts | prepended to every table part | docling repeats only the header row; the caption is what groups the parts later |
| over-long part | split by rows/lines → sentences → longest word prefix (binary search); **never truncated** | a warning names the part count |

Each chunk record carries:

```
chunk_id            "<sha256(file)[:12]>-<index:04d>"   e.g. fa9517fb84f3-0088   (stable across runs of the same PDF)
text                heading breadcrumb + body            ← this is what gets embedded
body_text           the body alone (tables: caption + Markdown table part)
heading_breadcrumb  ["7 Troubleshooting", "7.6 Incident-Liste"]      heading_level 2
kind                text | table | picture | mixed
caption             only for a single table/picture item
page_numbers        [23]                    dom_paths ["#/tables/17"]      bboxes (top-left origin, page size)
token_count         361                     (includes prefix and special tokens; max observed 512)
embedding           1024 floats (filled in step 5)
```

The ZSD run produced 112 chunks: 83 text, 26 table, 3 picture. Because `chunk_id` depends only on the file
hash and the position, two runs over the same PDF yield the same chunk ids — the property the indexer relies
on to replace a document in place.

### 4.4 Figures: describe, never invent

Pictures go to a vision model with a German prompt that ends in "Gib nur wieder, was lesbar ist; erfinde
nichts" (report only what is legible; invent nothing). The document's own caption is appended to the prompt.
The description is written into the picture's metadata, so it appears in the Markdown and becomes a
`kind: picture` chunk with the caption "Abbildung n: …" — citable and searchable like any text. Pictures
never become graph nodes; a figure enters the graph only as `figure_ref` in a node's provenance.
(ADR-0010 also foresees a "confirm" job — asking the model whether an already-extracted edge is visible in
the diagram — which is documented as a follow-up and not implemented.)

### 4.5 Embeddings

Each chunk's `text` (breadcrumb + body, not `body_text` alone) is embedded in batches of 64 through an
OpenAI-compatible `/embeddings` endpoint. The design target is `intfloat/multilingual-e5-large` (1024
dimensions) with the mandatory prefixes `passage: ` for chunks and `query: ` for questions; the verification
runs in this report used `bge-m3` (also 1024, no prefix). The model name and prefix are stored with every
document so that retrieval can warn when a question is embedded differently from the chunks. The response
is validated strictly: count, order (by returned index), dimension — any mismatch degrades the run.

### 4.6 Graph extraction: from YAML to a schema the model must obey

This is where the ontology does its main work. The service compiles `ontology.yaml` into a Pydantic
*template* at request time; docling-graph turns that template into the JSON schema the model must fill.
No free-form prompt asks the model to "find entities and relations" — the model is handed a strict
structure.

**Classes become entity models.** For every class the compiler creates a model whose docstring is the
German label/description plus the `cues_de` and the identity keys. Only the identity fields are required;
all other attributes are optional (a wrong optional value must not invalidate a whole batch). Four implicit
fields are added to every class: `label` (as written), `aliases[]`, `description`, and `quote` — "a
literal piece of evidence from the text, at most 200 characters".

**Relations become link components.** Each relation is compiled into a small model
`<Name>Link {target_type, target, polarity, qualifier, quote, <typed properties>}` and attached as a list to
every class that is an allowed *source*. The `target_type` description enumerates the allowed target
classes; `target` is described as "the identity value of the target node exactly as in the text (label,
ticket id, hostname, SOP id, path …) — the target must also appear in its own class list". The polarity
field description carries the negation triggers and the sentence "Verneinte Aussagen sind Daten, nicht
fehlende Kanten". Typed properties (`dependency_kind`, `raci`, `level`, …) are plain fields whose allowed
values are listed in the description and validated afterwards. A relation whose *source* is `NodeBase`
(`MENTIONED_IN`) cannot be attached to a class and is skipped — it is derived from provenance instead.

**The root** is a synthetic `ExtractionRoot` with one catalogue list per class. The schema hash of this
root (`4dec7c2b003fcf96` for the shipped ontology) is recorded in the output and in the result-cache key, so
a changed ontology invalidates cached results.

**The run.** docling-graph is invoked with the LLM backend against an OpenAI-compatible endpoint in
"many-to-one" mode with the *dense* extraction contract:

```
model               gemini-dev (verification) — configurable        temperature 0.0
structured_output   true  → response_format json_schema, strict; falls back to json_object / prompt mode on client error
context_limit       128 000 tokens          max_output_tokens 8 192
internal chunking   512 tokens (docling-graph's own chunker: tiktoken cl100k + MiniLM; separate from the embedding chunks)
parallel_workers    2                       max_retries 2            timeout budget from the request deadline (≥ 60 s)
dense_dedupe        off                     provenance standard
```

The dense contract runs in two phases, then a reconciliation:

```
Phase 1  skeleton discovery      ~15 LLM batches over the chunks: find instances of every class
                                 with their identity values; a coverage pass revisits chunks that yielded nothing
Phase 2  fill                    ~64 LLM jobs, one per class catalogue batch: attributes, links, quotes —
                                 each job sees only the chunks in which its node was found (scoped context)
Phase 3  alias reconciliation    one LLM confirmation call over candidate aliases (17 candidates → 7 confirmed,
                                 0 merged, 7 vetoed as siblings in the reference run); cannot be switched off
```

Node ids are assigned by docling-graph's id registry as `<Class>_<16 hex>`, a BLAKE2b digest of the
identity values and the class (`Person_c148c1f00683d662` for Kai Ostermann). Because the digest is computed
from *content*, the same person, ticket or host in another manual gets the *same id* — this is the whole
basis of the cross-document join later, and it needs no merge step.

### 4.7 Materialisation: the deterministic half of graph building

What comes back from docling-graph is a NetworkX graph with model-produced values. The service's
`materialize` step turns it into the validated, provenance-carrying output. Nothing here calls a model.

| Step | Rule |
|---|---|
| **Value normalisation** | enums matched case-insensitively; `DD.MM.YYYY` → ISO date; decimal comma and thousands separators fixed (`99,95` → 99.95, `1 284` → 1284); booleans from *ja/nein/true/false*; strings checked against the datatype regex. **Values are never dropped** — violations are recorded (`enum_violations`, `identity_pattern_violations`, `value_problems`). |
| **Polarity normalisation** | explicit *negative/negativ/verneint/nein* → `negative`; *positive/positiv/ja* → `positive`; anything else → `unknown` with a note; a **missing** polarity whose quote or qualifier contains a negation trigger → `unknown` + note "polarity missing but evidence contains a negation trigger" (word-boundary match, so "Keinesfalls" does not trigger "kein"). |
| **Identity normalisation** (`norm_key`) | non-breaking spaces → space, whitespace collapsed, trailing `.,;:` stripped, optional title stripping (*Dr., Prof., Dipl.-Ing., Herr, Frau*) for `strip_titles_then_casefold` classes, then `casefold()` — which also folds ß to ss (`Reuß` → `reuss`). |
| **Target resolution** | per class, a map from every normalised identity value, label and alias to the node id (first writer wins). A link's `target` text is resolved first under its declared `target_type`, then under the relation's other allowed classes. |
| **Range check** | a target that exists only under a class the relation does not allow is *not* turned into an edge; it becomes an `unresolved_target` with the reason "node exists only as X, not allowed as REL target". A target with no node at all: "no node with this identity value, label or alias". **No stub nodes are ever created.** |
| **Edge dedupe** | key `(source, target, type, polarity)`; a repeated hit enriches the existing edge (first non-empty quote and qualifier win, properties merged). |
| **Edge provenance** | the edge's quote is searched in the normalised `body_text` of every chunk (quotes < 12 chars ignored; exact match first, then the first 60-character window to tolerate small edits); fallback: the source node's chunks. Pages are derived from the chunks. |
| **Node provenance** | docling-graph's item references → chunk ids via the chunker's `self_ref` index; breadcrumb from the first chunk; `table_ref`/`figure_ref` from the caption prefix of the first table/picture chunk; `match` = *verbatim / observed / reconciled / derived*. |
| **Conflicts** | every `(source, target, type)` that carries **both** polarities is reported in `meta.conflicts` — the ontology's rule "never overwrite, report". |
| **Unknown classes / empty identities** | node skipped with a warning / dropped and listed. |

### 4.8 What comes out

The graph is a plain JSON object `{nodes, edges, meta}` — deliberately not a graph database format (ADR-0005).

```json
{"id":"Person_c148c1f00683d662","type":"Person","label":"Kai Ostermann",
 "attributes":{"role_title":"Verantwortlicher ZSD, IAM-Betrieb","phone_ext":"1315",
               "email":"iam-betrieb@bavd.bund.de","org_unit":"Bereich IT-S 1"},
 "aliases":[],"quote":"Kai Ostermann (Bereich IT-S 1, Durchwahl 1315)",
 "provenance":{"pages":[1,2],"chunk_ids":["2bb722f565a0-0001","2bb722f565a0-0002","2bb722f565a0-0003"],
               "dom_paths":["#/texts/5","#/tables/0", "..."],"heading_breadcrumb":["ZSD - Zentrale Sicherheitsdienste"],
               "table_ref":null,"figure_ref":null,"match":"verbatim"}}
```

A negative edge — the finding that Vault does *not* depend on the PKI for unsealing, with the qualifier
holding the scope, the quote holding the reason, and a typed property:

```json
{"source":"System_8c8c6e95949e6f73","target":"System_7c31e150e0343a40","type":"DEPENDS_ON",
 "polarity":"negative","qualifier":"für Vault-Unseal",
 "quote":"Der Vault-Unseal erfolgt manuell mit drei von fünf Anteilen (Tabelle 14) und benötigt weder PKI noch IAM, sondern nur die Anteile aus dem Tresor des Bereichs IT-S 1.",
 "properties":{"dependency_kind":"zertifikat"},"provenance":{"pages":[19],"chunk_ids":["2bb722f565a0-0062"]}}
```

A reified impact cell with `severity: keine` — a node of degree zero that no edge leads to, taken from
Tabelle 8:

```json
{"id":"ImpactStatement_79730cd28ce68b93","type":"ImpactStatement",
 "label":"Keycloak rollierend, mindestens 2 Knoten aktiv -> VPP (BHB-VRF-0207)",
 "attributes":{"event":"Keycloak rollierend, mindestens 2 Knoten aktiv","causing_system":"Keycloak",
               "affected_system":"VPP (BHB-VRF-0207)","severity":"keine","symptom":"keine"},
 "quote":"Keycloak rollierend, mindestens 2 Knoten aktiv | keine",
 "provenance":{"pages":[2,12,18,19],"chunk_ids":["2bb722f565a0-0004","2bb722f565a0-0040","..."],
               "heading_breadcrumb":["4 Konsumenten und Verknüpfungen"],"table_ref":"Tabelle 8","match":"verbatim"}}
```

`meta` records everything the pipeline decided or could not decide: counts by type and relation, polarity
counts, `unresolved_targets[]`, `conflicts[]`, the violation lists, `alias_reconciliation`, the ontology
name and schema hash, and the docling-graph version.

### 4.9 Numbers, and the honest part about non-determinism

The reference ZSD run: 250 nodes over 23 of the 26 classes (Host 36, ImpactStatement 20, Person 18,
Term 18, FirewallRule 16, System 15, Incident 14, Component 13, OrgUnit 13, Alert 12, SecretStorePath 11,
Procedure 11, StartupStep 11, …), 154 edges over 20 of the 32 relations (READS_SECRET 16, PARTNER_TICKET 16,
DEPENDS_ON 12, GOVERNED_BY 12, DEFINES_TERM 11, PRECEDES 10, IMPACT_OF 10, RESPONSIBLE_FOR 9, …),
149 positive / 5 negative / 0 unknown polarity, 0 conflicts, 14 unresolved targets, 6 identity-pattern
violations (for example a referenced document id `NET-ZK-004` that does not match `^BHB-(PLT|VRF)-\d{4}$`).

**Extraction is not reproducible run to run.** The same PDF with the same model at temperature 0 produced
279, 255 and 250 nodes in three runs (145, 131 and 154 edges). The dominant cause is the scoped fill: each
node's attributes and links are filled from the chunks in which *that node* was found, so a node discovered
in a different chunk set in phase 1 gets a different neighbourhood in phase 2. The measures taken are to pin
the dense contract (rather than an "auto" mode that flips strategies with `max_tokens`), disable
docling-graph's own dedupe, run at temperature 0, and validate everything against the ontology afterwards.
What *is* stable are the chunk ids and every content-addressed identity — which is why the storage layer
replaces a document as a unit instead of trying to upsert nodes.

The consequence for the rest of the system: **extraction counts are never quality evidence** and retrieval
numbers must not be compared across extraction runs or models. The known weak spot is *edge recall*, not
entity recall: one run had 13 relations with zero edges and 136 of 279 nodes isolated. That is the first
thing to improve upstream (table-driven relation passes, materialising `reference` attributes such as
`ImpactStatement.affected_system` as edges) before designing retrieval around the gaps.

---

## 5. Storing chunks and graph in OpenSearch

### 5.1 Why a search engine and no graph database

The graph is small: about 250 nodes and 150 edges per manual, a few thousand nodes for the thirty manuals
the organisation might have. ADR-0005 keeps it as JSON inside OpenSearch and loads it into memory when the
retrieval process starts; one hop over a dictionary adjacency is a sub-millisecond operation. What
OpenSearch adds is exactly what a graph database would not: BM25 over German text, approximate nearest
neighbour search over vectors, exact keyword lookups, filters, and multi-search in one round trip.

### 5.2 Four indices

The `osi` indexer writes one docling-graph run into four indices (aliases `bhb-chunks`, `bhb-nodes`,
`bhb-documents`, `bhb-manifest`, each over a versioned physical index). All mappings are `dynamic: strict`:
an unexpected field is an error, not a silently mapped string.

| Index | One document per | Purpose in retrieval |
|---|---|---|
| `bhb-chunks` (232 docs today) | chunk (`_id = chunk_id`) | the only index that is *searched*: text, vector, identifiers and the reverse index into the graph |
| `bhb-nodes` (460 docs) | node **per document** (`_id = <sha12 of the file>:<node_id>`) | inspection and smoke queries; the retrieval module reads nodes from the graph blob instead |
| `bhb-documents` (2 docs) | manual (`_id = doc_id`) | the **graph blob** (nodes + edges + meta, with computed edge ids), the Markdown, title/version, embedding model and prefix, counts |
| `bhb-manifest` (2 docs) | manual | ingest state and lock: `indexing / active / failed`, `run_id`, history |

There is no edges index. Edges live in the blob and, as `edge_ids[]`, on the chunks that prove them —
they are traversed in memory, never searched.

### 5.3 The chunk record: text, vector, and the reverse index

A chunk document is the docling-graph chunk plus three things the indexer adds. This is the real record for
the CaaS incident table that carries `ZSDSUP-0247` (vector omitted):

```
chunk_id     fa9517fb84f3-0088        doc_id BHB-PLT-0001        kind table        page_numbers [23]
caption      Tabelle 14: Incidents mit Mandantenauswirkung (Auszug)
heading_breadcrumb ["7 Troubleshooting", "7.6 Incident-Liste"]        token_count 361
text         "7 Troubleshooting\n7.6 Incident-Liste\nTabelle 14: …\n| Vorgang | Datum | Titel | … |\n| CAASUP-0351 | 02.07.2026 | Vault nach Knotenwartung versiegelt | … | 0:48 | Prüfschritt in SOP-CAAS-01 · ZSDSUP-0247 , DDSUP-1201 |"
body_text    the same without the breadcrumb lines
identifiers  [CAASUP-0198, CAASUP-0287, CAASUP-0338, CAASUP-0342, CAASUP-0351, DDSUP-1195, DDSUP-1201, ESSUP-1588, SOP-CAAS-01, ZSDSUP-0247]
node_ids     [FailureMode_cfdbd958a4c2690a, Incident_0250f84ebc1b847f, Incident_6e88412c73c159a0, …]   (8)
node_labels  [CAASUP-0198, CAASUP-0287, …, "Ingress-Wartung ohne Ankündigung", ZSDSUP-0247]
node_types   [FailureMode, Incident]          edge_ids [53cc6d6558f98bc4, b51a365c4f18ad20]
embedding    1024-dim vector                 embedding_model bge-m3        run_id …        indexed_at …
```

- **`identifiers`** are extracted from `text + caption` with the six ontology regexes (document, ticket,
  SOP, firewall rule, host, zone), stored exactly as matched, as a `keyword` field. This is what makes
  `ZSDSUP-0247` an exact hit instead of a bag of two tokens.
- **`node_ids` / `node_labels` / `node_types` / `edge_ids`** form the *reverse index*: at ingest time the
  indexer walks every node's and edge's `provenance.chunk_ids` and writes the graph neighbourhood onto the
  chunk (for an edge it also adds both endpoints, because the sentence proving an edge is not always in
  either node's chunk list). One search hit therefore already knows which entities and facts it proves.
- **`node_labels`** is a keyword with the `lc` normaliser (lowercase + trim): an exact, case-insensitive
  match on a label or alias — "vault", "zsdsup-0247", "vault versiegelt | vpp".

### 5.4 Text analysis and vectors

German text (`text`, `body_text`, `caption`, `heading_breadcrumb`) is analysed with a custom `de_text`
analyzer: standard tokenizer → lowercase → German stop words → `german_normalization` (folds umlauts and
ß variants) → **`light_german` stemmer**. The light stemmer was chosen because the full German stemmer
over-stems technical vocabulary. `text` is boosted twice over `body_text` and `caption` in BM25 queries,
because it also contains the breadcrumb.

The vector field is `knn_vector`, dimension 1024, HNSW with `m = 16`, `ef_construction = 128`, space
`cosinesimil`, **engine `lucene`**. Lucene was chosen explicitly over the 3.x default (faiss): it filters
*during* the search (a document filter inside the kNN clause narrows the candidate set instead of
post-filtering), and it needs no native memory outside the JVM heap.

### 5.5 Identity and idempotency

- **Node document id** `sha12:node_id` — the same graph node from two manuals becomes two node documents
  (they carry per-book attributes), while the `node_id` inside stays identical for the join.
- **Edge id** (edges have no id in docling-graph's output): `sha256` over the canonical JSON of
  `[source, target, type, polarity, qualifier, quote, sorted chunk_ids]`, first 16 hex characters. The same
  assertion in two books yields two edge ids (different quotes and chunks); retrieval merges them by the
  tuple, not the id.
- **`run_id`** is a fingerprint of the *canonical output* (document, chunks without vectors, a vector digest
  rounded to four decimals, nodes, edges, ontology fingerprint, model, mapping version) — so an identical
  rerun is recognised as a no-op even if float noise differs.
- **Replacement unit is the manual (`doc_id`)**, resolved with a fixed precedence: explicit override >
  the ontology's `meta.documents[].file` > a unique document-id regex hit on page-1 chunks > the source of a
  single `DOCUMENTS` edge > fail. Ingest = write all chunks/nodes/document with `index` (overwrite), refresh,
  verify counts, then *sweep* everything of that `doc_id` with an older `run_id`. A failure before the sweep
  leaves a **superset, never a hole**; the manifest records `failed` and the next run heals it. Readers never
  filter by `run_id` for that reason.

### 5.6 The search primitives available

| Primitive | OpenSearch feature | Used by retrieval as |
|---|---|---|
| lexical relevance | `multi_match` (BM25) on `text^2, body_text, caption` with `de_text` | the **bm25** channel |
| semantic similarity | `knn` query on `embedding` (HNSW, cosine), `k` and `size` both set | the **knn** channel |
| exact identifier | `term` on `identifiers` (keyword) | the **identifier** channel |
| exact entity label | `term` on `node_labels` (keyword, lowercase) | the **label** channel |
| restrict to manuals | `terms` on `doc_id` — inside the knn clause, in a `bool.filter` elsewhere | the per-user allowed-manuals filter |
| several queries, one round trip | `msearch` | all channels at once |
| fetch by id | `mget` on `_id = chunk_id` | the provenance chunks of graph facts |
| server-side fusion | `hybrid` query + search pipeline `bhb-rrf` (`score-ranker-processor`, `rrf`, rank constant 60) | **not used** by retrieval — see 6.5 |

The `bhb-rrf` pipeline exists and works, but retrieval fuses on the client. The server pipeline returns one
score per hit and loses *which clause found it at which rank*; that attribution is what the guardrail
reasons about and what the user interface shows (`via knn#2 bm25#1 identifier#3`). The pipeline also cannot
take a fifth list that did not come from a query — the graph channel.

---

## 6. From question to answer: the retrieval mechanism

This chapter answers the central question of the report: how does a German sentence become search requests
and graph traversals, and where exactly does a language model enter? The short version first:

> **Nothing between the question and the assembled context is a language model.** Identifiers are found
> by regular expressions. Entities are found by matching the question's word n-grams against the labels and
> aliases of the in-memory graph. Semantic similarity comes from an embedding model (a deterministic
> encoder, not a generator). Lists are fused by rank. The graph is expanded one hop over *all* relations
> around the matched entities; the question's wording only *orders* the resulting facts. The language
> model reads the finished context and writes the answer.

### 6.1 The pipeline

```
question ──► 1 analyze ──► 2 embed ──► 3 msearch (4 channels) ──► 4 RRF ──► 5 guardrail ──► 6 graph (slow) ──► 7 groups + citations ──► 8 prompt
              │                          knn · bm25 · identifier · label       │                 │  1 hop, all relations
              │ identifiers (regex)                                            │                 │  facts · entity cards · provenance chunks
              └ labels / aliases as n-grams; partial label matches             │                 └  5th list → RRF again
                                                                               └ weak evidence? → "Dazu steht nichts in den Handbüchern." (no model call)
```

Two modes exist: **fast** stops after step 5 (four search channels), **slow** adds the graph channel. The
fast/slow toggle in the chat is the live demonstration that the graph adds something — the same question
can be asked both ways. A typical slow retrieval takes 230–330 ms, of which about 200–270 ms is the
embedding call; the OpenSearch round trip is under 10 ms and the graph expansion 8–80 ms.

### 6.2 Step 1 — Analyze: identifiers and entities without a model

`analyze_question` does no I/O and calls no model. It produces a `QueryPlan` with four ingredients.

**Identifiers.** The six ontology regexes run over the question; the `host` pattern (lowercase by design)
additionally runs over the lowercased question so that "Vault-P01" typed with a capital still matches.
`Was war bei ZSDSUP-0247?` → identifiers `["ZSDSUP-0247"]`.

**Labels (exact entity mentions).** The question is tokenised (`[\w][\w\-./]*`) and every n-gram of length
4 down to 1 is normalised with the same `norm_key` used at indexing time (casefold, ß→ss, whitespace
collapsed) and looked up in the graph's **label index** — a dictionary built at load time from the `norm_key`
of every node label and alias. Greedy longest match wins and consumes its tokens; a multi-word match also
resolves its single words afterwards ("Vault entsiegeln" also yields "Vault"). Unigrams need at least three
characters and must not be in a German stop-word list (articles, question words, auxiliaries, prepositions,
and function words such as *passiert, läuft, hängt, daran, dazu* that happen to occur in labels). Hyphenated
compounds that did not match as a whole are retried by part ("TLS-Zertifikat" → "tls", "zertifikat").
`Was passiert, wenn Vault versiegelt ist?` → label candidates `["vault"]` → node ids of everything called
Vault (a `System`, a `Component`, a `Host`, a `Term`).

**Partial label matches.** Some of the most valuable nodes are unreachable by exact match and by any edge:
the reified `ImpactStatement`s are labelled "Vault versiegelt | VPP", "Vault versiegelt | Mars
Dokumentendienste", … . The analyzer therefore also collects nodes whose label or aliases contain at least
two distinct content words of the question — **provided one of them is an anchor**, i.e. a word of an exactly
resolved label or an identifier. The anchor rule was necessary: without it, "Dispatcher neu starten" pulled
in every "API-Server neu starten"/"Ingress-Router neu starten" statement. Document and glossary nodes are
excluded, at most 8 nodes are kept, ordered by how many question words they contain and how specific the
label is. For the Vault question this step yields the eight "Vault versiegelt | X" impact statements, among
them the one with `severity: keine` for VPP.

**Label terms for OpenSearch.** The label channel needs the *original lowercase spellings* (the index
normaliser only lowercases; it does not fold ß), so the plan carries `label_terms` such as
`["vault", "vault versiegelt | vpp", …]` separately from the `norm_key`s.

### 6.3 Step 2 — Embed

The (rewritten) question is embedded with the configured model and prefix. The result is compared with the
model and prefix recorded on the indexed documents; a mismatch (different model, `passage:` chunks with an
empty query prefix) is reported as a warning in the diagnostics, never hidden. If the embedding endpoint
fails, retrieval continues with the lexical channels.

### 6.4 Step 3 — Four channels in one request

All channels ask for `k = 20` hits, exclude the vector and bounding boxes from the returned source, and go
out in a single `msearch`:

| Channel | Query body (essentials) | Fires when |
|---|---|---|
| **knn** | `{"knn": {"embedding": {"vector": q, "k": 20, "filter": {"terms": {"doc_id": […]}}}}}` | always (unless embedding failed) |
| **bm25** | `{"multi_match": {"query": question, "fields": ["text^2", "body_text", "caption"]}}` | always |
| **identifier** | `{"bool": {"should": [{"term": {"identifiers": "ZSDSUP-0247"}}, …], "minimum_should_match": 1}}` | the question contains an identifier |
| **label** | `{"bool": {"should": [{"term": {"node_labels": "vault"}}, {"term": {"node_labels": "vault versiegelt \| vpp"}}, …]}}` | the question names a graph entity |

The per-user manual filter (`doc_ids`) goes *inside* the kNN clause (filter-during-search) and into a
`bool.filter` for the other three. For every hit the module records which channel found it at which rank
and, for the exact channels, *what* matched (`via identifier#2(ZSDSUP-0247)`, `via label#1(vault, …)`).

### 6.5 Step 4 — Reciprocal rank fusion on the client

Scores from BM25, cosine similarity and boolean term matches are not comparable, so fusion uses ranks only:

```
score(chunk) = Σ over channels that found it   1 / (60 + rank in that channel)
```

with the rank constant 60 from the SPEC. Ties are broken by more channels, then better best rank, then
chunk id — the result is fully deterministic. Hits are deduplicated by chunk id keeping the *union* of
channel evidence.

Two numbers explain most of the retrieval behaviour:

- a chunk at rank 1 in a single channel scores `1/61 ≈ 0.0164`;
- a chunk at rank 10 in **two** channels scores `2/70 ≈ 0.0286`.

Agreement between channels beats a single strong hit. That is intended (it is the whole point of RRF), but
it has a consequence for the graph channel (6.7): a chunk that *only* the graph found can never reach the
top ten against two-channel hits, so it needs a reserved slot.

### 6.6 Step 5 — The guardrail: refusing without a model call

If the corpus does not cover the question, the system must say exactly *"Dazu steht nichts in den
Handbüchern."* — and it must do so **without calling the model** (ADR-0011). The decision is made on
ranks and channels, never on an absolute similarity value: bge-m3 and e5 cosine scores compress to about
0.96 for almost everything, so a threshold would be arbitrary.

*Amendment (REQ-001, 2026-09-08).* The no-model-call refusal applies to a **first** turn. On a follow-up the
conversation itself is evidence: the model is called with the history and a note that no new passages were
found, so "Mach ein Script mit diesen Befehlen" after an answer that listed commands is answered from that
answer. The requirement documents in `retrieval/requirements/` and `chat-system/requirements/` record this
and the planned relaxations (approximate entity matching, ontology-driven overview mode).

```
evidence is STRONG if   an identifier matched   or   a graph label resolved
otherwise WEAK if       no hit at all
                  or    BM25 returned nothing               → "no lexical overlap with the corpus"
                  or    none of the top 3 fused chunks was found by ≥ 2 *search* channels
                                                            → "top hits were each found by a single channel only"
```

The graph channel never counts as evidence: in slow mode it is seeded from the very hits under suspicion,
and an early version that counted graph facts let the off-topic test question through. When the verdict is
weak, the graph expansion is skipped and the chat streams the canned sentence.
`Wie backe ich einen Apfelkuchen?` → kNN returns 20 chunks (it always does), BM25 returns 0 → weak.

### 6.7 Step 6 — The graph channel (slow mode)

This is where the ontology-grounded graph becomes context. It runs only when the evidence is not weak.

**Seeds.** The top 5 fused chunks plus the top 2 of every search channel. The per-channel seeds matter: for
the cold-start question the eleven-step table was kNN rank 2 but not in the fused top 5.

**Start nodes** (capped at 30, never `Document` or `Term`), in this order:

1. the exactly resolved label nodes (everything called "Vault");
2. the partial label matches (the "Vault versiegelt | X" statements);
3. the `node_ids` carried by the seed chunks (the reverse index from 5.3), sorted by: label mentions a
   question word → node type the question asks about (see the cue table below) → present in ≥ 2 seed
   chunks → static type priority (`ImpactStatement, Incident, Person, Procedure, Component, System,
   StartupStep, FirewallRule, Host`) → seed rank.

**Expansion.** One hop over **all relation types**, in **both directions**: every edge that touches a start
node, from any indexed manual (restricted to the user's allowed manuals). The same assertion in two manuals
is one edge id with two occurrences. No relation allowlist, no depth-2 chains.

**Facts.** The expanded edges become `GraphFact`s, ordered by: touches a resolved label → relation types the
question's wording asks about → **negative before positive** → static relation priority (`DEPENDS_ON,
IMPACT_OF, RESPONSIBLE_FOR, ESCALATES_TO, PARTNER_TICKET, PRECEDES, RUNS_ON, GOVERNED_BY, TENANT_OF`) →
position of the start node → page. At most 40 are kept. Each is rendered in German with its provenance:

```
Vault —DEPENDS_ON (hängt ab von)→ PKI (dependency_kind=zertifikat): NICHT (für Vault-Unseal) — „Der Vault-Unseal erfolgt manuell …“ [BHB-PLT-0007 S. 19; Kante 1a2b…]
Kai Ostermann —ESCALATES_TO (eskaliert an)→ Dr. Annika Reuß (level=2) [BHB-PLT-0007 S. 26; Kante …]
```

A negative edge is rendered as an explicit `NICHT` with qualifier and quote; polarity `unknown` is marked
`(unsicher)`. Properties are printed, the German relation label comes from the ontology's `label_de`.

**Entity cards.** Start nodes and reached neighbours become cards with their attributes — one occurrence per
manual, side by side when the manuals disagree (`purpose` from CaaS S. 12, `availability_target: 99.95` from
ZSD S. 19). Cards of the same type whose label or alias spellings coincide are merged ("Kai Ostermann" and
"Ostermann" with alias "Kai Ostermann"). Cards without attributes and quote are skipped; at most 15 are kept,
label-matched first. This is how `Vault versiegelt | VPP — severity: keine` reaches the prompt although no
edge leads to it.

**Provenance chunks as the fifth list.** The `chunk_ids` of the kept facts, then of the label nodes, then
of the neighbours (at most 15) are fetched with `mget` and fused as a fifth ranked list. Because a
graph-only chunk loses in RRF (6.5), the provenance chunks of the **two best facts are guaranteed a slot** in
the final list — otherwise the ZSD page 19 paragraph that proves the negative dependencies fell out of the
top ten while the facts quoted it.

#### How the question's wording chooses relations and types — the cue table

The plan foresaw *intent routing*: classify the question, then traverse only an allowlist of relations. The
implementation deliberately does something weaker and more robust: expand everything one hop, then **order**
facts and start nodes by cues in the wording. This is the complete table (`facts.RELATION_CUES`); it is a
set of regular expressions, not a classifier:

| Wording matches (regex, case-insensitive) | Relations sorted first | Node types sorted first |
|---|---|---|
| `zuständig \| verantwortlich \| ansprechpartner \| eskal \| wer \| wen \| wem \| kontakt \| erreich \| rufbereitschaft` | RESPONSIBLE_FOR, ESCALATES_TO, OPERATED_BY, STEP_RESPONSIBILITY | Person, OrgUnit |
| `reihenfolge \| kaltstart \| anfahr \| hochfahr \| fährt \| wiederanlauf \| schritt \| zuerst \| danach` | PRECEDES, STEP_RESPONSIBILITY | StartupStep, Procedure |
| `abhäng \| hängt \| auswirk \| passiert \| ausfall \| versiegelt \| neustart \| betroffen \| folgen` | DEPENDS_ON, IMPACT_OF, TENANT_OF, RUNS_ON | ImpactStatement, System, Component |
| `ticket \| vorfall \| incident \| störung \| vorgang \| (ZSD\|CAAS\|DD\|VPP\|ES)SUP-` | PARTNER_TICKET, RESULTED_IN_CHANGE, INSTANCE_OF_FAILURE, DETECTED_BY | Incident, FailureMode, Alert |
| `wie \| erneuer \| rotier \| entsiegel \| anleitung \| sop \| vorgehen \| schritte \| durchführ` | GOVERNED_BY, PRECEDES, RESPONSIBLE_FOR | Procedure, Person |

Several rows may fire; their relations are concatenated in order. Nothing is *excluded* by the cues — a
question about responsibility still receives the dependency facts, just later in the list (and possibly cut
by the cap of 40 or the prompt budget). Direction is not chosen either: the adjacency is undirected for
expansion, and the rendered fact keeps the edge's own direction (`source —REL→ target`), so "who is
responsible for Vault" and "what is Marcel Ebert responsible for" traverse the same `RESPONSIBLE_FOR` edge.

Why this is enough, measured on the corpus: the graph has about 0.5 edges per node and a median 1-hop
neighbourhood of one or two edges, and every competency question is a one- or two-hop pattern. Rendering
everything typed and polarity-aware costs a few hundred tokens; a classifier that guesses wrong loses the
answer. If neighbourhoods become noisy with more manuals, the documented next step is an
*ontology-constrained query plan*: a small model call that receives the question and the 32 relation names
with their German labels and returns `{start_entities, relations, direction, depth}` — the traversal itself
stays deterministic and can never name a relation outside the ontology. That would be the first place a
language model enters retrieval, and it is optional.

### 6.8 Step 7 — Groups and citations

The final ten chunks are grouped: table parts with the same document and caption become **one source** whose
pages are the union (Tabelle 5 in three parts → "BHB-PLT-0007 S. 9–10", header rows printed once). One
citation is produced per (document, pages) of the included groups plus one per fact, each carrying its chunk
and edge ids.

### 6.9 Step 8 — The prompt

The German system prompt sets seven rules: answer only from the context and from the assistant's own earlier
answers in the conversation, which may be reused and transformed (a script, a summary, a table) but never
extended with new facts; cite every statement as `[BHB-PLT-0007 S. 19]`; when the context answers only
partially or the question names no concrete system, first say what the manuals contain on the topic (with
sources), then ask in one sentence which system or manual is meant, naming the systems and manuals present in
the context as options — the canned sentence is reserved for the case where neither context nor earlier
answers hold anything (REQ-001, graded rule 3); facts marked `NICHT` and entries with `severity: keine` are
explicit negations and must be rendered as such with their reason; when two manuals contradict each other,
give both with sources; copy identifiers verbatim; answer in German, concisely, with numbered lists for
sequences. A follow-up whose retrieval found no new evidence receives a short note instead of the context and
is answered from the conversation.

The context block is rendered in a fixed order — **Entitäten** (entity cards), **Fakten** (up to 25),
**Quellen** (sources by rank, each with a header line `### Quelle n · doc „title“ · S. x · breadcrumb ·
caption (n Teile) · [chunk ids]`). Sources are added until a budget of 6 000 estimated tokens is spent,
using the `token_count` stored on every chunk plus about 40 per header; facts and entities always fit first,
dropped chunk ids are reported. The estimate uses 2.6 characters per token, measured on this corpus with the
verification model (a 19 120-character context was 7 336 tokens). The last `history_turns` user/assistant
pairs of the conversation precede the context (default 3; 10 on a deployment with a large served context); a
prompt above the model's context limit raises an error instead of being truncated silently. A streamed answer
cut by `max_tokens` is reported as `finish_reason=length` to the chat, which stores and shows it.

### 6.10 Where a language model is used, and where not

| Stage | Component | Model involved? |
|---|---|---|
| ingestion | parsing, clean-up, chunking | no (docling models are layout/table/OCR models, not generative) |
| ingestion | figure description | yes (vision model, describe only) |
| ingestion | embeddings | encoder model (deterministic for the same input) |
| ingestion | graph extraction | **yes** — constrained by the ontology schema; the non-deterministic step of the whole system |
| ingestion | materialisation, identity, validation, edge/node ids | no |
| indexing | identifiers, reverse index, run fingerprint | no |
| retrieval | analyze (identifiers, labels, partial labels) | no |
| retrieval | question embedding | encoder model |
| retrieval | four channels, RRF, guardrail, expansion, fact ordering, cards, grouping, citations, context rendering | **no** |
| conversation | rewriting a follow-up into a standalone question (last two turns) | yes, optional; falls back to the original on any error |
| answer | the German answer with citations | **yes** — the only generative step the user sees; skipped entirely when the guardrail fires |

### 6.11 Worked example 1 — "Was passiert, wenn Vault versiegelt ist?" (slow mode)

Analyze: no identifier; label `Vault` resolves to a System, a Component, a Host and a Term node; partial
matches: eight `ImpactStatement`s "Vault versiegelt | Observability / VPP / Mars Dokumentendienste /
Event-System 2.0 / CaaS-Plattform …" and the FailureMode "Vault nach Knotenwartung versiegelt". Cues: the
third row fires (`passiert`, `versiegelt`) → DEPENDS_ON, IMPACT_OF first; ImpactStatement, System, Component
types first.

Channels: knn 20 hits (3 ms), bm25 20 (3 ms), label 20 (4 ms) — the label channel is fed with
`vault` and the eight partial labels; graph 15. Guardrail: ok (a label resolved). 30 start nodes.

Top of the fused list (of 10):

```
 1. BHB-PLT-0001 S. 12 · 4.2 Was bei welchem Mandanten hängt        via knn#10 bm25#16 label#1(vault, vault versiegelt | event-system 2.0, …) graph#2(DEPENDS_ON from Zentrale Sicherheitsdienste)
 2. BHB-PLT-0007 S. 22 · 7.2.4 Vault nach Knotenwartung versiegelt  via knn#11 bm25#14 label#13 graph#8(GOVERNED_BY from Vault)
 3. BHB-PLT-0001 S. 15 · 5.3 Knotenwartung … › Sonderfall Vault      via knn#3 bm25#9 label#2
 …
 9. BHB-PLT-0007 S. 29 · 10.1 Glossar › Sealed / Unseal              via knn#2 bm25#7
10. BHB-PLT-0007 S. 19 · 6.3 Zirkuläre Abhängigkeit und ihre Auflösung   via knn#18 graph#1(DEPENDS_ON from Vault)   ← guaranteed slot
```

Hit 1 shows the fusion at work: rank 10 and 16 in the semantic and lexical channels, rank 1 in the label
channel, rank 2 in the graph channel — four agreeing channels beat any single top hit. Hit 10 is the
paragraph that proves the negative dependencies; it was only kNN rank 18 and would have been cut without
the guaranteed slot.

Facts 1 and 2 of 40:

```
Vault —DEPENDS_ON (hängt ab von)→ Keycloak (dependency_kind=identitaet): NICHT (für Vault-Unseal) — „Der Vault-Unseal erfolgt manuell mit drei von fünf Anteilen … benötigt weder PKI noch IAM …“ [BHB-PLT-0007 S. 19]
Vault —DEPENDS_ON (hängt ab von)→ PKI (dependency_kind=zertifikat): NICHT (für Vault-Unseal) — „…“ [BHB-PLT-0007 S. 19]
```

followed by the positive dependency chain (Mars Dokumentendienste, CaaS, dd-ingest-worker, Event-System and
PKI depend on Vault, each with `failure_effect` and `bridging`), the tenant relation, Marcel Ebert's
responsibility, `SOP-ZSD-05`, the `VaultSealed` alert, and three `PRECEDES` steps around "Vault entsiegeln".

Entity cards (15) start with the eight impact statements, among them
`Vault versiegelt | VPP (ImpactStatement) — severity: keine; symptom: unberührt, Keystores und Wallet liegen lokal auf den Knoten [BHB-PLT-0007 S. 19]`
and the same finding from the CaaS manual; then the Vault component (`technology: Vault 1.16.3, Raft`), the
System card with attributes from both manuals side by side, the Host card with `vault-0/1/2`.

Total 267 ms (embed 243 ms). The rendered context was about 6 850 tokens; nine of the ten sources were
dropped by the budget because the cards and facts already cost most of it — and they carry the answer. The
model's answer (verification run) lists the impact per consumer and states: *"VPP: nicht betroffen, da
Keystores und Wallet lokal auf den Knoten liegen [BHB-PLT-0001 S. 12; BHB-PLT-0007 S. 19]"* — the deliberate
non-coupling, stated as a negation, with its reason and two sources.

### 6.12 Worked example 2 — "Was war bei ZSDSUP-0247?" (fast mode)

Analyze: identifier `ZSDSUP-0247`; the same string is also a node label (the Incident), so the label
channel fires too. Channels: knn 20, bm25 20, **identifier 7**, label 11. The top seven hits are each found
by all four channels:

```
 1. BHB-PLT-0001 S. 21 · 7.3 Vault nach Knotenwartung versiegelt (CAASUP-0351) › Umgebung    via knn#2 bm25#1 identifier#2 label#2
 2. BHB-PLT-0001 S. 23 · Tabelle 14: Incidents mit Mandantenauswirkung                        via knn#6 bm25#5 identifier#3 label#4
 3. BHB-PLT-0007 S. 23 · Tabelle 9: Incidents der Zentralen Sicherheitsdienste (2 Teile)       via knn#1 bm25#4 identifier#7 label#10 …
```

Both manuals' incident tables are in the top three — one says 0:48, the other 38 minutes. In slow mode the
graph adds the `PARTNER_TICKET` chain `CAASUP-0351 ⇄ ZSDSUP-0247 ⇄ DDSUP-1201` and the Incident card with
both books' attributes side by side. The model's answer names both durations *and* the reason they differ
(different measurement points), instead of averaging or picking one. 227 ms in fast mode.

### 6.13 Worked example 3 — "In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?"

No identifier and no label ("Verbund" and "Totalausfall" are not node names). The second cue row fires
(`Reihenfolge`, `fährt`) → `StartupStep` nodes are boosted among the seed node ids and `PRECEDES` facts
are sorted first. The cold-start table was kNN rank 2 and became a seed through the per-channel rule; its
chunk carries the eleven `StartupStep` node ids. Result: 16 `PRECEDES` facts from both manuals
(`Virtualisierung → Firewall → AD/IAM → PKI → Control Plane → Worker → Vault entsiegeln → Kafka →
Event-System → Mars → VPP`) plus StartupStep cards with `order`, `duration`, `precondition`. Before the
per-channel seeding and the type boost, the same question yielded three PRECEDES facts.

### 6.14 Worked example 4 — "Wie backe ich einen Apfelkuchen?"

No identifier, no label. kNN returns its 20 nearest chunks regardless (the top one is about ACME requests
being dropped by a firewall — nearest is not near). BM25 returns nothing: no word of the question occurs in
the corpus. Verdict: weak evidence, "no lexical overlap with the corpus"; graph expansion skipped; the chat
answers *Dazu steht nichts in den Handbüchern.* in 197 ms without a model call and without citations.

### 6.15 Results on the ground-truth questions

The eight questions were chosen from the competency questions and the corpus' documented traps, with the
expected pages verified in the PDFs.

| # | Question | Expected (pages verified in the PDFs) | Outcome |
|---|---|---|---|
| 1 | Wer ist für IAM/Keycloak zuständig und wie eskaliere ich? | ZSD S. 1–2, 26; fact Ostermann —ESCALATES_TO→ Reuß | pages present; cue puts RESPONSIBLE_FOR/ESCALATES_TO first; card with phone 1315 from both books |
| 2 | Was passiert, wenn Vault versiegelt ist? | CaaS S. 12, 15, 19; ZSD S. 19, 15; negative DEPENDS_ON; VPP "keine" | see 6.11 — negations rendered as negations |
| 3 | Was war bei ZSDSUP-0247? | identifier channel; ZSD S. 22–23; CaaS S. 21, 23; partner tickets | see 6.12 — both durations explained |
| 4 | In welcher Reihenfolge fährt der Verbund … an? | CaaS S. 20 (Tabelle 13); ≥ 8 PRECEDES; ZSD S. 19 | 16 PRECEDES facts, eleven steps in order |
| 5 | Auf welchen Servern und Ports läuft ZSD? | ZSD S. 8–10 (Tabellen 4 and 5) | Tabelle 5 rank 1 in fast mode (3 parts grouped, header once); in slow mode it drops to rank 4 because the alias "ZSD" sits on 18 chunks — fast mode is the better mode here; hosts reach the prompt through the entity cards |
| 6 | Wer darf Vault entsiegeln und wie? | ZSD S. 15 (SOP-ZSD-05, Marcel Ebert), 17; CaaS S. 15, 19–20 | fact 1 Marcel Ebert —RESPONSIBLE_FOR→ SOP-ZSD-05; five steps of the SOP in the answer |
| 7 | Ich will den Dispatcher neu starten – was hängt daran? | ZSD S. 11–12, 19; CaaS S. 14–15 | label `Dispatcher`; PDB, Vault dependency, delivery effect; partial until the Event-System manual is indexed |
| 8 | Wie erneuere ich ein TLS-Zertifikat? | ZSD S. 15–17; CaaS S. 16 | no node is called "TLS-Zertifikat": found by kNN/BM25 seeds and `GOVERNED_BY → SOP-CAAS-04` |
| G | Wie backe ich einen Apfelkuchen? | weak evidence, no model call | see 6.14 |
| R | "Wer ist für Vault zuständig?" then "und bei Keycloak?" | rewritten question names Keycloak | rewrite → "Wer ist für Keycloak zuständig?" (one short model call) |

Every model answer in the verification run cited `[BHB-PLT-… S. n]` on every statement and stayed inside the
context. Two observations changed the implementation along the way and are worth remembering: the
verification model spends about 1 300 tokens of the output budget on reasoning before the first visible
token (answers were cut at a 1 500-token limit; the default is now 4 000), and generic aliases such as
"ZSD" that sit on many chunks dilute the label channel — a candidate for IDF-like damping later.

---

## 7. Users, limits and the chat application (overview)

Two modules turn the retrieval library into a product. Both are described in depth in their own folders.

**`users/` (package `rag_users`)** is the identity and policy seam of SPEC §10.2 / ADR-0008, mocked where
the specification defers real authentication. One `AuthContext{user_id, email, groups}` comes from one of
two adapters: a development adapter returning a fixed identity, or the production adapter reading the
headers an authenticating reverse proxy injects. A `Policy` maps groups to limits — the SPEC's ten messages
per user per day, a turn cap per conversation, and (an addition beyond the SPEC) the **manuals a group may
read**. That last one is what flows into retrieval as the `doc_ids` filter of 6.4: a read-only group that
may see only the security manual gets ZSD-only chunks, facts and citations, verified against the live index.
A request naming only manuals the user may not read is refused as *forbidden* before anything is counted.

**`chat-system/` (package `chat_system`)** is the Streamlit application with a conversation database
(SQLAlchemy/Alembic; SQLite by default, Postgres via a compose profile) and a backend service that never
imports the UI. A turn runs through eight phases: policy check → concurrency slot → reservation of the daily
usage counter together with the user's message in one transaction → rewrite of a follow-up from the last two
turns → retrieval with the effective manual filter → guardrail (canned sentence, no model call) or prompt →
streaming of the answer → persistence of the assistant row with citations (enriched with breadcrumb, channels
and a snippet), diagnostics and finish reason (`stop`, `guardrail`, `aborted`, `error` with refund). The
sidebar offers the fast/slow toggle, the manual filter, the diagnostics switch and resumable conversations;
under every answer a **Quellen** panel lists the sources, and the optional **Diagnostik** panel shows the
mode, the rewritten question, the channel table, timings, facts (negatives in red) and entities.

Verified state: 54 unit tests green on SQLite and Postgres, 5 UI smoke tests, 8 live integration tests
(two of them driving the real application against the real stack), six smoke questions answered through the
headless CLI, the container image built and answering from inside the container.

---

## 8. How deterministic is it, really?

"Deterministic search" is the promise the reader wants examined. Here is where the system stands, stage by
stage, given a fixed index.

| Stage | Deterministic? | Notes |
|---|---|---|
| Question analysis (identifiers, labels, partial labels, cues) | **yes, exactly** | pure string processing over a fixed label index |
| Question embedding | yes for the same model and input | an encoder is a fixed function; a different model or prefix is detected and reported |
| kNN channel | yes in practice | HNSW is approximate, but with a few hundred chunks and k = 20 the graph is essentially exhaustive; the same query returns the same ranks |
| BM25, identifier, label channels | **yes** | Lucene scoring is deterministic for a fixed index |
| Fusion, guardrail, seeds, start nodes, expansion, fact and card ordering, budgeting | **yes, exactly** | fixed formulas with explicit tie-breaks; 112 unit tests run them against a fake OpenSearch |
| Follow-up rewrite | no (model) | optional; deterministic path when there is no history; falls back to the original question |
| The answer | no (model) | constrained by the system prompt, the fixed context and the guardrail; temperature 0 |
| Graph extraction at ingest | **no (model)** | 279 / 255 / 250 nodes for the same PDF; constrained by the ontology schema and validated afterwards |

So the honest formulation is: **for a given index and question, everything up to the finished prompt is
reproducible byte for byte (timings aside), and the reader can see why every chunk and fact is there**
(`via knn#2 bm25#1`, `DEPENDS_ON from Vault`). Randomness lives in two places — the extraction model at
ingest and the answering model at the end — and both are fenced: the extractor may only produce instances
of the ontology, is validated and normalised deterministically, and its output is content-addressed; the
answerer only sees a context whose every line carries a citation, and is not called at all when the
evidence is weak.

What this determinism buys in practice:

- **Explainability.** Every hit shows the channels and ranks that found it; every fact shows the edge, the
  quote and the page. A wrong answer can be traced to a wrong fact or a missing chunk, not to "the model".
- **Testability.** The retrieval module has 112 unit tests over a fake search client that reimplements the
  needed OpenSearch behaviour (cosine kNN, token-overlap BM25 with German stop words, term filters,
  msearch, mget); the graph tests run on the real extraction output. The 13 live tests then only confirm
  that the real cluster behaves like the fake.
- **A guardrail without thresholds.** Refusal is a property of ranks and channel agreement, so it does not
  need re-tuning when the embedding model changes.

And its limits:

- **Exact matching needs the entity to be spelled like a label or alias.** "Unseal" versus "entsiegeln" is
  not bridged by the label channel; it is bridged by the semantic and lexical channels (the glossary chunk
  "Sealed / Unseal" appears in the Vault example) and, by design, by `Term` nodes whose `maps_to` points at
  the entity — a channel not yet exploited.
- **Cross-document joins are exact.** The same person under "Kai Ostermann" and "Ostermann" merges through
  an alias; "ZSD", "Zentrale Sicherheitsdienste" and "ZSD - Zentrale Sicherheitsdienste" are three System
  nodes until a merge module folds them.
- **Generic aliases dilute.** An alias on 18 chunks ("ZSD") pushes the label channel toward the title pages.
- **Edge recall at extraction is the weakest link.** Everything downstream can only rank what the
  extractor produced.

---

## 9. The reader's questions, answered directly

**Is an ontology at this level easy to replicate on real data?**
The framework parts — provenance and polarity on every element, identity rules with normalisation and
scope, the negation policy, competency questions as acceptance tests, identifier regexes — transfer as they
are. The 26 classes and 32 relations are specific to the *Betriebshandbuch* template and were written by a
domain expert against three anonymised real exports in days, not months. Real manuals written to a template
give most of the structure for free (that is why the edges are taken from mandated sections); manuals
without a template, without identifier conventions, or with inconsistent names produce a thinner graph,
visibly: fewer nodes, more `unresolved_targets`, no cross-document joins. The recommended start is ten
classes and ten relations, identity keys and negation policy from day one, growth driven by what the
extractor reports as unresolved. See 3.10.

**How is the graph created?**
docling parses the PDF (layout, TableFormer tables, OCR, figures at three times layout resolution); the
service cleans page furniture and infers table captions; docling's hybrid chunker cuts 512-token chunks with
caption and header on every table part; a vision model describes figures ("invent nothing"); each chunk is
embedded. Then the ontology is compiled into a strict JSON schema (classes with only identity fields
required; relations as typed link components with `target_type, target, polarity, qualifier, quote`), and
docling-graph runs a two-phase extraction with a language model — skeleton discovery over about 15 batches,
then about 64 scoped fill jobs, then one alias-reconciliation call — at temperature 0 with structured
output. The service then normalises values, resolves link targets against identity values, labels and
aliases, rejects targets of the wrong class as `unresolved_targets` (never creating stub nodes), dedupes
edges on `(source, target, type, polarity)`, binds every node and edge to chunk ids and pages through the
quotes, reports conflicts, and writes `{nodes, edges, meta}`. Node ids are content-addressed
(`Class_<blake2b16 of identity + class>`), so the same entity in two manuals has the same id. See chapter 4.

**How is the search mechanism actually working?**
Four OpenSearch queries in one request — semantic kNN, BM25 over German-analysed text, exact `term` on the
chunk's extracted identifiers, exact `term` on the chunk's graph labels — fused by reciprocal rank
(`Σ 1/(60+rank)`), deduplicated by chunk id with the union of channel evidence. A rank-based guardrail
refuses without a model when no exact channel fired and the top hits do not agree across channels. In slow
mode the entities the question names (by label, by partial label with an anchor, and by the node ids of the
seed chunks) are expanded one hop over all relations in both directions; facts are rendered in German with
polarity, qualifier, quote and page, entity cards carry attributes per manual, and the facts' provenance
chunks join the fusion as a fifth list with two guaranteed slots. Table parts are regrouped under their
caption; citations are one per document/pages plus one per fact. See chapter 6.

**How is data saved in OpenSearch and which tools search through it?**
Four strict-mapped indices: `bhb-chunks` (text with a light-German analyzer, a 1024-dimensional Lucene
HNSW cosine vector, `identifiers` and the reverse index `node_ids / node_labels / node_types / edge_ids` as
keywords), `bhb-nodes` (one node record per manual for inspection), `bhb-documents` (the whole graph as a
JSON blob with computed edge ids, the Markdown, title and embedding model), `bhb-manifest` (ingest state and
lock). Edges are never searched, only traversed in memory. The tools are BM25 `multi_match`, `knn`, `term`
and `terms` filters, `msearch` and `mget`; a server-side RRF pipeline exists but is not used because it hides
per-channel attribution. Ingest is idempotent by a content fingerprint and replaces a manual as a unit,
sweeping stale records only after verification. See chapter 5.

**How does a question translate into which edges or direction to pull? Is NLP or an LLM needed?**
It does not choose edges — it chooses **start nodes** and then takes every edge one hop around them, in
both directions, from every allowed manual. Start nodes come from exact string matching of the question's
n-grams against the graph's labels and aliases (after the same normalisation used at indexing), from
identifier regexes, from partial label matches anchored on a resolved word, and from the node ids carried by
the best search hits. The question's wording then only *orders* the result through a five-row table of
regular expressions (responsibility words → RESPONSIBLE_FOR/ESCALATES_TO and Person first; order words →
PRECEDES and StartupStep first; impact words → DEPENDS_ON/IMPACT_OF and ImpactStatement first; ticket words →
PARTNER_TICKET and Incident first; how-to words → GOVERNED_BY and Procedure first), with negative facts
before positive ones. No part-of-speech tagging, no classifier, no language model is involved. This works
because the graph is sparse (about 0.5 edges per node) and all competency questions are one- or two-hop
patterns. Should neighbourhoods grow noisy, the documented next step is a small model call that returns a
query plan constrained to the ontology's relation names — the traversal would still be deterministic. See
6.2 and 6.7.

---

## 10. Appendix

### 10.1 Parameters that shape the result

**Ingestion (docling-graph service, `DGS__*`)**

| Parameter | Default | Effect |
|---|---|---|
| `docling.images_scale` | 3.0 | figure resolution for the vision model (~216 dpi) |
| `docling.table_mode` | accurate | TableFormer model variant |
| `chunking.tokenizer` | `intfloat/multilingual-e5-large` | token counting with the embedding model's vocabulary |
| `chunking.max_tokens` | 512 | hard chunk cap = embedding model limit; budget = 512 − prefix − 2 |
| `chunking.merge_peers` | true | merge text neighbours under one heading |
| `chunking.strip_line_prefixes` | `["TESTDOKUMENT ·"]` | page header removal |
| `chunking.repeated_furniture_min_pages` / `furniture_band` | 3 / 0.12 | running header/footer detector |
| `embedding.model` / `dim` / `text_prefix` / `batch_size` | bge-m3 (e5 as target) / 1024 / "" ("passage: " for e5) / 64 | |
| `vlm.model` / `max_tokens` / `concurrency` | gemini-dev / 2000 / 2 | figure description |
| `llm.model` / `temperature` / `structured_output` | gemini-dev / 0.0 / true | extraction |
| `llm.context_limit` / `max_output_tokens` | 128 000 / 8 192 | batch sizing and per-call output |
| `llm.parallel_workers` / `max_retries` / `timeout_s` | 2 / 2 / 300 | |
| `graph.extraction_contract` / `dense_dedupe` / `provenance` / `chunk_max_tokens` | dense / off / standard / 512 | docling-graph's internal chunker for extraction batches |

**Index (`osi`, `OSI__*`)**

| Parameter | Default |
|---|---|
| `index.prefix` | `bhb` |
| `index.shards` / `replicas` | 1 / 0 |
| `index.knn_m` / `knn_ef_construction`; engine / space | 16 / 128; lucene hnsw / cosinesimil |
| `index.rrf_pipeline` / `rrf_rank_constant` | true / 60 |
| analyzer `de_text` | standard, lowercase, German stop words, german_normalization, light_german |
| normalizer `lc` | lowercase, trim (on `node_labels`, `nodes.label.keyword`, `nodes.aliases.keyword`) |
| `ingest.lock_ttl_s` / `history_keep` | 3600 / 20 |

**Retrieval (`RAG__RETRIEVAL__*`, `RAG__GUARDRAIL__*`, `RAG__LLM__*`)**

| Parameter | Default | Effect |
|---|---|---|
| `k_per_channel` / `final_k` | 20 / 10 | hits per channel; chunks kept after fusion |
| `rrf_rank_constant` | 60 | `1/(60+rank)` |
| `graph_seed_hits` / `graph_seed_per_channel` | 5 / 2 | seeds: fused top 5 plus top 2 per channel |
| `graph_max_start_nodes` | 30 | one table chunk can carry 25+ node ids |
| `graph_max_facts` / `max_facts_in_prompt` | 40 / 25 | |
| `graph_max_chunks` / `graph_min_sources` | 15 / 2 | provenance chunks fetched; guaranteed slots |
| `graph_max_entities` | 15 | entity cards |
| `label_max_ngram` / `label_min_chars` | 4 / 3 | label matching |
| `partial_label_min_tokens` / `partial_label_max_nodes` | 2 / 8 | anchored partial matches |
| `context_token_budget` | 6 000 (≈ 7 000 real tokens at 2.6 chars/token) | rendered context |
| guardrail `min_agreeing_channels` / `top_n` | 2 / 3 | |
| llm `temperature` / `max_tokens` / `context_limit_tokens` | 0.0 / 4 000 / 32 000 | reasoning models spend ~1 300 tokens thinking first |
| `history_turns` | 3 (server: 10) | user/assistant pairs in the prompt (REQ-001) |

### 10.2 Glossary

| Term | Meaning |
|---|---|
| Betriebshandbuch (BHB) | operations manual; one per IT system |
| Verfahren / Basisdienst / Plattformdienst | application system / basic service / platform service (System kinds) |
| Nabendienst | hub service (CaaS platform, central security services) |
| Mandant | tenant (of the platform) |
| Vorgang, Partnervorgang | ticket; the counterpart ticket in another team's system |
| Störungsbild | recurring failure picture |
| Auswirkungsmatrix / Auswirkungsaussage | impact matrix / reified impact statement (`ImpactStatement`) |
| Kaltstart, Wiederanlauf | cold start, restart order (`StartupStep`, `PRECEDES`) |
| SOP / Arbeitsanweisung | standard operating procedure (`Procedure`) |
| Portmatrix | firewall rule table (`FirewallRule`) |
| Versiegelt / Entsiegeln (Unseal) | sealed state of the secret store / unsealing with key shares |
| Kante / Knoten | edge / node |
| Quelle, Fakt, Entität | the three sections of the rendered context: source chunk, graph edge, entity card |
| "Dazu steht nichts in den Handbüchern." | the guardrail sentence: the manuals say nothing about this |

### 10.3 Where to read the code

| Topic | File |
|---|---|
| ontology | `user-manual-books/handbuch_daten/Ontologie/ontology.yaml`, `README-Testdaten.md` |
| ontology → extraction schema | `docling-graph/src/docling_graph_service/ontology.py` |
| chunking | `docling-graph/src/docling_graph_service/chunking.py` |
| extraction run and materialisation | `docling-graph/src/docling_graph_service/graph.py`, `normalize.py` |
| figures, embeddings | `docling-graph/src/docling_graph_service/describe.py`, `embed.py` |
| design notes for retrieval | `docling-graph/graph-retrieval-patterns.md` |
| index mappings and analyzers | `opensearch-index/src/opensearch_index/mappings.py` |
| transform, identifiers, reverse index | `opensearch-index/src/opensearch_index/transform.py` |
| identity, edge ids, run fingerprint | `opensearch-index/src/opensearch_index/identity.py` |
| ingest state machine | `opensearch-index/src/opensearch_index/indexer.py` |
| question analysis | `retrieval/src/rag_retrieval/query.py` |
| in-memory graph, expansion | `retrieval/src/rag_retrieval/graph.py` |
| facts, cue table, entity cards | `retrieval/src/rag_retrieval/facts.py` |
| channel bodies, fusion, guardrail | `retrieval/src/rag_retrieval/search.py`, `fusion.py`, `guardrail.py` |
| the orchestration | `retrieval/src/rag_retrieval/retriever.py` |
| prompt and context rendering | `retrieval/src/rag_retrieval/prompt.py` |
| results of the ground-truth questions | `retrieval/REPORT.md`, `retrieval/out/questions/` |
| architecture decisions | `SPEC.md`, `docs/adr/0001` … `0014` |
| users, chat | `users/README.md`, `chat-system/README.md`, `chat-system/REPORT.md` |

*End of report.*
