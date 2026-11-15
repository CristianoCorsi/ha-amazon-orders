# syntax=docker/dockerfile:1

ARG BUILD_FROM=ghcr.io/home-assistant/base-debian:trixie-2026.11.0

# ---- Stage 1: build the SvelteKit frontend (static files) -------------------
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS frontend
ARG PNPM_VERSION=12.15.0
RUN npm install -g "pnpm@${PNPM_VERSION}"
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---- Stage 2: Home Assistant Debian base (s6-overlay + bashio included) -----
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AMAZON_ORDERS_DATA_DIR=/data \
    AMAZON_ORDERS_FRONTEND_DIR=/opt/amazon_orders/frontend

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend /tmp/backend
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install /tmp/backend \
    && rm -rf /tmp/backend

COPY --from=frontend /src/frontend/build /opt/amazon_orders/frontend
COPY rootfs /
RUN chmod +x /etc/s6-overlay/s6-rc.d/amazon-orders/run

ARG BUILD_ARCH
ARG BUILD_VERSION
LABEL io.hass.type="addon" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.version="${BUILD_VERSION}" \
      org.opencontainers.image.title="Amazon Orders" \
      org.opencontainers.image.source="https://github.com/CristianoCorsi/ha-amazon-orders" \
      org.opencontainers.image.licenses="MIT"

EXPOSE 8099 8098
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD ["/opt/venv/bin/python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8099/api/status', timeout=4)"]
