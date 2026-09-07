"""Question analysis without any model call: identifiers (ontology regexes, SPEC §7.2) and graph node labels
found as n-grams in the question. Both feed exact-match channels and seed the graph expansion."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from opensearch_index.identity import norm_key
from opensearch_index.transform import extract_identifiers

from .graph import LOW_VALUE_TYPES, TOKEN_RE, GraphStore, tokenize, type_rank

# Function and question words that also happen to be (parts of) node labels must not seed the graph.
STOPWORDS_DE = frozenset(
    """
    der die das den dem des ein eine einen einem einer eines und oder aber wenn wie was wer wo wann warum wieso
    weshalb welche welcher welches welchen welchem ist sind war waren wird werden wurde wurden bin bist hat haben
    hatte hatten hätte kann können könnte konnte muss müssen musste soll sollen sollte darf dürfen will wollen
    möchte ich du er sie es wir ihr mich mir dich dir uns euch sich mein meine dein deine sein seine unser unsere
    nicht kein keine keinen keinem keiner auch noch nur schon dann denn dass damit für von vom zu zum zur mit bei
    beim nach über unter vor aus auf an in im am um durch ohne gegen bis als ob so hier da dort dies diese dieser
    dieses diesen diesem jene alle alles etwas nichts man mal bitte gibt geht passiert läuft hängt daran dazu davon
    dafür falls bzw etc sowie also ja nein mehr sehr viel viele wenig wenige ganz immer wieder jetzt heute gerade
    the a an of to and or is are how what who where when why which
    """.split()
)


@dataclass
class QueryPlan:
    question: str
    identifiers: list[str] = field(default_factory=list)
    label_candidates: list[str] = field(default_factory=list)  # matched n-gram keys (norm_key), in question order
    resolved: dict[str, set[str]] = field(default_factory=dict)  # key -> node ids
    label_terms: list[str] = field(default_factory=list)  # lowercased original spellings, for the terms query
    question_keys: list[str] = field(default_factory=list)  # content words of the question (norm_key)
    partial_nodes: list[str] = field(default_factory=list)  # labels containing >= 2 question words

    @property
    def start_nodes(self) -> list[str]:
        out: list[str] = []
        for key in self.label_candidates:
            for nid in sorted(self.resolved.get(key, ())):
                if nid not in out:
                    out.append(nid)
        return out

    @property
    def resolved_labels(self) -> list[str]:
        return list(self.label_candidates)

    def as_dict(self) -> dict[str, Any]:
        return {
            "identifiers": self.identifiers,
            "labels": self.label_candidates,
            "label_terms": self.label_terms,
            "start_nodes": self.start_nodes,
            "partial_nodes": self.partial_nodes,
        }


def question_keys(question: str, *, min_chars: int = 3) -> list[str]:
    """Content words of the question as ``norm_key`` tokens (hyphen compounds also split), stopwords removed."""
    out: list[str] = []
    for tok in TOKEN_RE.findall(question):
        parts = [tok, *re.split(r"[-/]+", tok)] if re.search(r"[-/]", tok) else [tok]
        for part in parts:
            key = norm_key(part)
            if len(key) >= min_chars and key not in STOPWORDS_DE and key not in out:
                out.append(key)
    return out


def partial_label_matches(
    keys: Sequence[str],
    graph: GraphStore | None,
    *,
    anchors: Collection[str],
    exclude: Collection[str] = (),
    min_tokens: int = 2,
    max_nodes: int = 8,
) -> list[str]:
    """Nodes whose label/aliases contain at least ``min_tokens`` distinct question words, one of them an *anchor*
    (a word of an exactly resolved label or an identifier). Reaches entities that no edge leads to, e.g. the
    ``ImpactStatement`` "Vault versiegelt | VPP" (severity: keine) for "Vault versiegelt"; the anchor keeps generic
    pairs such as "neu starten" from pulling in every "X neu starten" statement."""
    if graph is None or not keys or not anchors:
        return []
    matched: dict[str, set[str]] = {}
    for key in keys:
        for nid in graph.nodes_with_token(key):
            matched.setdefault(nid, set()).add(key)
    anchor_set = set(anchors)
    count = {nid: len(toks) for nid, toks in matched.items()}
    cands = [
        nid
        for nid, toks in matched.items()
        if len(toks) >= min_tokens
        and toks & anchor_set
        and nid not in exclude
        and graph.type_of(nid) not in LOW_VALUE_TYPES
    ]
    cands.sort(
        key=lambda nid: (
            -count[nid],
            -(count[nid] / max(1, len(graph.label_tokens(nid)))),
            type_rank(graph.type_of(nid)),
            nid,
        )
    )
    return cands[:max_nodes]


def extract_question_identifiers(question: str, regexes: dict[str, re.Pattern[str]]) -> list[str]:
    """All ontology identifiers in the question; the host pattern is lowercase-only, so it also runs on the
    lowercased question ("Vault-P01" typed with a capital)."""
    found = set(extract_identifiers(question, regexes))
    host = regexes.get("host")
    if host is not None:
        found.update(host.findall(question.lower()))
    return sorted(found)


def match_labels(
    question: str, graph: GraphStore | None, *, max_ngram: int = 4, min_chars: int = 3
) -> tuple[list[str], dict[str, set[str]], list[str]]:
    """Greedy longest-match of question n-grams against the graph's label index (``norm_key`` on both sides).

    Returns ``(matched keys in question order, key -> node ids, lowercased label spellings for OpenSearch)``.
    ``node_labels`` in the index is a keyword with the ``lc`` normalizer (lowercase only), so the terms sent there
    are the original spellings lowercased — not ``norm_key`` (which also folds ß to ss)."""
    if graph is None:
        return [], {}, []
    tokens = TOKEN_RE.findall(question)
    keys: list[str] = []
    resolved: dict[str, set[str]] = {}
    consumed = [False] * len(tokens)

    def accept(key: str) -> bool:
        if key in resolved:
            return True
        ids = graph.resolve(key)
        if not ids:
            return False
        keys.append(key)
        resolved[key] = ids
        return True

    i = 0
    while i < len(tokens):
        matched = 0
        for n in range(min(max_ngram, len(tokens) - i), 0, -1):
            window = tokens[i : i + n]
            key = norm_key(" ".join(window))
            if n == 1 and (len(key) < min_chars or key in STOPWORDS_DE):
                continue
            if accept(key):
                matched = n
                break
        if matched:
            for j in range(i, i + matched):
                consumed[j] = True
            if matched > 1:  # "Vault entsiegeln" also resolves "Vault" (ranked after the longer match)
                for tok in tokens[i : i + matched]:
                    key = norm_key(tok)
                    if len(key) >= min_chars and key not in STOPWORDS_DE:
                        accept(key)
            i += matched
        else:
            i += 1
    # hyphenated or slashed compounds: try their parts ("TLS-Zertifikat" -> "tls", "zertifikat")
    for tok, used in zip(tokens, consumed, strict=True):
        if used or not re.search(r"[-/]", tok):
            continue
        for part in re.split(r"[-/]+", tok):
            key = norm_key(part)
            if len(key) >= min_chars and key not in STOPWORDS_DE:
                accept(key)

    terms: list[str] = []
    for key in keys:
        for form in sorted(graph.label_forms(key)):
            low = form.lower().strip()
            if low and low not in terms:
                terms.append(low)
    return keys, resolved, terms


def analyze_question(
    question: str,
    *,
    regexes: dict[str, re.Pattern[str]],
    graph: GraphStore | None,
    max_ngram: int = 4,
    min_chars: int = 3,
    partial_min_tokens: int = 2,
    partial_max_nodes: int = 8,
) -> QueryPlan:
    identifiers = extract_question_identifiers(question, regexes)
    keys, resolved, terms = match_labels(question, graph, max_ngram=max_ngram, min_chars=min_chars)
    qkeys = question_keys(question, min_chars=min_chars)
    exact = {nid for ids in resolved.values() for nid in ids}
    anchors = {tok for key in keys for tok in tokenize(key, split_compounds=True)}
    anchors.update(i.lower() for i in identifiers)
    partial = partial_label_matches(
        qkeys,
        graph,
        anchors=anchors,
        exclude=exact,
        min_tokens=partial_min_tokens,
        max_nodes=partial_max_nodes,
    )
    if graph is not None:
        for nid in partial:
            n = graph.node(nid)
            if n is not None:
                low = n.label.lower().strip()
                if low and low not in terms:
                    terms.append(low)
    return QueryPlan(
        question=question,
        identifiers=identifiers,
        label_candidates=keys,
        resolved=resolved,
        label_terms=terms,
        question_keys=qkeys,
        partial_nodes=partial,
    )
