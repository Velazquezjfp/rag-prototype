PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: venv dev lint test show check

venv:
	python3 -m venv .venv && $(PIP) install --upgrade pip

dev: venv                    ## standalone venv; chat-system normally installs this package into its own .venv (-e ../users)
	$(PIP) install -e ".[dev]"

lint:
	.venv/bin/ruff check src tests

test:
	$(PY) -m pytest tests -q

show:                        ## the mock directory, the group rules and the limits per user; who USERS__* resolves to
	$(PY) -m rag_users

check: lint test show
