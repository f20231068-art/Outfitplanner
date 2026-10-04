from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """The repo-root .env for local development. In a container there is none (settings come from
    real environment variables), and that is fine."""
    return next((p / ".env" for p in Path(__file__).resolve().parents if (p / ".env").is_file()), None)


ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str = "postgresql://stylist:stylist_dev_password@localhost:5432/stylist"
    api_port: int = 8000
    # "<provider>/<model-id>", provider = openrouter | opencode
    stylist_model: str = "opencode/gpt-5.5"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    opencode_api_key: str = ""
    opencode_base_url: str = "https://opencode.ai/zen/v1"
    serpapi_api_key: str = ""
    # How structured output is requested. The OpenRouter free model rejects "json_schema" and
    # json_mode returned nulls in testing; tool-calling ("function_calling") works.
    structured_output_method: str = "function_calling"
    # Some networks stall ~40s trying IPv6 before falling back to IPv4.
    force_ipv4: bool = True
    # (opencode only) override the endpoint style if the guess from the model name is wrong: chat | responses
    llm_api_mode: str = ""

    # --- talking to the MCP tool server. The API signs each request with its PRIVATE key.
    # Only the API service should ever have this key; the MCP server gets the public half.
    mcp_url: str = "http://127.0.0.1:8001/mcp"
    mcp_jwt_private_key: str = ""  # PEM; line breaks may be written as \n
    mcp_jwt_issuer: str = "stylist-api"
    mcp_jwt_audience: str = "stylist-mcp"
    # Short on purpose: a token is minted fresh for every request and used immediately.
    mcp_jwt_ttl_s: int = 30

    # --- user login. A SEPARATE key pair from the MCP one, so the two kinds of token can never be
    # confused: a user's login token is useless against the tool server and vice versa.
    auth_jwt_private_key: str = ""
    auth_jwt_public_key: str = ""
    auth_jwt_issuer: str = "stylist-api"
    auth_jwt_audience: str = "stylist-web"
    auth_access_ttl_s: int = 900  # access token: 15 minutes
    auth_refresh_ttl_s: int = 14 * 24 * 3600  # "stay logged in": 14 days, replaced on every use
    auth_jwt_leeway_s: int = 10
    # The browser origin allowed to call this API (CORS), and whether the refresh cookie needs https.
    web_origin: str = "http://localhost:3000"
    cookie_secure: bool = False  # MUST be True when served over https (production)
    # --- abuse limits
    login_max_failures: int = 5  # per email+address per window
    login_window_s: int = 15 * 60
    chat_messages_per_min: int = 10  # per user
    daily_conversations_per_user: int = 30
    buy_links_per_min: int = 10  # per user (each costs a search credit)
    # comma-separated emails allowed to use /admin endpoints (e.g. verifying the audit log)
    admin_emails: str = ""
    environment: str = "dev"  # "prod" turns off the interactive API docs
    # "live" = real model + real search. "demo" = deterministic offline stand-ins (never allowed in prod).
    backend_mode: str = "live"
    # Prometheus scrapes /metrics with this bearer token. Empty = the endpoint is switched off.
    metrics_token: str = ""

    @property
    def jwt_private_key_pem(self) -> str:
        return self.mcp_jwt_private_key.strip().strip("\"'").replace("\\n", "\n").strip()  # some hosts keep the quotes

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def auth_private_key_pem(self) -> str:
        return self.auth_jwt_private_key.strip().strip("\"'").replace("\\n", "\n").strip()

    @property
    def auth_public_key_pem(self) -> str:
        return self.auth_jwt_public_key.strip().strip("\"'").replace("\\n", "\n").strip()


settings = Settings()
