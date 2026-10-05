"""The whole HTTP API, end to end: accounts, ownership, streaming chat, buy links, audit.
Real Postgres; a fake chat model and fake search so nothing touches the network."""

import json
import time
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from fastmcp.exceptions import ToolError
from langgraph.checkpoint.memory import MemorySaver

from api import audit
from api.agent.graph import build_graph
from api.agent.products import mock_search
from api.config import Settings
from api.main import create_app
from api.telemetry import InstrumentedLLM, InstrumentedSearch, RunStats
from tests.test_accounts import AUTH_PRIV, AUTH_PUB, _pem_pair
from tests.test_agent import FakeLLM

PW = "correct horse battery"
XRW = {"X-Requested-With": "stylist-web"}


def _instrumented_graph(saver, stats):
    """The same wrapping the real app applies, around the fake model and mock search."""
    stats = stats or RunStats()
    return build_graph(InstrumentedLLM(FakeLLM(), stats), InstrumentedSearch(mock_search, stats), saver)


def make_cfg(**kw) -> Settings:
    return Settings(auth_jwt_private_key=AUTH_PRIV, auth_jwt_public_key=AUTH_PUB, _env_file=None, **kw)


class FakeTools:
    """Stands in for the MCP tool server in buy-link tests."""

    def __init__(self, primary=None, verdict="live", error=None):
        self.primary = primary or {"store": "Myntra", "url": "https://www.myntra.com/x/1/buy", "price_inr": 1200, "in_stock": True}
        self.verdict, self.error, self.calls = verdict, error, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        self.calls.append(name)
        if self.error:
            raise self.error
        if name == "get_buy_link":
            return SimpleNamespace(structured_content={"primary": self.primary})
        return SimpleNamespace(structured_content={"verdict": self.verdict})


@pytest.fixture
def env(pool):
    """(client, app, tools) with a fresh database. The chat model and search are fakes."""
    saver = MemorySaver()  # keeps conversation state between requests, like Postgres would
    tools = FakeTools()
    app = create_app(
        make_cfg(), pool=pool,
        graph_factory=lambda user_id, stats=None: _instrumented_graph(saver, stats),
        tool_client_factory=lambda user_id: tools,
    )
    with TestClient(app, base_url="http://localhost") as client:
        yield SimpleNamespace(client=client, app=app, tools=tools, pool=pool, saver=saver)


def signup(env, email="alice@example.com", password=PW):
    r = env.client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def events(response) -> list[tuple[str, dict]]:
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def say(env, auth, cid, text, style_id=None):
    body = {"text": text, **({"style_id": style_id} if style_id else {})}
    return events(env.client.post(f"/conversations/{cid}/messages", json=body, headers=auth))


def new_conversation(env, auth) -> str:
    return env.client.post("/conversations", headers=auth).json()["id"]


# ===== accounts ==========================================================================================
def test_register_gives_a_working_token_and_a_locked_down_refresh_cookie(env):
    r = env.client.post("/auth/register", json={"email": "Alice@Example.com", "password": PW})
    assert r.status_code == 201 and r.json()["token_type"] == "bearer" and r.json()["expires_in"] == 900
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/auth" in cookie
    me = env.client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["email"] == "alice@example.com"


@pytest.mark.parametrize(
    "body,status",
    [
        ({"email": "a@x.com", "password": "short"}, 422),
        ({"email": "not-an-email", "password": PW}, 422),
        ({"email": "a@x.com", "password": PW, "admin": True}, 422),  # unknown fields are refused
        ({"email": "a@x.com"}, 422),
        ({"email": "a@x.com", "password": "x" * 200}, 422),
    ],
)
def test_bad_signups_are_refused(env, body, status):
    assert env.client.post("/auth/register", json=body).status_code == status


def test_registering_an_email_twice_is_a_conflict(env):
    signup(env)
    assert env.client.post("/auth/register", json={"email": "ALICE@example.com", "password": PW}).status_code == 409


def test_wrong_password_and_unknown_email_get_the_identical_answer(env):
    signup(env)
    wrong = env.client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong password!"})
    unknown = env.client.post("/auth/login", json={"email": "nobody@example.com", "password": PW})
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()


