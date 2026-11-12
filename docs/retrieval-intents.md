# Retrieval intents and edge activation

**Purpose.** This file is the registry that decides, for a given question, which graph edges
get traversed in slow mode. It exists so that adding a new question type is an **entry in this
table, not a code change**, and so you can work backwards from "here is a new kind of question"
to "here is what the graph must supply".

**Source.** Intents are derived from `betriebshandbuch/v1/ontology.yaml → competency_questions`,
which are the ontology's own acceptance criteria. Relation names below are the exact 32 from
`ontology.yaml → relations`.

**Reading the columns.** `Edges` is an allowlist: only these relations are traversed for this
intent. `←` means the edge is traversed in reverse (`RESPONSIBLE_FOR` points Person → System,
so finding the person for a system walks it backwards). `Depth` is hops from the seed nodes
returned by the hybrid query.

---

## 1. The intents

### INT-CERT — certificate renewal
Maps to competency question **Q1**.

| | |
|---|---|
| **German triggers** | Zertifikat, TLS, Zertifikatserneuerung, erneuern, ablaufen, abgelaufen, keytool, cert-manager, ACME, Truststore, Keystore, CA-Wechsel, Issuing CA |
| **Edges** | `SECURED_BY`, `ISSUED_BY`, `GOVERNED_BY` |
| **Depth** | 1 |
| **Key fields** | `Certificate.renewal_mode`, `Procedure.steps`, `Procedure.commands`, `Certificate.alert_thresholds` |
| **Answer shape** | The procedure *for the system asked about*, naming the renewal mode explicitly (vollautomatisch / gemischt / manuell), with the SOP cited. If no system is named, present all three paths side by side and say they differ. |
| **Why it needs the graph** | The renewal mode lives with the system, the procedure lives in a SOP, and the central request process lives in a third document (`BHB-PLT-0007`, Kapitel 5.4). |

### INT-IMPACT — restart or maintenance, who is affected
Maps to **Q2**.

| | |
|---|---|
| **German triggers** | neu starten, Neustart, restart, entleeren, drainen, was hängt daran, Auswirkung, betrifft, Wartung, Knotenwartung, Wartungsfenster, PodDisruptionBudget |
| **Edges** | `HAS_COMPONENT`, `GOVERNED_BY`, `IMPACT_OF`, `DEPENDS_ON` ←, `AFFECTS` ←, `HAS_MAINTENANCE_WINDOW` |
| **Depth** | 1, **2 for `DEPENDS_ON`** |
| **Key fields** | `Component.restart_note`, `ImpactStatement.severity`, `ImpactStatement.symptom`, `DEPENDS_ON.failure_effect` |
| **Answer shape** | What breaks, how badly, what mitigates it, and any precedent incident by ticket number. |
| **Why it needs the graph** | The impact matrix is in the platform's manual, the component is in the consumer's manual, and the precedent is a third pair of tickets. |

### INT-CONTACT — responsibility and escalation
Maps to **Q3**.

| | |
|---|---|
| **German triggers** | Ansprechpartner, wer ist zuständig, Zuständigkeit, Verantwortlicher, eskalieren, Eskalation, Eskalationsweg, Durchwahl, Hotline, Servicedesk, Rufnummer, Postfach |
| **Edges** | `RESPONSIBLE_FOR` ←, `ESCALATES_TO`, `OPERATED_BY`, `CONTRACT_COVERS` ← |
| **Depth** | 1, **2 along `ESCALATES_TO`** to give the full chain |
| **Key fields** | `Person.phone_ext`, `Person.role_title`, `OrgUnit.mailbox`, `OrgUnit.jira_project`, `ESCALATES_TO.level` |
| **Answer shape** | Named person, role, extension, mailbox, Jira project, chat channel, then the escalation chain in order. |
| **Why it needs the graph** | Six people appear in four or five documents each; the escalation chain crosses org units. |

### INT-DEPLOY — where it runs, ports, zones
Maps to **Q4**.

| | |
|---|---|
| **German triggers** | Server, Serverinstanz, Host, Hostname, Port, Portmatrix, läuft auf, Instanz, Netzzone, Zone, DMZ, Firewall, Firewallregel, IP, IP-Adresse, Umgebung, Produktion, Test, Abnahme |
| **Edges** | `HAS_COMPONENT`, `RUNS_ON`, `LOCATED_IN`, `ALLOWS_TRAFFIC`, `USES_DATASTORE` |
| **Depth** | 1 |
| **Key fields** | `Host.hostname`, `Host.ip`, `FirewallRule.port`, `FirewallRule.protocol` |
| **Answer shape** | Table-shaped. Host, environment, zone, port, protocol. Cite the Portmatrix or Instanzen table by caption. |
| **Note** | This intent is the most likely to be answered correctly in **fast** mode too, because the source is a single table. Useful as a control case in the A/B. |

### INT-OUTAGE — failure of a central service
Maps to **Q5**. **This is the differentiating intent.**

