"""Read-only audit_log endpoints. Writes happen in-process via
`app.services.audit.record_change` at the mutation site; the API only
surfaces history queries (the CLI in tools/audit.py is the primary
consumer)."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_api_key

router = APIRouter(prefix="/audit", dependencies=[Depends(require_api_key)])


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = {**doc}
    out["id"] = str(out.pop("_id"))
    return out


@router.get("/log")
async def list_audit(
    request: Request,
    entity: Annotated[str | None, Query(description="exact match, e.g. 'user_profile.targets'")] = None,
    entity_id: Annotated[str | None, Query()] = None,
    changed_path: Annotated[
        str | None,
        Query(description="dotted field name (matches `changed_paths`)"),
    ] = None,
    actor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict[str, Any]]:
    db = request.app.state.db
    query: dict[str, Any] = {}
    if entity is not None:
        query["entity"] = entity
    if entity_id is not None:
        query["entity_id"] = entity_id
    if changed_path is not None:
        query["changed_paths"] = changed_path
    if actor is not None:
        query["actor"] = actor
    cur = db["audit_log"].find(query).sort("ts", -1).limit(limit)
    return [_serialize(d) async for d in cur]
