"""SQLite (FTS5) + numpy als Suchspeicher — Prüfstand für SUCHSPEICHER-VERGLEICH.md §3.

Eigenständiges Skript für den Vergleich; ``opensearch-index/`` und ``retrieval/`` bleiben unverändert und werden
nur importiert. Drei Teile:

1. Schema (§3.2) und Ingest in **einer** Transaktion (§3.5). Die Datensätze entstehen mit demselben
   ``opensearch_index.transform.build_batch`` wie beim Indexer → identisch zum heutigen ``_source``.
2. Die vier Kanäle und die Abrufe als SQL/numpy (§3.3): kNN exakt (Matrix im Speicher), BM25 über FTS5,
   Identifier/Label über Hilfstabellen mit Lucene-IDF.
3. ``SqliteSearchClient``: beantwortet die drei OpenSearch-Client-Aufrufe, die ``rag_retrieval`` macht
   (``msearch``, ``mget``, ``search``), damit der **echte Retriever unverändert** auf SQLite läuft.
   Das ist ein Shim für den Vergleich, nicht die Zielschnittstelle (§3.8 ``SearchBackend``).
"""

from __future__ import annotations

import json
import math
import os
import socket
import sqlite3
import threading
import time
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from opensearch_index.identity import resolve_doc_id, run_fingerprint
from opensearch_index.loader import load_run
from opensearch_index.mappings import MAPPING_VERSION
from opensearch_index.ontology import Ontology
from opensearch_index.settings import Settings as OsiSettings
from opensearch_index.transform import IndexBatch, build_batch, compute_edge_ids, node_doc_id

from de_analysis import ANALYZER_VERSION, FTS5_TOKENIZE, analyze, fts_document, fts_query

SCHEMA_VERSION = 1
EXCLUDE_FROM_SOURCE = ("embedding", "bboxes")  # wie EXCLUDE_FIELDS in rag_retrieval.search
BM25_FIELDS = {"text": 2.0, "body_text": 1.0, "caption": 1.0}  # multi_match "text^2", "body_text", "caption"

# --------------------------------------------------------------------------- 1. Schema (§3.2)
SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS manifest (          -- bhb-manifest: letzter ERFOLGREICHER Stand je Handbuch
  doc_id     TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL,
  doc_sha256 TEXT NOT NULL,
  status     TEXT NOT NULL,
  body       TEXT NOT NULL                     -- vollständiger Manifest-Datensatz als JSON
);
CREATE INDEX IF NOT EXISTS manifest_sha ON manifest(doc_sha256);

CREATE TABLE IF NOT EXISTS ingest_log (        -- jeder Versuch, auch noop und Fehler
  id          INTEGER PRIMARY KEY,
  doc_id      TEXT NOT NULL,
  run_id      TEXT NOT NULL,
  owner       TEXT,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  status      TEXT NOT NULL CHECK (status IN ('active', 'noop', 'failed')),
  error       TEXT
);

CREATE TABLE IF NOT EXISTS documents (         -- bhb-documents
  doc_id   TEXT PRIMARY KEY,
  run_id   TEXT NOT NULL,
  source   TEXT NOT NULL,                      -- Datensatz als JSON OHNE graph und markdown
  graph    TEXT,                               -- node-link-JSON, beim Chat-Start geladen
  markdown TEXT
);

