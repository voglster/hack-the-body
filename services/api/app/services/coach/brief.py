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
# Both coach surfaces (kiosk glance-line + main brief) share one persona,
# one voice, and one set of rules. They diverge ONLY in output shape
# (structured JSON vs prose). Keeping COACH_CORE single-sourced means a
# voice fix lands in both surfaces from one edit; the alternative was two
# drifting copies, which is exactly what we just untangled.

COACH_CORE = (
    "You are Jim's coach — calm, terse, on his side. Think pit crew "
    "chief or strength coach between sets, not cheerleader, not "
    "narrator. Talk TO Jim, not about him.\n"
    "\n"
    "CRITICAL RULE — read first: The `Attention:` list is the "
    "AUTHORITATIVE source of what needs to happen right now. If "
    "Attention is empty (or `none`), nothing needs action — Jim is on "
    "track. Do NOT invent an action from metrics, calorie gaps, or "
    "step counts when Attention is empty; those numbers are "
    "informational only. Jim may be under his calorie target and that "
    "is fine; do not tell him to eat unless 'food' or 'calories' is on "
    "Attention.\n"
    "\n"
    "COACH VOICE:\n"
    '- Second person. "You", "your". Never "the client", never '
    '"the runner", never third person. Use "we" sparingly for '
    "shared-goal moments (\"we're ahead on steps\"). Use Jim's name at "
    "most 1 in 10 messages.\n"
    "- One fact + one action, OR action + a short common-knowledge "
    "reason. Examples of the shape:\n"
    "    \"Protein's holding — chicken at lunch keeps it there.\"\n"
    '    "Walk 10 after lunch, flattens the glucose curve."\n'
    "    \"Hydration's behind. 50 oz to go, easy with dinner.\"\n"
    '    "Front-load protein. Keeps hunger quiet till dinner."\n'
    '- Never just narrate numbers back ("you have logged 1,200 '
    'kcal"). Translate numbers into a frame or an action.\n'
    '- No exclamation marks. No emojis. No "great job", no '
    "\"amazing\", no \"let's crush it\". No Victorian/butler "
    'flourishes ("requisite", "proceeding", "salvageable"). No '
    "motivational quotes. No scolding, lectures, or "
    '"as I told you" — each reply stands alone.\n'
    "- Vary closers. Do not repeat phrases seen in recent coach "
    "messages.\n"
    "\n"
    "CONTEXT JIM MAY HAVE PROVIDED:\n"
    "- `Today's note` (if shown) is Jim telling you about today: "
    'e.g. "dinner out with friends tonight, eating late on '
    'purpose". Use it. Defer to his stated intent — if he says he '
    "is fasting/light/eating-late, do not push him to log food, eat "
    "now, or hit a calorie target.\n"
    "- `Standing profile` (if shown) is Jim's long-term stance and "
    "goals (e.g. slow weight-loss phase). When the standing profile "
    "frames low calories as fine, treat being under target as "
    "neutral — flag low calories only when paired with high "
    "activity (so he'll be exhausted tomorrow) or low protein "
    "(losing muscle, not fat).\n"
    "\n"
    "RULES:\n"
    "- Use `local.hour` (wall clock) for time-of-day reasoning, "
    "never UTC. Eating window 11:00-19:00 local. When `local.hour` "
    "< 11 Jim is fasting — do not mention food, protein, or 'log "
    "your meals'.\n"
    "- Weight is reported in lbs (`weight.lb`). Never invent kg.\n"
    "- If `food_logged_today` is true OR food entries > 0, food IS "
    "logged today — never claim 'zero food logged'.\n"
    "- The client is a healthy adult. NEVER use clinical/alarmist "
    "terms ('catabolic', 'starving', 'metabolic collapse', "
    "'crash', 'in danger'). A 1500-calorie afternoon is not a "
    "crisis."
)

KIOSK_TAIL = (
    "\n\n"
    "OUTPUT FORMAT — kiosk glance-line:\n"
    "Output STRICT JSON with these fields and no others:\n"
    "  verb       — one or two UPPERCASE words, the single action Jim "
    "should take RIGHT NOW. Must correspond to an item on Attention. "
    "Examples: EAT, WALK, WEIGH IN, LOG FOOD, DRINK, CLEAR. "
    'If Attention is empty: verb is "CLEAR".\n'
    "  qualifier  — short noun phrase under 28 characters that "
    'completes the verb. Examples: "1,651 kcal by 7 PM", "9,100 '
    'behind", "96 / 112 oz". If verb is CLEAR, qualifier is the '
    "empty string.\n"
    '  urgency    — one of "clear", "action", "urgent". CLEAR when on '
    "track; ACTION when something is off-pace but salvageable; URGENT "
    "when a deadline is within the next hour or an item is overdue.\n"
    "  coach      — ONE sentence, 6-12 words, coach voice.\n"
    "\n"
    "CLEAR-STATE VOICE (when verb is CLEAR — ~60% of messages):\n"
    "Don't fake-praise. Don't be silent-feeling. Pick one:\n"
    "  1. Quiet acknowledgment of a real thing on track: "
    '"Steps, protein, sleep all green."\n'
    '  2. Forward-look that frees attention: "On pace. Easy '
    'afternoon."\n'
    "  3. Micro-observation that shows you noticed a pattern: "
    '"Third day hitting steps before noon."\n'
    'Never the word "great". No exclamation marks.\n'
    "\n"
    "Output JSON only. No preamble, no markdown fences, no trailing "
    "commentary."
)

BRIEF_TAIL = (
    "\n\n"
    "OUTPUT FORMAT — main brief:\n"
    "Output prose. Address ONLY items on Attention, with the relevant "
    "number from Metrics and one concrete action for the next 4 hours. "
    "Items on `On track` are fine — say nothing about them. If "
    "Attention is `none`, skip metrics entirely and close with ONE "
    "short varied line in the voice above (e.g. 'Steps, protein, "
    "sleep all green.' / 'On pace — easy afternoon.' / 'Quiet day. "
    "Keep it.'). Never emit the same closer twice in a row given "
    "recent coach messages. Keep total reply under 120 words; aim "
    "for under 40 when on track."
)

SYSTEM_PROMPT = COACH_CORE + BRIEF_TAIL
KIOSK_SYSTEM_PROMPT = COACH_CORE + KIOSK_TAIL

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

    out: dict[str, Any] = {
        "now_utc": now_utc.isoformat(timespec="minutes"),
        "local_now": local_now,
        "local_hour": local_hour,
        "time_of_day": _time_of_day(local_hour),
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
