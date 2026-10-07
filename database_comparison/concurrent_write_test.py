"""Chat und Indexer im selben Container auf derselben SQLite-Datei (SUCHSPEICHER-VERGLEICH.md §3.5/§3.6).

Szenario 1: 10 Lese-Threads (kNN + BM25 + Exakt + fetch) laufen ununterbrochen, während ein ZWEITER PROZESS alle
Handbücher aus RUN_DIRS erzwungen neu schreibt. Gezählt werden Fehler, Latenz je Phase, Top-1 und die gesehenen
``data_version``-Werte (Neuladen der Vektormatrix). Szenario 2: zwei Indexer-Prozesse gleichzeitig (BEGIN IMMEDIATE).
Arbeitet auf einer KOPIE (SQLite-Backup-API) unter data/conc/, die Notebook-Datei bleibt unberührt.

    .venv/bin/python concurrent_write_test.py
"""
import collections, os, resource, sqlite3, statistics, subprocess, sys, threading, time

DBC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DBC); os.chdir(DBC)
from dotenv import load_dotenv; load_dotenv(".env")  # noqa: E402
import numpy as np, sqlite_store as st  # noqa: E402

SRC = os.environ.get("SQLITE_PATH", "data/search.db")
COPY = os.path.join(DBC, "data", "conc", "search.db")
os.makedirs(os.path.dirname(COPY), exist_ok=True)
for suf in ("", "-wal", "-shm"):
    if os.path.exists(COPY + suf): os.remove(COPY + suf)
with sqlite3.connect(SRC) as src, sqlite3.connect(COPY) as dst:
    src.backup(dst)  # konsistente Kopie, auch wenn gerade geschrieben wird

client = st.SqliteSearchClient(COPY)
ro = st.open_db(COPY, readonly=True)
q = np.frombuffer(ro.execute("SELECT embedding FROM chunks WHERE embedding IS NOT NULL LIMIT 1 OFFSET 100").fetchone()[0], dtype="<f4").tolist()
QS = ["Wer ist verantwortlich für SOP-6?", "Welche Störung meldet der Dispatcher?", "Wie wird ein Systemereignis quittiert?",
      "Welche Rolle hat der Schichtleiter?", "Wie lautet die Eskalationsstufe bei Ausfall?"]
cid = lambda h: h.get("_id") or h.get("chunk_id")
phase = "vorher"; stop = threading.Event()
rec = collections.defaultdict(list); errs = []; top1 = collections.defaultdict(set); versions = collections.defaultdict(set)

def worker(i):
    while not stop.is_set():
        t = time.perf_counter(); ph = phase
        try:
            h = client.knn(q, 20); client.bm25(QS[i % len(QS)], 20); client.exact("label", ["dispatcher"], 20)
            client.fetch([cid(x) for x in h[:5]])
            rec[ph].append((time.perf_counter() - t) * 1000); top1[ph].add(cid(h[0])); versions[ph].add(client._loaded_version)
        except Exception as e:  # noqa: BLE001
            errs.append((ph, repr(e)))

INGEST = f"""
import os, sys, time; sys.path.insert(0, {DBC!r}); os.chdir({DBC!r})
from dotenv import load_dotenv; load_dotenv('.env')
import sqlite_store as st
from opensearch_index.ontology import load_ontology
from opensearch_index.settings import Settings as OsiSettings
s = OsiSettings(); o = load_ontology(os.environ['OSI__ONTOLOGY__PATH'])
for d in RUNS:
    t = time.perf_counter(); r = st.ingest({COPY!r}, d, settings=s, ontology=o, force=True)
    print('INGEST', d, r['status'], f'{{time.perf_counter() - t:.2f}}s', flush=True)
"""
runs = os.environ["RUN_DIRS"].split(",")
all_runs = INGEST.replace("for d in RUNS:", f"for d in {runs!r}:")
one_run = INGEST.replace("for d in RUNS:", f"for d in {runs[:1]!r}:")

threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(10)]
[t.start() for t in threads]; time.sleep(3)
phase = "während"; t0 = time.perf_counter()
p = subprocess.run([sys.executable, "-c", all_runs], capture_output=True, text=True)
dur = time.perf_counter() - t0
print(p.stdout.strip()); print(p.stderr.strip()[-1500:])
child_peak_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
phase = "nachher"; time.sleep(3); stop.set(); [t.join(timeout=5) for t in threads]

print(f"\nSzenario 1: 10 Lese-Threads, Indexer-Prozess schreibt {len(runs)} Handbücher (force) — Dauer {dur:.1f} s, Indexer-Prozess Peak-RSS {child_peak_mb:.0f} MB")
print(f"{'Phase':8} {'Aufrufe':>8} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8}  top1-chunk  data_version")
for ph in ("vorher", "während", "nachher"):
    L = rec[ph]
    if L: print(f"{ph:8} {len(L):8d} {statistics.median(L):8.0f} {np.percentile(L, 95):8.0f} {max(L):8.0f}  {sorted(top1[ph])}  {sorted(versions[ph])}")
print("Fehler:", len(errs), errs[:3])

t0 = time.perf_counter()
ps = [subprocess.Popen([sys.executable, "-c", one_run], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
outs = [pp.communicate() for pp in ps]
print(f"\nSzenario 2: zwei Indexer-Prozesse gleichzeitig, gleicher Lauf — gesamt {time.perf_counter() - t0:.1f} s")
for (o, e), pp in zip(outs, ps): print(" ", o.strip() or e.strip()[-300:], "| rc", pp.returncode)
c = sqlite3.connect(COPY)
pc, fl, ps_ = [c.execute(f"PRAGMA {x}").fetchone()[0] for x in ("page_count", "freelist_count", "page_size")]
wal = os.path.getsize(COPY + "-wal") / 1e6 if os.path.exists(COPY + "-wal") else 0.0
print(f"Datei: {pc * ps_ / 1e6:.1f} MB ({fl * ps_ / 1e6:.1f} MB frei), WAL {wal:.1f} MB, integrity_check: {c.execute('PRAGMA integrity_check').fetchone()[0]}")
