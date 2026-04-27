# tools/

Operator scripts for hack-the-body. They talk to the running API directly
instead of going through the FE — useful for batch reviews, audits, and
tuning the coach's prompt over time.

> **For the full coach debugging playbook** (triage → diagnose → edit →
> deploy → clear feedback), see [`docs/coach-debugging.md`](../docs/coach-debugging.md).
> This README is the install guide; that doc is the workflow.

## Setup (once)

```bash
cd tools
python -m venv .venv
.venv/bin/pip install -e .

cp .env.example .env
$EDITOR .env   # set HTB_API_URL and HTB_API_KEY
```

`tools/.env` is git-ignored.

## Coach feedback review loop

The dashboard captures 👍 / 👎 on each rendered coach insight. When the
coach gets something wrong (e.g. "you haven't eaten today" before you've
logged anything), thumbs-down it with a short note. Every few days:

```bash
.venv/bin/python coach_feedback.py count                  # how much piled up?
.venv/bin/python coach_feedback.py list --since 2026-04-01T00:00:00Z
.venv/bin/python coach_feedback.py show <feedback_id>     # full prompt + inputs
.venv/bin/python coach_feedback.py dump > /tmp/fb.json    # for an LLM review
```

Each saved insight (since the prompt-capture change) carries its full
inputs: `food_totals`, the `context` snapshot, the `history_snapshot`
(other coach messages that fed into this prompt), the literal rendered
`prompt` sent to Ollama, and the `system_prompt` that was active. So
when the coach says something nuts, `show <id>` answers "what was it
looking at, and which guard-rails were live?"

Then hand `/tmp/fb.json` to Claude with a prompt like:

> Here's a week of coach feedback. Each row has the rating, an optional
> note from the user, and the insight text + context that earned the
> rating. Identify recurring failure patterns, then propose specific
> edits to `services/api/app/services/coach.py::SYSTEM_PROMPT`. Quote
> at least two feedback rows per recommended edit.

Apply the prompt edits, deploy, and clear the now-addressed feedback so
the *next* review sees only complaints about the *new* prompt:

```bash
.venv/bin/python coach_feedback.py clear
```

`clear` archives rows to `coach_feedback_archive` in Mongo rather than
hard-deleting, so the audit trail of "what we tuned and when" survives.

After a prompt edit you usually also want to clear the *insights* so
the new prompt isn't biased by output from the old one (the LLM gets
`recent_coach_messages` as part of its prompt — stale outputs there
re-pollute the new prompt's behavior):

```bash
.venv/bin/python coach_feedback.py insights-count
.venv/bin/python coach_feedback.py insights-clear           # everything
.venv/bin/python coach_feedback.py insights-clear --before 2026-04-27T00:00:00Z
```

Archived to `coach_insights_archive` (audit trail).

## Recommending daily targets

`target_recommender.py` does Mifflin-St Jeor BMR + activity-tier TDEE +
goal-rate deficit math, then prints recommended calories and protein.
Optionally writes them to `/profile/targets`.

```bash
# Print a recommendation
.venv/bin/python target_recommender.py recommend \
  --age 44 --height-in 77 --weight-lb 250 \
  --activity light --goal lose-1lb-week

# Auto-pull current weight from the API instead of typing it
.venv/bin/python target_recommender.py recommend \
  --age 44 --height-in 77 --pull-weight \
  --activity light --goal lose-1lb-week

# Write the recommendation to /profile/targets (skip y/n with -y)
.venv/bin/python target_recommender.py apply \
  --age 44 --height-in 77 --pull-weight \
  --activity light --goal lose-1lb-week --step-goal 12000
```

Activity tiers: `auto` (default — uses Garmin's measured median
`total_kcal` from the last 14 days as observed TDEE), or pick by
hand: `sedentary` (desk job), `light` (~12k steps, no training),
`moderate` (12k steps + 3-5 sessions/week), `very`, `athlete`. Goal
rates: `maintain`, `lose-0.5lb-week`, `lose-1lb-week` (default),
`lose-1.5lb-week`. The tool flags unsustainable combinations (under
1,800 kcal, athlete + deficit, observed TDEE below predicted BMR).

`auto` is the recommended default — the multipliers are calibrated
for established athletes, so they tend to over-predict TDEE for
beginners. Garmin's per-day measurement is calibrated to *your* body.
Auto falls back to "light" formula when there are fewer than 5 days
of usable data.

Protein math anchors on the *target* body weight (BMI 22 midpoint by
default, override with `--target-weight-lb`) at ~0.9 g/lb — preserves
lean mass through a sustained cut.

Math is unit-tested — run `pytest tests/` from the tools dir. The math
functions are pure and importable, so you can also do:
```python
from target_recommender import recommend
recommend(age=44, sex="male", height_in=77, weight_lb=250,
          activity="light", goal="lose-1lb-week", target_weight_lb=None)
```

## Adding a new tool

Each script imports `_client.client()` and writes a `cmd_*` function per
subcommand using `argparse`. Keep deps minimal — `httpx` + `python-dotenv`
are the only currently-installed wheels.
