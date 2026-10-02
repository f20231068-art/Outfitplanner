"""Outbound HTTP: one place that decides timeouts, IPv4 and how failures are retried."""

import asyncio
import logging
import random

import httpx

from mcp_server.config import Settings, settings

RETRYABLE = {429, 500, 502, 503, 504}

# httpx logs full request URLs at INFO, and ours contain the search API key.
logging.getLogger("httpx").setLevel(logging.WARNING)


class UpstreamError(Exception):
    """An outside service failed in a way the caller may or may not retry."""

    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def make_client(cfg: Settings = settings, transport: httpx.AsyncBaseTransport | None = None):
    if transport is None and cfg.force_ipv4:
        transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    return httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), transport=transport)


async def get_json(
    client: httpx.AsyncClient, url: str, params: dict | None, *, retries: int = 2, base_delay: float = 0.5
) -> dict:
    """GET with retries on 429/5xx. Waits longer each time, with jitter, and honours Retry-After."""
    last = "unknown error"
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params=params) if params else await client.get(url)
        except httpx.TransportError as exc:  # timeouts, connection resets
            last = f"{type(exc).__name__}"
        else:
            if resp.status_code == 200:
                return resp.json()
            last = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRYABLE:
                # 4xx (bad key, bad request) will not fix itself: fail now
                raise UpstreamError(f"search provider rejected the request ({last})", retryable=False)
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit() and attempt < retries:
                await asyncio.sleep(min(int(retry_after), 10))
                continue
        if attempt < retries:
            await asyncio.sleep(base_delay * (2**attempt) + random.uniform(0, 0.25))
    raise UpstreamError(f"search provider unavailable after {retries + 1} tries ({last})", retryable=True)
