# Rebuild trigger: model web search release (needs OPENROUTER_API_KEY)
# MCP tool server. Build context: services/mcp
#   docker build -t stylist-mcp services/mcp
#
# Secrets are NEVER baked in: the JWT public key and the search API key arrive as environment
# variables at run time. The image holds code only.

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md* ./
# install dependencies first so this layer is cached until the lockfile changes
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
# a normal user with no shell: if something is ever exploited, the attacker is not root
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER app
EXPOSE 8001
# /health needs no login and returns only {"status":"ok"}
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"MCP_PORT\",\"8001\")}/health',timeout=2)" || exit 1
CMD ["python", "-m", "mcp_server.server"]
