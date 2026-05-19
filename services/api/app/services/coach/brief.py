"""Coach service — wraps Ollama for short, action-oriented insights.

The coach pulls the latest snapshot from Mongo (sleep / HRV / steps / today's
food) plus the last few previous insights, and asks the local LLM for one
observation per metric plus a single concrete action for the next few hours.

Each generated insight is persisted to `coach_insights` so future prompts can
reference what was said before — that's the difference between a one-shot
chatbot and a coach with a memory.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.services.coach.context import Findings, build_findings
from app.services.food_repo import FoodRepo
from app.services.metrics_repo import MetricsRepo

logger = logging.getLogger(__name__)

USER_PROFILE = (
    "43yo male, 6'5\", ~240lb. Goal: build calisthenics strength + cardio "
    "longevity. Lifelong runner; never barbell-lifted."
)

# ---- prompt composition --------------------------------------------------
#
# Two surfaces, two prompts. We deliberately do NOT share a giant
# negative-rule core — the prior version's "no Victorian flourishes, no
# catabolic, no scolding" stack was anti-pattern (the pink-elephant
# effect: mentioned tokens get anchored), and the shared "one fact + one
# action" shape rule was also why the brief collapsed into kiosk-shaped
# one-liners. Instead each surface is a positive, self-contained
# specification anchored on EXAMPLES of the wanted shape.
#
# A tiny COACH_VOICE block carries only what genuinely must agree across
# surfaces: persona, second-person voice, how to read Attention, how to
# read Jim's notes, how to handle units and time. Anything format-shaped
# lives in the surface-specific prompt.

COACH_VOICE = (
    "You are Jim's coach — calm, terse, on his side. Pit-crew chief "
    "register: spoken to between sets, not narrated about. Talk to "
    'Jim in second person — "you", "your". Use "we" sparingly '
    "for shared-goal moments. Use his name at most 1 in 10 messages. "
    "Translate numbers into meaning a teammate would say out loud: "
    "a frame, a pattern, a next step. Every reply stands alone — "
    'no "as I mentioned" or "still nothing on…".\n'
    "\n"
    "Authority of Attention:\n"
    "The `Attention:` list is the authoritative source of what needs "
    "to happen right now. Speak only to items on Attention; "
    "everything else in Metrics is informational. When Attention is "
    "empty, Jim is on track — find something substantive to observe "
    "instead of inventing an action from a calorie gap or a step "
    "count. Under-target calories alone is not a problem unless "
    "'food' or 'calories' is on Attention.\n"
    "\n"
    "Context Jim may have provided:\n"
    "- `Today's note` (if present) is Jim telling you his intent for "
    'today: "dinner out tonight, eating late on purpose." Defer to '
    "it — if he says he is fasting / eating light / eating late, "
    "take that as given and shape the message around it.\n"
    "- `Standing profile` (if present) is his long-lived stance "
    "(e.g. slow weight-loss phase). When it frames low calories as "
    "fine, treat being under target as neutral; flag low calories "
    "only when paired with high activity or low protein.\n"
    "\n"
    "Units and time:\n"
    "- Use `local.hour` (wall clock) for time-of-day reasoning. "
    "Eating window is 11:00-19:00 local. Before 11:00 Jim is "
    "fasting — talk about the day ahead, not eating now.\n"
    "- Use `local.weekday` and `local.is_weekend` for day-of-week "
    "framing. Saturday and Sunday are NOT workdays — do not say "
    '"after work", "before your meeting", "between calls", or '
    "anchor actions to a workday rhythm on weekends. Pick a "
    "weekend-shaped anchor instead (after coffee, this morning, "
    "before dinner, this afternoon). On weekdays, work-day "
    "anchors are fine.\n"
    "- Weight is reported in lbs (`weight.lb`).\n"
    "- `food_logged_today` is the source of truth for whether there "
    "is food on the books today.\n"
    "\n"
    "Audience: Jim is a healthy adult athlete. Calibrate intensity "
    "accordingly — a low-calorie afternoon is a Tuesday, not a "
    "crisis. Variety matters: invent a fresh closer each message; "
    "do not reuse phrases that appeared in recent coach messages."
)

KIOSK_SYSTEM_PROMPT = (
    COACH_VOICE
    + "\n\n"
    + "Surface: wall-mounted kiosk glance-line. Jim reads it from "
    + "across the room, in under two seconds, while walking past — "
    + "this is the most compressed surface in the system.\n"
    + "\n"
    + "Output STRICT JSON with exactly these fields, nothing else, no "
    + "preamble, no markdown fences:\n"
    + "  verb       — one or two UPPERCASE words. The single action "
    + "right now, drawn from a small kit: EAT, WALK, DRINK, LOG "
    + "FOOD, WEIGH IN, CLEAR. Must correspond to an item on "
    + "Attention. If Attention is empty: verb = CLEAR.\n"
    + "  qualifier  — short noun phrase ≤28 chars completing the "
    + "verb (the calorie gap, the step deficit). Empty when verb = "
    + "CLEAR.\n"
    + '  urgency    — "clear" | "action" | "urgent". CLEAR when on '
    + "track; ACTION when something is off-pace but salvageable; "
    + "URGENT when a deadline is within the hour or an item is "
    + "overdue.\n"
    + "  coach      — exactly ONE sentence, 6-12 words. Shape: a "
    + "fact + an action, OR an action + a short common-knowledge "
    + "reason. Examples of the wanted shape:\n"
    + "    \"Protein's holding — chicken at lunch keeps it there.\"\n"
    + '    "Walk 10 after lunch, flattens the glucose curve."\n'
    + "    \"Hydration's behind. 50 oz to go, easy with dinner.\"\n"
    + '    "Front-load protein. Keeps hunger quiet till dinner."\n'
    + "\n"
    + "CLEAR-day `coach` field (≈60% of messages): pick one shape, "
    + "rotating so two consecutive lines never share it —\n"
    + "  (a) quiet acknowledgement of a specific on-track thing,\n"
    + "  (b) a one-clause forward-look that frees attention,\n"
    + "  (c) a pattern observation that proves you noticed (a "
    + "streak, a comparison to yesterday, a time-of-day rhythm).\n"
    + "Invent the phrase fresh each time — do not echo recent coach "
    + "messages.\n"
    + "\n"
    + "Return JSON only."
)

BRIEF_SYSTEM_PROMPT = (
    COACH_VOICE
    + "\n\n"
    + "Surface: dashboard daily debrief. You are writing the read of "
    + "Jim's day so far — the kind of summary a coach delivers at a "
    + "checkpoint, sitting down with the athlete. Room and time to "
    + "be thoughtful. This is the surface where you actually "
    + "interpret the data; the kiosk handles glance-readable "
    + "snippets, so the brief earns its place by being analytical.\n"
    + "\n"
    + "Shape: prose, 2-4 sentences, roughly 30-80 words, cap 120 "
    + "even on heavy days.\n"
    + "1. Lead with an observation rooted in the data — a trend, a "
    + "number that moved, a streak, a recovery pattern, a comparison "
    + "to the week's average. Cite specific numbers from Metrics or "
    + "the Snapshot; the brief's value is naming what changed.\n"
    + "2. Then either a forward-look for the next 4 hours, OR — if "
    + "Attention has items — the concrete action for each off-pace "
    + "metric, named with its number.\n"
    + "3. If Attention has items, close with a one-line read on "
    + "everything else (do NOT enumerate the on-track list).\n"
    + "\n"
    + "Examples of the wanted shape:\n"
    + '  "Sleep ran short again (5h42), third night under 6 in a '
    + "row. HRV's holding so far but the trend usually turns by "
    + "night four — protect tonight, lights out before 10:30. Steps "
    + 'and protein are tracking."\n'
    + '  "Protein hit 110g by 2 PM, ahead of pace; lunch did the '
    + "heavy lifting. Calories will land around 1,800 if dinner "
    + "stays in the usual range — fine for the slow-cut. Walk after "
    + 'dinner; you said you wanted that habit back."\n'
    + '  "Steps are at 3,400 at 1 PM — pace puts you around 7k by '
    + "end of day, short of the 10k baseline. One 20-minute walk "
    + 'after lunch closes most of it. Everything else is on track."\n'
    + "\n"
    + "When Attention is empty (most days): same shape, same length. "
    + "Surface one substantive observation from the data — a 7d vs "
    + "30d trend shift, a streak, a recovery pattern. That "
    + "observation is the brief's reason to exist on a clear day; "
    + "the kiosk already covers the glance-line."
)

# Back-compat aliases. `SYSTEM_PROMPT` is what the rest of the codebase
# imports for the main brief; `COACH_CORE` is referenced by older tests
# and external review tooling.
SYSTEM_PROMPT = BRIEF_SYSTEM_PROMPT
COACH_CORE = COACH_VOICE

# How many recent insights to feed into the next prompt. More = better
# continuity, but tokens grow linearly. 5 fits in <2k tokens easily.
RECENT_LIMIT = 5


@dataclass
class Insight:
    text: str
    model: str
    eval_ms: int
    total_ms: int
    generated_at: datetime
    context: dict[str, Any]
    trigger: str = "manual"
    id: str | None = None  # populated after save_insight persists the row
    # Full inputs to the model — captured so a feedback review can answer
    # "what numbers + history was the model staring at when it wrote that?"
    # `prompt` is the literal rendered text sent to the LLM, including the
    # system prompt of the moment, so we can see which guard-rails were
    # active when a bad output happened (catalysts for prompt edits).
    food_totals: dict[str, Any] | None = None
    history_snapshot: list[dict[str, Any]] | None = None
    prompt: str | None = None
    system_prompt: str | None = None
    thread_id: str | None = None  # populated by generate_insight after thread creation
    anchors: dict[str, str] | None = None  # named placeholders in `text` for rendering


def _strip_meta(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop fields the coach doesn't need so prompts stay tight."""
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "meta", "raw"}:
            continue
        out[k] = v
    return out


