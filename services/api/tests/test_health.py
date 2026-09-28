from app.main import frontend_build_id


async def test_healthz_returns_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_version_reports_frontend_build(client):
    r = await client.get("/version")
    assert r.status_code == 200
    assert r.json() == {"build": "dev"}


def test_build_id_follows_index_html(tmp_path):
    (tmp_path / "index.html").write_text("<script src=/assets/index-A.js>")
    first = frontend_build_id(tmp_path)
    (tmp_path / "index.html").write_text("<script src=/assets/index-B.js>")
    assert frontend_build_id(tmp_path) != first
