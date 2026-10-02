"""Every SQL query the chat features use, in one readable place. Each takes a connection."""

import json

import psycopg


def create_conversation(conn: psycopg.Connection, user_id: str) -> dict:
    return conn.execute(
        "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id, title, created_at", (user_id,)
    ).fetchone()


def conversations_today(conn: psycopg.Connection, user_id: str) -> int:
    """How many conversations this user started in the last 24 hours (for the daily cap)."""
    return conn.execute(
        "SELECT count(*) AS n FROM conversations WHERE user_id = %s AND created_at > now() - interval '24 hours'",
        (user_id,),
    ).fetchone()["n"]


def get_conversation(conn: psycopg.Connection, conversation_id: str, user_id: str) -> dict | None:
    """Only ever returns a conversation that belongs to this user. Anyone else's looks like 'not found'."""
    return conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = %s AND user_id = %s",
        (conversation_id, user_id),
    ).fetchone()


def list_conversations(conn: psycopg.Connection, user_id: str, limit: int = 30) -> list[dict]:
    # served by conversations_user_recent_idx (user_id, updated_at DESC): no sorting needed
    return conn.execute(
        "SELECT id, title, updated_at FROM conversations WHERE user_id = %s ORDER BY updated_at DESC LIMIT %s",
        (user_id, limit),
    ).fetchall()


def touch_conversation(conn: psycopg.Connection, conversation_id: str, title: str | None = None) -> None:
    conn.execute(
        "UPDATE conversations SET updated_at = now(), title = CASE WHEN title = 'New conversation' AND %s::text IS NOT NULL THEN %s ELSE title END WHERE id = %s",
        (title, title, conversation_id),
    )


def next_batch(conn: psycopg.Connection, conversation_id: str) -> int:
    return conn.execute(
        "SELECT coalesce(max(batch), 0) + 1 AS n FROM outfits WHERE conversation_id = %s", (conversation_id,)
    ).fetchone()["n"]


def save_outfits(
    conn: psycopg.Connection, user_id: str, conversation_id: str, style_name: str, outfits: list[dict]
) -> int:
    """Store one round of outfits and their two products each. Returns the batch number."""
    batch = next_batch(conn, conversation_id)
    for position, o in enumerate(outfits, start=1):
        outfit_id = conn.execute(
            "INSERT INTO outfits (conversation_id, user_id, batch, position, style_name, total_inr, confidence, rationale)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (conversation_id, user_id, batch, position, style_name, o["total_inr"], o["confidence"], o["rationale"]),
        ).fetchone()["id"]
        for slot in ("top", "bottom"):
            p = o[slot]
            conn.execute(
                "INSERT INTO outfit_items (outfit_id, slot, product_id, title, retailer, price_inr, mrp_inr, url,"
                " url_kind, image_url, verification) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (outfit_id, slot, p.get("product_id"), p["title"], p["retailer"], p["price_inr"], p.get("mrp_inr"),
                 p["url"], p.get("url_kind"), p["image_url"], json.dumps(p.get("verification") or {})),
            )
    return batch


def outfits_for_conversation(conn: psycopg.Connection, conversation_id: str, user_id: str) -> list[dict]:
    """The saved outfits of a conversation, each with its items, newest batch last."""
    rows = conn.execute(
        "SELECT o.id AS outfit_id, o.batch, o.position, o.style_name, o.total_inr, o.confidence, o.rationale,"
        "       i.slot, i.product_id, i.title, i.retailer, i.price_inr, i.mrp_inr, i.url, i.url_kind,"
        "       i.image_url, i.verification"
        " FROM outfits o JOIN outfit_items i ON i.outfit_id = o.id"
        " WHERE o.conversation_id = %s AND o.user_id = %s"
        " ORDER BY o.batch, o.position",
        (conversation_id, user_id),
    ).fetchall()
    by_outfit: dict[str, dict] = {}
    for r in rows:
        o = by_outfit.setdefault(str(r["outfit_id"]), {
            "id": str(r["outfit_id"]), "batch": r["batch"], "position": r["position"], "style": r["style_name"],
            "total_inr": r["total_inr"], "confidence": r["confidence"], "rationale": r["rationale"],
        })
        o[r["slot"]] = {k: r[k] for k in ("product_id", "title", "retailer", "price_inr", "mrp_inr", "url",
                                          "url_kind", "image_url", "verification")}
    return list(by_outfit.values())


def user_owns_product(conn: psycopg.Connection, user_id: str, product_id: str) -> dict | None:
    """Is this product part of an outfit shown to THIS user? Stops anyone spending search credits
    by asking for buy links of products they were never shown."""
    return conn.execute(
        "SELECT i.title, i.retailer FROM outfit_items i JOIN outfits o ON o.id = i.outfit_id"
        " WHERE o.user_id = %s AND i.product_id = %s LIMIT 1",
        (user_id, product_id),
    ).fetchone()


def recent_outfits_within_budget(conn: psycopg.Connection, user_id: str, max_total: int, limit: int = 10) -> list[dict]:
    """Example report: this user's latest outfits at or under a budget, newest first."""
    return conn.execute(
        "SELECT o.id, o.style_name, o.total_inr, o.created_at FROM outfits o"
        " WHERE o.user_id = %s AND o.total_inr <= %s ORDER BY o.created_at DESC LIMIT %s",
        (user_id, max_total, limit),
    ).fetchall()
