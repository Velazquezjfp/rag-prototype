"""Input contract: the docling-graph-service ``ProcessResponse`` (copied from
``docling-graph/src/docling_graph_service/schemas.py`` so this module never imports docling).

``extra="allow"`` keeps unknown future fields, so they survive into the stored graph blob.
Optional parts are tolerated: ``graph`` may be ``None`` (``--no-graph``), ``embedding`` may be ``None``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Polarity = Literal["positive", "negative", "unknown"]

_ALLOW = ConfigDict(extra="allow")


class BBox(BaseModel):
    model_config = _ALLOW
    page: int
    l: float  # noqa: E741 - the API's field name
    t: float
    r: float
    b: float
    page_width: float
    page_height: float
    coord_origin: str = "TOPLEFT"


class Chunk(BaseModel):
    model_config = _ALLOW
    chunk_id: str
    text: str
    body_text: str = ""
    heading_breadcrumb: list[str] = Field(default_factory=list)
    heading_level: int = 0
    kind: str = "text"
    caption: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    dom_paths: list[str] = Field(default_factory=list)
    bboxes: list[BBox] = Field(default_factory=list)
    token_count: int = 0
    embedding: list[float] | None = None


class NodeProvenance(BaseModel):
    model_config = _ALLOW
    pages: list[int] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    dom_paths: list[str] = Field(default_factory=list)
    heading_breadcrumb: list[str] = Field(default_factory=list)
    table_ref: str | None = None
    figure_ref: str | None = None
    match: str | None = None


class GraphNode(BaseModel):
    model_config = _ALLOW
    id: str
    type: str
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    quote: str | None = None
    provenance: NodeProvenance = Field(default_factory=NodeProvenance)


class EdgeProvenance(BaseModel):
    model_config = _ALLOW
    pages: list[int] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    model_config = _ALLOW
    source: str
    target: str
    type: str
    polarity: Polarity = "positive"
    qualifier: str | None = None
    quote: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: EdgeProvenance = Field(default_factory=EdgeProvenance)


class GraphResult(BaseModel):
    model_config = _ALLOW
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    meta: dict[str, Any] = Field(default_factory=dict)


class Degraded(BaseModel):
    model_config = _ALLOW
    vlm: bool = False
    embeddings: bool = False
    graph: bool = False


class DocumentInfo(BaseModel):
    model_config = _ALLOW
    name: str
    format: str = "pdf"
    sha256: str
    pages: int = 0
    tables: int = 0
    pictures: int = 0


class ProcessResponse(BaseModel):
    model_config = _ALLOW
    document: DocumentInfo
    markdown: str = ""
    chunks: list[Chunk]
    graph: GraphResult | None = None
    degraded: Degraded = Field(default_factory=Degraded)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timings_s: dict[str, float] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    cached: bool = False
