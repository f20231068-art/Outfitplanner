from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """The repo-root .env for local development. In a container there is none (settings come from
    real environment variables), and that is fine."""
    return next((p / ".env" for p in Path(__file__).resolve().parents if (p / ".env").is_file()), None)


ENV_FILE = _find_env_file()

# Retailers we are willing to show (matched as lowercase substrings of Google's "source" name).
DEFAULT_ALLOWED_RETAILERS = (
    "myntra", "amazon", "flipkart", "ajio", "tata cliq", "tatacliq", "levi", "nykaa",
    "shoppers stop", "souled store", "bewakoof", "snitch", "h&m", "zara", "uniqlo",
    "jack & jones", "us polo", "u.s. polo", "van heusen", "peter england", "puma", "nike",
)

# Hosts we will open or link to (a host matches if it equals one of these or is a subdomain).
DEFAULT_ALLOWED_DOMAINS = (
    "myntra.com", "amazon.in", "flipkart.com", "ajio.com", "tatacliq.com", "levi.in",
    "nykaafashion.com", "nykaaman.com", "shoppersstop.com", "thesouledstore.com",
    "bewakoof.com", "snitch.com", "hm.com", "zara.com", "uniqlo.com", "jackjones.in",
    "ustopa.com", "vanheusenindia.com", "peterengland.com", "puma.com", "nike.com",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    serpapi_api_key: str = ""
    # --- who may call this server: the API signs short-lived JWTs, we verify with its PUBLIC key.
    # This server never receives the private key. Required: it will not start without the public key.
    mcp_jwt_public_key: str = ""  # PEM; line breaks may be written as \n
    mcp_jwt_issuer: str = "stylist-api"
    mcp_jwt_audience: str = "stylist-mcp"
    # Clock tolerance (problem: two machines never agree on the exact second). Kept small on
    # purpose: every second of leeway is a second a token lives longer than intended.
    mcp_jwt_leeway_s: int = 10
    # Refuse tokens that claim to live longer than this, even if correctly signed.
    mcp_jwt_max_lifetime_s: int = 60
    # --- abuse limits (see limits.py): they cap the damage, they do not keep anyone out
    mcp_rate_limit_per_min: int = 60  # tool calls per user per minute
    mcp_daily_credits_per_user: int = 40  # paid search calls per user per UTC day
    mcp_daily_credits_global: int = 100  # paid search calls for everyone per UTC day
    # Prometheus scrapes /metrics with this bearer token. Empty = the endpoint is switched off.
    metrics_token: str = ""
    # Extra Host names this server may be reached by (e.g. a private service name when deployed).
    mcp_allowed_hosts: str = ""  # comma-separated
    serpapi_base_url: str = "https://serpapi.com/search.json"
    # 127.0.0.1 = only this machine can reach the server. In a container use 0.0.0.0 so other
    # services on the PRIVATE network can reach it; the server then refuses to start unless
    # MCP_ALLOWED_HOSTS is set, and the host must give it no public address.
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001
    search_cache_ttl_s: int = 6 * 3600
    allowed_retailers: tuple[str, ...] = DEFAULT_ALLOWED_RETAILERS
    allowed_domains: tuple[str, ...] = DEFAULT_ALLOWED_DOMAINS
    force_ipv4: bool = True  # some networks stall ~40s on IPv6 before falling back

    @property
    def jwt_public_key_pem(self) -> str:
        """Hosts often store a PEM on one line with literal \\n; turn those back into line breaks."""
        return self.mcp_jwt_public_key.replace("\\n", "\n").strip()

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.mcp_allowed_hosts.split(",") if h.strip()]


settings = Settings()
