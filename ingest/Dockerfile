# ingest-service - the ingest API with the indexer library (opensearch-index) baked in.
# Build context is the REPOSITORY ROOT (compose: context: .., dockerfile: ingest/Dockerfile), so the two module
# folders can be copied. Root .dockerignore keeps venvs, data, .env, tests and the corpus out of the context.
#
# Kubernetes/OpenShift ready: runs under any user id (group 0) on a read-only root filesystem. The only writable
# path it needs is /tmp: an upload above 1 MB is spooled there as an unnamed file for the length of the request
# (freed when the request ends or the process dies). Jobs are kept in memory. No apt step.
#
# Local build:      cd ingest && docker compose build
# Enterprise build: BASE_IMAGE / PIP_INDEX_URL / PIP_TRUSTED_HOST / proxies as build args
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
# 1. third-party dependencies: the union of the two pyproject dependency lists (layer survives source edits)
COPY opensearch-index/pyproject.toml ./opensearch-index/
COPY ingest/pyproject.toml ./ingest/
RUN pip install --upgrade pip \
    && python -c "import tomllib, glob; deps = sorted({d for f in glob.glob('*/pyproject.toml') for d in tomllib.load(open(f,'rb'))['project']['dependencies']}); open('/tmp/requirements.txt','w').write('\n'.join(deps))" \
    && cat /tmp/requirements.txt && pip install -r /tmp/requirements.txt

# 2. the two packages themselves (no dependency resolution: everything is already there)
COPY opensearch-index/README.md opensearch-index/config.yaml ./opensearch-index/
COPY opensearch-index/src ./opensearch-index/src
COPY ingest/README.md ./ingest/
COPY ingest/src ./ingest/src
RUN pip install --no-deps ./opensearch-index ./ingest

# opensearch_index resolves its packaged config.yaml relative to the package (an editable install); installed into
# site-packages it needs the explicit path. HOME=/tmp: nothing is written to a home directory.
ENV OSI_CONFIG=/app/opensearch-index/config.yaml \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --no-create-home --uid 10001 --gid 0 ingest && chmod -R a+rX /app
USER 10001:0
WORKDIR /app/ingest
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/healthz', timeout=4)" || exit 1
CMD ["uvicorn", "--factory", "ingest_service.api:create_app", "--host", "0.0.0.0", "--port", "8090"]
