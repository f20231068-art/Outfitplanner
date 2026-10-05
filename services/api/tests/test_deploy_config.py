"""Deployment settings that cost a real incident when they were missing. They cannot be exercised without Docker,
so these tests pin the configuration and say why."""

from pathlib import Path

CADDYFILE = (Path(__file__).resolve().parents[3] / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")


def api_block() -> str:
    start = CADDYFILE.index("handle @api")
    return CADDYFILE[start : CADDYFILE.index("handle {", start + 1)]


def test_the_api_route_buffers_request_bodies_or_every_chat_reply_is_cut_off_at_60_seconds():
    # Measured: Caddy 2.11 ends ANY long POST response at exactly 60 s unless the request body is buffered. A chat turn
    # takes 1-2 minutes, so without this the shopper never receives the outfits.
    assert "request_buffers" in api_block()


def test_the_api_route_flushes_streamed_events_immediately():
    assert "flush_interval -1" in api_block()


def test_metrics_are_not_reachable_through_the_public_door():
    matcher = next(line for line in CADDYFILE.splitlines() if line.strip().startswith("@api path"))
    assert "/metrics" not in matcher and "/health" in matcher


def test_the_chat_stream_sends_keep_alives_more_often_than_a_minute():
    from api.routes.chat import HEARTBEAT_S

    assert HEARTBEAT_S <= 15  # proxies and load balancers commonly drop a connection that is silent for ~60 s
