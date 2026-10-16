# Образ приложения: сервер (Python) и собранный интерфейс. Он же — обработчик фоновых
# задач (другая команда). Контекст сборки — корень репозитория.

# LibreDWG (dwg2dxf) — чтение DWG (9.3); в Debian пакета нет, собирается из исходников
FROM debian:bookworm-slim AS libredwg
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

FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS server
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/ ./

FROM python:3.12-slim-bookworm
# печать PDF (WeasyPrint): Pango и шрифты с кириллицей
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
    libfontconfig1 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --home /app app && mkdir -p /data && chown app /data
WORKDIR /app
COPY --from=libredwg /opt/libredwg /opt/libredwg
COPY --from=server /app /app
COPY --from=web /web/dist /app/web
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 APP_STATIC_DIR=/app/web APP_DATA_DIR=/data \
    APP_DWG2DXF=/opt/libredwg/bin/dwg2dxf
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["python", "-m", "app", "serve"]
