ARG HERMES_BASE_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_BASE_IMAGE}

USER root

ARG CODEX_VERSION=0.149.1
ARG OPENSPEC_VERSION=1.6.0
ARG PASEO_VERSION=0.5.2
ENV CODEX_VERSION="${CODEX_VERSION}" \
    OPENSPEC_VERSION="${OPENSPEC_VERSION}" \
    PASEO_VERSION="${PASEO_VERSION}" \
    OPENSPEC_TELEMETRY=0

# Install GitHub CLI from GitHub's official Debian package repository.
RUN export DEBIAN_FRONTEND=noninteractive \
    && apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ca-certificates curl util-linux \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL \
        https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Install a reproducible standalone Codex CLI for explicit agent delegation.
RUN npm install --global --omit=dev --ignore-scripts "@openai/codex@${CODEX_VERSION}" \
    && test "$(codex --version)" = "codex-cli ${CODEX_VERSION}"

# Match the OpenSpec version pinned by the Reserhub review workspace.
RUN npm install --global --omit=dev --ignore-scripts "@fission-ai/openspec@${OPENSPEC_VERSION}" \
    && test "$(openspec --version)" = "$OPENSPEC_VERSION"

# Paseo runs Codex app-server behind its authenticated local/relay web UI.
RUN npm install --global --omit=dev --ignore-scripts "@getpaseo/cli@${PASEO_VERSION}" \
    && test "$(paseo --version)" = "$PASEO_VERSION" \
    && npm cache clean --force

COPY --chmod=0755 scripts/paseo-entrypoint.sh /usr/local/bin/paseo-entrypoint
COPY --chmod=0644 scripts/paseo-config.json /usr/local/share/paseo/config.json
