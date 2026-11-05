---
marp: true
title: Betriebshandbuch-Assistent
description: RAG mit Wissensgraph über IT-Betriebshandbücher
paginate: true
---

<!--
Folienquelle. Eine Folie je "---"-Abschnitt, Überschrift = Folientitel.
Diagramme sind ASCII-Blöcke (in jedem Slide-Tool als Codeblock darstellbar, Monospace).
Stand: 2026-09-11. Zahlen mit "gemessen" stammen aus Läufen auf der Entwicklungsmaschine,
Zahlen mit "Richtwert" sind Auslegungsschätzungen.
-->

# Betriebshandbuch-Assistent

### Frage in natürlicher Sprache → belegte Antwort aus den Betriebshandbüchern

RAG mit ontologiegestütztem Wissensgraph
Prototyp, lauffähig · 5 Module · 3 Handbücher indiziert

---

## Agenda

1. Problem und Projektidee
2. Rahmenbedingungen: Datenlage und Übertragbarkeit
3. Architektur: Module und zentraler Stack
4. Demo
5. Kernkonzepte: Ontologie · Graph · RAG-Graph · Hybride Suche
6. Kern-Retrieval: warum mehr als einfaches RAG
7. Enterprise-Einführung: Hardware, Pods, Abhängigkeiten

---

## 1 · Das Problem

Betriebswissen liegt in **Betriebshandbüchern** (PDF, ein Handbuch je System).
Die Fragen des Betriebs sind operativ und präzise:

- *Was passiert, wenn Vault versiegelt ist?*
- *Wer ist für IAM/Keycloak zuständig und wie eskaliere ich?*
- *Was war bei ZSDSUP-0247?*
- *In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?*

Zusätzlich: rund **70 % der nutzbaren Fakten stehen in Tabellen**,
und jede Aussage muss belegt sein: `[BHB-PLT-0007 S. 19]`.

---

## 1 · Warum einfaches RAG hier scheitert

| Eigenschaft der Frage | Problem für reine Vektorsuche |
|---|---|
| **Exakte Bezeichner** (`ZSDSUP-0247`, `SOP-ZSD-05`, `FW-CAAS-004`, `kv/dd/prod`) | Analyzer zerlegt `CAASUP-0342` in `caasup` + `0342` → trifft jedes CaaS-Ticket; Embeddings verwischen Bezeichner systembedingt |
| **Dokumentübergreifende Fakten** | Die Antwort steht in zwei Handbüchern (Auswirkungsmatrix hier, Abhängigkeitskette dort). **Kein einzelner Chunk enthält sie.** |
| **Verneinungen / bewusste Nicht-Kopplungen** | „VPP ist *nicht* betroffen, weil die Keystores lokal liegen“ — Ähnlichkeitssuche findet Chunks, die beide nennen, das Modell erfindet die Kopplung |

---

## 1 · Die Idee: Ontologie im Zentrum

```
                 ontology.yaml   26 Klassen · 32 Relationen · Identitätsregeln · Negationspolitik
                        │
      ┌─────────────────┼──────────────────────────┐
      ▼                 ▼                          ▼
 Extraktionsschema   Identitätsschlüssel    Bezeichner-Regexe
 (was das LLM        (wann sind zwei         (was ein exakter
  extrahieren darf)   Nennungen dasselbe)     Treffer ist)
      │                 │                          │
      ▼                 ▼                          ▼
 PDF ─► Chunks     typisierter Graph        Chunk-Felder
 (docling)         Knoten + Kanten          identifiers[]
                   + Provenienz             node_labels[]
      └─────────────────┴──────────┬───────────────┘
                                   ▼
                    OpenSearch (Chunks · Knoten · Graph)
                                   ▼
        Frage ─► Analyse ─► 4 Suchkanäle + 1-Hop-Graph ─► RRF ─► Kontext ─► LLM-Antwort
                 (Regex + Stringmatch, kein Modell)                          (mit Quellen)
```

---

## 1 · Vier Grundentscheidungen

1. **Der Graph ist typisiert und trägt Provenienz.**
   Jeder Knoten, jede Kante kennt Dokument, Seite, Chunk-IDs und das wörtliche Zitat → ein Graph-Fakt ist genauso zitierbar wie eine Textstelle.
2. **Negation ist Datum, nicht fehlende Kante.**
   „hängt *nicht* ab von“ wird `polarity: negative`; Auswirkung „keine“ wird ein Knoten mit `severity: keine`.
3. **Entitätsauflösung ist deterministisch.**
   Welche Nennungen dieselbe Entität sind, entscheidet eine Regel in der Ontologie — kein Modell. Zwei Handbücher erzeugen dieselbe Knoten-ID ohne Merge-Schritt.
4. **Im Retrieval läuft kein Sprachmodell.**
   Regex, Stringmatch, Embedding (Encoder), Rangfusion. Das LLM schreibt nur die Antwort.

---

## 2 · Rahmenbedingungen: die Daten

Der Korpus ist **fiktiv**, aber bewusst nah am realen Fall gebaut
(jede Seite trägt: *TESTDOKUMENT · KEINE ECHTEN BETRIEBSDATEN*).

| Dokument | Handbuch | Seiten | Rolle | Realbezug |
|---|---|---|---|---|
| `BHB-PLT-0007` | ZSD — Zentrale Sicherheitsdienste (IAM, PKI, Vault) | 29 | **Hub** | Sicherheitszentrale |
| `BHB-PLT-0001` | CaaS — Container-Plattform als Dienst | 27 | **Hub** | Container-Plattform |
| `BHB-PLT-0042` | Event-System 2.0 | 49 | Anwendung | Event-/Nachrichtenverteilung |
| `BHB-VRF-0118` | Mars Dokumentendienste | 50 | Anwendung | Dokumenteneingang, OCR |
| `BHB-VRF-0207` | VPP — Verfahrensportal | 50 | Anwendung | klassische Web-Anwendung |

**Drei davon sind verarbeitet und indiziert** (ZSD, CaaS, Event-System).

---

## 2 · Warum dieser Korpus aussagekräftig ist

