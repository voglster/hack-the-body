---
status: deferred
created: 2026-04-27
depends_on: 2026-04-27-prescriptive-nudges-design.md
---

# Sleep Accountability Loop — Design Stub (Deferred)

## Intent

Move sleep from passive logging into an accountability loop. When bedtime drifts
from the user's target (e.g. in bed by 10pm, ~8h asleep), the app initiates a
short retrospective conversation, captures an insight about *why* it happened,
and feeds that insight forward so future nudges and coach context get smarter
over time.

Sleep is the pilot signal because the user identifies it as the foundation of
everything else, and the data is clean (Garmin reports bedtime + duration). The
same loop machinery should generalize later to skipped vitamins, weight drift,
water shortfalls, etc.

## Loop Shape

1. **Detect deviation** — bedtime > target + threshold, or sleep < target hours.
   Reuses the rules engine from the Prescriptive Nudges spec.
2. **Prompt retrospective** — short conversational ask: "You went to bed at 2am
   last night — what happened?" Surfaces in dashboard and/or push.
3. **Capture insight** — free-text answer + structured tag (work, video games,
   YouTube, social, anxiety, travel, sick, etc.). Stored as an `insight`
   document keyed by date + signal.
4. **Feed forward** — insights flow into:
   - Coach prompt context (so the coach can reference patterns)
   - Pattern detection ("3 Sundays in a row late from YouTube")
   - Targeted future nudges ("it's 9:30pm Sunday — last 3 Sundays you stayed up
     past midnight on YouTube. Want to set a hard stop?")

## Open Questions (for future brainstorm session)

- Where does the retrospective conversation live? Dashboard card, dedicated
  chat surface, Telegram (Phase 2), or all three?
- Same-morning ask vs. delayed? Garmin sleep data lands when the user wakes;
  retrospective could fire then, or wait until evening.
- Insight schema: free text + tags, or structured Q&A, or both?
- How many insights before pattern detection kicks in? Hand-rolled rules vs.
  LLM-summarized weekly review?
- Do insights ever expire / decay, or are they permanent?
- Privacy/honesty: how do we keep this from feeling like surveillance? The
  user is the only audience, but the framing matters.

## Dependencies

- Prescriptive Nudges spec (Spec A) — provides the rules engine and the
  deviation detection surface this loop hooks into.
- Existing Garmin sleep ingestion — already in place.
- Existing coach plumbing (`routers/coach.py`, prompt feedback loop) — the
  insight feed-forward likely extends the coach's prompt context.

## Not in Scope (for this stub)

Implementation details, schema, prompt design, UI mockups. Those happen when
this spec graduates from `deferred` to `active`.