| | |
|---|---|
| **German triggers** | Ausfall, ausfällt, fällt aus, versiegelt, sealed, nicht verfügbar, Störung, betroffen, nicht betroffen, unberührt, was passiert wenn |
| **Edges** | `IMPACT_OF`, `DEPENDS_ON` ←, `AFFECTS` ←, `TENANT_OF` ←, `AUTHENTICATES_VIA` ←, `READS_SECRET` ← |
| **Depth** | 2 |
| **Key fields** | `ImpactStatement.severity`, `ImpactStatement.mitigation` |
| **Answer shape** | Per-consumer impact, **including consumers that are explicitly unaffected, with the documented reason**. |
| **Mandatory check** | `negative_check` from Q5: at least one answer must carry "keine Auswirkung" with a justification. Negative-polarity edges must be surfaced, not filtered out. A retrieval result for this intent that contains no negative edge is a **bug**, not an empty result. |
| **Why it needs the graph** | "Warum ist VPP nicht betroffen" is answerable only from the negative assertions, and ordinary RAG answers it wrongly and confidently. |

### INT-STARTUP — cold start ordering
Maps to **Q6**.

| | |
|---|---|
| **German triggers** | Kaltstart, Kaltstartreihenfolge, Reihenfolge, Totalausfall, anfahren, hochfahren, Wiederanlauf, Startreihenfolge, Voraussetzung |
| **Edges** | `PRECEDES` (traversed **topologically**, not depth-limited), `STEP_RESPONSIBILITY` |
| **Depth** | unbounded along `PRECEDES` |
| **Key fields** | `StartupStep.order`, `StartupStep.duration`, `StartupStep.precondition` |
| **Answer shape** | Ordered list, one line per step, with responsible party, duration and precondition. |
| **Why it needs the graph** | The chain has 11 steps and spans all five documents; `BHB-PLT-0001` Tabelle 13 cross-read against `SOP-ZSD-06`. |

### INT-PRECEDENT — has this happened before
Maps to **Q7**. `cross_document: true`.

| | |
|---|---|
| **German triggers** | schon einmal, früher, bereits, Vorfall, Störungsfall, Ticket, Vorgang, bekannt, gelöst, Präzedenz, Root Cause, Ursache — **plus any ticket-ID regex hit** |
| **Edges** | `INSTANCE_OF_FAILURE`, `PARTNER_TICKET`, `AFFECTS`, `RESULTED_IN_CHANGE`, `DETECTED_BY` |
| **Depth** | 2 — `PARTNER_TICKET` is what crosses documents |
| **Key fields** | `Incident.root_cause`, `Incident.resolution`, `Incident.process_change` |
| **Answer shape** | The incident, its counterpart ticket in the other document, both perspectives, and any resulting process change. |
| **Note** | When the question contains a ticket ID, the `identifiers` clause alone will find the seed with perfect precision; the graph supplies the counterpart. This is the cleanest demonstration of the fast/slow difference. |

### INT-GLOSSARY — terminology
**Not derived from a competency question.** Added because `plan.md` states that understanding
the vocabulary is critical, and the ontology defines `Term` and `DEFINES_TERM` but no
competency question exercises them. Flagged as a gap in the ontology's acceptance criteria:
consider adding a Q8 upstream.

| | |
|---|---|
| **German triggers** | was ist, was bedeutet, wofür steht, Abkürzung, Definition, Glossar, Begriff |
| **Edges** | `DEFINES_TERM`, `MENTIONED_IN` |
| **Depth** | 1 |
| **Answer shape** | Definition, the document that defines it, and where else it is used. |

---

## 2. Fallback

If no intent matches, run **fast mode only** and log the question with its rewritten form.

This is a deliberate graceful degradation, not an error path: a hybrid-only answer is
shallower but still grounded and still cited. Never fail a question because the router did
not recognise it.

`RELATED_DOCUMENT`, `DOCUMENTS`, `PUBLISHES_EVENT`, `CONSUMES_EVENT`, `MONITORS` and
`ISSUED_BY` are reachable through the intents above or through fast mode; they have no intent
of their own yet. That is expected — the registry is not required to cover all 32 relations.

---

## 3. How to add an intent

1. Write the question in German, as a user would actually type it.
2. Run it. If fast mode already answers it well, **stop** — it does not need an intent.
3. If it needs graph facts, name the traversal: which relations, which direction, what depth.
4. Add a row here with triggers, edges, depth, key fields and answer shape.
5. Add one golden-set item for it in `eval/`.
6. If the traversal cannot be expressed with the existing 32 relations, the **ontology** is
   missing something. Change `ontology.yaml` first, regenerate, then come back.

Step 6 is the important one: this registry is a downstream artifact. A question that no
traversal can answer is evidence about the ontology, not about the router.

---

## 4. The backlog loop

Every fallback hit is logged. The log **is** the backlog:

- A question type appearing repeatedly in the fallback log is a candidate intent.
- A question type appearing repeatedly *and* unanswerable in fast mode is a candidate
  ontology change.
- A question answered by fast mode as well as slow mode is evidence the graph adds nothing
  *for that intent*, which is a legitimate and reportable finding.

Review the fallback log before each demo. It is the cheapest source of truth about what users
actually ask.
