FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

RUN apt-get update && apt-get install -y --no-install-recommends git tmux jq ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY wheels/ /wheels/
COPY constraints.txt /wheels/constraints.txt
COPY guard-requirements.txt /wheels/guard-requirements.txt
RUN pip install --no-cache-dir -c /wheels/constraints.txt \
    -r /wheels/guard-requirements.txt /wheels/*.whl
RUN useradd --uid 1000 --create-home spike \
    && mkdir -p /home/spike/.claude && chown -R spike:spike /home/spike
USER spike
