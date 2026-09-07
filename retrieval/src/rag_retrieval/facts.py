"""Graph results as prompt-ready German facts and entity cards, every one with its provenance.

Facts are edges: ``Kai Ostermann —RESPONSIBLE_FOR (verantwortlich für)→ ZSD (raci=verantwortlich) [BHB-PLT-0007 S. 26]``;
a negative edge is rendered as an explicit negation (``: NICHT``) with its qualifier and quote, because "hängt nicht
ab von" is the finding the manuals make deliberately (README-Testdaten). Entity cards are nodes with attributes:
"VPP is unaffected by a sealed Vault" is not an edge at all but an ``ImpactStatement`` with ``severity: keine``."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from opensearch_index.identity import norm_key

from .graph import LOW_VALUE_TYPES, TYPE_PRIORITY, GEdge, GNode, GraphStore, type_rank
from .models import ChunkHit, EntityCard, EntityOccurrence, GraphFact, MatchedBy, cite

__all__ = [
    "LOW_VALUE_TYPES",
    "RELATION_PRIORITY",
    "TYPE_PRIORITY",
    "build_entity_cards",
    "build_facts",
    "graph_chunk_ids",
    "load_relation_labels",
    "relation_boost",
    "render_attributes",
    "render_fact",
    "select_start_nodes",
    "type_rank",
]

RELATION_PRIORITY: tuple[str, ...] = (
    "DEPENDS_ON",
    "IMPACT_OF",
    "RESPONSIBLE_FOR",
    "ESCALATES_TO",
    "PARTNER_TICKET",
    "PRECEDES",
    "RUNS_ON",
    "GOVERNED_BY",
    "TENANT_OF",
)
QUOTE_MAX = 220
VALUE_MAX = 400

# Question cues -> relation types to sort first. A heuristic on wording, not the intent router of ADR-0004
# (which stays out of scope); without it "wer ist zuständig" would list DEPENDS_ON facts before RESPONSIBLE_FOR.
RELATION_CUES: tuple[tuple[re.Pattern[str], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        re.compile(r"zuständig|verantwortlich|ansprechpartner|eskal|\bwer\b|\bwen\b|\bwem\b|kontakt|erreich|rufbereitschaft", re.I),
        ("RESPONSIBLE_FOR", "ESCALATES_TO", "OPERATED_BY", "STEP_RESPONSIBILITY"),
        ("Person", "OrgUnit"),
    ),
    (
        re.compile(r"reihenfolge|kaltstart|anfahr|hochfahr|fährt|wiederanlauf|schritt|zuerst|danach", re.I),
        ("PRECEDES", "STEP_RESPONSIBILITY"),
        ("StartupStep", "Procedure"),
    ),
    (
        re.compile(r"abhäng|hängt|auswirk|passiert|ausf[aä]ll|versiegelt|neustart|neu start|betroffen|folgen", re.I),
        ("DEPENDS_ON", "IMPACT_OF", "TENANT_OF", "RUNS_ON"),
        ("ImpactStatement", "System", "Component"),
    ),
    (
        re.compile(r"ticket|vorfall|incident|störung|vorgang|\b(?:ZSD|CAAS|DD|VPP|ES)SUP-", re.I),
        ("PARTNER_TICKET", "RESULTED_IN_CHANGE", "INSTANCE_OF_FAILURE", "DETECTED_BY"),
        ("Incident", "FailureMode", "Alert"),
    ),
    (
        re.compile(r"\bwie\b|erneuer|rotier|entsiegel|anleitung|\bsop\b|vorgehen|schritte|durchführ", re.I),
        ("GOVERNED_BY", "PRECEDES", "RESPONSIBLE_FOR"),
        ("Procedure", "Person"),
    ),
)


def relation_boost(question: str) -> tuple[str, ...]:
    """Relation types the question's wording asks about, in cue order; empty when no cue matches."""
    out: list[str] = []
    for rx, rels, _types in RELATION_CUES:
        if rx.search(question):
            for r in rels:
                if r not in out:
                    out.append(r)
    return tuple(out)


def type_boost(question: str) -> tuple[str, ...]:
    """Node types the question's wording asks about (start-node and entity-card order)."""
    out: list[str] = []
    for rx, _rels, types in RELATION_CUES:
        if rx.search(question):
            for t in types:
                if t not in out:
                    out.append(t)
    return tuple(out)


