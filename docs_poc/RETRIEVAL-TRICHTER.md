# Retrieval-Trichter: von der Frage zum LLM-Kontext

Beispiel an der Frage **„Wer ist verantwortlich für SOP-ZSD-06?“**. Die Chunk-Nummern (c42, c17 …) und Fakten sind
zur Veranschaulichung erfunden; Stufen, Felder, Indizes und Grenzen sind die echten (`retrieval/src/rag_retrieval/`).

```mermaid
flowchart TD
    Q["Frage<br/>„Wer ist verantwortlich für SOP-ZSD-06?“"]

    subgraph S1["1 · Analyse der Frage (Python, kein OpenSearch)"]
        A1["Identifier per Regex aus der Ontologie<br/>→ SOP-ZSD-06"]
        A2["Labels per n-Gramm-Abgleich mit dem Graphen<br/>→ sop-zsd-06"]
        A3["Embedding (bge-m3)<br/>→ Vektor mit 1024 Zahlen"]
        A4["Fragetext unverändert"]
    end

    subgraph S2["2 · Index bhb-chunks: 4 Kanäle in einem _msearch, je 20 Treffer"]
        K1["kNN · Feld embedding<br/>c42, c17, c08, c91 …"]
        K2["BM25 · Felder text, body_text, caption<br/>c42, c91, c17, c30 …"]
        K3["Identifier · term auf identifiers<br/>c42, c08"]
        K4["Label · term auf node_labels<br/>c42, c17, c55"]
    end

    F1["3 · RRF-Fusion 1 · score = Σ 1/(60+Rang)<br/>c42 (4 Listen) › c17 (3) › c08 (2) › c91 (2) › c55 (1) …"]

    subgraph S3["4 · Graph (nur langsamer Modus) · aus bhb-documents, im Speicher"]
        G1["Startknoten (max 30)<br/>SOP-ZSD-06 + node_ids der Seed-Chunks<br/>(Top 5 fusioniert + Top 2 je Kanal)"]
        G2["1 Hop → Fakten (max 40), sortiert<br/>① Max Muster RESPONSIBLE_FOR SOP-ZSD-06 · Quelle c42<br/>② Team Basis NICHT RESPONSIBLE_FOR SOP-ZSD-06 · Quelle c63<br/>③ SOP-ZSD-06 RUNS_ON SRV-ZSD-01 · Quelle c55"]
        G3["provenance.chunk_ids → _mget auf bhb-chunks (max 15)<br/>Graph-Liste: c42, c63, c55"]
    end

    F2["5 · RRF-Fusion 2 über 5 Listen + Garantie: 2 Graph-Chunks bleiben drin<br/>Top 10: c42, c17, c08, c55, c91, c63 …"]

    OUT["6 · LLM-Kontext (max 6000 Tokens)<br/>Entitäten (max 15): SOP-ZSD-06, Max Muster, SRV-ZSD-01<br/>Fakten (max 25): ① ② ③<br/>Quellen: Top-10-Chunks in Rangfolge, Tabellenteile gruppiert"]

    Q --> A1
    Q --> A2
    Q --> A3
    Q --> A4
    A3 --> K1
    A4 --> K2
    A1 --> K3
    A2 --> K4
    K1 --> F1
    K2 --> F1
    K3 --> F1
    K4 --> F1
    F1 --> G1
    G1 --> G2
    G2 --> G3
    G3 --> F2
    F1 --> F2
    F1 -.->|"schneller Modus: Top 10 direkt"| OUT
    F2 --> OUT

    classDef frage fill:#fff3cd,stroke:#b58900,color:#000
    classDef os fill:#dbeafe,stroke:#1d4ed8,color:#000
    classDef py fill:#f3f4f6,stroke:#6b7280,color:#000
    classDef grph fill:#dcfce7,stroke:#15803d,color:#000
    classDef out fill:#fde2e2,stroke:#b91c1c,color:#000
    class Q frage
    class K1,K2,K3,K4,G3 os
    class A1,A2,A3,A4,F1,F2 py
    class G1,G2 grph
    class OUT out
```

Farben: blau = Anfrage an OpenSearch, grau = Python im Retriever, grün = Graph im Speicher, rot = Ergebnis.

## Die erfundenen Chunks

| Chunk | Inhalt (Beispiel) | Gefunden durch |
|---|---|---|
| c42 | Tabelle „Verantwortlichkeiten“, Zeile SOP-ZSD-06 | alle 4 Kanäle + Graph |
| c17 | Abschnitt „Rollen und Zuständigkeiten“ | kNN, BM25, Label |
| c08 | Änderungshistorie, nennt SOP-ZSD-06 | kNN, Identifier |
| c91 | Einleitung, allgemeine Verantwortung | kNN, BM25 |
| c55 | Serverliste mit SRV-ZSD-01 | Label, Graph |
| c63 | Abgrenzung „nicht zuständig“ | nur Graph |

## Die Fusion nachgerechnet

Rang je Liste → Beitrag `1/(60+Rang)`; Summe ist der Score.

| Chunk | kNN | BM25 | Identifier | Label | Fusion 1 | Graph-Liste | Fusion 2 |
|---|---|---|---|---|---|---|---|
| c42 | 1 → 0,0164 | 1 → 0,0164 | 1 → 0,0164 | 1 → 0,0164 | **0,0656** | 1 → 0,0164 | **0,0820** |
| c17 | 2 → 0,0161 | 3 → 0,0159 | – | 2 → 0,0161 | 0,0481 | – | 0,0481 |
| c08 | 3 → 0,0159 | – | 2 → 0,0161 | – | 0,0320 | – | 0,0320 |
| c91 | 4 → 0,0156 | 2 → 0,0161 | – | – | 0,0318 | – | 0,0318 |
| c55 | – | – | – | 3 → 0,0159 | 0,0159 | 3 → 0,0159 | 0,0317 |
| c63 | – | – | – | – | 0 | 2 → 0,0161 | 0,0161 |

Lesart: c42 gewinnt, weil es in jeder Liste vorne steht, nicht weil ein Kanal einen hohen Score hatte. Die Graph-Liste
hebt c55 an und bringt c63 überhaupt erst ins Spiel; läge c63 außerhalb der Top 10, würde die Garantie
(`graph_min_sources = 2`) es als zweiten Graph-Chunk trotzdem hineinnehmen.
