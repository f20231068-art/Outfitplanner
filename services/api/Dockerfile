# Rebuild trigger: model web search release
# The API (FastAPI + the LangGraph agent). Build context is the REPO ROOT, because the agent's
# prompts live in /prompts:
#   docker build -f services/api/Dockerfile -t stylist-api .
#
# No secrets are baked in: keys, the database address and the rest arrive as environment variables.

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/api/src ./src
COPY services/api/migrations ./migrations
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
COPY --chown=app:app prompts /app/prompts
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ENVIRONMENT=prod COOKIE_SECURE=true
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)" || exit 1
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
