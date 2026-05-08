"""Tests for the treadmill -> Garmin uploader."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.treadmill_uploader import upload_pending


class FakeClient:
    def __init__(
        self, response=None, raises=None, set_type_raises=None,
        resolved_activity_id=None,
    ):
        self.response = response
        self.raises = raises
        self.set_type_raises = set_type_raises
        self.resolved_activity_id = resolved_activity_id
        self.uploads: list[bytes] = []
        self.logged_in = False
        self.set_type_calls: list[int | str] = []
        self.resolve_calls: list[datetime] = []

    def login(self):
        self.logged_in = True

    def upload_tcx(self, tcx_bytes, *, name_hint):  # noqa: ARG002
        self.uploads.append(tcx_bytes)
        if self.raises:
            raise self.raises
        return self.response

    def set_activity_type_walking(self, activity_id):
        self.set_type_calls.append(activity_id)
        if self.set_type_raises:
            raise self.set_type_raises
        return {"ok": True}

    def find_activity_by_start_time(self, started_at, tolerance_s=90):  # noqa: ARG002
        self.resolve_calls.append(started_at)
        return self.resolved_activity_id


@pytest.fixture(autouse=True)
def _no_resolve_delay(monkeypatch):
    # Keep tests fast: skip the inter-attempt sleep when polling for
    # the async-promoted activityId.
    monkeypatch.setattr("app.treadmill_uploader.RESOLVE_DELAY_S", 0)


@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    return client["testdb"]


def _workout_doc(**over):
    started = datetime(2026, 5, 1, 17, 0, 0, tzinfo=UTC)
    return {
        "started_at": started,
        "ended_at": started + timedelta(minutes=20),
        "duration_s": 1200,
        "distance_mi": 1.0,
        "avg_speed_mph": 3.0,
        "max_speed_mph": 3.5,
        "avg_hr": 120,
        "max_hr": 140,
        "calories": 150,
        "status": "complete",
        "source": "precor-csafe",
        "source_id": "treadmill:2026-05-01T17:00:00+00:00",
        "ts": started,
        **over,
    }


@pytest.mark.asyncio
async def test_uploader_skips_when_no_pending(db):
    client = FakeClient()
    counts = await upload_pending(db, client)
    assert counts["uploaded"] == 0 and counts["retyped"] == 0
    assert not client.logged_in
    assert client.uploads == []


@pytest.mark.asyncio
async def test_uploader_uploads_pending_and_marks_done(db):
    await db["workouts"].insert_one(_workout_doc())
    client = FakeClient(response={
        "detailedImportResult": {
            "successes": [{"internalId": 12345}],
        },
    })

    counts = await upload_pending(db, client)
    assert counts["uploaded"] == 1
    assert client.logged_in
    assert len(client.uploads) == 1
    # TCX content sanity check
    assert b"<Activity" in client.uploads[0]

    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert stored["garmin_activity_id"] == 12345
    # Activity was re-typed to walking immediately after upload.
    assert client.set_type_calls == [12345]
    assert stored["garmin_type_corrected"] is True


@pytest.mark.asyncio
async def test_uploader_marks_uncorrected_when_only_uploadid_and_resolve_fails(db):
    """If the upload returns only an uploadId AND we can't find the
    promoted activityId via lookup, fall back to the uploadId and leave
    the type uncorrected — at least the row is marked done so we don't
    loop."""
    await db["workouts"].insert_one(_workout_doc())
    client = FakeClient(
        response={
            "detailedImportResult": {
                "uploadId": 433973775291,
                "successes": [],
            },
        },
        resolved_activity_id=None,
    )
    counts = await upload_pending(db, client)
    assert counts["uploaded"] == 1
    assert client.set_type_calls == []
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert stored["garmin_activity_id"] == 433973775291
    assert stored["garmin_type_corrected"] is False
    # We polled — multiple times — to try to resolve.
    assert len(client.resolve_calls) >= 2


@pytest.mark.asyncio
async def test_uploader_resolves_uploadid_then_corrects_type(db):
    """The common production path: TCX upload returns successes:[]
    + uploadId, but the activity is on Garmin's side a beat later. We
    look it up by start time, store the real activityId, and reclassify
    it to walking."""
    await db["workouts"].insert_one(_workout_doc())
    client = FakeClient(
        response={
            "detailedImportResult": {
                "uploadId": 433973775291,
                "successes": [],
            },
        },
        resolved_activity_id=22769921591,
    )
    counts = await upload_pending(db, client)
    assert counts["uploaded"] == 1
    assert client.set_type_calls == [22769921591]
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert stored["garmin_activity_id"] == 22769921591
    assert stored["garmin_type_corrected"] is True


@pytest.mark.asyncio
async def test_uploader_survives_set_type_failure(db):
    """If set_activity_type errors out, the upload is still marked done so
    we don't loop. The corrected flag stays false so we know to fix it."""
    await db["workouts"].insert_one(_workout_doc())
    client = FakeClient(
        response={"detailedImportResult": {"successes": [{"internalId": 12345}]}},
        set_type_raises=RuntimeError("boom"),
    )
    counts = await upload_pending(db, client)
    assert counts["uploaded"] == 1
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert stored["garmin_activity_id"] == 12345
    assert stored["garmin_type_corrected"] is False