Die Schwierigkeiten sind **absichtlich eingebaut und dokumentiert** — damit messbar:

- **Zwei Hubs.** Jede Anwendung verweist auf Plattform und Sicherheitsdienste.
- **Zwei Join-Tabellen.** „Wer nutzt welchen Client/Pfad“ und „Auswirkung je Mandant“ — der direkte Weg von *„ich starte X neu“* zu *„das trifft Y und Z“*.
- **Dokumentierte Ringabhängigkeit.** Vault läuft auf der Plattform, die Plattform bezieht Zertifikate von der PKI, die PKI legt Material in Vault — und beide Hubs erklären, wie der Ring gebrochen wird.
- **Bewusste Nicht-Kopplungen.** VPP ist kein Mandant, nutzt das Event-System nicht, ist von versiegeltem Vault nicht betroffen.
- **Partnervorgänge.** Sieben Vorfälle stehen in zwei bis drei Handbüchern, je mit der Ticketnummer der Gegenseite.
- **Eine Zahl, zwei Wahrheiten.** Derselbe Vorfall: 48 Minuten laut Plattform, 38 laut Sicherheit — beide müssen erhalten bleiben.

---

## 2 · Übertragung auf den Realbetrieb

| Prototyp | Zielbild |
|---|---|
| 5 Handbücher à 27–50 Seiten | **30–40 Handbücher à 5–10 Seiten** |
| ~105 Seiten indiziert | ~300 Seiten |
| 401 Chunks, 540 Graphknoten | ~1 200 Chunks, ~4 000 Graphknoten (Hochrechnung) |
| Ontologie auf den Testkorpus zugeschnitten | Ontologie an die **reale Handbuchvorlage** anpassen |

**Konsequenzen**

- Mehr, aber kürzere Dokumente → Datenmenge bleibt unkritisch (< 100 MB Index), der Graph wächst linear.
- Der Hub-Effekt wird **stärker**, nicht schwächer: mehr Anwendungen zeigen auf dieselben zentralen Dienste.
- Die Ontologie ist der Anpassungsaufwand — **fachlich, nicht technisch** (YAML, keine Codeänderung).
- Die Qualität hängt an der Disziplin der Handbücher: Tabellen, konsistente Bezeichner, gepflegte Kontakte.
  Ein Handbuch, aus dem wenig extrahierbar ist, ist ein **unvollständiges Handbuch** — die Ontologie ist normativ und damit auch ein Qualitätsmaßstab.

---

## 3 · Architektur im Gesamtbild

```
            Betriebshandbücher (PDF)
                     │
        ┌────────────▼─────────────┐  Modul 1
        │      docling-graph       │  PDF → Markdown · Chunks+Vektoren · Wissensgraph
        │    FastAPI, CPU-lastig   │  ruft: VLM (Bilder) · Embedding · LLM (Extraktion)
        └────────────┬─────────────┘
                     │ response.json
        ┌────────────▼─────────────┐  Modul 2
        │        osi (Indexer)     │  idempotent, doc_id = Ersetzungseinheit
        └────────────┬─────────────┘
        ┌────────────▼──────────────────────┐
        │  OpenSearch  (k-NN-Plugin)        │  bhb-chunks · bhb-nodes
        │  Chunks+Vektoren · Knoten · Graph │  bhb-documents · bhb-manifest
        └────────────┬──────────────────────┘
        ┌────────────▼─────────────┐  Modul 3       ┌───────────────┐
        │      rag_retrieval       │◄───────────────┤  Embedding    │
        │  4 Kanäle + Graph + RRF  │                │  e5-large     │
        └────────────┬─────────────┘                └───────────────┘
        ┌────────────▼─────────────┐  Modul 5       ┌───────────────┐
        │       chat-system        │───────────────►│  LLM          │
        │  Streamlit + DB + CLI    │  Prompt/Stream │  OpenAI-komp. │
        └────────────┬─────────────┘                └───────────────┘
                     │  Modul 4: rag_users — Identität, Limits, erlaubte Handbücher
        ┌────────────▼─────────────┐
        │     Ingress / IAM        │  X-Forwarded-User / -Email / -Groups
        └──────────────────────────┘
```

---

## 3 · Die fünf Module

| # | Modul | Aufgabe | Läuft wann |
|---|---|---|---|
| 1 | `docling-graph` | PDF → Markdown, Chunks mit Vektoren, ontologiegestützter Graph. Ein Aufruf: `POST /v1/process` | **nur beim Einlesen** neuer Handbücher |
| 2 | `opensearch-index` | OpenSearch-Knoten + `osi`-CLI: idempotenter Ingest in vier Indizes, Manifest und Sperre je Dokument | Ingest + Dauerbetrieb (Suche) |
| 3 | `retrieval` | Frage → vier Suchkanäle + Graph-Expansion → fusionierter, zitierter Kontext + Prompt | je Frage (Bibliothek im Chat-Prozess) |
| 4 | `users` | Identität aus Ingress-Headern, Policy: Nachrichten/Tag, Runden/Gespräch, **erlaubte Handbücher** | je Frage (Bibliothek) |
| 5 | `chat-system` | Streamlit-Oberfläche + `ChatService`, Gesprächsdatenbank, Streaming, Zitate, Diagnose; headless CLI | Dauerbetrieb |

Module 3 und 4 sind **Bibliotheken** — sie laufen im Prozess des Chats, nicht als eigene Dienste.

---

## 3 · Was die Anwendung heute kann

**Chat (Streamlit)**

- Antwort **im Stream**, darunter der Block **Quellen**: Dokument, Seitenbereich, Überschrift, Ausschnitt
- Umschalter **schnell / Graph-Modus** — dieselbe Frage einmal mit und einmal ohne Graph
- **Handbuch-Filter** (nur das, was die Gruppe lesen darf)
- **Diagnose** auf Knopfdruck: umgeschriebene Frage, Kanaltabelle mit Rängen, Zeiten, Fakten (Verneinungen rot), Entitäten
- Gespräche sind **fortsetzbar**; Folgefragen werden automatisch zu eigenständigen Fragen umgeschrieben
- Limits sichtbar: Nachrichten am Tag, Runden im Gespräch