CREATE TABLE IF NOT EXISTS chunks (            -- bhb-chunks
  rid       INTEGER PRIMARY KEY,               -- interne Zeilen-ID; verbindet FTS5 und Hilfstabellen
  chunk_id  TEXT NOT NULL UNIQUE,
  doc_id    TEXT NOT NULL,
  run_id    TEXT NOT NULL,
  embedding BLOB,                              -- float32 little-endian, dim × 4 Byte
  bboxes    TEXT,
  source    TEXT NOT NULL                      -- JSON ohne embedding und bboxes = heutiges _source
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS chunk_identifiers ( -- Feld identifiers: wörtlich (case-sensitiv)
  identifier TEXT NOT NULL,
  rid        INTEGER NOT NULL REFERENCES chunks(rid) ON DELETE CASCADE,
  PRIMARY KEY (identifier, rid)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS chunk_identifiers_rid ON chunk_identifiers(rid);

CREATE TABLE IF NOT EXISTS chunk_labels (      -- Feld node_labels: lower(trim(label)), wie Normalizer lc
  label_lc TEXT NOT NULL,
  rid      INTEGER NOT NULL REFERENCES chunks(rid) ON DELETE CASCADE,
  PRIMARY KEY (label_lc, rid)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS chunk_labels_rid ON chunk_labels(rid);

-- BM25: eine FTS5-Tabelle je Feld (eigene Längennormierung je Feld, wie Lucene). rowid = chunks.rid.
-- Inhalt = die Tokens des Python-Analyzers; leere Felder bekommen KEINE Zeile.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_text    USING fts5(tokens, tokenize = "{FTS5_TOKENIZE}");
CREATE VIRTUAL TABLE IF NOT EXISTS fts_body    USING fts5(tokens, tokenize = "{FTS5_TOKENIZE}");
CREATE VIRTUAL TABLE IF NOT EXISTS fts_caption USING fts5(tokens, tokenize = "{FTS5_TOKENIZE}");
CREATE VIRTUAL TABLE IF NOT EXISTS fts_text_vocab    USING fts5vocab(fts_text, 'row');     -- Abnahme §3.9
CREATE VIRTUAL TABLE IF NOT EXISTS fts_body_vocab    USING fts5vocab(fts_body, 'row');
CREATE VIRTUAL TABLE IF NOT EXISTS fts_caption_vocab USING fts5vocab(fts_caption, 'row');

CREATE TABLE IF NOT EXISTS nodes (             -- bhb-nodes (vom Retriever nicht gelesen; status/search)
  id      TEXT PRIMARY KEY,                    -- {{sha12}}:{{node_id}}
  node_id TEXT NOT NULL,
  doc_id  TEXT NOT NULL,
  run_id  TEXT NOT NULL,
  source  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_doc ON nodes(doc_id);
CREATE INDEX IF NOT EXISTS nodes_node_id ON nodes(node_id);
"""

FTS_TABLE = {"text": "fts_text", "body_text": "fts_body", "caption": "fts_caption"}


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def open_db(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Eine Verbindung (eine je Thread, §3.6). WAL steht in der Datei; die übrigen PRAGMAs gelten je Verbindung."""
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)  # Autocommit; BEGIN explizit
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if readonly:
        conn.execute("PRAGMA query_only = ON")
    return conn


def bootstrap(path: str | Path, *, embedding_model: str, embedding_dim: int) -> dict[str, Any]:
    """Datei anlegen, WAL setzen, Schema und ``meta`` schreiben; bei bestehender Datei die Versionen prüfen."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_SQL)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if meta:
            for key, want in (
                ("schema_version", str(SCHEMA_VERSION)),
                ("embedding_dim", str(embedding_dim)),
                ("analyzer_version", ANALYZER_VERSION),
            ):
                if meta.get(key) != want:
                    raise RuntimeError(f"search.db: {key} {meta.get(key)!r} != {want!r} — Datei neu aufbauen")
            return {"created": False, "meta": meta}
        rows = {
            "schema_version": str(SCHEMA_VERSION),
            "mapping_version": str(MAPPING_VERSION),
            "embedding_model": embedding_model,
            "embedding_dim": str(embedding_dim),
            "analyzer_version": ANALYZER_VERSION,
            "data_version": "0",
        }
        conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", rows.items())
        return {"created": True, "meta": rows}
    finally:
        conn.close()


# --------------------------------------------------------------------------- 2. Ingest: eine Transaktion (§3.5)
def _source_json(record: dict[str, Any], exclude: Sequence[str]) -> str:
    return json.dumps({k: v for k, v in record.items() if k not in exclude}, ensure_ascii=False)


def ingest(
    path: str | Path,
    run_path: str | Path,
    *,
    settings: OsiSettings,
    ontology: Ontology,
    doc_id_override: str | None = None,
    force: bool = False,
    owner: str | None = None,
) -> dict[str, Any]:
    """``plan`` wie heute (noop bei gleichem run_id), dann BEGIN IMMEDIATE → löschen → schreiben → prüfen → manifest
    → data_version+1 → COMMIT. Fehler → ROLLBACK, der alte Stand bleibt aktiv."""
    t0 = time.perf_counter()
    resp = load_run(run_path)
    res = resolve_doc_id(resp, ontology, doc_id_override)
    emb = settings.embedding
    edge_ids = compute_edge_ids(resp.graph)
    run_id = run_fingerprint(
        resp,
        edge_ids,
        ontology_fingerprint=ontology.fingerprint,
        embedding_model=emb.model,
        embedding_dim=emb.dim,
        mapping_version=MAPPING_VERSION,
    )
    owner = owner or f"{socket.gethostname()}:{os.getpid()}"
    started = utcnow_iso()
    conn = open_db(path)
    try:
        prev = conn.execute("SELECT run_id, doc_sha256, body FROM manifest WHERE doc_id = ?", (res.doc_id,)).fetchone()
        prev_body = json.loads(prev[2]) if prev else None
        if prev and prev[0] == run_id and not force:
            conn.execute(
                "INSERT INTO ingest_log(doc_id, run_id, owner, started_at, finished_at, status) VALUES (?,?,?,?,?,'noop')",
                (res.doc_id, run_id, owner, started, utcnow_iso()),
            )
            return {"status": "noop", "doc_id": res.doc_id, "run_id": run_id, "duration_s": round(time.perf_counter() - t0, 3)}

        batch: IndexBatch = build_batch(
            resp,
            doc_id=res.doc_id,
            doc_id_source=res.source,
            run_id=run_id,
            ontology=ontology,
            embedding_model=emb.model,
            embedding_dim=emb.dim,
            embedding_text_prefix=emb.text_prefix,
            indexed_at=started,
        )
        conn.execute("BEGIN IMMEDIATE")  # Schreibsperre: ein zweiter Indexer wartet busy_timeout, dann Fehler
        try:
            again = conn.execute("SELECT run_id FROM manifest WHERE doc_id = ?", (res.doc_id,)).fetchone()
            if (again[0] if again else None) != (prev[0] if prev else None):
                raise RuntimeError(f"manifest of {res.doc_id} changed since the plan — re-run")

            # -- alte Zeilen des doc_id löschen (= swept)
            old_rids = [r[0] for r in conn.execute("SELECT rid FROM chunks WHERE doc_id = ?", (res.doc_id,))]
            for table in FTS_TABLE.values():
                conn.executemany(f"DELETE FROM {table} WHERE rowid = ?", [(r,) for r in old_rids])
            swept = {
                "chunks": conn.execute("DELETE FROM chunks WHERE doc_id = ?", (res.doc_id,)).rowcount,
                "nodes": conn.execute("DELETE FROM nodes WHERE doc_id = ?", (res.doc_id,)).rowcount,
                "documents": conn.execute("DELETE FROM documents WHERE doc_id = ?", (res.doc_id,)).rowcount,
                "edges": 0,
            }

            # -- neue Zeilen
            for c in batch.chunks:
                vec = c.get("embedding")
                blob = np.asarray(vec, dtype="<f4").tobytes() if vec is not None else None
                cur = conn.execute(
                    "INSERT INTO chunks(chunk_id, doc_id, run_id, embedding, bboxes, source) VALUES (?,?,?,?,?,?)",
                    (c["chunk_id"], c["doc_id"], run_id, blob, json.dumps(c.get("bboxes")), _source_json(c, EXCLUDE_FROM_SOURCE)),
                )
                rid = cur.lastrowid
                conn.executemany(
                    "INSERT OR IGNORE INTO chunk_identifiers(identifier, rid) VALUES (?, ?)",
                    [(i, rid) for i in c.get("identifiers") or []],
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO chunk_labels(label_lc, rid) VALUES (?, ?)",
                    [(lbl.strip().lower(), rid) for lbl in c.get("node_labels") or [] if lbl and lbl.strip()],
                )
                for field, table in FTS_TABLE.items():
                    tokens = analyze(c.get(field) or "")
                    if tokens:
                        conn.execute(f"INSERT INTO {table}(rowid, tokens) VALUES (?, ?)", (rid, fts_document(tokens)))
            conn.executemany(
                "INSERT INTO nodes(id, node_id, doc_id, run_id, source) VALUES (?,?,?,?,?)",
                [
                    (node_doc_id(batch.sha12, n["node_id"]), n["node_id"], n["doc_id"], run_id, json.dumps(n, ensure_ascii=False))
                    for n in batch.nodes
                ],
            )
            doc = batch.document
            conn.execute(
                "INSERT INTO documents(doc_id, run_id, source, graph, markdown) VALUES (?,?,?,?,?)",
                (
                    doc["doc_id"],
                    run_id,
                    _source_json(doc, ("graph", "markdown")),
                    json.dumps(doc.get("graph"), ensure_ascii=False) if doc.get("graph") is not None else None,
                    doc.get("markdown"),
                ),
            )

            # -- Zählung prüfen (wie _verify_counts)
            got = {
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id = ? AND run_id = ?", (res.doc_id, run_id)).fetchone()[0],
                "nodes": conn.execute("SELECT COUNT(*) FROM nodes WHERE doc_id = ? AND run_id = ?", (res.doc_id, run_id)).fetchone()[0],
            }
            expected = {"chunks": len(batch.chunks), "nodes": len(batch.nodes)}
            if got != expected:
                raise RuntimeError(f"count verification failed: expected {expected}, found {got}")

            # -- manifest (wie _finalize) + log + data_version
            history = list((prev_body or {}).get("history") or [])
            if prev and prev[0] != run_id:
                history.insert(0, {"run_id": prev[0], "replaced_at": utcnow_iso()})
            body = {
                "doc_id": res.doc_id,
                "status": "active",
                "run_id": run_id,
                "previous_run_id": prev[0] if prev else None,
                "doc_sha256": resp.document.sha256,
                "doc_name": resp.document.name,
                "doc_id_source": res.source,
                "owner": owner,
                "started_at": started,
                "finished_at": utcnow_iso(),
                "counts": batch.counts,
                "swept": swept,
                "embedding_model": emb.model,
                "mapping_version": MAPPING_VERSION,
                "history": history[: settings.ingest.history_keep],
            }
            conn.execute(
                "INSERT INTO manifest(doc_id, run_id, doc_sha256, status, body) VALUES (?,?,?,?,?) "
                "ON CONFLICT(doc_id) DO UPDATE SET run_id = excluded.run_id, doc_sha256 = excluded.doc_sha256, "
                "status = excluded.status, body = excluded.body",
                (res.doc_id, run_id, resp.document.sha256, "active", json.dumps(body, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO ingest_log(doc_id, run_id, owner, started_at, finished_at, status) VALUES (?,?,?,?,?,'active')",
                (res.doc_id, run_id, owner, started, body["finished_at"]),
            )
            conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'data_version'")
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            conn.execute(
                "INSERT INTO ingest_log(doc_id, run_id, owner, started_at, finished_at, status, error) VALUES (?,?,?,?,?,'failed',?)",
                (res.doc_id, run_id, owner, started, utcnow_iso(), str(exc)[:2000]),
            )
            raise
        return {
            "status": "replace" if prev else "active",
            "doc_id": res.doc_id,
            "doc_id_source": res.source,
            "run_id": run_id,
            "counts": batch.counts,
            "swept": swept,
            "duration_s": round(time.perf_counter() - t0, 3),
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- 3. Kanäle und Abrufe (§3.3)
# Die SQL-Texte sind Konstanten, damit das Notebook sie zeigen kann.
SQL_BM25 = """
SELECT f.rowid AS rid, -bm25({table}) AS score            -- bm25() ist negativ (kleiner = besser) → Vorzeichen drehen
FROM {table} f JOIN chunks c ON c.rid = f.rowid
WHERE {table} MATCH :q {doc_filter}
ORDER BY score DESC, {tie}
LIMIT :k"""

# Variante "lucene" (§3.3, Rückfall bei Abweichungen): FTS5 liefert nur die Kandidaten (MATCH), die Punktzahl wird in
# Python mit Lucenes BM25 berechnet — gleiche IDF, gleiche (gerundete) Dokumentlänge, gleiche float32-Arithmetik.
SQL_BM25_CANDIDATES = """
SELECT f.rowid AS rid, f.tokens
FROM {table} f JOIN chunks c ON c.rid = f.rowid
WHERE {table} MATCH :q {doc_filter}"""
SQL_BM25_STATS = "SELECT (SELECT COUNT(*) FROM {table}) AS n_docs, (SELECT SUM(cnt) FROM {table}_vocab) AS sum_ttf"
SQL_BM25_DOCFREQ = "SELECT term, doc FROM {table}_vocab WHERE term IN ({terms})"
LUCENE_K1, LUCENE_B = 1.2, 0.75


def _lucene_int_to_byte4(i: int) -> int:
    """``SmallFloat.intToByte4``: Lucene speichert die Feldlänge in einem Byte (4-Bit-Mantisse)."""
    num_free = 255 - _lucene_long_to_int4(2**31 - 1)
    return i if i < num_free else num_free + _lucene_long_to_int4(i - num_free)


def _lucene_long_to_int4(i: int) -> int:
    num_bits = i.bit_length()
    if num_bits < 4:
        return i
    shift = num_bits - 4
    return ((i >> shift) & 0x07) | ((shift + 1) << 3)


def _lucene_int4_to_long(i: int) -> int:
    bits, shift = i & 0x07, (i >> 3) - 1
    return bits if shift == -1 else (bits | 0x08) << shift


def lucene_doc_length(n_tokens: int) -> int:
    """Die Feldlänge, wie Lucene sie nach dem Byte-Encoding wieder liest (``dl, length of field (approximate)``)."""
    b = _lucene_int_to_byte4(n_tokens)
    num_free = 255 - _lucene_long_to_int4(2**31 - 1)
    return b if b < num_free else num_free + _lucene_int4_to_long(b - num_free)

SQL_EXACT = """
SELECT t.{col} AS term, c.rid, c.chunk_id
FROM {table} t JOIN chunks c ON c.rid = t.rid
WHERE t.{col} IN ({terms}) {doc_filter}"""

SQL_EXACT_IDF = """
SELECT (SELECT COUNT(DISTINCT rid) FROM {table}) AS n_docs_with_field,
       (SELECT COUNT(*) FROM {table} WHERE {col} = :term) AS n_docs_with_term"""

SQL_FETCH = "SELECT chunk_id, source FROM chunks WHERE chunk_id IN ({ids})"
SQL_VECTORS = "SELECT rid, chunk_id, doc_id, embedding FROM chunks WHERE embedding IS NOT NULL ORDER BY rid"
SQL_SOURCES = "SELECT rid, source FROM chunks WHERE rid IN ({rids})"
SQL_DOCUMENTS = "SELECT source, graph FROM documents ORDER BY doc_id"


def _doc_filter_sql(doc_ids: Collection[str] | None, params: dict[str, Any], alias: str = "c") -> str:
    if not doc_ids:
        return ""
    names = []
    for i, d in enumerate(sorted(set(doc_ids))):
        params[f"d{i}"] = d
        names.append(f":d{i}")
    return f"AND {alias}.doc_id IN ({', '.join(names)})"


def _lucene_idf(n_docs: int, n_term: int) -> float:
    """BM25-IDF wie Lucene: ln(1 + (N − n + 0,5) / (n + 0,5)); keyword-Felder haben keine Längennormierung."""
    return math.log(1.0 + (n_docs - n_term + 0.5) / (n_term + 0.5))


class VectorIndex:
    """Alle Vektoren als normierte float32-Matrix im Speicher; kNN = ``M @ q`` (exakt, §3.3)."""

    def __init__(self, conn: sqlite3.Connection):
        rows = conn.execute(SQL_VECTORS).fetchall()
        self.rids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
        self.chunk_ids = np.array([r[1] for r in rows], dtype=object)
        self.doc_ids = np.array([r[2] for r in rows], dtype=object)
        if rows:
            m = np.vstack([np.frombuffer(r[3], dtype="<f4") for r in rows]).astype(np.float32)
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            if not np.all(norms > 0):
                raise ValueError("zero vector in chunks.embedding")
            self.matrix = m / norms
        else:
            self.matrix = np.zeros((0, 0), dtype=np.float32)

    @property
    def nbytes(self) -> int:
        return int(self.matrix.nbytes)

    def knn(self, vector: Sequence[float], k: int, doc_ids: Collection[str] | None, *, tie_order: str = "rid") -> list[tuple[int, float]]:
        """(rid, score) absteigend; score = (1 + cos) / 2 wie OpenSearch ``cosinesimil`` (nur zum Vergleich — der
        Retriever nutzt ausschließlich Ränge)."""
        if self.matrix.size == 0:
            return []
        q = np.asarray(vector, dtype=np.float32)
        q /= np.linalg.norm(q)
        sims = self.matrix @ q
        if doc_ids:
            sims = np.where(np.isin(self.doc_ids, list(doc_ids)), sims, -np.inf)
        k = min(k, sims.shape[0])
        cand = np.argpartition(-sims, k - 1)[:k]
        tie = self.rids[cand] if tie_order == "rid" else self.chunk_ids[cand]
        cand = cand[np.lexsort((tie, -sims[cand]))]
        return [(int(self.rids[i]), float((1.0 + sims[i]) / 2.0)) for i in cand if np.isfinite(sims[i])]


class SqliteSearchClient:
    """Spricht die OpenSearch-Client-Methoden, die ``rag_retrieval`` benutzt. Eine Verbindung je Thread;
    Graph/Vektoren werden bei neuer ``data_version`` neu geladen (§3.6)."""

    def __init__(
        self,
        path: str | Path,
        *,
        prefix: str = "bhb",
        bm25_scoring: str = "lucene",
        tie_order: str = "chunk_id",
        exact_scoring: str = "count",
        doc_order: Sequence[str] | None = None,
    ):
        """``bm25_scoring``: ``"lucene"`` (Punktzahl in Python, Lucene-Formel) oder ``"fts5"`` (SQLite ``bm25()``).
        ``doc_order``: Reihenfolge der Handbücher in ``documents()`` (Standard: ``doc_id``). Der Retriever baut daraus den
        Graphen und nimmt bei handbuchübergreifenden Knoten Label/Aliase des zuerst geladenen Handbuchs; OpenSearch
        liefert sie in Indexreihenfolge. Für einen 1:1-Vergleich dieselbe Reihenfolge übergeben.
        ``exact_scoring`` für Identifier/Label: ``"count"`` = 1,0 je getroffenem Begriff — so bewertet OpenSearch die
        ``term``-Treffer auf den keyword-Feldern tatsächlich (per ``explain`` geprüft) — oder ``"idf"`` = Σ idf (§3.3).
        ``tie_order`` bei gleicher Punktzahl: ``"chunk_id"`` = deterministisch (§3.3) oder ``"rid"`` = Einfügereihenfolge.
        OpenSearch ordnet Gleichstände nach Lucene-Dokumentnummer, die von der Indexgeschichte abhängt — keine der
        beiden Konventionen reproduziert sie; der Vergleich bewertet Gleichstände deshalb mengenweise."""
        if bm25_scoring not in ("lucene", "fts5"):
            raise ValueError("bm25_scoring must be 'lucene' or 'fts5'")
        if tie_order not in ("rid", "chunk_id"):
            raise ValueError("tie_order must be 'rid' or 'chunk_id'")
        if exact_scoring not in ("count", "idf"):
            raise ValueError("exact_scoring must be 'count' or 'idf'")
        self.path = str(path)
        self.prefix = prefix
        self.bm25_scoring = bm25_scoring
        self.tie_order = tie_order
        self.exact_scoring = exact_scoring
        self.doc_order = list(doc_order) if doc_order else None
        self._local = threading.local()
        self._lock = threading.Lock()
        self._vectors: VectorIndex | None = None
        self._loaded_version = -1
        self._field_stats: dict[str, tuple[int, float]] = {}  # table -> (N, avgdl) für die aktuelle data_version
        self.last_sql: list[str] = []  # die zuletzt ausgeführten SQL-Texte (für das Notebook)
        self.indices = _Indices()
        self._ensure_loaded()

    # ---- Verbindungen / Laden
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = open_db(self.path, readonly=True)
            self._local.conn = c
        return c

    def data_version(self) -> int:
        row = self.conn().execute("SELECT value FROM meta WHERE key = 'data_version'").fetchone()
        return int(row[0]) if row else -1

    def _ensure_loaded(self) -> VectorIndex:
        v = self.data_version()
        with self._lock:
            if self._vectors is None or v != self._loaded_version:
                self._vectors = VectorIndex(self.conn())
                self._field_stats = {}
                self._loaded_version = v
            return self._vectors

    def field_stats(self, table: str) -> tuple[int, float]:
        """``(N, avgdl)`` eines FTS-Feldes = Lucenes ``docCount`` und ``sumTotalTermFreq / docCount`` (float32)."""
        self._ensure_loaded()
        if table not in self._field_stats:
            n_docs, sum_ttf = self.conn().execute(SQL_BM25_STATS.format(table=table)).fetchone()
            self._field_stats[table] = (int(n_docs or 0), float(np.float32((sum_ttf or 0) / n_docs)) if n_docs else 0.0)
        return self._field_stats[table]

    @property
    def vectors(self) -> VectorIndex:
        return self._ensure_loaded()

    # ---- die Kanäle
    def knn(self, vector: Sequence[float], k: int, doc_ids: Collection[str] | None = None) -> list[dict[str, Any]]:
        self.last_sql = ["-- kNN: numpy  sims = M @ q  (Maske auf doc_ids, Top-k)", SQL_SOURCES]
        return self._hits(self.vectors.knn(vector, k, doc_ids, tie_order=self.tie_order))

    def bm25(self, text: str, k: int, doc_ids: Collection[str] | None = None) -> list[dict[str, Any]]:
        tokens = analyze(text)
        if not tokens:
            self.last_sql = ["-- BM25: Frage besteht nur aus Stoppwörtern → Kanal leer"]
            return []
        params: dict[str, Any] = {"q": fts_query(sorted(set(tokens))), "k": k}
        flt = _doc_filter_sql(doc_ids, params)
        scores: dict[int, float] = {}
        self.last_sql = [f"-- Tokens: {tokens}", f"-- MATCH :q = {params['q']!r}", f"-- scoring: {self.bm25_scoring}"]
        for field, boost in BM25_FIELDS.items():
            table = FTS_TABLE[field]
            if self.bm25_scoring == "fts5":
                sql = SQL_BM25.format(table=table, doc_filter=flt, tie="c.rid" if self.tie_order == "rid" else "c.chunk_id")
                self.last_sql.append(sql)
                field_scores = {rid: s for rid, s in self.conn().execute(sql, params)}
            else:
                field_scores = self._lucene_bm25(table, tokens, params, flt)
            for rid, s in field_scores.items():
                scores[rid] = max(scores.get(rid, 0.0), boost * s)  # best_fields: Maximum über die Felder
        return self._hits(self._top(scores, k))

    def _lucene_bm25(self, table: str, tokens: list[str], params: dict[str, Any], flt: str) -> dict[int, float]:
        """Lucene ``BM25Similarity`` für ein Feld: ``Σ_t qtf·idf(t) · tf/(tf + k1·(1−b+b·dl/avgdl))`` in float32."""
        n_docs, avgdl = self.field_stats(table)
        if not n_docs:
            return {}
        query_tf = {}
        for t in tokens:  # doppelte Suchbegriffe zählen doppelt (Lucene fasst gleiche SHOULD-Klauseln zum Boost zusammen)
            query_tf[t] = query_tf.get(t, 0) + 1
        terms = sorted(query_tf)
        docfreq_sql = SQL_BM25_DOCFREQ.format(table=table, terms=", ".join(f":t{i}" for i in range(len(terms))))
        docfreq = dict(self.conn().execute(docfreq_sql, {f"t{i}": _fts_token_form(t) for i, t in enumerate(terms)}).fetchall())
        weight = {
            t: np.float32(query_tf[t]) * np.float32(_lucene_idf(n_docs, docfreq.get(_fts_token_form(t), 0)))
            for t in terms
            if docfreq.get(_fts_token_form(t))
        }
        if not weight:
            return {}
        cand_sql = SQL_BM25_CANDIDATES.format(table=table, doc_filter=flt)
        self.last_sql.extend([SQL_BM25_STATS.format(table=table), docfreq_sql, cand_sql])
        k1, b = np.float32(LUCENE_K1), np.float32(LUCENE_B)
        one = np.float32(1.0)
        out: dict[int, float] = {}
        for rid, stored in self.conn().execute(cand_sql, params):
            doc_tokens = stored.split(" ")
            dl = np.float32(lucene_doc_length(len(doc_tokens)))
            norm_inverse = one / (k1 * ((one - b) + b * dl / np.float32(avgdl)))
            score = np.float32(0.0)
            for t, w in weight.items():
                freq = doc_tokens.count(_fts_token_form(t))
                if freq:
                    score += w - w / (one + np.float32(freq) * norm_inverse)
            if score > 0:
                out[rid] = float(score)
        return out

    def exact(self, field: str, terms: Sequence[str], k: int, doc_ids: Collection[str] | None = None) -> list[dict[str, Any]]:
        table, col = ("chunk_identifiers", "identifier") if field == "identifiers" else ("chunk_labels", "label_lc")
        terms = sorted(set(terms))
        if not terms:
            return []
        params: dict[str, Any] = {f"t{i}": t for i, t in enumerate(terms)}
        flt = _doc_filter_sql(doc_ids, params)
        sql = SQL_EXACT.format(table=table, col=col, terms=", ".join(f":t{i}" for i in range(len(terms))), doc_filter=flt)
        self.last_sql = [sql, f"-- scoring: {self.exact_scoring}"]
        weight: dict[str, float] = dict.fromkeys(terms, 1.0)  # "count": 1,0 je Begriff, wie OpenSearch
        if self.exact_scoring == "idf":
            idf_sql = SQL_EXACT_IDF.format(table=table, col=col)
            self.last_sql.append(idf_sql)
            for t in terms:
                n_docs, n_term = self.conn().execute(idf_sql, {"term": t}).fetchone()
                weight[t] = _lucene_idf(n_docs, n_term) if n_term else 0.0
        scores: dict[int, float] = {}
        for term, rid, _chunk_id in self.conn().execute(sql, params):
            scores[rid] = scores.get(rid, 0.0) + weight[term]
        return self._hits(self._top(scores, k))

    def _top(self, scores: dict[int, float], k: int) -> list[tuple[int, float]]:
        """Absteigend nach Punktzahl; Gleichstand nach ``tie_order``."""
        if self.tie_order == "rid":
            ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        else:
            chunk_ids = self._chunk_ids(scores)
            ranked = sorted(scores.items(), key=lambda kv: (-kv[1], chunk_ids.get(kv[0], "")))
        return ranked[:k]

    def fetch(self, chunk_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not chunk_ids:
            return {}
        sql = SQL_FETCH.format(ids=", ".join("?" * len(chunk_ids)))
        self.last_sql = [sql]
        return {cid: json.loads(src) for cid, src in self.conn().execute(sql, list(chunk_ids))}

    def documents(self, *, include_graph: bool) -> list[dict[str, Any]]:
        out = []
        for src, graph in self.conn().execute(SQL_DOCUMENTS):
            d = json.loads(src)
            if include_graph:
                d["graph"] = json.loads(graph) if graph else None
            out.append(d)
        if self.doc_order:
            rank = {doc_id: i for i, doc_id in enumerate(self.doc_order)}
            out.sort(key=lambda d: (rank.get(d["doc_id"], len(rank)), d["doc_id"]))
        return out

    def _chunk_ids(self, scores: dict[int, float]) -> dict[int, str]:
        if not scores:
            return {}
        rids = list(scores)
        rows = self.conn().execute(f"SELECT rid, chunk_id FROM chunks WHERE rid IN ({', '.join('?' * len(rids))})", rids)
        return dict(rows.fetchall())

    def _hits(self, ranked: list[tuple[int, float]]) -> list[dict[str, Any]]:
        """``[(rid, score)]`` → OpenSearch-Trefferformat ``{"_id", "_score", "_source"}`` in gegebener Reihenfolge."""
        if not ranked:
            return []
        rids = [r for r, _ in ranked]
        sql = SQL_SOURCES.format(rids=", ".join("?" * len(rids)))
        src = {rid: json.loads(s) for rid, s in self.conn().execute(sql, rids)}
        return [{"_id": src[rid]["chunk_id"], "_score": score, "_source": src[rid]} for rid, score in ranked if rid in src]

    # ---- OpenSearch-Client-Schnittstelle (nur was rag_retrieval aufruft)
    def msearch(self, body: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        responses = []
        for header, query in zip(body[0::2], body[1::2], strict=True):
            t0 = time.perf_counter()
            try:
                hits = self._dispatch(query)
                responses.append({"took": int((time.perf_counter() - t0) * 1000), "hits": {"hits": hits}})
            except Exception as exc:  # wie OpenSearch: ein fehlender Kanal, nicht die ganze Anfrage
                responses.append({"error": {"reason": f"{type(exc).__name__}: {exc}"}})
        return {"responses": responses}

    def mget(self, body: dict[str, Any], **_: Any) -> dict[str, Any]:
        found = self.fetch(list(body.get("ids") or []))
        return {"docs": [{"_id": cid, "found": cid in found, **({"_source": found[cid]} if cid in found else {})} for cid in body["ids"]]}

    def search(self, index: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
        """``match_all`` auf documents/chunks/nodes/manifest mit ``_source``-Auswahl und ``size`` (Katalog, Anzeige)."""
        size = int(body.get("size", 10))
        src_opt = body.get("_source") or {}
        includes, excludes = set(src_opt.get("includes") or []), set(src_opt.get("excludes") or [])
        kind = index.rsplit("-", 1)[-1]
        if kind.startswith("documents"):
            rows = self.documents(include_graph=not includes or "graph" in includes)
        elif kind.startswith("chunks"):
            rows = [json.loads(s) for (s,) in self.conn().execute("SELECT source FROM chunks ORDER BY rid")]
        elif kind.startswith("nodes"):
            rows = [json.loads(s) for (s,) in self.conn().execute("SELECT source FROM nodes ORDER BY doc_id, node_id")]
        elif kind.startswith("manifest"):
            rows = [json.loads(b) for (b,) in self.conn().execute("SELECT body FROM manifest ORDER BY doc_id")]
        else:
            raise ValueError(f"unknown index {index}")
        hits = []
        for r in rows[:size]:
            s = {k: v for k, v in r.items() if (not includes or k in includes) and k not in excludes}
            hits.append({"_id": r.get("chunk_id") or r.get("doc_id"), "_source": s})
        return {"hits": {"total": {"value": len(rows)}, "hits": hits}}

    def _dispatch(self, query_body: dict[str, Any]) -> list[dict[str, Any]]:
        """Die vier Request-Bodies aus ``rag_retrieval.search`` auf die Kanäle abbilden."""
        k = int(query_body.get("size", 10))
        q = query_body["query"]
        if "knn" in q:
            clause = q["knn"]["embedding"]
            return self.knn(clause["vector"], int(clause.get("k", k)), _terms_filter(clause.get("filter")))
        doc_ids = None
        if "bool" in q and "must" in q["bool"]:
            doc_ids = _terms_filter((q["bool"].get("filter") or [None])[0])
            q = q["bool"]["must"][0]
        if "multi_match" in q:
            return self.bm25(q["multi_match"]["query"], k, doc_ids)
        if "bool" in q and "should" in q["bool"]:
            terms: dict[str, list[str]] = {}
            for clause in q["bool"]["should"]:
                (field, value), = clause["term"].items()
                terms.setdefault(field, []).append(value)
            (field, values), = terms.items()
            return self.exact(field, values, k, doc_ids)
        raise ValueError(f"unsupported query: {list(q)}")


class _Indices:
    def exists_alias(self, name: str) -> bool:  # für Retriever.check()
        return True


def _fts_token_form(token: str) -> str:
    """Wie der Token in der FTS5-Tabelle steht (``de_analysis.fts_document``: ASCII-Apostroph → ’)."""
    return token.replace("'", "’")


def _terms_filter(flt: dict[str, Any] | None) -> list[str] | None:
    if not flt:
        return None
    return list(flt["terms"]["doc_id"])


# --------------------------------------------------------------------------- Status / Prüfung
def status(path: str | Path) -> dict[str, Any]:
    conn = open_db(path, readonly=True)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        tables = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("chunks", "chunk_identifiers", "chunk_labels", "nodes", "documents", "manifest", "ingest_log")
        }
        fts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in FTS_TABLE.values()}
        per_doc = [
            {"doc_id": d, "chunks": c, "nodes": conn.execute("SELECT COUNT(*) FROM nodes WHERE doc_id = ?", (d,)).fetchone()[0]}
            for d, c in conn.execute("SELECT doc_id, COUNT(*) FROM chunks GROUP BY doc_id ORDER BY doc_id")
        ]
        manifests = [json.loads(b) for (b,) in conn.execute("SELECT body FROM manifest ORDER BY doc_id")]
        shared = conn.execute("SELECT COUNT(*) FROM (SELECT node_id FROM nodes GROUP BY node_id HAVING COUNT(DISTINCT doc_id) > 1)").fetchone()[0]
        size = sum(Path(str(path) + suffix).stat().st_size for suffix in ("", "-wal", "-shm") if Path(str(path) + suffix).exists())
        return {
            "meta": meta,
            "tables": tables,
            "fts": fts,
            "per_doc": per_doc,
            "manifests": manifests,
            "cross_document_node_ids": shared,
            "file_bytes": size,
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
        }
    finally:
        conn.close()


def fts_vocabulary(path: str | Path, field: str = "text") -> set[str]:
    """Die Tokens, wie FTS5 sie gespeichert hat (Abnahme §3.9: müssen den Python-Tokens entsprechen)."""
    conn = open_db(path, readonly=True)
    try:
        return {t for (t,) in conn.execute(f"SELECT term FROM {FTS_TABLE[field]}_vocab")}
    finally:
        conn.close()
