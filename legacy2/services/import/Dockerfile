# The import service: the common recipe of a service (deploy/service.Dockerfile)
# plus LibreDWG, the DWG converter. The same image runs the API and the build worker.
#
#   docker build -f services/import/Dockerfile -t twin-import .     (the context is the repository root)

# ---- LibreDWG (dwg2dxf, dxf2dwg): not packaged in Debian, built from the release tarball
FROM debian:trixie-slim AS libredwg
ARG LIBREDWG_VERSION=0.14
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl pkg-config python3 xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.xz" \
        | tar -xJ --strip-components=1 \
    && ./configure --prefix=/opt/libredwg --disable-bindings --disable-docs \
    && make -j"$(nproc)" \
    && make install-strip \
    && rm -rf /opt/libredwg/share /opt/libredwg/include /opt/libredwg/lib/*.a /opt/libredwg/lib/*.la

FROM python:3.12-slim-trixie AS deps
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY libs/chassis /src/libs/chassis
WORKDIR /src/services/import
COPY services/import/pyproject.toml services/import/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /src twin \
    && mkdir -p /data && chown twin /data
COPY --from=libredwg /opt/libredwg /opt/libredwg
COPY --from=deps /opt/venv /opt/venv
COPY libs/chassis /src/libs/chassis
COPY contracts /src/contracts
COPY services/import /src/services/import
WORKDIR /src/services/import
ENV PATH="/opt/venv/bin:/opt/libredwg/bin:$PATH" \
    LD_LIBRARY_PATH=/opt/libredwg/lib \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/.cache \
    TWIN_CONTRACTS=/src/contracts \
    TWIN_DATA=/data \
    DWG3D_DWG2DXF=/opt/libredwg/bin/dwg2dxf
USER twin
EXPOSE 8000
ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "python -m twin_chassis.migrate && exec uvicorn app.main:build --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' --no-access-log"]