**Ohne Oberfläche**

- `chat-ask` — dieselbe Antwortrunde headless (Skripte, Tests, Massenfragen), `--json`
- `rag-retrieve` — Retrieval allein inspizieren; `osi` — indizieren, prüfen, entfernen
- `chat-doctor` — Selbsttest: Datenbank, indizierte Handbücher, Modellprobe, aufgelöster Benutzer, Promptbudget

---

## 3 · Zentraler Stack: was das System braucht

| Baustein | Rolle | Beschaffung |
|---|---|---|
| **OpenSearch mit k-NN** | einziger Speicher: Chunks, Vektoren, Knoten, Graph-Blob, Manifest | zentrale Enterprise-Instanz, eigener Index-Präfix `bhb-*` |
| **Embedding-Endpunkt** | Vektor je Chunk (Ingest) und je Frage (200–270 ms) | OpenAI-kompatibel (TEI/vLLM) |
| **LLM-Endpunkt** | schreibt die Antwort; extrahiert den Graph beim Ingest | OpenAI-kompatibel, GPU |
| **IAM am Ingress** | Identität + Gruppen als Header | zentrale Komponente (PGA) |
| **Datenbank** | Gespräche, Nachrichten, Tageszähler | SQLite (Standard) oder Postgres |
| **Ontologie-Datei** | Extraktionsschema, Identität, Bezeichner-Regexe, deutsche Relationslabels | im Repository, als Volume eingebunden |

Alle Modellzugriffe laufen über **OpenAI-kompatible Endpunkte** — Tausch des Anbieters ist Konfiguration, kein Code.

---

## 3 · Datenfluss Ingest (einmalig je Handbuch)

```
PDF ─► 1 Parsen (docling)  ─► 2 Aufräumen ─► 3 Bilder (VLM) ─► 4 Markdown + Chunks ─► 5 Embeddings
                                                                                            │
     ┌──────────────────────────────────────────────────────────────────────────────────────┘
     ▼
 6 Graph-Extraktion (LLM, an das Ontologieschema gebunden) ─► 7 Materialisieren
                                                              (normalisieren · auflösen ·
                                                               validieren · Provenienz)
                                                                       │
                                                                       ▼
                                             response.json  ─►  osi ingest  ─► OpenSearch
```

- Nur das Parsen ist ein harter Fehler. Bilder, Embeddings, Graph setzen je ein `degraded`-Flag → ein Handbuch ohne Graph ist trotzdem durchsuchbar.
- Ergebnisse sind **inhaltsadressiert zwischengespeichert** (Dateihash + Optionen + Schemahash + Modellnamen).
- **Gemessen je Handbuch (27–49 Seiten):** Konvertieren 6–15 min · Bilder ~15 s · Chunking ~2 s · Embedding 1,5–2,5 min · Graph 4–6 min → **13–21 min**.

---

## 3 · Datenfluss Frage → Antwort

```
Frage ─► 1 Analyse ─► 2 Embedding ─► 3 msearch (4 Kanäle) ─► 4 RRF ─► 5 Guardrail ─► 6 Graph ─► 7 Gruppen ─► 8 Prompt
          │                            knn · bm25 ·              │         │           1 Hop      + Zitate
          │ Bezeichner (Regex)         identifier · label        │         │           Fakten · Entitätskarten
          └ Labels/Aliase als n-Gramme                           │         │           Belegstellen ─► 5. Liste
                                                                 │         └► schwache Evidenz? → Antwort ohne Modellaufruf
                                                                 └► Fusion nach Rang, nicht nach Score
```

**Zwei Modi:** *schnell* endet nach Schritt 5 (vier Suchkanäle), *Graph* ergänzt den Graphkanal —
im Chat umschaltbar, damit der Beitrag des Graphen sichtbar wird.

**Gemessen:** Retrieval 230–330 ms (davon 200–270 ms Embedding, OpenSearch < 10 ms, Graph-Expansion 8–80 ms).
Gesamte Antwortrunde inkl. Modell: ~13 s.

---

## 4 · Demo

> *Platzhalter — Fragetypen werden hier live gezeigt.*

Vorgesehene Kategorien:

- Entitätsfrage mit Wirkungskette
- Bezeichnerfrage (Ticket, SOP, Firewall-Regel)
- Verneinung / „wen trifft es *nicht*“
- Zuständigkeit und Eskalation
- Frage außerhalb des Korpus (Guardrail)
- Technik-Assistent: Log analysieren, Skript erzeugen, Befehle anpassen

---

## 5 · Ontologie (1/3): Was sie ist

`ontology.yaml` — **873 Zeilen, eine einzige Quelle der Wahrheit** für drei Dinge:

1. das **Pydantic-Modell** (generiert),
2. das **Extraktionsschema**, an das das LLM gebunden wird,
3. das **Kantenvokabular** des Graphen inklusive Polarität und Provenienz (deutsche Labels für die Anzeige).

| Abschnitt | Anzahl | Inhalt |
|---|---|---|
| `datatypes` | 27 | Basistypen mit Regex (`doc_id`, `ticket_id`, `hostname`, `vault_path`, `port`, …) |
| `enums` | 16 | kontrollierte Vokabulare (`Polarity`, `ImpactSeverity`, `CertRenewalMode`, …) |
| `mixins` | 3 | `Provenance`, `NodeBase`, `EdgeBase` — auf **jedem** Knoten und jeder Kante |
| `classes` | 26 | Entitätstypen mit Identitätsregel, deutschen Stichwörtern, Tabellenhinweisen |
| `relations` | 32 | typisierte Kanten mit Domain/Range, deutschem Label, Eigenschaften |
| `competency_questions` | 7 | die Fragen, die der Graph beantworten **muss** — die Abnahmekriterien |

Sie ist **normativ**, nicht beschreibend: sie sagt, was ein Handbuch enthalten *soll*.

---

## 5 · Ontologie (2/3): Klassen, Identität, Relationen

**26 Klassen in fünf Schichten** — mit je einer Identitätsregel:

