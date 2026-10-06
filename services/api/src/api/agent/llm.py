import httpx
from langchain_openai import ChatOpenAI

from api.config import Settings, settings

# OpenCode Zen serves GPT/Grok on /responses and Qwen/DeepSeek/Kimi/GLM/MiniMax on /chat/completions.
_RESPONSES_FAMILIES = ("gpt", "grok")


def _http_clients(cfg: Settings) -> dict:
    """Optionally pin connections to IPv4 (binding to 0.0.0.0 skips the slow IPv6 attempt)."""
    if not cfg.force_ipv4:
        return {}
    return {
        "http_client": httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0")),
        "http_async_client": httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0")
        ),
    }


def get_llm(cfg: Settings = settings) -> ChatOpenAI:
    """Chat model from STYLIST_MODEL = '<provider>/<model-id>', provider: openrouter | opencode.

    The model id may itself contain slashes/colons, e.g. 'openrouter/apodex/apodex-1.1-mini:free'.
    """
    provider, _, model = cfg.stylist_model.partition("/")
    if not model:
        raise ValueError(
            f"STYLIST_MODEL must look like 'openrouter/<model-id>' or 'opencode/<model-id>', "
            f"got {cfg.stylist_model!r}"
        )

    if provider == "openrouter":
        if not cfg.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is empty. Set it in the repo-root .env file.")
        return ChatOpenAI(
            model=model,
            api_key=cfg.openrouter_api_key,
            base_url=cfg.openrouter_base_url,
            default_headers={"X-Title": "AI Stylist"},  # optional, shows the app on OpenRouter
            timeout=cfg.llm_timeout_s,
            max_retries=cfg.llm_max_retries,
            **({"extra_body": {"reasoning": {"effort": cfg.llm_reasoning_effort}}} if cfg.llm_reasoning_effort else {}),
            **_http_clients(cfg),
        )

    if provider == "opencode":
        if not cfg.opencode_api_key:
            raise RuntimeError("OPENCODE_API_KEY is empty. Set it in the repo-root .env file.")
        if model.startswith("claude"):
            raise NotImplementedError(
                "Claude models on OpenCode use the Anthropic-style /messages endpoint; "
                "pick a gpt/qwen/deepseek/kimi model or add langchain-anthropic support."
            )
        mode = cfg.llm_api_mode or ("responses" if model.startswith(_RESPONSES_FAMILIES) else "chat")
        return ChatOpenAI(
            model=model,
            api_key=cfg.opencode_api_key,
            base_url=cfg.opencode_base_url,
            use_responses_api=(mode == "responses"),
            timeout=cfg.llm_timeout_s,
            max_retries=cfg.llm_max_retries,
            **_http_clients(cfg),
        )

    raise ValueError(f"Unknown provider {provider!r} in STYLIST_MODEL={cfg.stylist_model!r}")
