"""Skalierung der eingebetteten Suche: Chunks vervielfacht (gleiche Texte, andere doc_ids) → 1×=401, 10×≈4 000 (≈40 Handbücher), 30×≈12 000 (≈100 Handbücher)."""
import os, sys, sqlite3, time
DBC=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, DBC); os.chdir(DBC)
from dotenv import load_dotenv; load_dotenv(".env")
import numpy as np, sqlite_store as st, nbhelpers as nb, de_analysis as da
from rag_retrieval import search as rs
OUT=os.path.join(DBC, "data", "scale"); os.makedirs(OUT, exist_ok=True)
QS = ["Wer ist verantwortlich für SOP-ZSD-06?","Wer ist verantwortlich für SOP-6?","Wer ist für die Erneuerung der TLS-Zertifikate im Event-System zuständig?",
      "Was passiert, wenn Vault versiegelt ist?","In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?","Welche Firewall-Regeln braucht das Event-System?",
      "Wie wird ein Kafka-Topic bereinigt?","Welche Alerts gibt es für den Dispatcher?","Wer vertritt Tobias Reinhardt?","Was kostet ein Kaffee in Berlin?"]
def build(factor):
    path=f"{OUT}/search_x{factor}.db"
    for suf in ("","-wal","-shm"):
        if os.path.exists(path+suf): os.remove(path+suf)
    src=sqlite3.connect("data/search.db"); dst=sqlite3.connect(path); src.backup(dst); src.close()
    base=dst.execute("SELECT MAX(rid) FROM chunks").fetchone()[0]
    t0=time.perf_counter()
    for i in range(1, factor):
        off=base*i
        dst.execute(f"INSERT INTO chunks(rid, chunk_id, doc_id, run_id, embedding, bboxes, source) SELECT rid+{off}, chunk_id||'-{i}', doc_id||'-{i}', run_id, embedding, bboxes, source FROM chunks WHERE rid <= {base}")
        dst.execute(f"INSERT INTO chunk_identifiers(identifier, rid) SELECT identifier, rid+{off} FROM chunk_identifiers WHERE rid <= {base}")
        dst.execute(f"INSERT INTO chunk_labels(label_lc, rid) SELECT label_lc, rid+{off} FROM chunk_labels WHERE rid <= {base}")
        for t in ("fts_text","fts_body","fts_caption"):
            dst.execute(f"INSERT INTO {t}(rowid, tokens) SELECT rowid+{off}, tokens FROM {t} WHERE rowid <= {base}")
    dst.execute("UPDATE meta SET value='99' WHERE key='data_version'"); dst.commit()
    n=dst.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    cands=[dst.execute("SELECT COUNT(*) FROM fts_text WHERE fts_text MATCH ?", (da.fts_query(da.analyze(q)),)).fetchone()[0] for q in QS if da.analyze(q)]
    dst.close()
    return path, n, time.perf_counter()-t0, int(np.mean(cands)), os.path.getsize(path)/1e6
ro=sqlite3.connect("data/search.db")
qvecs=[np.frombuffer(r[0], "<f4").tolist() for r in ro.execute("SELECT embedding FROM chunks WHERE embedding IS NOT NULL ORDER BY rid LIMIT 10 OFFSET 50")]
print(f"{'Faktor':>6} {'Chunks':>7} {'Datei MB':>8} {'Kand./Frage':>11} {'Matrix MiB':>10} {'Laden ms':>8}  Variante   1 Thread p50   10 Threads p50   /s")
for factor in (1, 10, 30):
    path, n, build_s, cands, mb = build(factor)
    for name, kw in (("Lucene", {}), ("fts5  ", {"bm25_scoring": "fts5"})):
        client=st.SqliteSearchClient(path, **kw)
        t0=time.perf_counter(); m=client.vectors.matrix; load_ms=(time.perf_counter()-t0)*1000
        def call(i, client=client):
            q=QS[i%10]; rs.run_channels(client, "bhb-chunks", {"knn": rs.knn_body(qvecs[i%10], 20), "bm25": rs.bm25_body(q, 20)})
        r1=nb.concurrent(call, workers=1, calls=50); r10=nb.concurrent(call, workers=10, calls=50)
        print(f"{factor:>6} {n:>7} {mb:>8.1f} {cands:>11} {m.nbytes/2**20:>10.1f} {load_ms:>8.0f}  {name}   {r1['p50_ms']:>9.0f} ms   {r10['p50_ms']:>11.0f} ms   {r10['calls_per_s']:>4.0f}")
