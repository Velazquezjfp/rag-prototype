"""Echter Retriever: OpenSearch vs SQLite mit Lucene-Formel vs SQLite mit FTS5-eigenem bm25() — 10 Batch-Fragen."""
import os, sys
DBC=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, DBC); os.chdir(DBC)
from dotenv import load_dotenv; load_dotenv(".env")
import pandas as pd, sqlite_store as st, nbhelpers as nb
from opensearch_index.client import make_client
from rag_retrieval.settings import Settings as RagSettings
from rag_retrieval.embed import QuestionEmbedder
from rag_retrieval.retriever import Retriever
from rag_retrieval import search as rs
QS = ["Wer ist verantwortlich für SOP-ZSD-06?","Wer ist verantwortlich für SOP-6?","Wer ist für die Erneuerung der TLS-Zertifikate im Event-System zuständig?",
      "Was passiert, wenn Vault versiegelt ist?","In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?","Welche Firewall-Regeln braucht das Event-System?",
      "Wie wird ein Kafka-Topic bereinigt?","Welche Alerts gibt es für den Dispatcher?","Wer vertritt Tobias Reinhardt?","Was kostet ein Kaffee in Berlin?"]
rag = RagSettings(); emb = QuestionEmbedder.from_settings(rag.embedding); osc = make_client(rag.opensearch)
order = [d["doc_id"] for d in rs.fetch_documents(osc, "bhb-documents", include_graph=False)]
res_os = {q: Retriever(rag, client=osc, embedder=emb).retrieve(q) for q in QS}
KEYS = ("Guardrail gleich", "Überschneidung Top-10", "Top-10 gleiche Reihenfolge", "Fakten gleich", "Entitäten gleich", "Zitate gleich", "Kontext gleich")
for name, c in (("Lucene-Formel", st.SqliteSearchClient("data/search.db", doc_order=order)),
                ("FTS5 bm25()  ", st.SqliteSearchClient("data/search.db", bm25_scoring="fts5", doc_order=order))):
    r = Retriever(rag, client=c, embedder=emb)
    df = pd.DataFrame([nb.compare_results(res_os[q], r.retrieve(q), names=("OpenSearch", "SQLite")) for q in QS])
    summary = {k: (f"{int(df[k].sum())}/{len(df)}" if df[k].dtype == bool else f"{df[k].mean():.2f}") for k in KEYS}
    summary["Fakten nur OS/SQLite"] = f"{int(df['Fakten nur OpenSearch'].sum())}/{int(df['Fakten nur SQLite'].sum())}"
    print(name, summary)
