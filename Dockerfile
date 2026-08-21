ARG HERMES_BASE_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_BASE_IMAGE}

USER root

ARG OPENSPEC_VERSION=1.6.0
ENV OPENSPEC_VERSION="${OPENSPEC_VERSION}" \
    OPENSPEC_TELEMETRY=0

# Install GitHub CLI from GitHub's official Debian package repository.
RUN export DEBIAN_FRONTEND=noninteractive \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
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

# Match the OpenSpec version pinned by the Reserhub review workspace.
RUN npm install --global --omit=dev --ignore-scripts "@fission-ai/openspec@${OPENSPEC_VERSION}" \
    && test "$(openspec --version)" = "$OPENSPEC_VERSION" \
    && npm cache clean --force