| Schicht | Beispiele | Identität |
|---|---|---|
| Dokument & Organisation | `Document`, `OrgUnit`, `Person` | `doc_id` · Label · Label ohne Titel |
| System & Architektur | `System`, `Component`, `Host`, `NetworkZone`, `FirewallRule` | Label · Hostname · `fw_id` |
| Identität & Geheimnisse | `IdentityClient`, `Certificate`, `CertificateAuthority`, `SecretStorePath` | Label · `vault_path` |
| Betriebsprozesse | `Procedure`, `MaintenanceWindow`, `StartupStep` | `sop_id` · Reihenfolge |
| Störung & Wirkung | `Incident`, `FailureMode`, **`ImpactStatement`**, `Alert`, `Term` | `ticket_id` · Ereignis+System |

- **Drei Klassen sind systemgebunden** (`Component`, `MaintenanceWindow`, `FailureMode`): ein „Dispatcher“ hier und dort darf nicht verschmelzen.
- **`ImpactStatement` verdinglicht eine Tabellenzelle**: „Ereignis X bei A wirkt auf B so“ wird ein Knoten mit eigenen Attributen — auch wenn keine Kante hinführt.
- **`DEPENDS_ON`** ist die wichtigste Relation: `dependency_kind`, `criticality`, `failure_effect`, `bridging` machen aus „A hängt von B ab“ eine Betriebsaussage.

---

## 5 · Ontologie (3/3): Negation und Abnahme

**Negation ist an vier Stellen verankert:**

1. `polarity` auf **jeder** Kante (positiv | negativ)
2. 7 `negative_assertions` — Aussagen, die der Korpus bewusst verneint, je mit Belegdokument und Grund
3. Deutsche Auslöserwörter: *kein, keine, nicht, ohne, unberührt, nicht angebunden, entfällt* — der Grund landet im `qualifier`
4. **Regel:** eine negative Kante darf eine positive gleichen Typs **nie überschreiben** — Konflikte werden gemeldet, nicht stillschweigend aufgelöst

**Sieben Kompetenzfragen** definieren die Abnahme, z. B.:

| Frage | Pfad im Graphen |
|---|---|
| Q2 Komponente neu starten — wen trifft es? | `Component ← HAS_COMPONENT — System`; `ImpactStatement`; `← DEPENDS_ON` |
| Q5 Was passiert bei Ausfall von Z? | alle `ImpactStatement` — **mindestens eine Antwort muss „keine Auswirkung“ mit Grund sein** |
| Q6 Reihenfolge nach Totalausfall? | `StartupStep —PRECEDES→ …` topologisch |

Alle sieben sind **Ein- bis Zwei-Hop-Muster** — das rechtfertigt die spätere Bauentscheidung: einen Hop expandieren statt einen Intent-Klassifikator bauen.

---

## 5 · Graph (1/2): Wie er entsteht

Die Ontologie wird zur **Laufzeit in ein JSON-Schema kompiliert**, das das Modell ausfüllen muss —
kein Freitextprompt „finde Entitäten und Relationen“.

```
Chunks ─► LLM (an Schema gebunden) ─► rohe Knoten/Kanten
                                            │
                       ┌────────────────────┴───────────────────┐
                       ▼   deterministische Nachbearbeitung     ▼
          normalisieren (Datum, Dezimal,      auflösen (Identitätsregel →
           Bezeichner unangetastet)            stabile Knoten-ID, Aliase)
                       │                                        │
                       ▼                                        ▼
            validieren (Typen, Regex,              Provenienz anhängen
             Domain/Range, Konflikte)               (Dokument, Seite, Tabelle,
                       │                             Zitat, Chunk-IDs)
                       └──────────────► Graph {nodes, edges, meta}
```

**Der Zufall ist eingezäunt:** das Modell darf nur Instanzen der Ontologie erzeugen, das Ergebnis wird
deterministisch validiert, normalisiert und ist inhaltsadressiert.

---

## 5 · Graph (2/2): Was herauskommt

**Gemessen über drei Handbücher:**

| Handbuch | Seiten | Tabellen | Chunks | Knoten | Kanten |
|---|---|---|---|---|---|
| ZSD `BHB-PLT-0007` | 29 | 22 | 112 | 250 | 154 |
| CaaS `BHB-PLT-0001` | 27 | 24 | 120 | 210 | 127 |
| Event-System `BHB-PLT-0042` | 49 | 50 | 169 | 214 | 79 |

Vereinigungsgraph im Speicher: **540 Knoten · 360 Kantenschlüssel** — geladen in ~1,3 s beim Start.

**Jeder Chunk trägt:** stabile `chunk_id`, Überschriften-Breadcrumb, Seitenzahlen, Bounding-Boxen, Tokenzahl,
1024-dim Vektor — **und den Rückwärtsindex** in den Graphen: `node_ids`, `node_labels`, `node_types`, `edge_ids`.
Ein Suchtreffer weiß also bereits, welche Entitäten und Fakten er belegt.

---

## 5 · RAG-Graph: warum Text **und** Graph

Klassisches RAG endet an der Chunkgrenze. Hier liefert der Graph drei Dinge, die kein Chunk liefert:

| Baustein | Was er beiträgt | Beispiel |
|---|---|---|
| **Fakten** (Kanten, 1 Hop, alle Relationstypen, beide Richtungen) | die dokumentübergreifende Verbindung, mit Polarität | `Vault —hängt ab von→ PKI: NICHT (für Vault-Unseal)` [BHB-PLT-0007 S. 19] |
| **Entitätskarten** (Knotenattribute) | Aussagen ohne Kante — der wertvollste Negativbefund hat **Grad 0** | `Vault versiegelt \| VPP — severity: keine` |
| **Belegstellen** (Chunk-IDs der Fakten) | der Originaltext zum Graph-Fakt, als fünfte Trefferliste | ZSD S. 19, der Absatz, der die Verneinung beweist |

Gerendert wird deutsch und zitierfähig:

```
Vault —DEPENDS_ON (hängt ab von)→ PKI (dependency_kind=zertifikat): NICHT (für Vault-Unseal)
   — „Der Vault-Unseal erfolgt manuell …“  [BHB-PLT-0007 S. 19; Kante 1a2b…]
```

