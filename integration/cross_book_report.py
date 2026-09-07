#!/usr/bin/env python3
"""Is a newly ingested manual an island, or connected to the others? Read every graph blob from bhb-documents,
union them by node_id and report what two or more books share (SPEC §4.4 / §11.3, graph-retrieval-patterns §3.4).

    ../opensearch-index/.venv/bin/python cross_book_report.py            # settings from opensearch-index/.env / OSI__*
    ../opensearch-index/.venv/bin/python cross_book_report.py --json

Reports: books present; node ids shared by several books (by class, with each book's label); cross-book edges
(edges whose other endpoint also exists in another book); Document nodes and who carries them; partner tickets;
the expected_graph_shape items two books can answer (documented cycle, shared persons, negative edges, hubs).
Read-only; needs only the opensearch-index venv.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OSI_DIR = HERE.parent / "opensearch-index"
sys.path.insert(0, str(OSI_DIR / "src"))
os.environ.setdefault("OSI_CONFIG", str(OSI_DIR / "config.yaml"))

from opensearch_index.client import make_client
from opensearch_index.identity import norm_key
from opensearch_index.mappings import IndexNames
from opensearch_index.settings import Settings

# from ontology.yaml -> expected_graph_shape (kept literal here so the report needs no ontology path)
EXPECTED_CYCLE = ["Vault", "CaaS-Plattform", "BAVD Issuing CA 3", "Vault"]
HUB_SYSTEMS = ["CaaS-Plattform", "Zentrale Sicherheitsdienste"]


def load_books(client, names: IndexNames) -> list[dict[str, Any]]:
    res = client.search(
        index=names.documents,
        body={"size": 100, "_source": ["doc_id", "name", "counts", "run_id", "graph"], "query": {"match_all": {}}},
    )
    return [h["_source"] for h in res["hits"]["hits"]]


def build_union(books: list[dict[str, Any]]) -> dict[str, Any]:
    """node_id -> {type, labels: {doc_id: label}, aliases}, plus all edges tagged with their book."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for b in books:
        g = b.get("graph") or {}
        for n in g.get("nodes", []):
            entry = nodes.setdefault(n["id"], {"type": n["type"], "labels": {}, "aliases": set(), "attrs": {}})
            entry["labels"][b["doc_id"]] = n["label"]
            entry["aliases"].update(n.get("aliases") or [])
            entry["attrs"][b["doc_id"]] = n.get("attributes") or {}
        for e in g.get("edges", []):
            edges.append({**e, "doc_id": b["doc_id"]})
    return {"nodes": nodes, "edges": edges}


def matches(entry: dict[str, Any], wanted: str, *, exact: bool) -> bool:
    w = norm_key(wanted)
    for label in list(entry["labels"].values()) + list(entry["aliases"]):
        k = norm_key(label)
        if k == w or (not exact and w in k):
            return True
    return False


def find_nodes(nodes: dict[str, dict[str, Any]], wanted: str, types: set[str] | None = None) -> list[str]:
    """Exact (casefolded) label/alias matches first; substring matches only when nothing matches exactly, so that
    'Vault' does not pull in every vault-* host."""
    pool = [(nid, e) for nid, e in nodes.items() if types is None or e["type"] in types]
    exact = [nid for nid, e in pool if matches(e, wanted, exact=True)]
    return exact or [nid for nid, e in pool if matches(e, wanted, exact=False)]


