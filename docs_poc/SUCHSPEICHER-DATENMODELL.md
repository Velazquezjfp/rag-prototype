# Suchspeicher: Datenmodell und Abfragen

Stand 2026-10-07. Was der Suchspeicher halten und abfragen muss, einmal für **OpenSearch 3.8.0** (heute) und einmal
für **SQLite 3.46.1 + numpy** (Vorschlag). Alle Beispiele sind echte Zeilen und echte Abfragen aus
`database_comparison/data/search.db` (drei Handbücher). Entscheidung: `SUCHSPEICHER-ENTSCHEIDUNG-KURZ.md`.

## 1. Tabellen

OpenSearch hat **vier Indizes**. SQLite hat dieselben vier Tabellen und zusätzlich **Hilfstabellen**, weil OpenSearch
die Suchstrukturen für Felder automatisch baut, SQLite nicht.

| Tabelle (SQLite) | OpenSearch | Eine Zeile = | Spalten | Wofür | Zeilen bei 3 Handbüchern |
|---|---|---|---|---|---|
| `documents` | `bhb-documents` | ein Handbuch | `doc_id`, `source` (Metadaten als JSON), `graph` (Wissensgraph als JSON), `markdown` | Graph wird beim Chat-Start geladen; Katalog der Handbücher | 3 |
| `chunks` | `bhb-chunks` | ein Textabschnitt | `rid`, `chunk_id`, `doc_id`, `run_id`, `embedding` (Vektor), `source` (Chunk als JSON) | Treffer aller vier Kanäle | 401 |
| `nodes` | `bhb-nodes` | ein Graph-Knoten je Handbuch | `id` (`sha12:node_id`), `node_id`, `doc_id`, `source` | nur Diagnose (`osi status/search`); der Chat liest den Graph aus `documents.graph` | 674 |
| `manifest` | `bhb-manifest` | ein Handbuch, letzter erfolgreicher Stand | `doc_id`, `run_id`, `doc_sha256`, `status`, `body` | Ingest: überspringen, ersetzen oder abweisen | 3 |
| `chunk_identifiers` | Feld `identifiers` in `bhb-chunks` | eine ID in einem Chunk | `identifier`, `rid` | Kanal 3 | 367 |
| `chunk_labels` | Feld `node_labels` in `bhb-chunks` | ein Name in einem Chunk | `label_lc` (kleingeschrieben), `rid` | Kanal 4 | 2 493 |
| `fts_text`, `fts_body`, `fts_caption` | Felder `text`, `body_text`, `caption` in `bhb-chunks` | ein Textfeld eines Chunks | `tokens` (Wörter nach deutscher Analyse), `rowid` = `chunks.rid` | Kanal 2 | 401 / 401 / 108 |
| `meta`, `ingest_log` | `_meta` im Mapping | – | Modell, Dimension, `data_version`; jeder Ingest-Versuch | Start-Prüfung, Neuladen nach Ingest | 6 / 4 |

Dateigröße: 6,1 MB. `rid` ist die interne Zeilennummer, über die Hilfstabellen auf `chunks` zeigen.

## 2. Ein Chunk und woher seine Felder kommen

Der Indexer liest `response.json` von dgs und schreibt je Chunk eine Zeile. Gekürzt:

```js
{
  "chunk_id": "b6d7d486423e-0093",            // {Anfang des PDF-Hashes}-{Nummer}
  "doc_id": "BHB-PLT-0042",
  "kind": "table", "page_numbers": [25],
  "text": "5 Administration\n5.5 Standard Operating Procedures\nTabelle 23: … | SOP | Titel | Auslöser | …",
  "identifiers": ["SOP-1", "SOP-2", "SOP-3", "SOP-4", "SOP-5", "SOP-6", "SOP-7"],
  "node_labels": ["Miriam Falk", "SOP-6", "TLSCertExpirySoon", "imc-dispatcher", …],   // 16
  "node_ids":    ["Person_fd3e064a23582274", "Procedure_53d37ee243c4f7f3", …],          // 16
  "edge_ids":    ["58ec2aad5e2670ed", …],                                               // 9
  "embedding":   [-0.00355, -0.01071, -0.02837, …]                                      // 1024 Zahlen
}
```

