# opensearch-index - the `osi` CLI as a small image (for servers without a Python venv; the OpenSearch node itself
# is the official opensearchproject/opensearch image, see compose.yaml).
#
# Local build:      docker compose --profile tools build
# Enterprise build: set BASE_IMAGE / PIP_INDEX_URL / proxy variables in .env (see .env.example)
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
# 1. third-party dependencies (layer survives source edits)
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# 2. the tool itself (config.yaml next to the package = packaged defaults; OSI__* env overrides)
COPY README.md config.yaml ./
COPY src ./src
RUN pip install --no-deps .

RUN useradd --create-home --uid 10001 osi && chown -R osi /app
USER osi
ENTRYPOINT ["osi"]
CMD ["--help"]