def test_five_wrong_passwords_lock_the_login_for_a_while(env):
    signup(env)
    for _ in range(5):
        assert env.client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong password!"}).status_code == 401
    locked = env.client.post("/auth/login", json={"email": "alice@example.com", "password": PW})  # even the RIGHT one
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0


def test_login_works_and_clears_earlier_failures(env):
    signup(env)
    for _ in range(3):
        env.client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong password!"})
    assert env.client.post("/auth/login", json={"email": "alice@example.com", "password": PW}).status_code == 200


def test_refresh_needs_the_csrf_header_and_rotates_the_cookie(env):
    signup(env)
    assert env.client.post("/auth/refresh").status_code == 403  # a hostile page cannot add that header
    first_cookie = env.client.cookies.get("refresh_token")
    r = env.client.post("/auth/refresh", headers=XRW)
    assert r.status_code == 200 and r.json()["access_token"]
    assert env.client.cookies.get("refresh_token") != first_cookie  # replaced by a new one


def test_a_replayed_refresh_cookie_logs_everyone_out_and_is_recorded(env):
    signup(env)
    stolen = env.client.cookies.get("refresh_token")
    assert env.client.post("/auth/refresh", headers=XRW).status_code == 200  # the real owner moves on
    env.client.cookies.set("refresh_token", stolen, path="/auth")
    assert env.client.post("/auth/refresh", headers=XRW).status_code == 401  # the thief's copy
    assert env.client.post("/auth/refresh", headers=XRW).status_code == 401  # and the owner's new one is gone too
    with env.pool.connection() as conn:
        actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "refresh_token_reuse_detected" in actions


def test_logout_ends_the_session(env):
    signup(env)
    assert env.client.post("/auth/logout", headers=XRW).status_code == 204
    assert env.client.post("/auth/refresh", headers=XRW).status_code == 401


@pytest.mark.parametrize(
    "label,header",
    [
        ("no token", None),
        ("garbage", "Bearer not.a.token"),
        ("wrong scheme", "Basic abc"),
        ("empty bearer", "Bearer "),
    ],
)
def test_protected_endpoints_refuse_missing_or_bad_tokens(env, label, header):
    headers = {"Authorization": header} if header else {}
    for call in (env.client.get("/auth/me", headers=headers), env.client.get("/conversations", headers=headers),
                 env.client.post("/conversations", headers=headers)):
        assert call.status_code == 401, label


def test_an_expired_token_and_a_service_token_are_both_refused(env):
    now = int(time.time())
    base = {"iss": "stylist-api", "sub": "someone", "iat": now - 4000}
    expired = jwt.encode({**base, "aud": "stylist-web", "exp": now - 3000}, AUTH_PRIV, algorithm="RS256")
    for_mcp = jwt.encode({**base, "aud": "stylist-mcp", "iat": now, "exp": now + 60}, AUTH_PRIV, algorithm="RS256")
    forged = jwt.encode({**base, "aud": "stylist-web", "iat": now, "exp": now + 60}, _pem_pair()[0], algorithm="RS256")
    for token in (expired, for_mcp, forged):
        assert env.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_responses_carry_security_headers_and_a_request_id(env):
    r = env.client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert len(r.headers["x-request-id"]) == 16
    assert env.client.post("/auth/login", json={"email": "a@x.com", "password": "x"}).headers["cache-control"] == "no-store"