| Feld | Herkunft |
|---|---|
| `text`, `body_text`, `caption`, `embedding` | direkt aus dem dgs-Chunk |
| `identifiers` | Regex der Ontologie über Text und Bildunterschrift, z. B. `\bSOP-(?:\d+\|(?:CAAS\|ZSD\|DD\|VPP)-\d{2})\b` |
| `node_labels`, `node_ids`, `edge_ids` | aus dem **Graph**, nicht aus der `nodes`-Tabelle: jeder Knoten und jede Kante nennt die Chunks, aus denen sie extrahiert wurden (`provenance.chunk_ids`). Name und Aliase des Knotens werden in diese Chunks kopiert |

Derselbe Chunk in den SQLite-Hilfstabellen:

```text
chunk_identifiers   ('SOP-1', 326) ('SOP-2', 326) … ('SOP-6', 326) ('SOP-7', 326)
chunk_labels        ('miriam falk', 326) ('sop-6', 326) ('imc-dispatcher', 326) …
fts_text            "5 administration 5.5 standard operating procedur tabell 23 … verantwortlich sop 1 …"
```

Die Analyse zerlegt `SOP-6` in `sop` und `6`. Deshalb gibt es den Identifier-Kanal: nur er findet `SOP-6` als Ganzes.

## 3. Vektoren

| | OpenSearch | SQLite + numpy |
|---|---|---|
| Gespeichert | Feld `embedding` im Chunk-Dokument, Typ `knn_vector`, 1024 Dimensionen, Kosinus | Spalte `chunks.embedding`, BLOB mit 1024 float32 = 4 096 Byte |
| Suchstruktur | HNSW-Graph (Engine `lucene`, m = 16, ef_construction = 128), baut OpenSearch selbst | keine. Beim Chat-Start werden alle Vektoren als eine Matrix geladen: 401 × 1024 = 1,6 MiB, bei 12 000 Chunks 49 MB |
| Suche | native kNN-Abfrage, **approximativ**; Filter auf Handbücher wirkt in der Suche | Matrixprodukt `M @ q`, **exakt**; Filter als Maske |
| Ergebnis | gemessen: dieselben Top-20 in derselben Reihenfolge | |

## 4. Die vier Kanäle am Beispiel

Frage: **„Wer ist verantwortlich für SOP-6?“** Zuerst zerlegt Python die Frage, für beide Speicher gleich:

```text
identifiers  ['SOP-6']                            Ontologie-Regex
label_terms  ['sop-6']                            Knotennamen aus dem Graph, die in der Frage stehen
BM25-Tokens  ['wer', 'verantwortlich', 'sop', '6'] deutsche Analyse
Vektor       1024 Zahlen                          Embedding-Modell bge-m3
```

Jeder Kanal liefert bis zu 20 Chunks samt `source`. Ein Filter auf Handbücher hängt in OpenSearch
`"filter": [{"terms": {"doc_id": [...]}}]` an, in SQLite `AND c.doc_id IN (...)`.

**Kanal 1, kNN: gleiche Bedeutung, andere Worte**

```json
{"size": 20, "query": {"knn": {"embedding": {"vector": [0.0012, -0.0234, …], "k": 20}}}}
```
```python
sims = M @ q                     # M: alle Chunk-Vektoren, q: Fragevektor, beide auf Länge 1 normiert
top20 = argsort(-sims)[:20]      # danach: SELECT rid, source FROM chunks WHERE rid IN (…)
```
Ergebnis: 20 Treffer. Platz 1 und 2 sind die SOP-Tabellen von ZSD und Event-System.

**Kanal 2, BM25: dieselben Wörter, gewichtet nach Seltenheit**

```json
{"size": 20, "query": {"multi_match": {"query": "Wer ist verantwortlich für SOP-6?", "fields": ["text^2", "body_text", "caption"]}}}
```
```sql
SELECT f.rowid AS rid, f.tokens
FROM fts_text f JOIN chunks c ON c.rid = f.rowid
WHERE fts_text MATCH '"6" OR "sop" OR "verantwortlich" OR "wer"';
-- ebenso fts_body und fts_caption; Häufigkeiten aus fts_text_vocab.
-- Score je Feld nach der Lucene-Formel in Python, Chunk-Score = max(2 × text, body, caption)
```
Ergebnis: 20 Treffer. Platz 2 ist die SOP-Tabelle des Event-Systems.

