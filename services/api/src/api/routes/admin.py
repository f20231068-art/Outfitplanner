"""Operator-only endpoints. Anyone else gets 404, so the endpoint's existence is not revealed."""

from fastapi import APIRouter, Depends, HTTPException, Request

from api import accounts, audit
from api.deps import current_user
from api.security.tokens import Identity

router = APIRouter(prefix="/admin", tags=["admin"])


def admin_only(request: Request, who: Identity = Depends(current_user)) -> Identity:
    s = request.app.state
    with s.pool.connection() as conn:
        user = accounts.get_user(conn, who.user_id)
    if user is None or user["email"] not in s.cfg.admin_emails_list:
        raise HTTPException(404, "Not found.")
    return who


@router.get("/audit/verify")
def verify_audit(request: Request, _: Identity = Depends(admin_only)):
    """Walk the whole tamper-evident log and report whether the chain is intact."""
    with request.app.state.pool.connection() as conn:
        report = audit.verify_chain(conn)
    return {"ok": report.ok, "entries": report.entries, "first_bad_id": report.first_bad_id, "reason": report.reason}
