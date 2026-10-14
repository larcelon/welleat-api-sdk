FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /usr/local/bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ARG AGENT_UID=1000
RUN useradd --create-home --uid "${AGENT_UID}" judge \
    && mkdir -p /var/cache/judge \
    && chown judge /var/cache/judge
COPY server.py /opt/judge/server.py
USER judge
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/var/cache/judge/venv \
    UV_CACHE_DIR=/var/cache/judge/uv \
    PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "/opt/judge/server.py"]
