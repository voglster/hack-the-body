"""Voice food entry — say what you ate, have it logged.

Synchronous on purpose. The "nothing blocking" rule that governs the ingestors
was written for slow models and flaky networks; this is one user on their own
tailnet, and the repo has no general worker to hand the job to. The frontend
already awaits a multi-second `/foods/parse` behind a spinner.

Audio arrives as 16 kHz mono int16 PCM because the browser decodes it — which
is why the API image needs no ffmpeg.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.auth import require_api_key
from app.models.food import Food, Macros, MealEntry
from app.services.food_parser import parse_food_text
from app.services.food_repo import FoodRepo
from app.services.voice.boundary import BoundaryUnavailable, build_transcriber
from app.services.voice.vocabulary import build_speech_context

log = logging.getLogger(__name__)

router = APIRouter(prefix="/foods/voice", tags=["voice"], dependencies=[Depends(require_api_key)])


@router.post("/log", status_code=201)
async def log_dictation(
    request: Request,
    audio: UploadFile = File(...),
    slot: str = Form("snack"),
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
        # accelerator on a logger that works without it.
        log.warning("voice unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="voice is unavailable — type it instead",
        ) from exc
    transcribe_ms = int((perf_counter() - t0) * 1000)

    transcript = (transcript or "").strip()
    items = []
    t1 = perf_counter()
    if transcript:
        items = await parse_food_text(settings, transcript)
    parse_ms = int((perf_counter() - t1) * 1000)

    repo = FoodRepo(db)
    when = datetime.now(UTC)
    logged: list[dict] = []
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
            slot=slot,  # type: ignore[arg-type]
            macros=macros,
        )
        logged.append(await repo.insert_entry(entry))

    entry_ids = [e["id"] for e in logged]
    await db["voice_entries"].insert_one({
        "created_at": when,
        "transcript": transcript,
        "slot": slot,
        "hotword_count": len(ctx.hotwords),
        "items_parsed": len(items),
        "logged_entry_ids": entry_ids,
        "ms": {
            "transcribe": transcribe_ms,
            "parse": parse_ms,
            "total": transcribe_ms + parse_ms,
        },
        "stt_model": settings.voice_stt_model,
        "llm_model": settings.llm_model,
    })

    return {
        "transcript": transcript,
        "items": [
            {"name": i.name, "servings": i.servings, "calories": i.calories,
             "protein_g": i.protein_g, "carbs_g": i.carbs_g, "fat_g": i.fat_g}
            for i in items
        ],
        "logged_entry_ids": entry_ids,
        "count": len(logged),
    }