def test_only_our_web_origin_may_call_the_api_from_a_browser(env):
    ok = env.client.options("/auth/login", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    bad = env.client.options("/auth/login", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


# ===== the audit log ======================================================================================
def test_account_events_are_audited_without_secrets_and_the_chain_verifies(env):
    signup(env)
    env.client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong password!"})
    with env.pool.connection() as conn:
        rows = conn.execute("SELECT action, details FROM audit_log ORDER BY id").fetchall()
        blob = json.dumps([dict(r) for r in rows], default=str)
        assert [r["action"] for r in rows] == ["register", "login_failed"]
        assert "alice@example.com" not in blob and PW not in blob and "wrong password" not in blob
        assert audit.verify_chain(conn).ok


def test_only_an_admin_can_verify_the_audit_log_and_everyone_else_sees_404(env):
    signup(env, "boss@example.com")
    normal = signup(env, "alice@example.com")
    assert env.client.get("/admin/audit/verify", headers=normal).status_code == 404
    env.app.state.cfg = make_cfg(admin_emails="boss@example.com")
    boss = {"Authorization": "Bearer " + env.client.post("/auth/login", json={"email": "boss@example.com", "password": PW}).json()["access_token"]}
    report = env.client.get("/admin/audit/verify", headers=boss).json()
    assert report["ok"] is True and report["entries"] >= 3


# ===== conversations ======================================================================================
def test_a_user_only_sees_and_touches_their_own_conversations(env):
    alice, bob = signup(env, "alice@example.com"), signup(env, "bob@example.com")
    cid = new_conversation(env, alice)
    assert [c["id"] for c in env.client.get("/conversations", headers=alice).json()] == [cid]
    assert env.client.get("/conversations", headers=bob).json() == []
    assert env.client.get(f"/conversations/{cid}", headers=bob).status_code == 404  # looks like it does not exist
    assert env.client.post(f"/conversations/{cid}/messages", json={"text": "hi"}, headers=bob).status_code == 404
    assert env.client.get("/conversations/not-a-uuid", headers=alice).status_code == 404


def test_a_full_conversation_streams_progress_asks_questions_and_delivers_outfits(env):
    auth = signup(env)
    cid = new_conversation(env, auth)

    first = say(env, auth, cid, "under 4000")  # no occasion yet: the agent asks
    assert [e for e, _ in first] == ["status", "message", "pending", "done"]
    ask = next(d for e, d in first if e == "pending")
    assert ask["type"] == "ask" and "occasion" in ask["question"]

    second = say(env, auth, cid, "college")  # answers the question: styles to choose from
    types = [e for e, _ in second]
    assert types[-1] == "done" and types[-2] == "pending"
    styles = next(d for e, d in second if e == "pending")
    assert styles["type"] == "choose_style" and len(styles["styles"]) == 5

    chosen = styles["styles"][2]
    third = say(env, auth, cid, chosen["name"], style_id=chosen["id"])  # clicks a style card
    kinds = [e for e, _ in third]
    assert kinds.count("status") >= 4 and kinds[-4:] == ["outfits", "message", "pending", "done"]
    assert third[-2][1] is None  # nothing is pending: the shopper can simply type what to change
    outfits = next(d for e, d in third if e == "outfits")["outfits"]
    assert len(outfits) == 4 and all(o["total_inr"] <= 4000 for o in outfits)
    assert all(o["top"]["image_url"] and o["bottom"]["title"] for o in outfits)

    history = env.client.get(f"/conversations/{cid}", headers=auth).json()
    assert history["pending"] is None and history["phase"] == "outfits_shown" and len(history["outfits"]) == 4
    assert history["messages"][0] == {"role": "user", "text": "under 4000"}
    assert history["title"] == "under 4000"


def test_outfits_are_saved_with_the_evidence_for_each_item(env):
    auth = signup(env)
    cid = new_conversation(env, auth)
    say(env, auth, cid, "college under 4000")
    say(env, auth, cid, "Style 0", style_id="s0")
    with env.pool.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM outfits").fetchone()["n"] == 4
        row = conn.execute("SELECT verification FROM outfit_items LIMIT 1").fetchone()
    assert row["verification"]["is_match"] is True and row["verification"]["checks"]


def test_the_audit_log_records_that_messages_were_sent_but_never_what_they_said(env):
    auth = signup(env)
    cid = new_conversation(env, auth)
    say(env, auth, cid, "my secret budget is under 4000 for college")
    with env.pool.connection() as conn:
        blob = json.dumps([dict(r) for r in conn.execute("SELECT action, details FROM audit_log").fetchall()], default=str)
        assert "message_sent" in blob and "secret" not in blob and "college" not in blob
        assert audit.verify_chain(conn).ok


@pytest.mark.parametrize("text,status", [("", 422), ("   ", 422), ("x" * 501, 422)])
def test_empty_blank_and_oversized_messages_are_refused(env, text, status):
    auth = signup(env)
    cid = new_conversation(env, auth)
    assert env.client.post(f"/conversations/{cid}/messages", json={"text": text}, headers=auth).status_code == status
    assert env.client.post(f"/conversations/{cid}/messages", json={"text": "hi", "x": 1}, headers=auth).status_code == 422


def test_messages_are_rate_limited_per_user(env):
    env.app.state.chat_limiter.limit = 2
    auth = signup(env)
    cid = new_conversation(env, auth)
    for _ in range(2):
        assert env.client.post(f"/conversations/{cid}/messages", json={"text": "under 4000"}, headers=auth).status_code == 200
    r = env.client.post(f"/conversations/{cid}/messages", json={"text": "under 4000"}, headers=auth)
    assert r.status_code == 429 and "retry-after" in r.headers


def test_a_second_message_while_one_is_running_is_refused_not_interleaved(env):
    auth = signup(env)
    cid = new_conversation(env, auth)
    env.app.state.active_conversations.add(cid)  # as if a turn were still running
    assert env.client.post(f"/conversations/{cid}/messages", json={"text": "hi"}, headers=auth).status_code == 409


def test_the_daily_limit_on_new_conversations_is_enforced(env):
    env.app.state.cfg = make_cfg(daily_conversations_per_user=2)
    auth = signup(env)
    assert new_conversation(env, auth) and new_conversation(env, auth)
    assert env.client.post("/conversations", headers=auth).status_code == 429


def test_when_the_agent_crashes_the_user_gets_a_clean_message_and_the_conversation_is_not_stuck(env):
    class Boom:
        def get_state(self, config):
            return SimpleNamespace(tasks=(), values={})

        def stream(self, *a, **k):
            raise RuntimeError("secret internal detail: db password is hunter2")

    env.app.state.graph_factory = lambda user_id, stats=None: Boom()
    auth = signup(env)
    cid = new_conversation(env, auth)
    resp = env.client.post(f"/conversations/{cid}/messages", json={"text": "hi"}, headers=auth)
    kinds = [e for e, _ in events(resp)]
    assert kinds == ["error", "done"]
    assert "hunter2" not in resp.text and "RuntimeError" not in resp.text and "traceback" not in resp.text.lower()
    assert cid not in env.app.state.active_conversations  # the lock was released
    with env.pool.connection() as conn:
        assert "chat_error" in [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]


def test_a_rate_limited_model_gives_a_friendly_busy_message(env):
    class RateLimited(Exception):
        pass

    class Busy:
        def get_state(self, config):
            return SimpleNamespace(tasks=(), values={})

        def stream(self, *a, **k):
            raise RateLimited("429 Too Many Requests")

    env.app.state.graph_factory = lambda user_id, stats=None: Busy()
    auth = signup(env)
    cid = new_conversation(env, auth)
    err = next(d for e, d in events(env.client.post(f"/conversations/{cid}/messages", json={"text": "hi"}, headers=auth)) if e == "error")
    assert "busy" in err["message"]


def test_the_conversation_continues_after_outfits_and_new_sets_are_added(env):
    auth = signup(env)
    cid = new_conversation(env, auth)
    say(env, auth, cid, "college under 4000")
    say(env, auth, cid, "Style 0", style_id="s0")
    again = say(env, auth, cid, "can you make it cheaper")  # typed, not clicked: routed from the saved state
    assert [e for e, _ in again][-4:] == ["outfits", "message", "pending", "done"]
    assert any(d.get("stage") == "refine" for e, d in again if e == "status")
    history = env.client.get(f"/conversations/{cid}", headers=auth).json()
    assert len(history["outfits"]) == 8 and {o["batch"] for o in history["outfits"]} == {1, 2}


# ===== buy links ===========================================================================================
def _shown_product(env, auth) -> str:
    cid = new_conversation(env, auth)
    say(env, auth, cid, "college under 4000")
    say(env, auth, cid, "Style 0", style_id="s0")
    with env.pool.connection() as conn:
        return conn.execute("SELECT product_id FROM outfit_items WHERE product_id IS NOT NULL LIMIT 1").fetchone()["product_id"]


def test_buy_link_resolves_a_product_the_user_was_shown_and_checks_it(env):
    auth = signup(env)
    pid = _shown_product(env, auth)
    r = env.client.post(f"/products/{pid}/buy-link", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"store": "Myntra", "url": "https://www.myntra.com/x/1/buy", "price_inr": 1200, "in_stock": True, "link_status": "live"}
    assert env.tools.calls == ["get_buy_link", "check_link"]


def test_buy_link_refuses_products_the_user_was_never_shown_so_credits_cannot_be_drained(env):
    alice, bob = signup(env, "alice@example.com"), signup(env, "bob@example.com")
    pid = _shown_product(env, alice)
    assert env.client.post(f"/products/{pid}/buy-link", headers=bob).status_code == 404
    assert env.client.post("/products/made-up-id/buy-link", headers=alice).status_code == 404
    assert env.client.post(f"/products/{'x' * 200}/buy-link", headers=alice).status_code == 404
    assert env.tools.calls == []  # not one credit was spent on any of those


def test_buy_link_is_rate_limited_and_requires_login(env):
    auth = signup(env)
    pid = _shown_product(env, auth)
    assert env.client.post(f"/products/{pid}/buy-link").status_code == 401
    env.app.state.buy_limiter.limit = 1
    assert env.client.post(f"/products/{pid}/buy-link", headers=auth).status_code == 200
    assert env.client.post(f"/products/{pid}/buy-link", headers=auth).status_code == 429


def test_a_tool_server_limit_becomes_a_clear_503_and_an_outage_a_generic_502(env):
    auth = signup(env)
    pid = _shown_product(env, auth)
    env.tools.error = ToolError("You have used today's search allowance. It resets at 00:00 UTC.")
    r = env.client.post(f"/products/{pid}/buy-link", headers=auth)
    assert r.status_code == 503 and "allowance" in r.json()["detail"]
    env.tools.error = ConnectionError("10.0.0.7:8001 refused")
    r = env.client.post(f"/products/{pid}/buy-link", headers=auth)
    assert r.status_code == 502 and "10.0.0.7" not in r.text


def test_a_dead_store_link_is_reported_not_hidden(env):
    auth = signup(env)
    pid = _shown_product(env, auth)
    env.tools.verdict = "dead"
    assert env.client.post(f"/products/{pid}/buy-link", headers=auth).json()["link_status"] == "dead"


def test_a_conversation_saved_by_the_older_pausing_agent_simply_continues_on_the_new_one(env):
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    class Old(TypedDict, total=False):
        answer: str

    def wait(state):
        return {"answer": interrupt({"type": "choose_style"})}

    old = StateGraph(Old)
    old.add_node("wait_for_choice", wait)
    old.add_edge(START, "wait_for_choice")
    old.add_edge("wait_for_choice", END)
    auth = signup(env)
    cid = new_conversation(env, auth)
    old.compile(checkpointer=env.saver).invoke({}, {"configurable": {"thread_id": cid}})  # paused, as before

    reply = say(env, auth, cid, "college wear under 4000")  # the old pause is invisible to the new graph
    assert [e for e, _ in reply][-2:] == ["pending", "done"] and "error" not in [e for e, _ in reply]
    assert next(d for e, d in reply if e == "pending")["type"] == "choose_style"


# ===== no usage limits by default ==========================================================================
def test_there_are_no_usage_limits_unless_one_is_configured(env):
    auth = signup(env)
    for _ in range(25):  # far past the old 10-per-minute chat limit and 10 new conversations
        cid = new_conversation(env, auth)
        r = env.client.post(f"/conversations/{cid}/messages", json={"text": "hi"}, headers=auth)
        assert r.status_code == 200
    for i in range(40):  # and past the old 30-a-minute limit on sign-in calls from one address
        r = env.client.post("/auth/login", json={"email": f"nobody{i}@example.com", "password": "a long wrong passphrase"})
        assert r.status_code == 401  # refused for the password, never for being too fast