@pytest.mark.asyncio
async def test_uploader_doesnt_re_upload(db):
    await db["workouts"].insert_one(
        _workout_doc(garmin_activity_id=999, garmin_type_corrected=True),
    )
    client = FakeClient()
    counts = await upload_pending(db, client)
    assert counts["uploaded"] == 0 and counts["retyped"] == 0
    assert client.uploads == []


@pytest.mark.asyncio
async def test_uploader_retypes_stranded_workouts(db):
    """Pre-fix uploads (or transient set_activity_type failures) leave rows
    with garmin_activity_id set but garmin_type_corrected=False. On the next
    pass we resolve the real activityId and reclassify to walking."""
    await db["workouts"].insert_one(
        _workout_doc(garmin_activity_id=433973775291, garmin_type_corrected=False),
    )
    client = FakeClient(resolved_activity_id=22769921591)
    counts = await upload_pending(db, client)
    assert counts["retyped"] == 1
    assert counts["uploaded"] == 0
    assert client.set_type_calls == [22769921591]
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert stored["garmin_activity_id"] == 22769921591
    assert stored["garmin_type_corrected"] is True


@pytest.mark.asyncio
async def test_uploader_retype_uses_stored_id_when_resolve_fails(db):
    """If we can't find the activity by start time, fall back to the stored
    id (which may be a real activityId from a transient set-type failure)."""
    await db["workouts"].insert_one(
        _workout_doc(garmin_activity_id=12345, garmin_type_corrected=False),
    )
    client = FakeClient(resolved_activity_id=None)
    counts = await upload_pending(db, client)
    assert counts["retyped"] == 1
    assert client.set_type_calls == [12345]


@pytest.mark.asyncio
async def test_uploader_retype_records_failure(db):
    await db["workouts"].insert_one(
        _workout_doc(garmin_activity_id=12345, garmin_type_corrected=False),
    )
    client = FakeClient(
        resolved_activity_id=12345,
        set_type_raises=RuntimeError("boom"),
    )
    counts = await upload_pending(db, client)
    assert counts["retype_failed"] == 1
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert stored["garmin_type_corrected"] is False


@pytest.mark.asyncio
async def test_uploader_uses_uploadid_when_successes_empty_and_no_lookup(db):
    # When successes is empty and the lookup also can't find it, we
    # still record the uploadId so the row isn't re-uploaded.
    await db["workouts"].insert_one(_workout_doc())
    client = FakeClient(
        response={
            "detailedImportResult": {
                "uploadId": 433973775291,
                "uploadUuid": {"uuid": "abc"},
                "successes": [],
            },
        },
        resolved_activity_id=None,
    )
    counts = await upload_pending(db, client)
    assert counts["uploaded"] == 1
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert stored["garmin_activity_id"] == 433973775291


@pytest.mark.asyncio
async def test_uploader_marks_duplicate_when_no_id_returned(db):
    await db["workouts"].insert_one(_workout_doc())
    client = FakeClient(response={"detailedImportResult": {"successes": []}})
    counts = await upload_pending(db, client)
    assert counts["duplicate"] == 1
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert "garmin_upload_skipped" in stored
    # Subsequent run is a no-op
    counts2 = await upload_pending(db, client)
    assert counts2["uploaded"] == 0
    assert len(client.uploads) == 1  # didn't retry


@pytest.mark.asyncio
async def test_uploader_records_error_on_failure(db):
    await db["workouts"].insert_one(_workout_doc())
    client = FakeClient(raises=RuntimeError("boom"))
    counts = await upload_pending(db, client)
    assert counts["failed"] == 1
    stored = await db["workouts"].find_one({"source": "precor-csafe"})
    assert "garmin_last_error" in stored
    assert "boom" in stored["garmin_last_error"]
    # Failures aren't permanently skipped — next call retries
    counts2 = await upload_pending(db, client)
    assert counts2["failed"] == 1