---

## 5 · Hybride Suche: vier Kanäle in **einer** Anfrage

| Kanal | Technik | Feuert wenn | Fängt |
|---|---|---|---|
| **knn** | HNSW über 1024-dim Vektoren, Kosinus, Engine **lucene** (filtert *während* der Suche) | immer | Bedeutung, Umschreibungen |
| **bm25** | `multi_match` auf `text^2, body_text, caption`, deutscher Analyzer | immer | Wortlaut, Fachbegriffe |
| **identifier** | `term` auf Keyword-Feld `identifiers` | Frage enthält `ZSDSUP-0247`, `SOP-…`, `FW-…`, Hostname | **exakte** Bezeichner |
| **label** | `term` auf `node_labels` (klein geschrieben) | Frage nennt eine Graph-Entität | benannte Entitäten inkl. Aliase |

Deutscher Analyzer: Standard-Tokenizer → lowercase → Stoppwörter → `german_normalization` (Umlaute, ß) →
**`light_german`** Stemmer (der volle Stemmer über-stemmt Fachvokabular).

**Fusion im Client per RRF:** `score = Σ 1/(60 + Rang je Kanal)`.
Übereinstimmung mehrerer Kanäle schlägt einen einzelnen starken Treffer — Rang 10 in zwei Kanälen (0,0286) gewinnt gegen Rang 1 in einem (0,0164).

---

## 5 · Speicher: vier Indizes, kein Graphsystem

| Index | Ein Dokument je | Rolle |
|---|---|---|
| `bhb-chunks` | Chunk | **der einzige durchsuchte Index**: Text, Vektor, Bezeichner, Rückwärtsindex |
| `bhb-nodes` | Knoten je Handbuch | Inspektion, Smoke-Abfragen |
| `bhb-documents` | Handbuch | der **Graph-Blob** (Knoten + Kanten + Meta), Markdown, Embedding-Modell |
| `bhb-manifest` | Handbuch | Ingest-Zustand und Sperre: `indexing / active / failed`, `run_id`, Historie |

**Warum kein Graphsystem?** Der Graph ist klein (einige tausend Knoten). Er liegt als JSON im Index und wird
beim Start in den Speicher geladen — ein Hop über ein Dictionary ist Sub-Millisekunden-Arbeit.
OpenSearch liefert dafür BM25, k-NN, exakte Keywords, Filter und Multi-Search in **einem** Roundtrip.

**Idempotenz:** Ersetzungseinheit ist das Handbuch (`doc_id`). Gleiche Ausgabe = No-Op, neue Extraktion = Ersetzen;
ein Abbruch hinterlässt eine **Obermenge, nie eine Lücke**, das Manifest heilt beim nächsten Lauf.

---

## 6 · Kern-Retrieval: die acht Schritte

| # | Schritt | Kein Modell? | Was passiert |
|---|---|---|---|
| 1 | **Analyse** | ✔ regex + string | Bezeichner (6 Ontologie-Regexe); Label-n-Gramme (4→1) gegen den Labelindex; Teiltreffer mit Ankerregel |
| 2 | **Embedding** | Encoder | Frage vektorisieren, Modell/Präfix gegen den Index prüfen (Abweichung wird gemeldet) |
| 3 | **Suche** | ✔ | 4 Kanäle, je 20 Treffer, **ein** `msearch`, Handbuchfilter im k-NN-Clause |
| 4 | **Fusion** | ✔ | RRF mit festen Tie-Breaks → vollständig deterministisch |
| 5 | **Guardrail** | ✔ | schwache Evidenz → Antwort ohne Modellaufruf |
| 6 | **Graph** | ✔ | 1 Hop um bis zu 30 Startknoten, ≤ 40 Fakten, ≤ 15 Entitätskarten, Belegstellen als 5. Liste |
| 7 | **Gruppen + Zitate** | ✔ | Tabellenteile gleicher Überschrift → **eine** Quelle mit Seitenbereich |
| 8 | **Prompt** | — | deutscher Kontextblock: Entitäten → Fakten → Quellen, 6 000-Token-Budget |

**Das Sprachmodell sieht erst Schritt 8.** Alles davor ist reproduzierbar.

---

## 6 · Warum das mehr ist als einfaches RAG

| Einfaches RAG | Dieses System |
|---|---|
| ein Kanal (Vektor), Top-k | **vier Kanäle + Graphkanal**, Fusion nach Rang |
| Bezeichner zerfallen im Analyzer | eigenes Keyword-Feld → `ZSDSUP-0247` ist ein **exakter** Treffer |
| Chunk = Antwortgrenze | **1-Hop-Graph** verbindet Handbücher: Auswirkungsmatrix + Abhängigkeitskette |
| Verneinung geht verloren | **Polarität als Datum**, „NICHT“ wird mit Grund und Zitat gerendert |
| Tabellen zerfallen in Fragmente | Tabellen bleiben ganze Chunks, Teile werden zu einer Quelle gruppiert |
| Bei Nichtwissen wird halluziniert | **Guardrail**: feste Absage, ohne das Modell zu fragen |
| Quelle = „irgendein Chunk“ | Quelle = Dokument + Seite + Tabelle + wörtliches Zitat + Kanten-ID |
| „warum kam das?“ unbeantwortbar | jeder Treffer zeigt Kanal und Rang: `via knn#2 bm25#1 identifier#3` |

---

## 6 · Der Guardrail: absagen ohne Modellaufruf

```
Evidenz ist STARK, wenn   ein Bezeichner traf   oder   ein Graph-Label exakt auflöste
sonst SCHWACH, wenn       gar kein Treffer
                    oder  BM25 lieferte nichts          → „keine lexikalische Überlappung“
                    oder  keiner der Top-3 wurde von ≥ 2 *Such*-Kanälen gefunden
```

- **Kein Schwellwert.** Die Entscheidung fällt auf Rängen und Kanalübereinstimmung — Kosinuswerte liegen bei
  bge-m3/e5 für fast alles um 0,96, ein Schwellwert wäre willkürlich.
