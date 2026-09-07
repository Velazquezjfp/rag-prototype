import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))

from opensearch_index.ontology import load_ontology  # noqa: E402
from opensearch_index.schemas import ProcessResponse  # noqa: E402
from opensearch_index.transform import IndexBatch, build_batch  # noqa: E402

from rag_retrieval.graph import DocInfo, GraphStore  # noqa: E402
from rag_retrieval.settings import Settings  # noqa: E402

REPO = ROOT.parent
ONTOLOGY_PATH = REPO / "user-manual-books" / "handbuch_daten" / "Ontologie" / "ontology.yaml"
FIXTURE = REPO / "opensearch-index" / "tests" / "data" / "response_small.json"
GRAPH_ZSD = REPO / "out" / "remote-zsd" / "graph.json"
GRAPH_CAAS = REPO / "out" / "remote-caas" / "graph.json"
DOC_ID_SMALL = "BHB-PLT-0007"


@pytest.fixture(scope="session")
def ontology():
    if not ONTOLOGY_PATH.is_file():
        pytest.skip(f"ontology not found at {ONTOLOGY_PATH}")
    return load_ontology(ONTOLOGY_PATH)


@pytest.fixture(scope="session")
def response_small() -> ProcessResponse:
    if not FIXTURE.is_file():
        pytest.skip(f"fixture not found at {FIXTURE}")
    return ProcessResponse.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def small_batch(response_small, ontology) -> IndexBatch:
    """The indexer's view of the small ZSD fixture: 12 chunks (8-dim vectors), 59 nodes, 11 edges, graph blob."""
    return build_batch(
        response_small,
        doc_id=DOC_ID_SMALL,
        doc_id_source="test",
        run_id="run-test",
        ontology=ontology,
        embedding_model="test-8d",
        embedding_dim=8,
        embedding_text_prefix="",
        indexed_at="2026-09-04T00:00:00Z",
    )


@pytest.fixture
def fake_client(small_batch):
    from fake_search_client import FakeSearchClient

    client = FakeSearchClient(prefix="bhb")
    client.load_batch(small_batch)
    return client


@pytest.fixture(scope="session")
def graph_small(small_batch) -> GraphStore:
    return GraphStore.from_documents([small_batch.document])


@pytest.fixture(scope="session")
def real_graph() -> GraphStore:
    """Union of the two real extraction graphs (fixtures without edge ids); skipped when out/ is absent."""
    if not (GRAPH_ZSD.is_file() and GRAPH_CAAS.is_file()):
        pytest.skip("reference graphs not found under out/remote-*/graph.json")
    store = GraphStore()
    for doc_id, path, title in (
        ("BHB-PLT-0007", GRAPH_ZSD, "Betriebshandbuch ZSD - Zentrale Sicherheitsdienste"),
        ("BHB-PLT-0001", GRAPH_CAAS, "CaaS - Container-Plattform als Dienst"),
    ):
        store.add_document(
            doc_id,
            json.loads(path.read_text(encoding="utf-8")),
            info=DocInfo(doc_id=doc_id, title=title, embedding_model="bge-m3", embedding_text_prefix=""),
        )
    return store


@pytest.fixture
def settings() -> Settings:
    """Test settings: the developer's .env is not read; fixture vectors are 8-dimensional."""
    return Settings(
        _env_file=None,
        opensearch={"url": "http://localhost:9200"},
        index={"prefix": "bhb"},
        embedding={"model": "test-8d", "dim": 8, "query_prefix": "", "api_key": "k"},
        llm={"model": "fake-llm", "api_key": "k"},
        ontology={"path": str(ONTOLOGY_PATH)},
    )