**Kanal 3, Identifier: exakte ID, Groß- und Kleinschreibung zählt**

```json
{"size": 20, "query": {"bool": {"should": [{"term": {"identifiers": "SOP-6"}}], "minimum_should_match": 1}}}
```
```sql
SELECT t.identifier, c.rid, c.chunk_id
FROM chunk_identifiers t JOIN chunks c ON c.rid = t.rid
WHERE t.identifier IN ('SOP-6');
```
Ergebnis: 9 Treffer. Score = Anzahl getroffener IDs, hier überall 1,0.

**Kanal 4, Label: exakter Name eines Graph-Knotens, kleingeschrieben**

```json
{"size": 20, "query": {"bool": {"should": [{"term": {"node_labels": "sop-6"}}], "minimum_should_match": 1}}}
```
```sql
SELECT t.label_lc, c.rid, c.chunk_id
FROM chunk_labels t JOIN chunks c ON c.rid = t.rid
WHERE t.label_lc IN ('sop-6');
```
Ergebnis: 9 Treffer, Score wie Kanal 3.

## 5. Danach: Python, unabhängig vom Speicher

1. **Fusion (RRF):** Score je Chunk = Σ 1 / (60 + Rang) über alle Kanäle, die ihn fanden. Platz 1 wird `b6d7d486423e-0093`, von allen vier Kanälen gefunden.
2. **Guardrail:** Hat Kanal 3 getroffen oder steht ein Knotenname aus dem Graph in der Frage, gilt die Evidenz als stark. Sonst muss BM25 etwas liefern, und einer der Top-3 muss von zwei Kanälen kommen. Ist der Guardrail eingeschaltet und die Evidenz schwach, antwortet der Chat ohne LLM „Dazu steht nichts in den Handbüchern.“
3. **Graph, ein Schritt:** Startknoten sind die Knoten der Top-Chunks und die in der Frage erkannten Namen. Von dort folgt der Retriever jeder Kante einen Schritt in beide Richtungen, im Graph aus `documents.graph`. Jede Kante wird ein Fakt:

   ```json
   {"source": "Person_6cbefc94f3651b59", "type": "RESPONSIBLE_FOR", "target": "Procedure_53d37ee243c4f7f3",
    "properties": {"raci": "verantwortlich"}, "provenance": {"pages": [4, 5], "chunk_ids": ["b6d7d486423e-0010", "…"]}}
   ```
   ```text
   Jonas Brinkmann —RESPONSIBLE_FOR (verantwortlich für)→ SOP-6 (raci=verantwortlich) [BHB-PLT-0042 S. 4–5]
   ```
4. **Graph-Chunks:** Die Chunks, aus denen die Fakten stammen, werden per ID nachgeladen und als fünfte Liste in die Fusion gegeben. Nur hier liest der Retriever per ID (`mget` bzw. `SELECT … WHERE chunk_id IN (…)`).
5. **An das LLM:** die 10 besten Chunks, die Fakten (hier 40) und Steckbriefe der beteiligten Knoten (hier 15).

## 6. Was ein Speicher dafür können muss

| Fähigkeit | Genutzt von | OpenSearch | SQLite + numpy |
|---|---|---|---|
| Vektorfeld, kNN mit Filter | Kanal 1 | eingebaut (`knn_vector`, HNSW) | BLOB-Spalte, Suche in numpy |
| Volltext mit deutscher Analyse, BM25 über drei Felder mit Gewicht | Kanal 2 | eingebaut (Analyzer `de_text`, `multi_match`) | FTS5 speichert und findet; Analyse und Lucene-Formel in Python (≈ 230 Zeilen) |
| Exakter Abgleich auf Listenfeldern, wörtlich und kleingeschrieben | Kanal 3 und 4 | eingebaut (`keyword`, Normalizer `lc`) | zwei Hilfstabellen mit Index |
| Lesen per ID | Graph-Chunks | `mget` | `SELECT … IN` |
| JSON ablegen, ohne es zu durchsuchen | Graph, Markdown | `enabled: false`, `index: false` | Textspalte |
| Handbuch ersetzen mit Versionsprüfung | Ingest | fünf Schritte, `seq_no` | eine Transaktion |

Nicht im Speicher, sondern in Python: Fusion, Guardrail, Graph, Prompt. Diese Liste ist der Prüfstein für jede andere
Datenbank.
