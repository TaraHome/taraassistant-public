ARG BUILD_FROM=ghcr.io/tarahome/taraassistant:latest
FROM ${BUILD_FROM}

# Switch to root for add-on compatibility
USER root

# Copy add-on entrypoint
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
