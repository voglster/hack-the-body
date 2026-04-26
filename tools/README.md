# tools/

Operator scripts for hack-the-body. They talk to the running API directly
instead of going through the FE — useful for batch reviews, audits, and
tuning the coach's prompt over time.

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
.venv/bin/python coach_feedback.py dump > /tmp/fb.json    # for an LLM review
```

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

## Adding a new tool

Each script imports `_client.client()` and writes a `cmd_*` function per
subcommand using `argparse`. Keep deps minimal — `httpx` + `python-dotenv`
are the only currently-installed wheels.