_TIME_OF_DAY_BUCKETS: tuple[tuple[int, str], ...] = (
    (5, "late-night"),
    (11, "morning"),
    (14, "midday"),
    (18, "afternoon"),
    (22, "evening"),
)


_SATURDAY = 5  # Python's datetime.weekday(): Mon=0..Sun=6.


def _time_of_day(hour: int) -> str:
    for cutoff, label in _TIME_OF_DAY_BUCKETS:
        if hour < cutoff:
            return label
    return "night"


def resolve_day_window(
    day_start: datetime | None, day_end: datetime | None,
) -> tuple[datetime, datetime]:
    """Return UTC bounds of the user's local day.

    The browser passes its computed bounds when calling /coach/insight; the
    scheduler has no browser, so we derive bounds from the TZ env var. Both
    paths must agree, otherwise food totals (router-resolved) and steps_today
    (gather_context-resolved) drift across the local-midnight crossing.
    Centralizing here is the fix for that drift.
    """
    if day_start is not None and day_end is not None:
        return day_start, day_end
    tz_name = os.environ.get("TZ") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = UTC
    now_local = datetime.now(UTC).astimezone(tz)
    start = datetime.combine(now_local.date(), time.min, tzinfo=tz).astimezone(UTC)
    return start, start + timedelta(days=1)


