from app.services.coach.brief import (
    COACH_CORE,
    KIOSK_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    render_brief_prompt,
)
from app.services.coach.context import Findings


def _empty_findings() -> Findings:
    return Findings(
        snapshot={}, metrics={}, on_track=[], attention=[],
        food_totals={"entries": 0, "food_logged_today": False},
    )


def test_render_uses_default_prompt():
    out = render_brief_prompt(_empty_findings(), history=[])
    assert out.startswith(SYSTEM_PROMPT)


def test_render_uses_kiosk_prompt_when_passed():
    out = render_brief_prompt(
        _empty_findings(), history=[], system_prompt=KIOSK_SYSTEM_PROMPT,
    )
    assert out.startswith(KIOSK_SYSTEM_PROMPT)
    assert SYSTEM_PROMPT not in out.split("Client:")[0]


def test_kiosk_prompt_is_pit_crew_coach_json_contract():
    """The kiosk prompt should set the pit-crew/coach voice (second person,
    no butler/third-person flourishes) and describe the structured JSON
    contract (verb / qualifier / urgency / coach)."""
    assert "Jim's coach" in KIOSK_SYSTEM_PROMPT
    assert "pit crew" in KIOSK_SYSTEM_PROMPT.lower()
    # Voice guardrails — these phrases are explicitly banned in the prompt
    # body, so they should appear (in the ban list) rather than be absent.
    assert "third person" in KIOSK_SYSTEM_PROMPT.lower()
    assert "butler" in KIOSK_SYSTEM_PROMPT.lower()
    for field in ("verb", "qualifier", "urgency", "coach"):
        assert field in KIOSK_SYSTEM_PROMPT
    assert "STRICT JSON" in KIOSK_SYSTEM_PROMPT


# ---------- shared-core composition ----------

def test_both_prompts_share_coach_core():
    """KIOSK_SYSTEM_PROMPT and SYSTEM_PROMPT must derive from the same
    COACH_CORE. Without this, voice fixes drift between surfaces — exactly
    the situation that left the main coach as 'no-nonsense' while the
    kiosk was already 'pit crew'."""
    assert COACH_CORE in KIOSK_SYSTEM_PROMPT
    assert COACH_CORE in SYSTEM_PROMPT


def test_only_tails_differ():
    """The two surfaces should differ ONLY in their output-format tail —
    JSON vs prose. Structurally, this means each prompt is exactly
    COACH_CORE plus a small surface-specific suffix."""
    assert "STRICT JSON" in KIOSK_SYSTEM_PROMPT
    assert "STRICT JSON" not in SYSTEM_PROMPT
    assert "Output prose" in SYSTEM_PROMPT
    assert "Output prose" not in KIOSK_SYSTEM_PROMPT


def test_main_prompt_inherits_pit_crew_voice():
    """The main brief prompt must carry the same pit-crew voice the
    kiosk uses — second person, no butler. This was the bug pre-refactor:
    SYSTEM_PROMPT was still 'no-nonsense health coach'."""
    assert "Jim's coach" in SYSTEM_PROMPT
    assert "pit crew" in SYSTEM_PROMPT.lower()
    assert "third person" in SYSTEM_PROMPT.lower()


# ---------- day-note + coach-note prompt injection ----------
#
# The CORE prompt itself references "Today's note" and "Standing profile"
# in its guidance section. Tests look for the renderer's injection marker
# "from Jim:\n" which only appears when the renderer actually injects a
# populated block, so we don't confuse guidance with payload.

_DAY_MARKER = "Today's note from Jim:\n"
_COACH_MARKER = "Standing profile from Jim:\n"


def _findings_with_notes(*, day=None, coach=None) -> Findings:
    return Findings(
        snapshot={}, metrics={}, on_track=[], attention=[],
        food_totals={"entries": 0, "food_logged_today": False},
        day_note=day, coach_note=coach,
    )


def test_render_omits_note_blocks_when_unset():
    """No note set → no injection block. The CORE still mentions the
    concepts as guidance, but no payload is emitted."""
    out = render_brief_prompt(_empty_findings(), history=[])
    assert _DAY_MARKER not in out
    assert _COACH_MARKER not in out


def test_render_injects_day_note_when_set():
    f = _findings_with_notes(day="dinner out tonight, eating late on purpose")
    out = render_brief_prompt(f, history=[])
    assert _DAY_MARKER in out
    assert "dinner out tonight" in out
    # Standing profile block should still be absent (only coach_note drives it).
    assert _COACH_MARKER not in out
    # Note must appear BEFORE the Client: line so it reads like context
    # the coach was given before the data dump.
    assert out.index(_DAY_MARKER) < out.index("Client:")


def test_render_injects_coach_note_when_set():
    f = _findings_with_notes(
        coach="Trying to lose weight slowly. Low calories alone is fine.",
    )
    out = render_brief_prompt(f, history=[])
    assert _COACH_MARKER in out
    assert "lose weight slowly" in out
    assert out.index(_COACH_MARKER) < out.index("Client:")


def test_render_injects_both_notes_independently():
    f = _findings_with_notes(day="late dinner", coach="cutting phase")
    out = render_brief_prompt(f, history=[])
    assert "late dinner" in out
    assert "cutting phase" in out
    # Coach note (long-lived stance) comes before day note (today only) so
    # the model reads "who Jim is" before "what Jim is up to today."
    assert out.index(_COACH_MARKER) < out.index(_DAY_MARKER)


def test_core_describes_note_handling():
    """COACH_CORE must teach the model how to USE the notes — defer to
    stated intent (day note), treat low calories as neutral when the
    standing profile frames Jim as cutting. Without this, the notes get
    plumbed but ignored."""
    lowered = COACH_CORE.lower()
    assert "today's note" in lowered or "day note" in lowered
    assert "standing profile" in lowered or "coach note" in lowered
    # Behavioral guidance — at minimum, "defer to" stated intent OR
    # "treat being under target as neutral".
    assert "defer" in lowered or "neutral" in lowered or "fine" in lowered
