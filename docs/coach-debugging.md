# Debugging the Coach

Playbook for "the coach said something wrong/weird, what now?". The goal
is a tight closed loop: thumbs-down it in the app → inspect what the
model actually saw → make a targeted prompt edit → deploy → clear the
addressed feedback so the next review starts fresh.

This doc is the single reference for that loop. If you're handing this
task to Claude in a new session, link to this file and they should be
able to drive the whole flow.

## Prereqs

- `tools/.env` configured with `HTB_API_URL` + `HTB_API_KEY` (see
  `tools/README.md`).
- `tools/.venv` set up: `cd tools && python -m venv .venv && .venv/bin/pip install -e .`

## Capturing bad outputs

Every rendered coach insight in the dashboard has a 👍 / 👎 row under it.
👎 opens a small textarea — write a one-liner saying what was wrong.
Brevity is fine ("clinical alarmism over normal numbers", "told me I
fasted but I logged at 12 PM"). The note is the only mining input later;
no note = harder to spot the pattern.

Keep going for a few days so you have enough rows to see patterns. One
weird output is rarely worth a prompt edit; three thumbs-down on the
same theme is.

## Triage round

```bash
cd tools
.venv/bin/python coach_feedback.py count
.venv/bin/python coach_feedback.py list --limit 50
```

`list` shows: rating, timestamp, the user note, and a one-line preview
of the insight that earned it. Skim for clusters: same theme, same
trigger ("manual" vs "scheduled-7am"), same time of day, etc. A cluster
is a tuning opportunity. A one-off is probably ignorable.

## Deep dive on one bad row

Pick a rating ID from `list` and:

```bash
.venv/bin/python coach_feedback.py show <feedback_id>
```

`show` prints, in order:

1. **Rating + user note** — what was wrong, in your own words.
2. **Insight output** — what the model actually wrote.
3. **food_totals (input)** — what calorie/macro numbers were in the
   prompt. If `entries: 0`, no food was logged yet for the local day.
   `food_logged_today: false` is the explicit boolean the prompt also
   sees.
4. **context (input)** — sleep/HRV/weight/daily_summary/steps_today
   plus `local_now`, `local_hour`, `time_of_day`, and
   `local_day_start_utc`. This is the model's snapshot of "what's
   happening right now."
5. **history_snapshot (input)** — the prior coach messages that fed
   into this prompt as `Recent coach messages`. Filtered to the local
   day so yesterday's ghosts don't haunt today's prompt.
6. **system_prompt (active when generated)** — the full instructions
   the model was given. Key for finding which guard-rail was missing.
7. **full rendered prompt sent to LLM** — exact bytes that hit Ollama.

If any of these say `(not captured)`, the row predates the prompt-input
capture (commit `a35e5a9`). Newer rows have all of it.

## Diagnosing what to change

For each clustered failure, ask three questions:

1. **Did the model see the right inputs?** If `food_totals` was zero
   because `entries: 0` and the user just hadn't logged yet, the bug
   isn't the prompt — it's the FE/UX (logging friction). Flag separately.
2. **Did the model violate a guard-rail we wrote?** Search the
   `system_prompt` block for the keywords that should have stopped the
   bad behavior. If the rule is there and the model ignored it, the
   rule needs to be louder (caps, repetition near the end of the
   prompt, an explicit "NEVER" with examples).
3. **Was there no guard-rail for this pattern?** Add one. Be concrete:
   forbid the specific words (`"catabolic"`, `"starving"`,
   `"metabolic collapse"`) rather than abstractions (`"don't be
   alarmist"`).

The active rules live in `services/api/app/services/coach/brief.py::SYSTEM_PROMPT`.
There are tests in `services/api/tests/test_coach.py` (e.g.
`test_system_prompt_forbids_clinical_alarmism`) that pin the strings —
if you add a guard-rail you care about, add an assertion so a future
edit can't quietly drop it.

## Making the edit

Edit `SYSTEM_PROMPT` in `services/api/app/services/coach/brief.py`. Pattern
that has worked so far:

- One sentence stating the principle.
- One sentence with the *forbidden words*, verbatim.
- One sentence saying what to do *instead* (so the model has a positive
  alternative, not just a "no").
- If it's a recurring failure mode, cap with `IMPORTANT — <topic>:` so
  the model has clear topic-anchors near the end of the prompt.

Don't refactor the prompt for "elegance" — concatenated rules with
explicit topic prefixes work better in practice than a single tidy
paragraph. The model picks up topic-anchors when scanning.

## Test, deploy, verify

```bash
cd services/api && .venv/bin/pytest tests/test_coach.py -v
```

Push. Watchtower picks up the new image (~60s). Manually ask the coach
once or twice on cases you know used to fail; confirm the new output
respects the rule.

If the model still violates the new rule, the rule isn't loud enough.
Consider:
- Moving it later in the prompt (recency effect).
- Repeating it (yes, really — duplicate the key sentence).
- Adding an explicit example: `e.g. don't say "catabolic state" — say "1,200 cal so far — protein next?"`.

## Clearing addressed feedback

Once a prompt edit is deployed and verified, sweep the feedback so the
next review starts on the new prompt:

```bash
.venv/bin/python coach_feedback.py clear           # everything
.venv/bin/python coach_feedback.py clear --before 2026-04-26T23:00:00Z   # only old
```

`clear` archives rows to `coach_feedback_archive` in Mongo; nothing is
hard-deleted. The audit trail of "what we tuned and when" survives so
later reviews can ask "did we already try a fix for this?".

After a prompt edit, also archive the **insights** generated by the
old prompt — otherwise they'll show up in the new prompt's
`recent_coach_messages` block and re-pollute its behavior:

```bash
.venv/bin/python coach_feedback.py insights-clear           # everything
.venv/bin/python coach_feedback.py insights-clear --before 2026-04-27T00:00:00Z
```

Archived to `coach_insights_archive`. The audit trail of "what the
coach said with the old prompt" survives if you want to compare
behavior across prompt versions later.

Skip clearing if:
- Some feedback wasn't addressed by your edit (use `clear --before`
  with a timestamp picked just before the unaddressed rows).