def load_relation_labels(path: str | Path) -> dict[str, str]:
    """``relations[].name -> label_de`` from ontology.yaml (the indexer's ``Ontology`` does not keep relations)."""
    p = Path(path)
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for rel in data.get("relations") or []:
        if isinstance(rel, dict) and rel.get("name") and rel.get("label_de"):
            out[str(rel["name"])] = str(rel["label_de"])
    return out


def relation_rank(r: str) -> int:
    return RELATION_PRIORITY.index(r) if r in RELATION_PRIORITY else len(RELATION_PRIORITY)


# --------------------------------------------------------------------------- start nodes


def select_start_nodes(
    store: GraphStore,
    *,
    label_nodes: Sequence[str],
    seed_hits: Sequence[ChunkHit],
    max_nodes: int,
    partial_nodes: Sequence[str] = (),
    question_keys: Collection[str] = (),
    boost_types: Sequence[str] = (),
) -> list[str]:
    """Label-resolved nodes, then partial label matches, then node ids of the seed chunks — those whose label
    mentions a question word first, then types the question asks about (``boost_types``), then those present in
    >= 2 seed chunks, then by type priority (ImpactStatement, Incident, Person, ...), then by seed rank."""
    label_set = [n for n in dict.fromkeys(label_nodes) if store.has_node(n)]
    partial = [n for n in dict.fromkeys(partial_nodes) if store.has_node(n) and n not in label_set]
    taken = set(label_set) | set(partial)
    keys = set(question_keys)
    boosted = set(boost_types)
    count: dict[str, int] = {}
    first_rank: dict[str, int] = {}
    for h in seed_hits:
        for nid in h.node_ids:
            if not store.has_node(nid) or store.type_of(nid) in LOW_VALUE_TYPES:
                continue
            count[nid] = count.get(nid, 0) + 1
            first_rank.setdefault(nid, h.rank)
    seeded = sorted(
        (n for n in count if n not in taken),
        key=lambda n: (
            0 if keys & store.label_tokens(n) else 1,
            0 if store.type_of(n) in boosted else 1,
            0 if count[n] >= 2 else 1,
            type_rank(store.type_of(n)),
            first_rank[n],
            n,
        ),
    )
    return (label_set + partial + seeded)[:max_nodes]


# --------------------------------------------------------------------------- facts


def _fmt_value(v: Any) -> str:
    if isinstance(v, list | tuple):
        s = ", ".join(_fmt_value(x) for x in v if x is not None)
    elif isinstance(v, dict):
        s = "; ".join(f"{k}: {_fmt_value(x)}" for k, x in v.items() if x is not None)
    else:
        s = " ".join(str(v).split())
    return s if len(s) <= VALUE_MAX else s[: VALUE_MAX - 1].rstrip() + "…"


def render_props(props: Mapping[str, Any]) -> str:
    parts = [f"{k}={_fmt_value(v)}" for k, v in props.items() if v not in (None, "", [], {})]
    return ", ".join(parts)


def _quote(q: str | None) -> str | None:
    if not q:
        return None
    q = " ".join(q.split())
    return q if len(q) <= QUOTE_MAX else q[: QUOTE_MAX - 1].rstrip() + "…"


def _cites(occ: Sequence[GEdge] | Sequence[GNode]) -> str:
    seen: list[str] = []
    for o in occ:
        c = cite(o.doc_id, o.pages)
        if c not in seen:
            seen.append(c)
    return "; ".join(seen)


def render_fact(
    store: GraphStore, occ: Sequence[GEdge], *, relation_de: str | None, edge_ref: bool = True
) -> str:
    e = occ[0]
    rel = f"{e.type} ({relation_de})" if relation_de else e.type
    text = f"{store.label(e.source)} —{rel}→ {store.label(e.target)}"
    props = render_props(e.properties)
    if props:
        text += f" ({props})"
    quote = _quote(e.quote)
    if e.polarity == "negative":
        text += ": NICHT"
        if e.qualifier:
            text += f" ({e.qualifier})"
        if quote:
            text += f" — „{quote}“"
    else:
        if e.qualifier:
            text += f" [{e.qualifier}]"
        if e.polarity == "unknown":
            text += " (unsicher)"
        if quote:
            text += f" — „{quote}“"
    text += f" [{_cites(occ)}"
    if edge_ref:
        text += f"; Kante {e.id}"
    return text + "]"


