# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.13.14-slim-bookworm@sha256:fcbd8dfc2605ba7c2eca646846c5e892b2931e41f6227985154a596f26ab8ed7

FROM ${PYTHON_IMAGE} AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY requirements-build.lock requirements.lock ./
RUN python -m pip install \
    --require-hashes \
    --requirement requirements-build.lock
RUN python -m pip install \
    --require-hashes \
    --prefix=/install \
    --requirement requirements.lock

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
RUN python -m pip install \
    --no-build-isolation \
    --no-deps \
    --prefix=/install \
    .

FROM ${PYTHON_IMAGE} AS runtime

ENV CLOUDFILEFLOW_PROJECT_ROOT=/app \
    PATH=/usr/local/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 cloudfileflow \
    && useradd \
        --uid 10001 \
        --gid cloudfileflow \
        --no-create-home \
        --shell /usr/sbin/nologin \
        cloudfileflow \
    && mkdir --parents /app /data \
    && chown cloudfileflow:cloudfileflow /app /data

WORKDIR /app

COPY --from=build /install/ /usr/local/
COPY --chown=cloudfileflow:cloudfileflow alembic.ini ./
COPY --chown=cloudfileflow:cloudfileflow migrations/ migrations/

USER 10001:10001

EXPOSE 8080

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"]

CMD ["uvicorn", "cloudfileflow.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
