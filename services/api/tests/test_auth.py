from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import require_api_key
from app.config import Settings


async def test_missing_key_rejected():
    app = FastAPI()
    app.state.settings = Settings(api_key="secret")

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/protected")
    assert r.status_code == 401


async def test_wrong_key_rejected():
    app = FastAPI()
    app.state.settings = Settings(api_key="secret")

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/protected", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


async def test_correct_key_accepted():
    app = FastAPI()
    app.state.settings = Settings(api_key="secret")

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/protected", headers={"X-API-Key": "secret"})
    assert r.status_code == 200
