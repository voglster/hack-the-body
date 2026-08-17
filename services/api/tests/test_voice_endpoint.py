"""POST /foods/voice/log — audio in, meal entries out."""
from unittest.mock import patch

import httpx

from app.services.food_repo import FoodRepo
from app.services.voice.boundary import MockTranscriber
from tests.conftest import llm_body

H = {"X-API-Key": "test-key"}
PARSED = '[{"name": "Scrambled Eggs", "servings": 2, "calories": 150}]'


def _llm(text: str):
    """Stub only the internal LLM call.

    `httpx.AsyncClient.post` is patched at the class level, which also
    covers the test's own ASGI-transport `client` fixture (same class).
    Route real ASGI requests through, and only fake the plain outbound
    call `app.services.llm.complete` makes to the proxy.
    """
    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return llm_body(text)

    orig_post = httpx.AsyncClient.post

    async def _post(self, url, **kw):
        if isinstance(self._transport, httpx.ASGITransport):
            return await orig_post(self, url, **kw)
        return _R()
    return _post


def _audio(n: int = 3200) -> bytes:
    return b"\x00\x01" * (n // 2)


async def test_logs_what_was_heard(client, mock_db):
    with patch.object(httpx.AsyncClient, "post", _llm(PARSED)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs")):
        r = await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "breakfast"},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["transcript"] == "two scrambled eggs"
    assert body["count"] == 1
    assert len(body["logged_entry_ids"]) == 1
    assert await mock_db["meal_entries"].count_documents({}) == 1


async def test_voice_logged_foods_are_marked_as_such(client, mock_db):
    """Mis-hearings become permanent catalog rows; source keeps them sweepable."""
    with patch.object(httpx.AsyncClient, "post", _llm(PARSED)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs")):
        await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "breakfast"},
        )
    food = await mock_db["foods"].find_one({"name": "Scrambled Eggs"})
    assert food["source"] == "voice"


async def test_an_empty_transcript_writes_nothing(client, mock_db):
    """Silently logging nothing-shaped-as-something is the failure that would
    never get noticed."""
    with patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("   ")):
        r = await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "snack"},
        )
    assert r.status_code == 201
    assert r.json()["count"] == 0
    assert await mock_db["meal_entries"].count_documents({}) == 0


async def test_an_unavailable_vendor_degrades_rather_than_500ing(client):
    with patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber(fail=True)):
        r = await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "snack"},
        )
    assert r.status_code == 503
    assert "voice" in r.json()["detail"].lower()


async def test_oversize_audio_is_rejected(client, settings):
    too_big = b"\x00" * (settings.voice_max_audio_bytes + 2)
    r = await client.post(
        "/foods/voice/log", headers=H,
        files={"audio": ("a.wav", too_big, "audio/wav")},
        data={"slot": "snack"},
    )
    assert r.status_code == 413


async def test_the_dictation_is_recorded_for_later_tuning(client, mock_db):
    """voice_entries is what makes it keep working: the transcript sits beside
    the entries it produced, which is the mined-correction signal."""
    with patch.object(httpx.AsyncClient, "post", _llm(PARSED)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs")):
        await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "breakfast"},
        )
    doc = await mock_db["voice_entries"].find_one({})
    assert doc["transcript"] == "two scrambled eggs"
    assert len(doc["logged_entry_ids"]) == 1
    assert doc["items_parsed"] == 1
    assert doc["hotword_count"] >= 0


async def test_an_invalid_slot_is_rejected_before_any_write(client, mock_db):
    """A bogus slot must 422 before `upsert_food` runs — otherwise it orphans
    a `source="voice"` Food row with no matching entry and no voice_entries
    doc to undo it by."""
    with patch.object(httpx.AsyncClient, "post", _llm(PARSED)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs")):
        r = await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "elevenses"},
        )
    assert r.status_code == 422
    assert await mock_db["foods"].count_documents({}) == 0
    assert await mock_db["voice_entries"].count_documents({}) == 0


async def test_an_unavailable_vendor_still_records_a_voice_entry_with_error(client, mock_db):
    with patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber(fail=True)):
        await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "snack"},
        )
    doc = await mock_db["voice_entries"].find_one({})
    assert doc is not None
    assert doc["error"]
    assert doc["logged_entry_ids"] == []


async def test_a_failure_mid_write_still_records_a_voice_entry_and_keeps_undo_ids(client, mock_db):
    """One item lands, the second write blows up: the first entry's id must
    survive into voice_entries so undo still works, and the original error
    must not be swallowed."""
    two_items = (
        '[{"name": "Scrambled Eggs", "servings": 2, "calories": 150}, '
        '{"name": "Toast", "servings": 1, "calories": 80}]'
    )
    orig_insert_entry = FoodRepo.insert_entry
    calls = {"n": 0}

    async def flaky_insert_entry(self, entry):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return await orig_insert_entry(self, entry)

    with patch.object(httpx.AsyncClient, "post", _llm(two_items)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs and toast")), \
         patch.object(FoodRepo, "insert_entry", flaky_insert_entry):
        try:
            await client.post(
                "/foods/voice/log", headers=H,
                files={"audio": ("a.wav", _audio(), "audio/wav")},
                data={"slot": "breakfast"},
            )
        except RuntimeError as exc:
            assert "boom" in str(exc)
        else:
            raise AssertionError("expected the underlying error to propagate")

    assert await mock_db["meal_entries"].count_documents({}) == 1
    doc = await mock_db["voice_entries"].find_one({})
    assert doc is not None
    assert doc["error"] and "boom" in doc["error"]
    assert len(doc["logged_entry_ids"]) == 1


async def test_requires_the_api_key(client):
    r = await client.post(
        "/foods/voice/log",
        files={"audio": ("a.wav", _audio(), "audio/wav")},
        data={"slot": "snack"},
    )
    assert r.status_code in (401, 403)
