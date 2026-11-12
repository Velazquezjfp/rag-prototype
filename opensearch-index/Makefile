PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
OSI ?= .venv/bin/osi
OUT ?= ../out/remote-zsd
COMPOSE ?= docker compose
DATA_DIR ?= data/opensearch

.PHONY: venv dev lint test test-integration init up wait down reset logs health verify bootstrap ingest-zsd status search-smoke preflight-image image-build image-save

venv:
	python3 -m venv .venv && $(PIP) install --upgrade pip

dev: venv
	$(PIP) install -e ".[dev]"

lint:
	.venv/bin/ruff check src tests scripts

test:
	$(PY) -m pytest tests/unit -q

test-integration:            ## needs the compose node: make up && make bootstrap
	OSI_INTEGRATION=1 OSI_INTEGRATION_URL=$${OSI_INTEGRATION_URL:-http://localhost:9200} $(PY) -m pytest tests/integration -q -s

init:                        ## the node runs as uid 1000; on rootless podman that uid is one of YOUR subordinate uids
	@mkdir -p $(DATA_DIR)
	@if docker info --format '{{.Host.Security.Rootless}}' 2>/dev/null | grep -q true; then \
	  if [ "$$(podman unshare stat -c %u $(DATA_DIR))" != "1000" ]; then \
	    echo "rootless podman: podman unshare chown -R 1000:1000 $(DATA_DIR)"; podman unshare chown -R 1000:1000 $(DATA_DIR); \
	  fi; \
	elif [ "$$(id -u)" != "1000" ]; then \
	  echo "note: make $(DATA_DIR) writable for uid 1000: sudo chown -R 1000:1000 $(DATA_DIR)"; \
	fi

up: init                     ## portable: no `--wait` (podman-compose lacks it); readiness is polled from the host
	$(COMPOSE) up -d opensearch
	bash scripts/wait_healthy.sh

wait:
	bash scripts/wait_healthy.sh

down:
	$(COMPOSE) down

reset: down                  ## DESTROYS the local data directory (rootless podman: files belong to a subordinate uid)
	@if docker info --format '{{.Host.Security.Rootless}}' 2>/dev/null | grep -q true; then podman unshare rm -rf $(DATA_DIR); else rm -rf $(DATA_DIR); fi

logs:
	$(COMPOSE) logs -f opensearch

health:                      ## --noproxy: a loopback check must never be routed through a corporate proxy
	curl -fsS --noproxy '*' 'http://localhost:9200/_cluster/health?pretty'

verify:
	$(OSI) verify

bootstrap:
	$(OSI) bootstrap

ingest-zsd:
	$(OSI) ingest $(OUT)

status:
	$(OSI) status

search-smoke:
	$(OSI) search --identifier ZSDSUP-0247
	$(OSI) search --knn-from-chunk 2bb722f565a0-0060 --k 3

preflight-image:
	bash scripts/preflight_image.sh

image-build:
	$(COMPOSE) --profile tools build

image-save:                  ## offline transfer of the node image (then: gunzip -c … | docker load on the server)
	docker save $${OPENSEARCH_IMAGE:-opensearchproject/opensearch:3.8.0} | gzip > opensearch-3.8.0.tar.gz && ls -la opensearch-3.8.0.tar.gz
