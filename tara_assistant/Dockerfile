ARG BUILD_FROM=ghcr.io/tarahome/taraassistant:latest
FROM ${BUILD_FROM}

# Switch to root for add-on compatibility
USER root

# Install jq for parsing add-on options
RUN apt-get update && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/*

# Copy add-on entrypoint
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