def report(books: list[dict[str, Any]]) -> dict[str, Any]:
    union = build_union(books)
    nodes, edges = union["nodes"], union["edges"]
    book_ids = sorted(b["doc_id"] for b in books)
    out: dict[str, Any] = {
        "books": [
            {"doc_id": b["doc_id"], "name": b.get("name"), "counts": b.get("counts"), "run_id": str(b.get("run_id"))[:12]}
            for b in sorted(books, key=lambda b: b["doc_id"])
        ]
    }

    # ---- shared nodes
    shared = {nid: e for nid, e in nodes.items() if len(e["labels"]) >= 2}
    by_type = Counter(e["type"] for e in shared.values())
    out["shared_nodes"] = {
        "count": len(shared),
        "by_type": dict(by_type.most_common()),
        "examples": [
            {"node_id": nid, "type": e["type"], "labels": e["labels"]}
            for nid, e in sorted(shared.items(), key=lambda kv: (kv[1]["type"], kv[0]))[:40]
        ],
    }

    # ---- Document nodes: who carries which manual
    docs = {nid: e for nid, e in nodes.items() if e["type"] == "Document"}
    out["document_nodes"] = sorted(
        (
            {
                "node_id": nid,
                "doc_id": next((a.get("doc_id") for a in e["attrs"].values() if a.get("doc_id")), None),
                "carried_by": sorted(e["labels"]),
                "is_own_book": any(a.get("doc_id") in book_ids for a in e["attrs"].values()),
            }
            for nid, e in docs.items()
        ),
        key=lambda d: (str(d["doc_id"]), d["node_id"]),
    )

    # ---- cross-book edges: an endpoint exists in another book than the edge's own
    cross: list[dict[str, Any]] = []
    for e in edges:
        s, t = nodes.get(e["source"]), nodes.get(e["target"])
        if not s or not t:
            continue
        other_s = set(s["labels"]) - {e["doc_id"]}
        other_t = set(t["labels"]) - {e["doc_id"]}
        if other_s or other_t:
            cross.append(
                {
                    "book": e["doc_id"],
                    "type": e["type"],
                    "polarity": e.get("polarity"),
                    "source": s["labels"].get(e["doc_id"], e["source"]),
                    "target": t["labels"].get(e["doc_id"], e["target"]),
                    "source_also_in": sorted(other_s),
                    "target_also_in": sorted(other_t),
                }
            )
    out["cross_book_edges"] = {
        "count": len(cross),
        "by_type": dict(Counter(c["type"] for c in cross).most_common()),
        "examples": cross[:40],
    }

    # ---- partner tickets
    incidents = {nid: e for nid, e in nodes.items() if e["type"] == "Incident"}
    partner = [
        {
            "book": e["doc_id"],
            "source": incidents.get(e["source"], {}).get("labels", {}).get(e["doc_id"], e["source"]),
            "target": incidents.get(e["target"], {}).get("labels", {}).get(e["doc_id"], e["target"]),
            "source_shared": len(incidents.get(e["source"], {}).get("labels", {})) >= 2,
            "target_shared": len(incidents.get(e["target"], {}).get("labels", {})) >= 2,
        }
        for e in edges
        if e["type"] == "PARTNER_TICKET"
    ]
    out["partner_tickets"] = {
        "edges": len(partner),
        "shared_incident_nodes": sorted(
            next(iter(e["labels"].values())) for e in incidents.values() if len(e["labels"]) >= 2
        ),
        "examples": partner[:20],
    }

    # ---- expected_graph_shape items two books can answer
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in edges:
        adjacency[e["source"]].append(e)
        adjacency[e["target"]].append(e)
    hops = []
    for a, b in itertools.pairwise(EXPECTED_CYCLE):
        a_ids = set(find_nodes(nodes, a))
        b_ids = set(find_nodes(nodes, b))
        found = [
            {"book": e["doc_id"], "type": e["type"], "polarity": e.get("polarity"),
             "direction": "a->b" if e["source"] in a_ids else "b->a"}
            for nid in a_ids
            for e in adjacency.get(nid, [])
            if (e["source"] in a_ids and e["target"] in b_ids) or (e["source"] in b_ids and e["target"] in a_ids)
        ]
        hops.append({"hop": f"{a} -- {b}", "a_nodes": len(a_ids), "b_nodes": len(b_ids), "edges": found[:6], "present": bool(found)})
    persons_shared = sorted(
        next(iter(e["labels"].values())) for e in nodes.values() if e["type"] == "Person" and len(e["labels"]) >= 2
    )
    out["expected_graph_shape"] = {
        "books_present": len(book_ids),
        "documented_cycle": {"path": EXPECTED_CYCLE, "hops": hops, "complete": all(h["present"] for h in hops)},
        "hub_systems": {
            hub: {"node_ids": find_nodes(nodes, hub, {"System"}), "books": sorted({d for nid in find_nodes(nodes, hub, {"System"}) for d in nodes[nid]["labels"]})}
            for hub in HUB_SYSTEMS
        },
        "persons_shared_across_books": {"count": len(persons_shared), "names": persons_shared, "target_for_5_books": 6},
        "negative_edges": {"count": sum(1 for e in edges if e.get("polarity") == "negative"), "target_for_5_books": 7},
    }
    return out


