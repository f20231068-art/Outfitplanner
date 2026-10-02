"""Buy links. Search results only point at a Google Shopping page; when the shopper clicks "buy" we
ask the tool server for the store's own page (costs one search credit) and check it is alive."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastmcp.exceptions import ToolError

from api import audit, repo
from api.deps import current_user, enforce
from api.security.tokens import Identity

log = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["products"])


@router.post("/{product_id}/buy-link")
async def buy_link(product_id: str, request: Request, who: Identity = Depends(current_user)):
    s = request.app.state
    if not 1 <= len(product_id) <= 64:
        raise HTTPException(404, "Product not found.")
    with s.pool.connection() as conn:
        owned = repo.user_owns_product(conn, who.user_id, product_id)
    if owned is None:  # only products this user was actually shown: stops random credit spending
        raise HTTPException(404, "Product not found.")
    enforce(s.buy_limiter, who.user_id)

    try:
        async with s.tool_client_factory(who.user_id) as tools:
            offer = (await tools.call_tool("get_buy_link", {"product_id": product_id})).structured_content
            primary = (offer or {}).get("primary")
            if primary is None:
                raise HTTPException(502, "The store link is not available right now.")
            check = (await tools.call_tool("check_link", {"url": primary["url"]})).structured_content
    except HTTPException:
        raise
    except ToolError as exc:  # a limit or refusal from the tool server: its message is shopper-safe
        raise HTTPException(503, str(exc)) from exc
    except Exception:
        log.exception("buy-link failed")
        raise HTTPException(502, "The store link is not available right now.") from None

    with s.pool.connection() as conn:
        audit.append(conn, who.user_id, "buy_link_opened", {
            "product": product_id, "store": primary["store"], "link_verdict": check["verdict"],
        })
    return {
        "store": primary["store"], "url": primary["url"], "price_inr": primary.get("price_inr"),
        "in_stock": primary.get("in_stock"), "link_status": check["verdict"],
    }
