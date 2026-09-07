# chat-system - Streamlit UI + backend with the three sibling libraries baked in.
# Build context is the REPOSITORY ROOT (compose: context: .., dockerfile: chat-system/Dockerfile), so the four module
# folders can be copied. Root .dockerignore keeps venvs, data, .env, tests and the corpus out of the context.
#
# Local build:      cd chat-system && docker compose --profile local build
# Enterprise build: BASE_IMAGE / PIP_INDEX_URL / PIP_TRUSTED_HOST / proxies from .env (see .env.example)
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_CLIENT_TOOLBAR_MODE=viewer

# curl for the HEALTHCHECK (python:3.12-slim has none)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# 1. third-party dependencies: the union of the four pyproject dependency lists (layer survives source edits)
COPY opensearch-index/pyproject.toml ./opensearch-index/
COPY users/pyproject.toml ./users/
COPY retrieval/pyproject.toml ./retrieval/
COPY chat-system/pyproject.toml ./chat-system/
RUN pip install --upgrade pip \
    && python -c "import tomllib, glob; deps = sorted({d for f in glob.glob('*/pyproject.toml') for d in tomllib.load(open(f,'rb'))['project']['dependencies']}); open('/tmp/requirements.txt','w').write('\n'.join(deps))" \
    && cat /tmp/requirements.txt && pip install -r /tmp/requirements.txt

# 2. the four packages themselves (no dependency resolution: everything is already there)
COPY opensearch-index/README.md opensearch-index/config.yaml ./opensearch-index/
COPY opensearch-index/src ./opensearch-index/src
COPY users/README.md ./users/
COPY users/src ./users/src
COPY retrieval/README.md retrieval/config.yaml ./retrieval/
COPY retrieval/src ./retrieval/src
COPY chat-system/README.md chat-system/config.yaml chat-system/alembic.ini chat-system/app.py ./chat-system/
COPY chat-system/.streamlit ./chat-system/.streamlit
COPY chat-system/src ./chat-system/src
RUN pip install --no-deps ./opensearch-index ./users ./retrieval ./chat-system

# rag_retrieval / opensearch_index resolve their packaged config.yaml relative to the package (an editable install);
# installed into site-packages they need the explicit path.
ENV RAG_CONFIG=/app/retrieval/config.yaml \
    OSI_CONFIG=/app/opensearch-index/config.yaml

RUN useradd --create-home --uid 10001 chat && mkdir -p /app/chat-system/data && chown -R chat /app
USER chat
WORKDIR /app/chat-system
VOLUME ["/app/chat-system/data"]
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fsS http://localhost:8501/_stcore/health || exit 1
ENTRYPOINT ["streamlit", "run", "app.py"]
