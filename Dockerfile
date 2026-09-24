ARG HERMES_BASE_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_BASE_IMAGE}

USER root

ARG PASEO_VERSION=0.5.2
ENV PASEO_VERSION="${PASEO_VERSION}"

# Hermes delegates PR review tasks to Paseo and uses GitHub CLI for the review
# workflow. The Codex runtime and its larger build dependencies live in the
# separate Paseo image.
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

# Hermes needs only the Paseo client to delegate work; Codex itself runs in the
# isolated Paseo service image.
RUN npm install --global --omit=dev --ignore-scripts "@getpaseo/cli@${PASEO_VERSION}" \
    && test "$(paseo --version)" = "$PASEO_VERSION" \
    && npm cache clean --force
