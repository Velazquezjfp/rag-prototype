"""What the indexer reads from ``ontology.yaml``: identifier regexes (SPEC §7.2), identity rules per class
(``classes.<Class>.identity``) and the corpus document list (``meta.documents``: file -> doc_id, root system)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Fallback when the ontology has no ``document`` regex: SPEC §7.2 document id pattern.
BUILTIN_DOC_ID_RE = re.compile(r"\bBHB-(?:PLT|VRF)-\d{4}\b")


@dataclass(frozen=True)
class IdentityRule:
    keys: tuple[str, ...]
    normalize: str | None = None  # upper | casefold | strip_titles_then_casefold | None
    scope: str | None = None  # "system": unique only within the document's root system
    secondary_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentMeta:
    doc_id: str
    file: str
    root_system: str | None = None


@dataclass(frozen=True)
class Ontology:
    path: Path
    name: str | None
    version: str | None
    fingerprint: str  # sha256 of the file bytes
    regexes: dict[str, re.Pattern[str]] = field(default_factory=dict)
    identity: dict[str, IdentityRule] = field(default_factory=dict)
    documents: dict[str, DocumentMeta] = field(default_factory=dict)  # by doc_id

    def doc_for_file(self, file_name: str) -> DocumentMeta | None:
        for meta in self.documents.values():
            if meta.file == file_name:
                return meta
        return None

    def root_system(self, doc_id: str) -> str | None:
        meta = self.documents.get(doc_id)
        return meta.root_system if meta else None

    @property
    def doc_id_regex(self) -> re.Pattern[str]:
        return self.regexes.get("document", BUILTIN_DOC_ID_RE)


def load_ontology(path: str | Path) -> Ontology:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"ontology file not found: {p} (set OSI__ONTOLOGY__PATH or --ontology)")
    return parse_ontology(p.read_bytes(), source=p)


def parse_ontology(raw: bytes, *, source: str | Path = "<upload>") -> Ontology:
    """The ontology from its YAML bytes (a file read by :func:`load_ontology`, or an uploaded document)."""
    p = Path(source)
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"ontology {p}: the YAML document must be a mapping")
    meta = data.get("meta") or {}

    regexes: dict[str, re.Pattern[str]] = {}
    for name, pattern in ((data.get("extraction") or {}).get("identifier_regexes_for_linking") or {}).items():
        regexes[str(name)] = re.compile(str(pattern))

    identity: dict[str, IdentityRule] = {}
    for cls, spec in (data.get("classes") or {}).items():
        ident = (spec or {}).get("identity") or {}
        keys = tuple(str(k) for k in ident.get("keys") or ["label"])
        identity[str(cls)] = IdentityRule(
            keys=keys,
            normalize=ident.get("normalize"),
            scope=ident.get("scope"),
            secondary_keys=tuple(str(k) for k in ident.get("secondary_keys") or ()),
        )

    documents: dict[str, DocumentMeta] = {}
    for d in meta.get("documents") or []:
        if d.get("id") and d.get("file"):
            documents[str(d["id"]).upper()] = DocumentMeta(
                doc_id=str(d["id"]).upper(), file=str(d["file"]), root_system=d.get("root_system")
            )

    return Ontology(
        path=p,
        name=meta.get("name"),
        version=str(meta["version"]) if meta.get("version") is not None else None,
        fingerprint=hashlib.sha256(raw).hexdigest(),
        regexes=regexes,
        identity=identity,
        documents=documents,
    )