- Der **Graphkanal zählt nie als Evidenz**: er wird aus genau den Treffern gespeist, die in Verdacht stehen.
- *„Wie backe ich einen Apfelkuchen?“* → k-NN liefert wie immer 20 Chunks, BM25 liefert 0 → schwach → feste Absage.
- **Folgefragen** sind ausgenommen: dort ist das Gespräch selbst die Evidenz.

---

## 6 · Zwei Prompt-Profile

| | **Handbuch-Antworten** (strikt) | **Technik-Assistent** |
|---|---|---|
| Aktiv wenn | Guardrail an (Standard) | `RAG__GUARDRAIL__ENABLED=false` |
| Wissensquelle | nur Kontext + eigene frühere Antworten | zusätzlich allgemeines Fachwissen, **gekennzeichnet** |
| Umgebungsangaben (Hosts, Pfade, Kontakte, Alarmwege) | aus dem Kontext, mit Quelle | ebenso — fehlt etwas: `<PLATZHALTER>` + „Offene Angaben:“ |
| Schwache Evidenz | feste Absage | Modell antwortet, Kontext als „Evidenzlage: schwach“ markiert |
| Aufgaben | Fragen beantworten | zusätzlich: Log analysieren, **Skript erzeugen**, Befehle anpassen |
| Struktur | 7 Regeln | Regeln + **Gedankenkette im Prompt**: jede Antwort beginnt mit einem Block *Aufgabe · Bereich · System · Grundlage*, der vor der Anzeige abgetrennt wird |

Beides ist **ein einziger Modellaufruf** — kein Agent, keine Werkzeugschleife.
Außerhalb des Aufgabenbereichs (z. B. Apfelkuchen) antwortet auch der Assistent mit einem einzigen Absagesatz.

---

## 6 · Determinismus und Nachvollziehbarkeit

| Stufe | Deterministisch? |
|---|---|
| Frageanalyse (Bezeichner, Labels, Cues) | **ja, exakt** — reine Stringverarbeitung |
| Embedding der Frage | ja bei gleichem Modell (Encoder = feste Funktion) |
| BM25-, Bezeichner-, Label-Kanal | **ja** |
| k-NN | in der Praxis ja (bei dieser Korpusgröße ist HNSW quasi erschöpfend) |
| Fusion, Guardrail, Startknoten, Expansion, Faktenreihenfolge, Budget | **ja, exakt** — feste Formeln mit expliziten Tie-Breaks |
| Graph-Extraktion beim Ingest | **nein (Modell)** — eingezäunt durch Schema, Validierung, Content-Adressierung |
| Die Antwort | nein (Modell) — gebunden an Kontext, Prompt, Temperatur 0 |

> **Für einen festen Index und eine feste Frage ist alles bis zum fertigen Prompt Byte für Byte reproduzierbar** —
> und für jeden Chunk und jeden Fakt ist sichtbar, warum er da ist.

---

## 6 · Belastbarkeit: Tests und Abnahme

| Modul | Tests |
|---|---|
| `docling-graph` | 55 Unit- + 12 Integrationstests, Containerlauf verifiziert |
| `opensearch-index` | 66 Unit- + 12 Integrationstests, Live-Ingest gegen den echten Knoten |
| `retrieval` | **154 Unit-Tests** gegen einen nachgebauten OpenSearch (Kosinus-k-NN, BM25 mit deutschen Stoppwörtern, msearch, mget) + 13 Live-Tests |
| `users` | 39 Unit-Tests, Handbuchfilter live durchgereicht |
| `chat-system` | 64 Unit-Tests (auch gegen Postgres), 6 UI-Smokes, 8 Live-Tests, Containerlauf |

**Acht Grundwahrheitsfragen** mit in den PDFs verifizierten Seitenzahlen sind durchgespielt —
inklusive der Fallen: Verneinungen werden als Verneinungen wiedergegeben, beide widersprüchlichen Dauern
(48 vs. 38 min) bleiben erhalten, Partnervorgänge werden verbunden, die Apfelkuchenfrage wird abgelehnt.

---

## 7 · Enterprise: Zielbild

```
                     Nutzer (Browser)
                            │ HTTPS
                 ┌──────────▼───────────┐
                 │  Ingress + IAM (PGA) │  authentifiziert, injiziert Gruppen-Header
                 └──────────┬───────────┘
                            │  Session-Affinität (Streamlit = WebSocket)
   ╔════════════════════════▼════════════════════════════════════╗  Kubernetes
   ║   chat-system  × 2      250 m CPU / 512 Mi                   ║
   ║                                                              ║
   ║   Jobs bei Bedarf:  docling-graph 8 CPU / 12 Gi              ║
   ║                     osi-Indexer   0,5 CPU / 512 Mi           ║
   ╚════════╪═════════════════════╪══════════════════╪════════════╝
            │                     │                  │
   ┌────────▼────────┐  ┌─────────▼──────┐  ┌────────▼────────┐
   │ OpenSearch      │  │ LLM-Endpunkt   │  │ Embedding       │
   │ Enterprise      │  │ GPU, OpenAI-   │  │ e5-large        │
   │ + k-NN-Plugin   │  │ kompatibel     │  │ (CPU genügt)    │
   └─────────────────┘  └────────────────┘  └─────────────────┘
       zentral               zentral              zentral
```

**In Kubernetes liegt nur die Laufzeit** — Speicher, Modelle und IAM kommen als zentrale Dienste.

---

## 7 · Gemessene Ressourcen (Entwicklungsmaschine, 12 vCPU / 23 GB)

| Komponente | Image | RAM **gemessen** | CPU |
|---|---|---|---|
| OpenSearch 3.8.0, Heap 2 GB | 2,83 GB | **2,9 GB** RSS (1,1 GB Heap belegt) | < 3 % im Leerlauf |
| `docling-graph` — Leerlauf | 6,35 GB | 1,5 GB | — |
| `docling-graph` — **Konvertierung 50 Seiten** | | **5,0 GB Spitze** | 4,5–7 Kerne |
| `chat-system` — vollständige Antwortrunde (3 Handbücher geladen) | 952 MB | **92 MB Spitze** | < 1 Kern |
| Streamlit-Prozess ohne Sitzung | | 52 MB | — |
| `osi`-Indexer (kurzlebig) | 283 MB | < 300 MB | — |
| Postgres (optional) | 420 MB | ~150 MB | — |