- You want to A/B-eyeball pre/post edit behavior over a few days. Just
  flag in your head which feedback is from before vs. after, and clear
  later.

## Common patterns we've already guarded against

These are written in `SYSTEM_PROMPT` as of commit `a35e5a9`. If a new
failure looks similar, check whether the existing rule fired and just
needs more force, vs. a genuinely new pattern.

- **"You haven't eaten today"** when entries=0. Rule: zero entries means
  "nothing logged yet," not "fasted." Pinned by
  `test_insight_signals_no_food_logged_yet`.
- **Cross-day history bleed** ("you said yesterday..."). Rule: history
  is filtered by `since=local-day-start`. Pinned by
  `test_recent_filters_by_since`.
- **Clinical alarmism** ("catabolic", "starving", "metabolic collapse",
  "crash", "in danger"). Rule: forbidden vocabulary; report numbers
  neutrally. Pinned by `test_system_prompt_forbids_clinical_alarmism`.
- **Scolding** ("you ignored", "as I told you", "you didn't listen").
  Rule: each reply stands alone; no reproaching prior coach messages.
- **Stale snapshots in history** (older message claims data that the
  current snapshot contradicts). Rule: trust current snapshot over
  older coach text.
- **Inventing baselines** ("TDEE = 3000", "you should be eating
  X cal"). Rule: only judge against `targets` if present; null target
  means "don't judge that metric." Set targets in the More tab →
  Daily targets card; they flow into the coach prompt automatically.
- **Mandatory action items** ("Action: walk 20 minutes"). Rule: end
  with an action ONLY if something is meaningfully off-track relative
  to a target; otherwise close with "on track" and stop.

## Architecture notes (for new sessions)

The coach lives in a package at `services/api/app/services/coach/`, with
the main SYSTEM_PROMPT in `brief.py`. Each saved insight (`coach_insights`
collection) carries:

- `text` — model output
- `context` — a `Findings.to_dict()` object produced by
  `services/api/app/services/coach/context.py::build_findings()`. This is
  a rich pre-digested view (not a raw snapshot) containing the deterministic
  findings the brief is rendered from: `snapshot` (sleep/HRV/weight/steps),
  `metrics` (calorie/macro state), `on_track` (boolean per metric),
  `attention` (flagged anomalies), and `local` (local time info).
- `food_totals` — calorie/macro/entry counts for the local day
- `history_snapshot` — the prior coach messages that fed into this
  prompt
- `prompt` — literal bytes sent to Ollama
- `system_prompt` — the rule-set active at generation time

Feedback (`coach_feedback`) joins to insights by `insight_id`.
`/coach/feedback` returns the joined view; `tools/coach_feedback.py`
formats it.

The reason all of these are persisted: tuning a prompt blind (without
seeing what the model saw when it failed) is the #1 way to ship a "fix"
that addresses an imagined problem and leaves the real one untouched.
