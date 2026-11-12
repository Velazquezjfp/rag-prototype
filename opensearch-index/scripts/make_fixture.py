#!/usr/bin/env python3
"""Build tests/data/response_small.json from a real response.json: the first N chunks with short unit vectors
(dim 8, derived deterministically from the real ones) plus every node/edge that is anchored to those chunks.

    python scripts/make_fixture.py ../out/remote-zsd/response.json --chunks 12 --dim 8
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("response", type=Path)
    ap.add_argument("--chunks", type=int, default=12)
    ap.add_argument("--dim", type=int, default=8)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "tests/data/response_small.json")
    args = ap.parse_args()

    resp = json.loads(args.response.read_text(encoding="utf-8"))
    chunks = resp["chunks"][: args.chunks]
    keep = {c["chunk_id"] for c in chunks}
    for c in chunks:
        if c.get("embedding"):
            v = c["embedding"][: args.dim]
            n = math.sqrt(math.fsum(x * x for x in v)) or 1.0
            c["embedding"] = [round(x / n, 6) for x in v]
    graph = resp.get("graph")
    if graph:
        nodes = []
        for n in graph["nodes"]:
            cids = [cid for cid in n["provenance"]["chunk_ids"] if cid in keep]
            if cids:
                n["provenance"]["chunk_ids"] = cids
                nodes.append(n)
        node_ids = {n["id"] for n in nodes}
        edges = []
        for e in graph["edges"]:
            cids = [cid for cid in e["provenance"]["chunk_ids"] if cid in keep]
            if cids and e["source"] in node_ids and e["target"] in node_ids:
                e["provenance"]["chunk_ids"] = cids
                edges.append(e)
        graph["nodes"], graph["edges"] = nodes, edges
        graph["meta"]["node_count"], graph["meta"]["edge_count"] = len(nodes), len(edges)
    resp["chunks"] = chunks
    resp["markdown"] = resp.get("markdown", "")[:3000]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.out}: {len(chunks)} chunks, {len(graph['nodes']) if graph else 0} nodes, {len(graph['edges']) if graph else 0} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