**Datenmenge heute:** 3 Handbücher / 105 Seiten → 401 Chunks, 674 Knotendokumente, **Index gesamt 3,3 MB**.

---

## 7 · Hochrechnung auf 40 Handbücher

| Größe | Heute (3 Bücher) | 40 Bücher à 5–10 Seiten |
|---|---|---|
| Chunks | 401 | ~1 200 |
| Indexdaten | 3,3 MB | **< 15 MB** (mit Reserve < 100 MB) |
| Graphknoten im Speicher | 540 | ~4 000 |
| RAM des Chat-Prozesses | 92 MB | **< 250 MB** |
| OpenSearch-Heap | 2 GB | 2–4 GB (JVM-Grundbedarf, nicht Datenmenge) |
| Ingest je Handbuch | 13–21 min (27–49 S.) | **2–5 min** (5–10 S.) |
| Erstbefüllung 40 Handbücher | — | **2–3 h einmalig**, parallelisierbar |

> Die Datenmenge ist **kein Dimensionierungstreiber**. Dimensioniert wird nach LLM-Last und Ingest-Spitzen.

---

## 7 · Pod-Dimensionierung (Kubernetes)

| Workload | Replikate | CPU req/lim | RAM req/lim | Storage | Anmerkung |
|---|---|---|---|---|---|
| **chat-system** (UI + Retrieval + Policy) | 2 | 250 m / 1 | 512 Mi / 1 Gi | — | Session-Affinität nötig; 10 gleichzeitige Antworten je Pod (Semaphore) |
| **docling-graph** (Ingest-Job) | 0–1, bei Bedarf | 4 / 8 | 8 Gi / 12 Gi | 20 GB ephemeral | Image 6,35 GB + Modell-Cache; CPU-lastig, kein Dauerbetrieb |
| **osi-Indexer** (Job) | je Ingest | 500 m / 1 | 512 Mi / 1 Gi | liest Ingest-Volume | Laufzeit Minuten |
| **Postgres** (optional) | 1 | 250 m / 1 | 256 Mi / 1 Gi | 5 GB PVC | nur wenn Verlauf zentral/mehrere Repliken |
| **Ingest-Ablage** (PVC) | — | — | — | 5 GB | `response.json` + Markdown je Handbuch |

**Dauerbetrieb gesamt: ~1 CPU / 2 GB RAM.**
**Ingest-Spitze: + 8 CPU / 12 GB**, zeitlich begrenzt und planbar.

---

## 7 · Anforderung: OpenSearch (Enterprise-Instanz)

| Punkt | Anforderung |
|---|---|
| Version | ≥ 2.19, verifiziert auf **3.8.0** |
| Plugin | **k-NN (Pflicht)** — `knn_vector` 1024 Dim, HNSW, Engine **lucene**, `m=16`, `ef_construction=128` |
| Textanalyse | eingebaut (deutsche Stoppwörter, `german_normalization`, `light_german`) — **kein Zusatzplugin** |
| Indizes | 4 Stück `bhb-chunks / -nodes / -documents / -manifest`, je mit Alias, `dynamic: strict`, 1 Shard, 1 Replika |
| Rechte des Ingest-Kontos | Index + Alias anlegen, schreiben, `refresh`, `delete_by_query` (Sweep), lesen |
| Rechte des Lesekontos | `search`, `msearch`, `mget` auf `bhb-*` |
| Transport | TLS und Basic-Auth werden unterstützt (`username`/`password`, `ca_certs`) |
| Volumen | < 100 MB bei 40 Handbüchern → **kein eigener Cluster**, ein Index-Präfix auf der bestehenden Instanz reicht |
| **Nicht** benötigt | Dashboards, ML-Plugin, serverseitige RRF-Pipeline (Fusion läuft im Client) |

---

## 7 · Anforderung: IAM / Benutzerverwaltung

**Heute (Prototyp):** ein Mock-Verzeichnis mit vier Benutzern und drei Gruppen — die Struktur ist echt, die Daten sind es nicht.

**Für Enterprise benötigt:**

- **Authentifizierender Ingress** (oauth2-proxy-Muster), der `X-Forwarded-User`, `-Email`, `-Groups` injiziert.
  Die Anwendung liest **nur Header** — kein OIDC-Client, keine Tokenverwaltung im Dienst. Headernamen sind konfigurierbar.
- **Vertrag/Onboarding mit PGA** in Kubernetes: Routing, Gruppen als Claim, Namenskonvention der Gruppen.
- **Gruppen → Policy-Abbildung** (heute hart kodiert, künftig Konfiguration oder Claims):

| Gruppe | Nachrichten/Tag | Runden/Gespräch | Handbücher |
|---|---|---|---|
| `admin` | 100 | 20 | alle |
| `bavd-ops` | 10 | 10 | alle |
| `bavd-readonly` | 5 | 5 | nur ZSD |

- **Erlaubte Handbücher je Gruppe** sind der **Mandantenschnitt im Retrieval**: der Filter geht in die Suche hinein (auch in das k-NN-Clause), nicht erst in die Anzeige.
- Die Zählung liegt bereits in der Datenbank → mehrere Browser-Tabs und mehrere Pods sind unkritisch.
- **Limits sind vom LLM-Vertrag abhängig** und daher bewusst Konfiguration.

---

## 7 · Anforderung: LLM (Mindestanforderung)

