# API and build worker (same image, different command).
#
#   docker build -t dwg3d-api backend/
#   api:    uvicorn dwg3d.api:app --host 0.0.0.0 --port 8000
#   worker: python -m dwg3d worker -n 2

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

# ---- Python dependencies (uv, locked)
FROM python:3.12-slim-trixie AS deps
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---- runtime
FROM python:3.12-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /app dwg3d
COPY --from=libredwg /opt/libredwg /opt/libredwg
COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
COPY alembic.ini ./
COPY dwg3d ./dwg3d
ENV PATH="/opt/venv/bin:/opt/libredwg/bin:$PATH" \
    LD_LIBRARY_PATH=/opt/libredwg/lib \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/.cache \
    DWG3D_DATA=/data \
    DWG3D_DWG2DXF=/opt/libredwg/bin/dwg2dxf
RUN mkdir -p /data && chown dwg3d /data
USER dwg3d
EXPOSE 8000
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "dwg3d.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
