# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ubuntu:24.04 AS backend-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=15 update && \
    apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=15 install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        openssl \
        sudo \
        lm-sensors \
        speedtest-cli \
        systemd \
        util-linux \
        ca-certificates && \
    python3 -m venv "$VIRTUAL_ENV" && \
    "$VIRTUAL_ENV/bin/pip" install --upgrade pip

COPY backend/requirements.txt /app/backend/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend-builder /build/frontend/dist /app/backend/app/static
COPY scripts/liveu-admin-action /usr/local/bin/liveu-admin-action
COPY scripts/liveu-config-read /usr/local/bin/liveu-config-read
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod 755 /entrypoint.sh /usr/local/bin/liveu-admin-action /usr/local/bin/liveu-config-read \
    && useradd -m -u 10001 app \
    && mkdir -p /app/data \
    && chown -R app:app /app /usr/local/bin/liveu-admin-action /usr/local/bin/liveu-config-read \
    && echo "app ALL=(root) NOPASSWD: /usr/bin/systemctl restart liveu, /usr/bin/systemctl is-active liveu, /usr/bin/env SYSTEMCTL_FORCE_BUS=1 /usr/bin/systemctl restart liveu, /usr/bin/env SYSTEMCTL_FORCE_BUS=1 /usr/bin/systemctl is-active liveu, /usr/local/bin/liveu-config-read *, /sbin/reboot, /opt/liveu/debug/version.sh, /usr/bin/nsenter" > /etc/sudoers.d/liveu-monitor \
    && chmod 0440 /etc/sudoers.d/liveu-monitor

USER app

EXPOSE 8443

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8443", "--ssl-keyfile", "/app/data/certs/server.key", "--ssl-certfile", "/app/data/certs/server.crt"]