| Punkt | Anforderung |
|---|---|
| Schnittstelle | **OpenAI-kompatibel** `/v1/chat/completions` mit Streaming (vLLM, Ollama, TGI oder internes Gateway) — mehr braucht das System nicht |
| Kontextfenster | Systemprompt ~0,8k + Ökosystem 0,4k + Kontext 6k + Material ≤ 3k + Verlauf bis 8k + Antwort 4k → **≥ 32k Token**, empfohlen 128k |
| Sprache | belastbares **Deutsch**: Fachtexte, Verneinungen, wörtliche Bezeichner, Tabellen |
| Modellklasse | ≥ 24B dicht bzw. ≥ 30B MoE, instruktionsgetunt. Erprobt: Gemma 26B (Ollama), Qwen3-Coder-30B-A3B (vLLM), Gemini (Entwicklung) |
| Last | 10 gleichzeitige Nutzer, 10 Nachrichten/Tag → Auslegung **3–5 parallele Streams**, ≥ 20–30 Token/s je Stream |
| Hardware *(Richtwert)* | 4-Bit-Quantisierung 26–30B ≈ 16–20 GB Gewichte + KV-Cache → **1 GPU mit 48 GB** (L40S/A6000-Klasse) für 32k Kontext und 4 Streams; BF16 oder 128k Kontext → 1×80 GB bzw. 2×48 GB |
| CPU-Inferenz | für interaktiven Chat **nicht praktikabel** (erprobt, deutlich zu langsam) |
| Denkende Modelle | Denk-Token gehen vom Antwortbudget ab → per Konfiguration abschaltbar (`RAG__LLM__EXTRA_BODY`) |

Dasselbe Modell wird beim **Ingest** für die Graph-Extraktion genutzt (4–6 min je Handbuch) — planbare Batchlast.

---

## 7 · Anforderung: Embedding-Modell

| Punkt | Anforderung |
|---|---|
| Modell | `intfloat/multilingual-e5-large` — 1024 Dimensionen, Präfixe `passage: ` / `query: ` |
| **Kritisch** | Ingest und Abfrage **müssen dasselbe Modell und Präfix** verwenden. Das System speichert beides je Dokument und **meldet Abweichungen** statt sie zu verschlucken. Modellwechsel = alle Handbücher neu indizieren. |
| Schnittstelle | OpenAI-kompatibel `/v1/embeddings` (TEI, vLLM, Gateway) |
| Last | 1 Aufruf je Frage (**200–270 ms gemessen**); beim Ingest Batches zu 64 |
| Ressourcen | 560M-Parameter-Modell → **2 CPU / 4 GB genügen** für die Abfragelast; GPU nur für Massen-Ingest sinnvoll |

---

## 7 · Speicher, Betrieb, Datensicherung

**Kein Backup nötig — der Index ist reproduzierbar.**

- Quelle der Wahrheit sind die **Handbücher** (PDF) und die **Ontologie**. Geht der Index verloren:
  Handbücher erneut verarbeiten und indizieren.
- Der Ingest ist **idempotent**: gleiche Ausgabe = No-Op, neue Extraktion = Ersetzen des ganzen Handbuchs.
- **Sinnvoll aufzuheben (optional, kein Backup-Verfahren nötig):**
  - `response.json` je Handbuch (2–3 MB) → spart die teure Neuverarbeitung (13–21 min je Buch)
  - Gesprächsverlauf, falls fachlich gewünscht → SQLite-PVC oder Postgres

**Netzwerkfreigaben** (alles ausgehend, keine eingehenden Verbindungen außer dem Ingress):

```
chat-system  ──► OpenSearch (9200)   ──► LLM-Endpunkt   ──► Embedding-Endpunkt
docling-graph ──► LLM · VLM · Embedding          osi ──► OpenSearch
```

---

## 7 · Offene Punkte und Abhängigkeiten

| Thema | Stand | Was gebraucht wird |
|---|---|---|
| **Benutzerverwaltung** | Mock-Verzeichnis, echte Header-Anbindung fertig | Vertrag mit PGA, Gruppennamen, Claims |
| **Limits** (Nachrichten/Tag, Runden) | konfigurierbar, Werte aus der Spezifikation | Abhängig vom LLM-Kontingent |
| **LLM-Bereitstellung** | erprobt gegen 3 Endpunkte | GPU-Kapazität, Modellentscheidung, Kontingent |
| **OpenSearch** | Prototyp ohne Security-Plugin | Mandant auf der Enterprise-Instanz, Konten und Rechte |
| **Ingest-Betriebsmodell** | CLI/Job, manuell ausgelöst | Entscheidung: geplanter Job vs. Self-Service-Upload im Chat |
| **Ontologie für echte Handbücher** | auf den Testkorpus zugeschnitten | fachliche Abstimmung anhand der realen Handbuchvorlage |
| **Verlaufsspeicher** | SQLite (Standard), Postgres vorbereitet | Entscheidung nur nötig bei mehreren Repliken |

---

## Zusammenfassung

- **Das Problem** ist nicht „Suche“, sondern Bezeichner, dokumentübergreifende Fakten und Verneinungen.
- **Die Antwort** ist eine Ontologie im Zentrum: sie steuert Extraktion, Identität und Kantenvokabular —
  und macht jeden Graph-Fakt so zitierbar wie eine Textstelle.
- **Das Retrieval** kombiniert vier Suchkanäle mit einem Hop im Wissensgraphen und arbeitet
  **ohne Sprachmodell** bis zum fertigen Prompt — reproduzierbar und erklärbar.
- **Der Guardrail** sagt ab, ohne das Modell zu fragen; der Technik-Assistent öffnet dieselbe Basis
  für Skripte, Loganalyse und Befehlsanpassung — geerdet in den Handbüchern.
- **Die Einführung** ist leichtgewichtig: ~1 CPU / 2 GB im Dauerbetrieb, < 100 MB Index für 40 Handbücher.
  Die realen Abhängigkeiten sind **LLM-Kapazität, OpenSearch-Mandant und IAM-Anbindung** — nicht die Hardware der Anwendung.

---

## Nächste Schritte

1. Ontologie an der realen Handbuchvorlage abstimmen
2. Zwei bis drei echte Handbücher verarbeiten und bewerten
3. OpenSearch-Mandant und Konten bereitstellen
4. IAM-Anbindung mit PGA vereinbaren
5. LLM-Kapazität festlegen (Modell, Kontextfenster, Kontingent)
6. Pilotgruppe und Limits festlegen
