PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
COMPOSE ?= docker compose
Q ?= Was passiert, wenn Vault versiegelt ist?
ARGS ?=
CHAT_BIND ?= 127.0.0.1
CHAT_PORT ?= 8501

.PHONY: venv dev lint test test-ui test-all test-integration doctor db-init db-upgrade db-revision db-current run ask smoke \
        db-up db-down db-logs up down image-build up-enterprise down-enterprise logs health

venv:
	python3 -m venv .venv && $(PIP) install --upgrade pip

dev: venv                    ## editable install of opensearch-index, users, retrieval (siblings) + this package with dev extras
	$(PIP) install -r requirements.txt

lint:
	.venv/bin/ruff check src tests

test:                        ## unit tests without the Streamlit AppTest (fast)
	$(PY) -m pytest tests/unit -q -m "not ui and not integration"

test-ui:                     ## Streamlit AppTest smoke over app.py with a fake-backed service
	$(PY) -m pytest tests/unit -q -m ui

test-all: test test-ui

test-integration:            ## real wiring: OpenSearch with both manuals + LiteLLM from .env, temporary SQLite
	CHAT_INTEGRATION=1 $(PY) -m pytest tests/integration -q -s -m integration

doctor:                      ## DB + schema, OpenSearch documents, LLM probe, resolved user, prompt budget
	.venv/bin/chat-doctor

db-init: db-upgrade          ## create/upgrade the schema of CHAT__DB__URL
db-upgrade:
	.venv/bin/chat-db upgrade
db-revision:                 ## make db-revision M="add column x"
	.venv/bin/chat-db revision -m "$(M)"
db-current:
	.venv/bin/chat-db current

run:                         ## the UI: http://127.0.0.1:8501 (CHAT_BIND/CHAT_PORT to change)
	.venv/bin/streamlit run app.py --server.address $(CHAT_BIND) --server.port $(CHAT_PORT)

ask:                         ## make ask Q="Was war bei ZSDSUP-0247?" ARGS="--no-graph --user rita.read"
	.venv/bin/chat-ask "$(Q)" $(ARGS)

smoke:                       ## the smoke questions of scripts/smoke_questions.txt through chat-ask (needs the live stack)
	bash scripts/smoke.sh

db-up:                       ## Postgres 16 in compose (profile postgres), waits until it accepts connections
	$(COMPOSE) --profile postgres up -d postgres
	bash scripts/wait_db.sh
db-down:
	$(COMPOSE) --profile postgres down
db-logs:
	$(COMPOSE) --profile postgres logs --tail 50 postgres

up:                          ## the UI as a container with host networking (dev box / server with tunnels), SQLite in a volume
	$(COMPOSE) --profile local up -d --build
down:
	$(COMPOSE) --profile local down
image-build:
	$(COMPOSE) --profile local build
up-enterprise:               ## published port + Postgres (profiles enterprise + postgres); no `--wait` (podman-compose)
	$(COMPOSE) --profile postgres --profile enterprise up -d --build
	bash scripts/wait_db.sh
down-enterprise:
	$(COMPOSE) --profile postgres --profile enterprise down
logs:
	$(COMPOSE) --profile local --profile enterprise logs -f --tail 100

health:                      ## --noproxy: a loopback check must never be routed through a corporate proxy
	curl -fsS --noproxy '*' http://127.0.0.1:$(CHAT_PORT)/_stcore/health && echo
