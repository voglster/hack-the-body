"""Voice food entry — say what you ate, have it logged.

Synchronous on purpose. The "nothing blocking" rule that governs the ingestors
was written for slow models and flaky networks; this is one user on their own
tailnet, and the repo has no general worker to hand the job to. The frontend
already awaits a multi-second `/foods/parse` behind a spinner.

Audio arrives as a 16 kHz mono WAV file — the browser decodes and encodes it
itself, which is why the API image needs no ffmpeg. The WhisperLive boundary
strips the WAV header before transcribing; a bare int16 PCM body works too.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.auth import require_api_key
from app.models.food import Food, Macros, MealEntry, MealSlot
from app.services.food_parser import parse_food_text
from app.services.food_repo import FoodRepo
from app.services.voice.boundary import BoundaryUnavailable, build_transcriber
from app.services.voice.vocabulary import build_speech_context

log = logging.getLogger(__name__)

router = APIRouter(prefix="/foods/voice", tags=["voice"], dependencies=[Depends(require_api_key)])


@router.post("/log", status_code=201)
async def log_dictation(
    request: Request,
    audio: Annotated[UploadFile, File()],
    slot: Annotated[MealSlot, Form()] = "snack",
) -> dict:
    settings = request.app.state.settings
    db = request.app.state.db

    pcm = await audio.read()
    if len(pcm) > settings.voice_max_audio_bytes:
        raise HTTPException(status_code=413, detail="recording too large")

    ctx = await build_speech_context(db)
    transcriber = build_transcriber(settings)

    t0 = perf_counter()
    try:
        transcript = await transcriber.transcribe(pcm, ctx)
    except BoundaryUnavailable as exc:
        # Not an error the user should see as a failure: voice is an
        # accelerator on a logger that works without it. Still recorded,
        # error and all — a silent failure is invisible to the tuning loop
        # this feature exists to feed.
        log.warning("voice unavailable: %s", exc)
        await _record_voice_entry(
            db, settings, slot=slot, ctx=ctx, transcript="",
            items_parsed=0, entry_ids=[],
            transcribe_ms=int((perf_counter() - t0) * 1000), parse_ms=0,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503, detail="voice is unavailable — type it instead",
        ) from exc
    transcribe_ms = int((perf_counter() - t0) * 1000)

    transcript = (transcript or "").strip()
    items = []
    parse_ms = 0
    entry_ids: list[str] = []
    error: str | None = None
    try:
        t1 = perf_counter()
        if transcript:
            items = await parse_food_text(settings, transcript)
        parse_ms = int((perf_counter() - t1) * 1000)

        repo = FoodRepo(db)
        when = datetime.now(UTC)
        for it in items:
            macros = Macros(
                calories=it.calories, protein_g=it.protein_g,
                carbs_g=it.carbs_g, fat_g=it.fat_g,
            )
            food = Food(
                name=it.name, category="food", serving_g=1.0, serving_label=None,
                per_serving=macros, source="voice",
            )
            food.created_at = when
            stored = await repo.upsert_food(food)
            entry = MealEntry(
                ts=when, food_id=stored["id"], food_name=stored["name"],
                food_category="food", quantity_g=1.0, servings=it.servings,
                slot=slot,
                macros=macros,
            )
            inserted = await repo.insert_entry(entry)
            # Appended immediately, not collected and derived at the end —
            # an exception partway through the loop must still leave undo
            # reachable for whatever already landed.
            entry_ids.append(inserted["id"])
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        await _record_voice_entry(
            db, settings, slot=slot, ctx=ctx, transcript=transcript,
            items_parsed=len(items), entry_ids=entry_ids,
            transcribe_ms=transcribe_ms, parse_ms=parse_ms, error=error,
        )

    return {
        "transcript": transcript,
        "items": [
            {"name": i.name, "servings": i.servings, "calories": i.calories,
             "protein_g": i.protein_g, "carbs_g": i.carbs_g, "fat_g": i.fat_g}
            for i in items
        ],
        "logged_entry_ids": entry_ids,
        "count": len(entry_ids),
    }


async def _record_voice_entry(
    db, settings, *, slot: str, ctx, transcript: str, items_parsed: int,
    entry_ids: list[str], transcribe_ms: int, parse_ms: int,
    error: str | None,
) -> None:
    """Every dictation gets a `voice_entries` row — success, degraded, or
    failed — because the transcript beside what it produced (or didn't) is
    the mined-correction signal the tuning loop reads."""
    await db["voice_entries"].insert_one({
        "created_at": datetime.now(UTC),
        "transcript": transcript,
        "slot": slot,
        "hotword_count": len(ctx.hotwords),
        "items_parsed": items_parsed,
        "logged_entry_ids": entry_ids,
        "error": error,
        "ms": {
            "transcribe": transcribe_ms,
            "parse": parse_ms,
            "total": transcribe_ms + parse_ms,
        },
        "stt_model": settings.voice_stt_model,
        "llm_model": settings.llm_model,
    })
