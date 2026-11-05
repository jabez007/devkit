FROM mcr.microsoft.com/playwright:v1.64.1-noble@sha256:2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python-is-python3 git tmux jq libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/devkit
COPY guard-requirements.txt /tmp/guard-requirements.txt
RUN /opt/devkit/bin/pip install --no-cache-dir -r /tmp/guard-requirements.txt \
    && mkdir -p /home/ubuntu/.claude && chown -R ubuntu:ubuntu /home/ubuntu/.claude
ENV PATH="/opt/devkit/bin:${PATH}"
ENV HOME="/home/ubuntu"
USER ubuntu