def build_facts(
    store: GraphStore,
    expanded: Mapping[str, Sequence[GEdge]],
    *,
    start_nodes: Sequence[str],
    label_nodes: Collection[str],
    relation_labels: Mapping[str, str],
    max_facts: int,
    boost: Sequence[str] = (),
) -> list[GraphFact]:
    """Order: edges touching a label-resolved node first, then relation types the question asks about (``boost``),
    negative before positive, the static relation priority, the position of the start node, then page."""
    label_set = set(label_nodes)
    start_pos = {n: i for i, n in enumerate(start_nodes)}
    boost_pos = {r: i for i, r in enumerate(boost)}

    def via(e: GEdge) -> str | None:
        cands = [n for n in (e.source, e.target) if n in start_pos]
        if not cands:
            return None
        return min(cands, key=lambda n: start_pos[n])

    def key(item: tuple[str, Sequence[GEdge]]) -> tuple:
        e = item[1][0]
        touches_label = e.source in label_set or e.target in label_set
        v = via(e)
        return (
            0 if touches_label else 1,
            boost_pos.get(e.type, len(boost_pos)),
            0 if e.polarity == "negative" else 1,
            relation_rank(e.type),
            start_pos.get(v, 10**6),
            e.pages[0] if e.pages else 10**6,
            e.id,
        )

    facts: list[GraphFact] = []
    for eid, occ in sorted(expanded.items(), key=key)[:max_facts]:
        e = occ[0]
        pages = sorted({p for o in occ for p in o.pages})
        chunk_ids = sorted({c for o in occ for c in o.chunk_ids})
        v = via(e)
        facts.append(
            GraphFact(
                edge_id=eid,
                doc_ids=sorted({o.doc_id for o in occ}),
                source_id=e.source,
                source_label=store.label(e.source),
                source_type=store.type_of(e.source),
                relation=e.type,
                relation_de=relation_labels.get(e.type),
                target_id=e.target,
                target_label=store.label(e.target),
                target_type=store.type_of(e.target),
                polarity=e.polarity if e.polarity in ("positive", "negative", "unknown") else "unknown",  # type: ignore[arg-type]
                qualifier=e.qualifier,
                quote=e.quote,
                properties=dict(e.properties),
                pages=pages,
                chunk_ids=chunk_ids,
                via_start_node=store.label(v) if v else None,
                rendered=render_fact(store, occ, relation_de=relation_labels.get(e.type)),
            )
        )
    return facts


# --------------------------------------------------------------------------- entity cards


def render_attributes(attrs: Mapping[str, Any]) -> str:
    return "; ".join(f"{k}: {_fmt_value(v)}" for k, v in attrs.items() if v not in (None, "", [], {}))


def render_card(card_label: str, card_type: str, aliases: Sequence[str], occurrences: Sequence[EntityOccurrence]) -> str:
    head = f"{card_label} ({card_type}"
    if aliases:
        head += "; auch: " + ", ".join(aliases)
    head += ")"
    distinct = {render_attributes(o.attributes) or (o.quote or "") for o in occurrences}
    if len(distinct) <= 1:
        body = next(iter(distinct)) if distinct else ""
        cites = "; ".join(dict.fromkeys(cite(o.doc_id, o.pages) for o in occurrences))
        return f"{head} — {body} [{cites}]" if body else f"{head} [{cites}]"
    lines = [head + ":"]
    for o in occurrences:
        body = render_attributes(o.attributes) or (o.quote or "")
        lines.append(f"    · {body} [{cite(o.doc_id, o.pages)}]")
    return "\n".join(lines)


