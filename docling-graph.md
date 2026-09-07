 ┌─────────────────────────────────────────────────────────────┐
 │                    Client Application                       │
 └──────────────────────────────┬──────────────────────────────┘
                                │ POST /ingest
                                │ { base64_doc, format, json_ontology }
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                Docling-Graph Ingestion Docker               │
 │                                                             │
 │  1. Docling Core       ──► PDF / Layout Parsing             │
 │  2. Local EasyOCR      ──► Text Extraction                  │
 │  3. HybridChunker      ──► Structural Chunking              │
 │  4. Docling-Graph      ──► Schema Mapping (JSON Ontology)   │
 │  5. LiteLLM Client     ──► Orchestration Layer              │
 └──────────────┬──────────────────────────────┬───────────────┘
                │ LiteLLM (REST)               │ Batch HTTP
                ▼                              ▼
 ┌──────────────────────────────┐ ┌────────────────────────────┐
 │     Remote vLLM Service      │ │  Remote Embeddings (TEI)   │
 │ - Qwen-30B (Graph Extraction)│ │ - multilingual-e5-large    │
 │ - Granite VLM (Image/Tables) │ └────────────────────────────┘
 └──────────────────────────────┘