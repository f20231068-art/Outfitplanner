from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_server.sellers import ALL_DOMAINS


def _find_env_file() -> Path | None:
    """The repo-root .env for local development. In a container there is none (settings come from
    real environment variables), and that is fine."""
    return next((p / ".env" for p in Path(__file__).resolve().parents if (p / ".env").is_file()), None)


ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # --- product search: Tavily Search (https://docs.tavily.com). One search = 1 credit (2 for "advanced").
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com/search"
    tavily_search_depth: str = "basic"  # basic | fast | ultra-fast = 1 credit; advanced = 2 credits
    tavily_max_results: int = 20  # the most one search returns; it costs the same as 5
    # Tavily only DISCOVERS pages; their price, image and stock are read from the store's own page (free):
    # Pages are read best-first in small batches until there are enough in-stock products, so a search whose top
    # candidates are sold out reads more, and one that finds good products at once reads few.
    page_reads_per_search: int = 15  # never read more than this many candidate pages for one search
    page_read_batch: int = 5  # read this many at a time (also the concurrency limit)
    enough_products: int = 8  # stop reading once this many usable products are in hand (the agent's reader then drops the ones that do not fit)
    tavily_country: str = ""  # e.g. "india" boosts Indian pages; empty = not sent
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
    mcp_rate_limit_per_min: int = 0  # tool calls per user per minute (0 = no limit)
    mcp_daily_credits_per_user: int = 0  # paid search calls per user per UTC day (0 = no limit)
    mcp_daily_credits_global: int = 0  # paid search calls for everyone per UTC day (0 = no limit)
    # Prometheus scrapes /metrics with this bearer token. Empty = the endpoint is switched off.
    metrics_token: str = ""
    # Extra Host names this server may be reached by (e.g. a private service name when deployed).
    mcp_allowed_hosts: str = ""  # comma-separated
    # 127.0.0.1 = only this machine can reach the server. In a container use 0.0.0.0 so other
    # services on the PRIVATE network can reach it; the server then refuses to start unless
    # MCP_ALLOWED_HOSTS is set, and the host must give it no public address.
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001
    search_cache_ttl_s: int = 6 * 3600
    # Hosts we search and link to (a host matches if it equals one of these or is a subdomain): the 100 sellers
    allowed_domains: tuple[str, ...] = ALL_DOMAINS
    force_ipv4: bool = True  # some networks stall ~40s on IPv6 before falling back

    @property
    def jwt_public_key_pem(self) -> str:
        """Hosts often store a PEM on one line with literal \\n; turn those back into line breaks."""
        return self.mcp_jwt_public_key.strip().strip("\"'").replace("\\n", "\n").strip()  # some hosts keep the quotes

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.mcp_allowed_hosts.split(",") if h.strip()]


settings = Settings()