def build_entity_cards(
    store: GraphStore,
    node_ids: Sequence[str],
    *,
    matched_by: Mapping[str, MatchedBy],
    doc_ids: Collection[str] | None = None,
    max_entities: int,
    boost_types: Sequence[str] = (),
) -> list[EntityCard]:
    """One card per entity: occurrences per book (conflicting attributes side by side), then cards of the same
    type whose label/alias spellings coincide are merged (``Kai Ostermann`` / alias ``Ostermann``). Nodes without
    attributes and without a quote add nothing beyond their label and are skipped."""
    cards: list[dict[str, Any]] = []
    for nid in dict.fromkeys(node_ids):
        occ = [n for n in store.occurrences(nid) if doc_ids is None or n.doc_id in doc_ids]
        if not occ:
            continue
        if not any(n.attributes or n.quote for n in occ):
            continue
        keys = set()
        for n in occ:
            keys.add(norm_key(n.label))
            keys.update(norm_key(a) for a in n.aliases if a)
        cards.append(
            {
                "node_ids": [nid],
                "type": occ[0].type,
                "label": occ[0].label,
                "aliases": list(dict.fromkeys(a for n in occ for a in n.aliases if a and a != occ[0].label)),
                "keys": keys,
                "occ": [
                    EntityOccurrence(
                        doc_id=n.doc_id,
                        label=n.label,
                        attributes=dict(n.attributes),
                        pages=list(n.pages),
                        chunk_ids=list(n.chunk_ids),
                        quote=n.quote,
                    )
                    for n in occ
                ],
                "matched_by": matched_by.get(nid, "neighbour"),
            }
        )
    # merge by shared label/alias key within the same type
    merged: list[dict[str, Any]] = []
    for c in cards:
        target = next((m for m in merged if m["type"] == c["type"] and m["keys"] & c["keys"]), None)
        if target is None:
            merged.append(c)
            continue
        target["node_ids"].extend(c["node_ids"])
        target["keys"] |= c["keys"]
        for a in [c["label"], *c["aliases"]]:
            if a != target["label"] and a not in target["aliases"]:
                target["aliases"].append(a)
        target["occ"].extend(c["occ"])
        target["matched_by"] = min(target["matched_by"], c["matched_by"], key=_matched_rank)
    boosted = set(boost_types)
    merged.sort(key=lambda c: (_matched_rank(c["matched_by"]), 0 if c["type"] in boosted else 1, type_rank(c["type"])))
    out: list[EntityCard] = []
    for c in merged[:max_entities]:
        occ = _dedupe_occurrences(c["occ"])
        out.append(
            EntityCard(
                node_ids=c["node_ids"],
                type=c["type"],
                label=c["label"],
                aliases=c["aliases"],
                occurrences=occ,
                matched_by=c["matched_by"],
                rendered=render_card(c["label"], c["type"], c["aliases"], occ),
            )
        )
    return out


def _dedupe_occurrences(occ: Sequence[EntityOccurrence]) -> list[EntityOccurrence]:
    """Same book, same attributes (and quote when there are none) -> one occurrence with the union of pages."""
    out: list[EntityOccurrence] = []
    for o in occ:
        body = render_attributes(o.attributes) or (o.quote or "")
        same = next(
            (x for x in out if x.doc_id == o.doc_id and (render_attributes(x.attributes) or (x.quote or "")) == body),
            None,
        )
        if same is None:
            out.append(o.model_copy(deep=True))
            continue
        same.pages = sorted(set(same.pages) | set(o.pages))
        same.chunk_ids = list(dict.fromkeys([*same.chunk_ids, *o.chunk_ids]))
    return out


def _matched_rank(m: str) -> int:
    return {"label": 0, "identifier": 1, "hit": 2, "neighbour": 3}.get(m, 4)


def graph_chunk_ids(
    facts: Sequence[GraphFact], store: GraphStore, *, label_nodes: Iterable[str], neighbours: Iterable[str], limit: int
) -> list[str]:
    """Provenance chunks for the graph channel: of the kept facts first, then of the label-resolved nodes, then of
    the reached neighbours; deduplicated, capped."""
    out: list[str] = []

    def add(ids: Iterable[str]) -> None:
        for c in ids:
            if c not in out:
                out.append(c)

    for f in facts:
        add(f.chunk_ids)
    for nid in label_nodes:
        for n in store.occurrences(nid):
            add(n.chunk_ids)
    for nid in neighbours:
        for n in store.occurrences(nid):
            add(n.chunk_ids)
    return out[:limit]