def print_report(r: dict[str, Any]) -> None:
    print("== books")
    for b in r["books"]:
        print(f"  {b['doc_id']}  {b['name']}  run={b['run_id']}  {b['counts']}")
    sn = r["shared_nodes"]
    print(f"\n== node ids shared by >= 2 books: {sn['count']}  by type: {sn['by_type']}")
    for ex in sn["examples"][:25]:
        print(f"  {ex['type']:20} {ex['node_id']:34} " + " | ".join(f"{d}: {l}" for d, l in ex["labels"].items()))
    print("\n== Document nodes (which books carry which manual)")
    for d in r["document_nodes"]:
        flag = "own+referenced" if d["is_own_book"] and len(d["carried_by"]) > 1 else ("own" if d["is_own_book"] else "referenced only")
        print(f"  {d['doc_id']!s:14} {d['node_id']:34} {flag:16} in {d['carried_by']}")
    ce = r["cross_book_edges"]
    print(f"\n== cross-book edges (an endpoint also exists in another book): {ce['count']}  by type: {ce['by_type']}")
    for e in ce["examples"][:20]:
        print(f"  [{e['book']}] {e['source']} -{e['type']}({e['polarity']})-> {e['target']}   also in: {e['source_also_in'] or ''} {e['target_also_in'] or ''}")
    pt = r["partner_tickets"]
    print(f"\n== partner tickets: {pt['edges']} PARTNER_TICKET edges; incident nodes present in >= 2 books: {pt['shared_incident_nodes']}")
    egs = r["expected_graph_shape"]
    cyc = egs["documented_cycle"]
    print(f"\n== expected_graph_shape with {egs['books_present']} book(s)")
    print(f"  documented cycle {' -> '.join(cyc['path'])}: {'COMPLETE' if cyc['complete'] else 'incomplete'}")
    for h in cyc["hops"]:
        kinds = sorted({(e['book'], e['type'], e['direction']) for e in h['edges']})
        print(f"    {h['hop']:36} nodes {h['a_nodes']}/{h['b_nodes']}  {'edge ' + str(kinds) if h['present'] else 'NO EDGE'}")
    for hub, info in egs["hub_systems"].items():
        print(f"  hub {hub:28} System nodes {len(info['node_ids'])} in books {info['books']}")
    ps = egs["persons_shared_across_books"]
    print(f"  persons shared across books: {ps['count']} (target with 5 books: {ps['target_for_5_books']}) {ps['names'][:10]}")
    ne = egs["negative_edges"]
    print(f"  negative edges: {ne['count']} (target with 5 books: {ne['target_for_5_books']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    s = Settings(_env_file=str(OSI_DIR / ".env") if (OSI_DIR / ".env").is_file() else None)
    client = make_client(s.opensearch)
    names = IndexNames(s.index.prefix)
    books = load_books(client, names)
    if not books:
        print("no documents indexed (bhb-documents is empty) - run osi ingest first", file=sys.stderr)
        return 1
    r = report(books)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1, default=list))
    else:
        print_report(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
