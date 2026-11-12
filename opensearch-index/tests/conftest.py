import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opensearch_index.ontology import load_ontology  # noqa: E402
from opensearch_index.schemas import ProcessResponse  # noqa: E402
from opensearch_index.settings import Settings  # noqa: E402

FIXTURE = ROOT / "tests" / "data" / "response_small.json"
ONTOLOGY_PATH = ROOT.parent / "user-manual-books" / "handbuch_daten" / "Ontologie" / "ontology.yaml"
REAL_RESPONSE = ROOT.parent / "out" / "remote-zsd" / "response.json"


@pytest.fixture(scope="session")
def ontology():
    if not ONTOLOGY_PATH.is_file():
        pytest.skip(f"ontology not found at {ONTOLOGY_PATH}")
    return load_ontology(ONTOLOGY_PATH)


@pytest.fixture
def response_small() -> ProcessResponse:
    return ProcessResponse.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def real_response() -> ProcessResponse:
    if not REAL_RESPONSE.is_file():
        pytest.skip(f"reference run not found at {REAL_RESPONSE}")
    return ProcessResponse.model_validate(json.loads(REAL_RESPONSE.read_text(encoding="utf-8")))


@pytest.fixture
def settings() -> Settings:
    """Test settings: the developer's .env is not read; the fixture vectors are 8-dimensional."""
    return Settings(
        _env_file=None,
        opensearch={"url": "http://localhost:9200"},
        index={"prefix": "bhbtest"},
        embedding={"model": "test-8d", "dim": 8, "text_prefix": ""},
        ontology={"path": str(ONTOLOGY_PATH)},
    )
