# Образ приложения: сервер (Python) и собранный интерфейс. Он же — обработчик фоновых
# задач (другая команда). Контекст сборки — корень репозитория.
#
# Базовые образы — Debian 13 (ADR-0022) и закреплены дайджестами: каждое обновление собирает
# систему из тех же образов, что проверены, а не из того, что лежит под тегом в день сборки
# (R-038). Тег рядом — для человека. Как обновить — docs/INSTALL.md, «Базовые образы».

# LibreDWG (dwg2dxf) — чтение DWG (9.3); в Debian пакета нет, собирается из исходников.
# Архив сверяется с суммой до распаковки (R-038). Новая версия — новая сумма: sha256 архива,
# подпись которого (.sig рядом в релизе) проверена ключом сопровождающего LibreDWG.
FROM debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4 AS libredwg
ARG LIBREDWG_VERSION=0.14
ARG LIBREDWG_SHA256=62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl pkg-config python3 xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL -o /tmp/libredwg.tar.xz \
        "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.xz" \
    && echo "${LIBREDWG_SHA256}  /tmp/libredwg.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/libredwg.tar.xz --strip-components=1 \
    && rm /tmp/libredwg.tar.xz \
    && ./configure --prefix=/opt/libredwg --disable-bindings --disable-docs \
    && make -j"$(nproc)" \
    && make install-strip \
    && rm -rf /opt/libredwg/share /opt/libredwg/include /opt/libredwg/lib/*.a /opt/libredwg/lib/*.la

FROM node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# uv той же версии, что UV_RELEASE в .gitlab-ci.yml (ADR-0001)
FROM ghcr.io/astral-sh/uv:0.12.24-python3.12-trixie-slim@sha256:c45e18882c3b26a1631ac8b64537a2213e301b752edaa2471d32226090ccaafe AS server
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/ ./

FROM python:3.12-slim-trixie@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
# печать PDF (WeasyPrint): Pango и шрифты с кириллицей; те же пакеты ставит задание server
# в .gitlab-ci.yml (ADR-0001)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
    libfontconfig1 fonts-dejavu-core ffmpeg \
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
