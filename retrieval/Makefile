PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
RAG ?= .venv/bin/rag-retrieve
Q ?= Was passiert, wenn Vault versiegelt ist?
ARGS ?=

.PHONY: venv dev lint test test-integration ask answer graph-stats check questions

venv:
	python3 -m venv .venv && $(PIP) install --upgrade pip

dev: venv                    ## editable install of opensearch-index (sibling) + this package with dev extras
	$(PIP) install -r requirements.txt

lint:
	.venv/bin/ruff check src tests

test:
	$(PY) -m pytest tests/unit -q

test-integration:            ## needs OpenSearch with both manuals indexed + the embedding/LLM endpoint from .env
	RAG_INTEGRATION=1 $(PY) -m pytest tests/integration -q -s

ask:                         ## make ask Q="Was war bei ZSDSUP-0247?" ARGS="--no-graph"
	$(RAG) ask "$(Q)" $(ARGS)

answer:                      ## retrieval + model answer, streamed
	$(RAG) ask "$(Q)" --answer --stream $(ARGS)

graph-stats:
	$(RAG) graph-stats

check:                       ## aliases, document embedding model vs configured, embedding probe, LLM probe
	$(RAG) check

questions:                   ## the ground-truth questions of REPORT.md, fast and slow
	bash scripts/run_questions.sh