async def today_food_totals(
    food_repo: FoodRepo, start: datetime, end: datetime,
) -> dict[str, Any]:
    """Sum food entries inside the local-day window into a coach-prompt blob.

    Water (food_name=='Water', zero macros) is tallied separately into
    `water_oz` so it doesn't inflate `entries` or macro totals.
    """
    entries = await food_repo.list_entries_in_range(start, end)
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    food_count = 0
    water_grams = 0.0
    for e in entries:
        if e.get("food_name") == "Water":
            water_grams += float(e.get("quantity_g") or 0)
            continue
        m = e.get("macros") or {}
        for k in totals:
            v = m.get(k)
            if v is not None:
                totals[k] += float(v)
        food_count += 1
    out = {k: round(v, 1) for k, v in totals.items()}
    out["entries"] = food_count
    out["food_logged_today"] = food_count > 0
    out["water_oz"] = round(water_grams / 29.5735, 1)
    return out


async def gather_context(
    repo: MetricsRepo,
    *,
    day_start: datetime | None = None,
    day_end: datetime | None = None,
    targets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot the latest data for the coach prompt.

    `day_start` / `day_end` are the UTC bounds of the user's *local* day (the
    browser computes them from its IANA tz). When omitted (e.g. a scheduled
    push that has no browser to ask) we derive them from the TZ env var so
    'today' lines up with the user's wall clock. Without this, a 7am-local
    push at 12:00 UTC would treat 'today' as starting at midnight UTC =
    6pm-local-yesterday, sweeping in last-evening's steps as if they were
    today's.
    """
    sleep = _strip_meta(await repo.latest_sleep())
    hrv = _strip_meta(await repo.latest_hrv())
    weight = _strip_meta(await repo.latest_weight())
    # The model speaks in lbs; convert at the boundary so it never sees kg
    # and can't accidentally regurgitate the metric value of the wrong unit.
    if weight and "kg" in weight:
        weight = {**weight, "lb": round(weight["kg"] * 2.2046226, 1)}
        weight.pop("kg", None)
    daily = _strip_meta(await repo.latest_daily_summary())

    now_utc = datetime.now(UTC)
    day_start, day_end = resolve_day_window(day_start, day_end)
    intraday = await repo.range_steps_intraday(day_start, day_end)
    today_steps = sum(int(b.get("steps", 0)) for b in intraday)

    # Derive the user's local hour from the day window: midpoint of the
    # window matches their local noon, so window-start is local midnight.
    # `(now - window_start) % 24h` gives the local hour offset.
    elapsed = (now_utc - day_start).total_seconds()
    local_seconds = elapsed % 86_400
    local_hour = int(local_seconds // 3600)
    local_minute = int((local_seconds % 3600) // 60)
    local_now = f"{local_hour:02d}:{local_minute:02d}"

    # Weekday derived from the local-day start so Saturday-evening UTC
    # doesn't read as Sunday-local (or vice versa) — same fix as the
    # local_hour drift, applied to day-of-week framing.
    tz_name = os.environ.get("TZ") or "UTC"
    try:
        local_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        local_tz = UTC
    local_date = day_start.astimezone(local_tz).date()
    weekday = local_date.strftime("%A")
    # weekday(): Mon=0..Fri=4, Sat=5, Sun=6.
    is_weekend = local_date.weekday() >= _SATURDAY

    out: dict[str, Any] = {
        "now_utc": now_utc.isoformat(timespec="minutes"),
        "local_now": local_now,
        "local_hour": local_hour,
        "time_of_day": _time_of_day(local_hour),
        "weekday": weekday,
        "is_weekend": is_weekend,
        "local_day_start_utc": day_start.isoformat(timespec="minutes"),
        "sleep": sleep,
        "hrv": hrv,
        "weight": weight,
        "daily_summary": daily,
        "steps_today": today_steps,
    }
    if targets is not None:
        # Strip fields the model doesn't need (the timestamp); keep only
        # the actual target values. None = don't judge that metric.
        out["targets"] = {
            k: targets.get(k)
            for k in (
                "daily_calories", "daily_protein_g",
                "daily_water_oz", "step_goal_override",
            )
        }
    return out


async def recent_insights(
    db: AsyncDatabase,
    limit: int = RECENT_LIMIT,
    *,
    since: datetime | None = None,
    include_kiosk: bool = False,
) -> list[dict[str, Any]]:
    """Return the most recent N insights ordered newest-first, trimmed for prompt size.

    When `since` is provided, only insights generated at or after that
    timestamp are returned. Callers from `/coach/insight` pass the local-day
    start so yesterday's coach messages don't bleed into today's prompt
    (a real failure mode: an "you haven't eaten yet" message from 11 PM
    yesterday makes the morning coach repeat the same accusation).

    Kiosk-trigger insights are excluded by default. They store a raw JSON
    string in `text` (verb/qualifier/urgency/coach) which would (a) render
    as gibberish in the dashboard CoachCard and (b) confuse the normal
    coach LLM when fed back as "recent coach messages" history.
    """
    query: dict[str, Any] = {}
    if since is not None:
        query["generated_at"] = {"$gte": since}
    if not include_kiosk:
        query["trigger"] = {"$ne": "kiosk"}
    cur = db["coach_insights"].find(query).sort("generated_at", -1).limit(limit)
    return [
        {
            "id": str(doc["_id"]),
            "generated_at": doc.get("generated_at"),
            "text": doc.get("text"),
            "trigger": doc.get("trigger", "manual"),
            # Included so the FE debug panel can show what the model saw
            # for any rendered insight, not just the freshly-generated one.
            "food_totals": doc.get("food_totals"),
            "context": doc.get("context"),
            "anchors": doc.get("anchors"),
        }
        async for doc in cur
    ]


async def save_insight(db: AsyncDatabase, insight: Insight) -> str:
    """Persist an insight; return its id as a string.

    The prompt inputs (`food_totals`, `history_snapshot`, `prompt`,
    `system_prompt`) are stored alongside the response so a feedback
    review can reconstruct exactly what the model saw. Without these,
    we'd be tuning the prompt blind.
    """
    doc = {
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
        "trigger": insight.trigger,
        "food_totals": insight.food_totals,
        "history_snapshot": insight.history_snapshot,
        "prompt": insight.prompt,
        "system_prompt": insight.system_prompt,
        "thread_id": insight.thread_id,
        "anchors": insight.anchors,
    }
    res = await db["coach_insights"].insert_one(doc)
    return str(res.inserted_id)


def render_brief_prompt(
    findings: Findings,
    history: list[dict[str, Any]],
    *,
    system_prompt: str = SYSTEM_PROMPT,
) -> str:
    parts: list[str] = [system_prompt, ""]
    # Note blocks go ABOVE `Client:` so they read like Jim talking to
    # the coach before any data dump. Both are omitted when unset so
    # the prompt stays tight on empty days.
    if findings.coach_note:
        parts.append(f"Standing profile from Jim:\n{findings.coach_note}")
        parts.append("")
    if findings.day_note:
        parts.append(f"Today's note from Jim:\n{findings.day_note}")
        parts.append("")
    parts.extend([f"Client: {USER_PROFILE}", ""])
    parts.append("Snapshot:")
    parts.append(json.dumps(findings.snapshot, indent=2, default=str))
    parts.append("")
    parts.append("Metrics (trends + anomalies):")
    parts.append(json.dumps(findings.metrics, indent=2, default=str))
    parts.append("")
    parts.append(f"On track: {', '.join(findings.on_track) or 'none'}")
    parts.append(f"Attention: {', '.join(findings.attention) or 'none'}")
    parts.append("")
    if findings.food_totals:
        parts.append("Today's food totals:")
        parts.append(json.dumps(findings.food_totals, indent=2, default=str))
    if findings.habits:
        parts.append("")
        parts.append("Today's habits:")
        parts.extend(
            f"  - {h['name']} ({h['kind']}): {h['status']}"
            for h in findings.habits
        )
    if history:
        parts.append("Recent coach messages (oldest first):")
        for h in reversed(history):
            ts = h.get("generated_at")
            ts_s = (
                ts.isoformat(timespec="minutes")
                if isinstance(ts, datetime) else str(ts)
            )
            parts.append(f"[{h.get('trigger', 'manual')} @ {ts_s}] {h.get('text', '')}")
    return "\n".join(parts)


async def generate_insight(
    settings: Settings,
    db: AsyncDatabase,
    *,
    trigger: str = "manual",
    day_start: datetime | None = None,
    day_end: datetime | None = None,
    targets: dict[str, Any] | None = None,
    system_prompt: str = SYSTEM_PROMPT,
    response_format: str | None = None,
) -> Insight:
    repo = MetricsRepo(db)
    food_repo = FoodRepo(db)
    day_start, day_end = resolve_day_window(day_start, day_end)
    findings = await build_findings(
        repo, food_repo,
        day_start=day_start, day_end=day_end, targets=targets,
    )
    history = await recent_insights(db, since=day_start)
    prompt = render_brief_prompt(findings, history, system_prompt=system_prompt)
    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.4, "num_predict": 400},
    }
    if response_format is not None:
        payload["format"] = response_format
    async with httpx.AsyncClient(timeout=settings.coach_timeout_s) as c:
        r = await c.post(f"{settings.ollama_url}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    insight = Insight(
        text=(data.get("response") or "").strip(),
        model=settings.ollama_model,
        eval_ms=int(data.get("eval_duration", 0)) // 1_000_000,
        total_ms=int(data.get("total_duration", 0)) // 1_000_000,
        generated_at=datetime.now(UTC),
        context=findings.to_dict(),
        trigger=trigger,
        food_totals=findings.food_totals,
        history_snapshot=history,
        prompt=prompt,
        system_prompt=system_prompt,
    )
    # Create a thread with the brief as turn 1 BEFORE saving the insight so
    # the insight row can store thread_id.
    from app.services.coach.threads import Turn, create_thread  # noqa: PLC0415
    thread_id = await create_thread(
        db,
        initial_turn=Turn(
            role="coach", text=insight.text, findings_snapshot=findings.to_dict(),
        ),
    )
    insight.thread_id = thread_id
    insight.id = await save_insight(db, insight)
    return insight
