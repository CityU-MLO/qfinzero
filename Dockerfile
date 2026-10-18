# QFinZero: hub + UPQ + ESP + PMB + MCP + web UI in one image.
#
#   docker build -t qfinzero .
#   docker run -p 19777:19777 -v qfz-data:/data -e QFZ_SAMPLE=1 \
#              -e QFZ_ADMIN_PASSWORD=change-me-please qfinzero
#
# /data is QFZ_DATA_ROOT (upq/ esp/ _state/). QFZ_SAMPLE=1 fills an empty
# /data with the synthetic sample on first start.

# ── UPQ (Rust) ───────────────────────────────────────────────────────────
FROM rust:1.90-bookworm AS upq
WORKDIR /src
COPY infra/upq/ ./
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/src/target \
    cargo build --release -p upq-service \
 && cp target/release/upq-service /upq-service

# ── Web UI (Next.js) ─────────────────────────────────────────────────────
FROM node:20-bookworm-slim AS web
WORKDIR /web
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY infra/dashboard-web/package.json infra/dashboard-web/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY infra/dashboard-web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build && pnpm prune --prod

# ── Runtime ──────────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm
# shown by /health; e.g. --build-arg QFINZERO_GIT_HASH=$(git rev-parse --short HEAD)
ARG QFINZERO_GIT_HASH=unknown
ENV QFINZERO_GIT_HASH=$QFINZERO_GIT_HASH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    QFZ_DATA_ROOT=/data QFZ_SERVER_HOST=0.0.0.0 NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 qfz && mkdir -p /data /app && chown qfz /data /app
COPY --from=web /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
# dependencies first (cached), then the source as an editable install so the
# supervisor finds infra/ next to the package
COPY pyproject.toml README.md LICENSE ./
COPY qfinzero/ qfinzero/
COPY clients/ clients/
RUN pip install ".[server,pipeline,databento,massive]" && pip uninstall -y qfinzero && rm -rf qfinzero clients
COPY --chown=qfz . .
RUN pip install --no-deps -e .
COPY --chown=qfz --from=upq /upq-service infra/upq/target/release/upq-service
COPY --chown=qfz --from=web /web/.next infra/dashboard-web/.next
COPY --from=web /web/node_modules infra/dashboard-web/node_modules
USER qfz
VOLUME ["/data"]
EXPOSE 19777
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD curl -fs http://127.0.0.1:19777/health || exit 1
ENTRYPOINT ["tini", "--", "/app/docker/entrypoint.sh"]
