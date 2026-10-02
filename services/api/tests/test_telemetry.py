"""Traces, metrics, logs and demo mode: how the system reports on itself."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from api.agent.demo import STYLES, ScriptedLLM, parse_budget, parse_occasion
from api.agent.schemas import OutfitPlan, PrefsExtraction, StyleList
from api.config import Settings
from api.main import create_app
from api.telemetry import (
    InstrumentedLLM,
    JsonFormatter,
    RunStats,
    parse_trace_id,
    request_id_var,
    trace_id_var,
)
from tests.test_accounts import AUTH_PRIV, AUTH_PUB
from tests.test_http import (  # noqa: F401  (shared fixtures)
    env,
    events,
    new_conversation,
    say,
    signup,
)

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE}-00f067aa0ba902b7-01"


# ---- trace ids -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "traceparent,x_trace,expected",
    [
        (TRACEPARENT, None, TRACE),
        (None, TRACE, TRACE),
        (TRACEPARENT.upper(), None, TRACE),
        ("garbage", None, None),
        (f"01-{TRACE}-00f067aa0ba902b7-01", None, None),  # unknown version
        (f"00-{'0' * 32}-00f067aa0ba902b7-01", None, None),  # the all-zero id is invalid
        (None, "short", None),
        (None, "../../etc/passwd", None),
        (None, "zz" * 16, None),
        (None, None, None),
    ],
)
def test_only_well_formed_trace_ids_are_adopted(traceparent, x_trace, expected):
    assert parse_trace_id(traceparent, x_trace) == expected


def test_a_callers_trace_id_is_adopted_returned_and_written_to_the_audit_log(env):  # noqa: F811
    auth = signup(env)
    cid = new_conversation(env, auth)
    r = env.client.post(f"/conversations/{cid}/messages", json={"text": "under 4000"},
                        headers={**auth, "traceparent": TRACEPARENT})
    assert r.headers["x-trace-id"] == TRACE
    done = events(r)[-1]
    assert done[0] == "done" and done[1]["trace_id"] == TRACE
    with env.pool.connection() as conn:
        rows = conn.execute("SELECT details FROM audit_log WHERE action = 'message_sent'").fetchall()
    assert rows[0]["details"]["trace_id"] == TRACE  # the audit entry can be matched to the trace


def test_a_malformed_trace_id_is_ignored_and_a_fresh_one_is_made(env):  # noqa: F811
    r = env.client.get("/health", headers={"traceparent": "'; DROP TABLE users;--"})
    tid = r.headers["x-trace-id"]
    assert len(tid) == 32 and all(c in "0123456789abcdef" for c in tid)
    assert "DROP" not in json.dumps(dict(r.headers))


def test_every_response_has_a_request_id_and_a_trace_id(env):  # noqa: F811
    r = env.client.get("/health")
    assert len(r.headers["x-request-id"]) == 16 and len(r.headers["x-trace-id"]) == 32


# ---- per-turn numbers --------------------------------------------------------------------------------
def test_each_step_reports_how_long_it_took_and_done_reports_the_totals(env):  # noqa: F811
    auth = signup(env)
    cid = new_conversation(env, auth)
    say(env, auth, cid, "college under 4000")
    third = say(env, auth, cid, "s0")
    statuses = [d for e, d in third if e == "status"]
    assert statuses and all(isinstance(d["duration_ms"], int) and d["duration_ms"] >= 0 for d in statuses)
    elapsed = [d["elapsed_ms"] for d in statuses]
    assert elapsed == sorted(elapsed)  # time only moves forward

    done = third[-1][1]
    assert done["outcome"] == "ok" and done["outfit_count"] == 4 and len(done["trace_id"]) == 32
    assert done["stats"]["llm_calls"] == 1  # picking a style resumes at plan_outfits: one model call
    assert done["stats"]["searches"] == 8  # four outfits, a top and a bottom each
    assert done["stats"]["search_errors"] == 0


def test_a_turn_that_asks_a_question_reports_that_it_is_waiting(env):  # noqa: F811
    auth = signup(env)
    cid = new_conversation(env, auth)
    done = say(env, auth, cid, "under 4000")[-1][1]
    assert done["outcome"] == "waiting_for_user" and done["outfit_count"] == 0


def test_the_model_wrapper_counts_and_times_every_call():
    stats = RunStats()
    llm = InstrumentedLLM(ScriptedLLM(), stats)
    llm.with_structured_output(StyleList).invoke([])
    llm.with_structured_output(StyleList).invoke([])
    assert stats.llm_calls == 2 and stats.llm_seconds >= 0 and llm.model_name == "demo-scripted"


# ---- metrics -----------------------------------------------------------------------------------------
def _metrics_client(env, token="scrape-token-123"):  # noqa: F811
    env.app.state.cfg = Settings(auth_jwt_private_key=AUTH_PRIV, auth_jwt_public_key=AUTH_PUB, metrics_token=token, _env_file=None)
    return env.client


def test_metrics_are_off_unless_a_token_is_configured(env):  # noqa: F811
    assert env.client.get("/metrics").status_code == 404


def test_metrics_need_the_right_bearer_token(env):  # noqa: F811
    c = _metrics_client(env)
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = c.get("/metrics", headers={"Authorization": "Bearer scrape-token-123"})
    assert ok.status_code == 200 and "stylist_http_requests_total" in ok.text


def test_a_conversation_shows_up_in_the_metrics_with_templated_routes(env):  # noqa: F811
    c = _metrics_client(env)
    auth = signup(env)
    cid = new_conversation(env, auth)
    say(env, auth, cid, "college under 4000")
    say(env, auth, cid, "s0")
    text = c.get("/metrics", headers={"Authorization": "Bearer scrape-token-123"}).text
    assert 'stylist_chat_turns_total{outcome="ok"}' in text
    assert "stylist_outfits_delivered_total" in text and "stylist_stage_seconds_bucket" in text
    assert 'route="/conversations/{conversation_id}/messages"' in text  # not the raw id: keeps metrics small
    assert cid not in text  # no ids, no user data in metrics
    assert "alice@example.com" not in text


def test_failed_logins_and_rate_limits_are_counted(env):  # noqa: F811
    c = _metrics_client(env)
    signup(env)
    c.post("/auth/login", json={"email": "alice@example.com", "password": "wrong password!"})
    text = c.get("/metrics", headers={"Authorization": "Bearer scrape-token-123"}).text
    assert 'stylist_logins_total{outcome="failed"}' in text


# ---- logs --------------------------------------------------------------------------------------------
def test_log_lines_are_json_and_carry_the_ids_but_nothing_else_sensitive():
    request_id_var.set("req123")
    trace_id_var.set(TRACE)
    record = logging.LogRecord("api", logging.INFO, "f.py", 1, "POST /auth/login -> 200 in 12ms", None, None)
    line = json.loads(JsonFormatter().format(record))
    assert line["request_id"] == "req123" and line["trace_id"] == TRACE and line["level"] == "INFO"
    assert set(line) == {"ts", "level", "logger", "msg", "request_id", "trace_id"}


def test_exceptions_are_logged_with_their_stack_as_one_json_line():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord("api", logging.ERROR, "f.py", 1, "failed", None, sys.exc_info())
    line = JsonFormatter().format(record)
    assert "\n" not in line and "ValueError: boom" in json.loads(line)["exc"]


# ---- demo mode -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,budget",
    [("around 4000 rupees", 4000), ("under 4k", 4000), ("₹4,500", 4500), ("budget 12000", 12000),
     ("2 shirts please", None), ("no number here", None), ("I have 250 rupees", None)],
)
def test_budgets_are_read_from_natural_phrases(text, budget):
    assert parse_budget(text) == budget


def test_occasions_are_recognised():
    assert parse_occasion("something for my College fest") == "college"
    assert parse_occasion("nothing special") is None


def test_the_scripted_model_plans_varied_outfits_inside_the_budget():
    runner = ScriptedLLM().with_structured_output(OutfitPlan)
    context = {"preferences": {"budget_inr": 4000}, "chosen_style": {"id": "streetwear"}, "outfits_needed": 4}
    plan = runner.invoke([type("M", (), {"content": json.dumps(context), "type": "human"})()])
    assert len(plan.outfits) == 4
    assert all(o.top.max_price_inr + o.bottom.max_price_inr <= 4000 for o in plan.outfits)
    pairs = {(o.top.item, o.bottom.item) for o in plan.outfits}
    assert len(pairs) == 4  # no two outfits use the same garments


def test_different_styles_start_from_different_pieces():
    def plan(style):
        ctx = {"preferences": {"budget_inr": 4000}, "chosen_style": {"id": style}, "outfits_needed": 4}
        return ScriptedLLM().with_structured_output(OutfitPlan).invoke([type("M", (), {"content": json.dumps(ctx), "type": "human"})()])

    assert plan("streetwear").outfits[0].top.item != plan("minimalist").outfits[0].top.item


def test_the_scripted_model_extracts_preferences_only_from_the_shoppers_words():
    ai = type("M", (), {"content": "How about 9000 for the college trip?", "type": "ai"})()
    human = type("M", (), {"content": "casual wear please", "type": "human"})()
    prefs = ScriptedLLM().with_structured_output(PrefsExtraction).invoke([ai, human])
    assert prefs.budget_inr is None and prefs.occasion == "casual"  # the assistant's 9000 is not the shopper's budget


def test_demo_mode_runs_a_whole_conversation_through_the_real_checkpointer(db_url, pool):
    cfg = Settings(database_url=db_url, backend_mode="demo", auth_jwt_private_key=AUTH_PRIV,
                   auth_jwt_public_key=AUTH_PUB, _env_file=None)
    with TestClient(create_app(cfg, pool=pool), base_url="http://localhost") as client:
        token = client.post("/auth/register", json={"email": "shopper@example.com", "password": "a long test passphrase"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        cid = client.post("/conversations", headers=auth).json()["id"]
        first = events(client.post(f"/conversations/{cid}/messages", json={"text": "college wear, around 4000 rupees"}, headers=auth))
        assert [d["type"] for e, d in first if e == "interrupt"] == ["choose_style"]
        final = events(client.post(f"/conversations/{cid}/messages", json={"text": STYLES[1][0]}, headers=auth))
        outfits = next(d["outfits"] for e, d in final if e == "outfits")
        assert len(outfits) == 4 and all(o["total_inr"] <= 4000 for o in outfits)
        # the conversation survives in Postgres: a brand-new request reads it back
        history = client.get(f"/conversations/{cid}", headers=auth).json()
        assert history["pending"] is None and len(history["outfits"]) == 4
        buy = client.post(f"/products/{outfits[0]['top']['product_id']}/buy-link", headers=auth)
        assert buy.status_code == 200 and buy.json()["store"] == "Demo Store"


def test_demo_mode_is_refused_in_production():
    with pytest.raises(RuntimeError, match="not allowed"):
        create_app(Settings(backend_mode="demo", environment="prod", _env_file=None))
