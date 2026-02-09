FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone app source from GitHub
ARG REPO_URL=https://github.com/TaraHome/taraassistant-public.git
ARG REPO_BRANCH=main
RUN git clone --depth 1 --branch ${REPO_BRANCH} ${REPO_URL} /tmp/src \
    && cp -r /tmp/src/app /tmp/src/requirements.txt /tmp/src/scripts.yaml . \
    && rm -rf /tmp/src

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory
RUN mkdir -p /app/data

# Copy add-on entrypoint
COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8000

CMD [ "/run.sh" ]
