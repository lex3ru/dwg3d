# The image of a service: services/<SERVICE> with the shared chassis and the contracts.
#
#   docker build -f deploy/service.Dockerfile --build-arg SERVICE=ping -t twin-ping .
#
# The context is the repository root. On start the service applies its
# migrations, then serves on port 8000.

FROM python:3.12-slim-trixie AS deps
ARG SERVICE
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY libs/chassis /src/libs/chassis
WORKDIR /src/services/${SERVICE}
COPY services/${SERVICE}/pyproject.toml services/${SERVICE}/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-trixie
ARG SERVICE
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /src twin
COPY --from=deps /opt/venv /opt/venv
COPY libs/chassis /src/libs/chassis
COPY contracts /src/contracts
COPY services/${SERVICE} /src/services/${SERVICE}
WORKDIR /src/services/${SERVICE}
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TWIN_CONTRACTS=/src/contracts
USER twin
EXPOSE 8000
ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "python -m twin_chassis.migrate && exec uvicorn app.main:build --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' --no-access-log"]
