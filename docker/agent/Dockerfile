FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /usr/local/bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/*
ARG AGENT_UID=1000
RUN useradd --create-home --uid "${AGENT_UID}" --shell /bin/bash agent \
    && mkdir -p /home/agent/.claude /home/agent/.cache \
    && chown agent /home/agent/.claude /home/agent/.cache
COPY ask_judge.py /usr/local/bin/ask-judge
RUN chmod 755 /usr/local/bin/ask-judge
USER agent
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH=/home/agent/.local/bin:$PATH \
    CLAUDE_CONFIG_DIR=/home/agent/.claude \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/home/agent/.cache/venv \
    UV_CACHE_DIR=/home/agent/.cache/uv
WORKDIR /workspace
CMD ["claude"]
