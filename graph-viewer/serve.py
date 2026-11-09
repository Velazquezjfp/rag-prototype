#!/usr/bin/env python3
"""Graph-Viewer: kleiner HTTP-Server (nur Python-Standardbibliothek) über den Laufordnern in ``out/``.

Liefert ``index.html`` und ``vendor/``, listet Graph-Dateien bei jedem Aufruf neu (nichts wird gecacht),
fasst mehrere Graphen so zusammen wie der Chat (``rag_retrieval.graph.GraphStore``: Knoten nach ``id``,
eine gezeichnete Kante pro ``(source, target, type, polarity)`` mit allen Vorkommen) und liefert Chunk-Texte
für die Provenienz nach.

Start:  python3 graph-viewer/serve.py [--port 8010] [--root out]
Aufruf: http://localhost:8010/  (auf einem anderen Rechner: ssh -N -L 8010:localhost:8010 <user>@<rechner>)

Schutz: bindet standardmäßig nur an 127.0.0.1; Anfragen mit fremdem Host-Header werden abgewiesen (DNS-Rebinding);
die Seite kommt mit einer Content-Security-Policy, die nur Skripte von diesem Server und das Inline-Skript von
``index.html`` (per Hash) zulässt.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"
MAX_JSON_BYTES = 64 * 1024 * 1024  # größere JSON-Dateien werden beim Scannen übersprungen
SCAN_DEPTH = 2  # out/<lauf>/graph.json (1) oder out/<charge>/<lauf>/graph.json (2)
CHUNK_FIELDS = ("chunk_id", "text", "heading_breadcrumb", "page_numbers", "kind", "caption", "dom_paths")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
WILDCARD_BINDS = ("0.0.0.0", "::", "")
INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)  # nur Skripte ohne Attribute (die mit src= sind 'self')


# --------------------------------------------------------------------------- Graphen lesen


def extract_graph(data: Any) -> dict[str, Any] | None:
    """Node-Link-Dict aus ``graph.json`` (``nodes``/``edges`` oben) oder ``response.json`` (unter ``graph``)."""
    if not isinstance(data, dict):
        return None
    g = data.get("graph") if isinstance(data.get("graph"), dict) else data
    if isinstance(g.get("nodes"), list) and isinstance(g.get("edges"), list):
        return g
    return None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_path(root: Path, rel: str) -> Path:
    """``rel`` unterhalb von ``root`` auflösen; alles außerhalb wird abgewiesen."""
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise PermissionError(rel)
    return p


def _json_files(root: Path, depth: int):
    stack = [(root, 0)]
    while stack:
        d, level = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.name.startswith("."):
                continue
            if p.is_dir() and level < depth:
                stack.append((p, level + 1))
            elif p.is_file() and p.suffix == ".json" and level >= 1:
                yield p


def list_graphs(root: Path) -> dict[str, Any]:
    """Ordner unter ``root`` mit ihren Graph-Dateien; Erkennung durch Parsen (nur Dateien mit nodes+edges)."""
    folders: dict[str, list[dict[str, Any]]] = {}
    for p in _json_files(root, SCAN_DEPTH):
        size = p.stat().st_size
        if size > MAX_JSON_BYTES:
            continue
        try:
            g = extract_graph(read_json(p))
        except (ValueError, OSError):
            continue
        if g is None:
            continue
        rel = p.relative_to(root)
        folders.setdefault(rel.parent.as_posix(), []).append(
            {"path": rel.as_posix(), "name": p.name, "nodes": len(g["nodes"]), "edges": len(g["edges"]), "size": size}
        )
    return {"root": str(root), "folders": [{"name": k, "files": v} for k, v in sorted(folders.items())]}


# --------------------------------------------------------------------------- zusammenführen


def edge_id(e: dict[str, Any]) -> str:
    """Kanten-Id wie im Indexer (``opensearch_index.identity.edge_id``): sha256[:16] über die Aussage."""
    prov = e.get("provenance") or {}
    payload = [
        e.get("source"),
        e.get("target"),
        e.get("type"),
        e.get("polarity") or "positive",
        e.get("qualifier") or "",
        e.get("quote") or "",
        sorted(prov.get("chunk_ids") or []),
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def merge_graphs(root: Path, rel_paths: list[str]) -> dict[str, Any]:
    """Vereinigung mehrerer Graphen: Knoten nach ``id`` (erste Datei bestimmt Typ/Label, alle Vorkommen bleiben
    nebeneinander), Kanten einmal pro ``(source, target, type, polarity)`` mit ihren Vorkommen je Handbuch."""
    nodes: dict[str, dict[str, Any]] = {}
    pending: list[tuple[str, dict[str, Any]]] = []
    files_meta: list[dict[str, Any]] = []
    for rel in rel_paths:
        p = safe_path(root, rel)
        g = extract_graph(read_json(p))
        if g is None:
            raise ValueError(f"{rel}: keine Graph-Datei (nodes/edges fehlen)")
        doc = p.parent.relative_to(root).as_posix()
        if doc == ".":
            doc = p.stem
        for n in g["nodes"]:
            nid = n.get("id")
            if not nid:
                continue
            m = nodes.get(nid)
            if m is None:
                m = nodes[nid] = {"id": nid, "type": n.get("type") or "?", "label": n.get("label") or nid, "docs": [], "occurrences": []}
            if doc not in m["docs"]:
                m["docs"].append(doc)
            m["occurrences"].append(
                {
                    "doc": doc,
                    "label": n.get("label"),
                    "type": n.get("type"),
                    "aliases": n.get("aliases") or [],
                    "attributes": n.get("attributes") or {},
                    "quote": n.get("quote"),
                    "provenance": n.get("provenance") or {},
                }
            )
        for e in g["edges"]:
            pending.append((doc, e))
        files_meta.append({"path": rel, "doc": doc, "nodes": len(g["nodes"]), "edges": len(g["edges"])})

    edges: dict[str, dict[str, Any]] = {}
    dropped = 0
    for doc, e in pending:
        s, t = e.get("source"), e.get("target")
        if s not in nodes or t not in nodes:
            dropped += 1
            continue
        typ = e.get("type") or "?"
        pol = e.get("polarity") or "positive"
        key = f"{s}|{t}|{typ}|{pol}"
        m = edges.get(key)
        if m is None:
            m = edges[key] = {
                "id": "e" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12],
                "source": s,
                "target": t,
                "type": typ,
                "polarity": pol,
                "docs": [],
                "occurrences": [],
            }
        if doc not in m["docs"]:
            m["docs"].append(doc)
        m["occurrences"].append(
            {
                "doc": doc,
                "id": edge_id(e),
                "qualifier": e.get("qualifier"),
                "quote": e.get("quote"),
                "properties": e.get("properties") or {},
                "provenance": e.get("provenance") or {},
            }
        )

    degree: Counter[str] = Counter()
    for m in edges.values():
        degree[m["source"]] += 1
        degree[m["target"]] += 1
    for m in nodes.values():
        m["degree"] = degree.get(m["id"], 0)

    meta = {
        "files": files_meta,
        "node_ids": len(nodes),
        "edge_count": len(edges),
        "shared_nodes": sum(1 for m in nodes.values() if len(m["docs"]) > 1),
        "isolated_nodes": sum(1 for m in nodes.values() if m["degree"] == 0),
        "negative_edges": sum(1 for m in edges.values() if m["polarity"] == "negative"),
        "dropped_edges": dropped,
        "nodes_by_type": dict(Counter(m["type"] for m in nodes.values()).most_common()),
        "edges_by_type": dict(Counter(m["type"] for m in edges.values()).most_common()),
    }
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "meta": meta}


# --------------------------------------------------------------------------- Provenienz-Texte


def load_chunks(root: Path, folder: str, ids: list[str]) -> list[dict[str, Any]]:
    """Chunk-Texte (ohne Embeddings) aus ``<ordner>/chunks.json`` oder ``response.json`` für die gegebenen Ids."""
    d = safe_path(root, folder)
    chunks: Any = None
    if (d / "chunks.json").is_file():
        chunks = read_json(d / "chunks.json")
    elif (d / "response.json").is_file():
        chunks = read_json(d / "response.json").get("chunks")
    wanted = set(ids)
    out = []
    for c in chunks or []:
        if isinstance(c, dict) and c.get("chunk_id") in wanted:
            out.append({k: c.get(k) for k in CHUNK_FIELDS})
    return out


# --------------------------------------------------------------------------- Schutz


def host_name(header: str | None) -> str:
    """Host-Name aus dem Host-Header, ohne Port: ``localhost:8010`` -> ``localhost``, ``[::1]:8010`` -> ``::1``."""
    h = (header or "").strip().lower()
    if h.startswith("["):
        return h[1 : h.index("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def allowed_hosts(bind: str, extra: list[str]) -> frozenset[str]:
    """Erlaubte Host-Header: lokal, die Bind-Adresse (falls konkret) und alles aus ``--allow-host``."""
    names = set(LOCAL_HOSTS) | {e.strip().lower().strip("[]") for e in extra if e.strip()}
    if bind not in WILDCARD_BINDS:
        names.add(bind.lower())
    return frozenset(names)


def csp_for(html: str) -> str:
    """Content-Security-Policy für ``index.html``. Der Hash des Inline-Skripts wird bei jedem Aufruf neu berechnet,
    Änderungen an der Seite brauchen also keinen Neustart. Inline-Styles bleiben erlaubt (``style=""`` in der
    Detailspalte; alle Werte darin sind escaped), Inline-Event-Handler (``onclick=``) nicht."""
    html = html.replace("\r\n", "\n").replace("\r", "\n")  # der HTML-Parser normalisiert Zeilenenden vor dem Hashen
    hashes = [
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'"
        for body in INLINE_SCRIPT.findall(html)
    ]
    return "; ".join(
        [
            "default-src 'none'",
            " ".join(["script-src 'self'", *hashes]),
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )


# --------------------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    root: Path = HERE.parent / "out"
    allowed: frozenset[str] = LOCAL_HOSTS
    server_version = "GraphViewer/1.0"

    def do_GET(self) -> None:  # noqa: N802 (http.server-Konvention)
        if host_name(self.headers.get("Host")) not in self.allowed:
            self._error(403, "Host nicht erlaubt (Schutz gegen DNS-Rebinding); weitere Namen mit --allow-host freigeben")
            return
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                html = (HERE / "index.html").read_bytes()
                csp = csp_for(html.decode("utf-8"))
                self._send(200, html, "text/html; charset=utf-8", {"Content-Security-Policy": csp})
            elif u.path.startswith("/vendor/"):
                f = VENDOR / Path(u.path).name
                if f.is_file():
                    self._file(f, "application/javascript; charset=utf-8")
                else:
                    self._error(404, "Datei nicht gefunden")
            elif u.path == "/api/list":
                self._json(list_graphs(self.root))
            elif u.path == "/api/graph":
                files = q.get("f") or []
                if not files:
                    self._error(400, "Parameter f fehlt (eine oder mehrere Graph-Dateien)")
                else:
                    self._json(merge_graphs(self.root, files))
            elif u.path == "/api/chunks":
                folder = (q.get("folder") or ["."])[0]
                ids = [i for v in q.get("ids", []) for i in v.split(",") if i]
                self._json(load_chunks(self.root, folder, ids))
            else:
                self._error(404, "nicht gefunden")
        except PermissionError:
            self._error(404, "Pfad liegt außerhalb des Wurzelverzeichnisses")
        except FileNotFoundError as exc:
            self._error(404, f"Datei fehlt: {exc.filename or exc}")
        except ValueError as exc:
            self._error(400, str(exc))

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj: Any) -> None:
        self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, path: Path, ctype: str) -> None:
        self._send(200, path.read_bytes(), ctype)

    def _error(self, status: int, message: str) -> None:
        self._send(status, json.dumps({"error": message}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Graph-Viewer über den Laufordnern (graph.json / response.json).")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind-Adresse (Standard: nur lokal, von anderen Rechnern per SSH-Tunnel). "
                         "0.0.0.0 = alle Schnittstellen, ohne Anmeldung und unverschlüsselt")
    ap.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                    help="weiterer erlaubter Host-Name/IP im Host-Header, z. B. die IP der VM bei --host 0.0.0.0 (wiederholbar)")
    ap.add_argument("--root", type=Path, default=HERE.parent / "out", help="Verzeichnis mit den Laufordnern (Standard: ../out)")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    if not root.is_dir():
        print(f"Wurzelverzeichnis fehlt: {root}", file=sys.stderr)
        return 2
    Handler.root = root
    Handler.allowed = allowed_hosts(a.host, a.allow_host)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    shown = "localhost" if a.host in WILDCARD_BINDS or a.host.lower() in LOCAL_HOSTS else a.host
    print(f"Graph-Viewer läuft: http://{shown}:{a.port}/   Wurzel: {root}   (Beenden mit Strg+C)", flush=True)
    if a.host in WILDCARD_BINDS:
        print(f"Achtung: lauscht auf allen Schnittstellen, ohne Anmeldung. Erlaubte Host-Namen: {', '.join(sorted(Handler.allowed))}",
              file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
