"""Public authentication endpoint.

The browser doesn't get the API key handed to it any more (we removed it from
/config.js). Instead the user types a password into the FE; the FE POSTs it
here; if it matches `settings.api_key`, we return 200 and the FE stores the
password in localStorage as the value to send on `X-API-Key` for all future
calls. On any 401 from a protected route, the FE clears localStorage and
re-prompts.

This endpoint is intentionally not behind require_api_key — it's the way IN.
A small constant-time delay would slow brute force; we rely on Caddy / WAF
upstream rate limiting for now since this is single-user.
"""
import hmac

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth")


class VerifyReq(BaseModel):
    password: str = Field(min_length=1)


@router.post("/verify")
async def verify(req: VerifyReq, request: Request) -> dict[str, bool]:
    expected = request.app.state.settings.api_key
    if not hmac.compare_digest(req.password, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password")
    return {"ok": True}
