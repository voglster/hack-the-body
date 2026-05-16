import re

from app.services.coach.brief import (
    BRIEF_SYSTEM_PROMPT,
    COACH_VOICE,
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
    # Sanity: the brief-only framing isn't in the kiosk render either.
    assert "dashboard daily debrief" not in out.split("Client:")[0].lower()


# ---------- back-compat: SYSTEM_PROMPT is the brief prompt ----------

def test_system_prompt_is_brief_alias():
    """`SYSTEM_PROMPT` is the legacy import name. It must point at the
    brief surface so existing imports (chat.py, scheduler, tests) keep
    working after the refactor."""
    assert SYSTEM_PROMPT == BRIEF_SYSTEM_PROMPT


# ---------- kiosk prompt: positive shape spec ----------

def test_kiosk_prompt_describes_glance_line_surface_positively():
    """The kiosk prompt should set the pit-crew/coach voice and describe
    its surface and JSON contract in positive terms — what the output
    IS, not a list of forbidden tokens."""
    assert "Jim's coach" in KIOSK_SYSTEM_PROMPT
    # Positive surface identity.
    lowered = KIOSK_SYSTEM_PROMPT.lower()
    assert "pit-crew" in lowered or "pit crew" in lowered
    assert "kiosk" in lowered or "glance-line" in lowered
    # JSON contract.
    for field in ("verb", "qualifier", "urgency", "coach"):
        assert field in KIOSK_SYSTEM_PROMPT
    assert "STRICT JSON" in KIOSK_SYSTEM_PROMPT
    # One-sentence shape spec (positive: "exactly ONE sentence, 6-12 words").
    assert "one sentence" in lowered
    assert "6-12 words" in lowered


def test_kiosk_prompt_carries_glance_line_examples():
    """The kiosk's defining shape — a short fact+action sentence — is
    taught by example. The four canonical examples live here, not in
    any shared core (otherwise the brief surface anchors on them too)."""
    # At least the protein/walk examples should be present verbatim.
    assert "Protein's holding" in KIOSK_SYSTEM_PROMPT
    assert "Walk 10 after lunch" in KIOSK_SYSTEM_PROMPT


# ---------- brief prompt: positive prose spec, distinct from kiosk ----------

def test_brief_prompt_describes_debrief_surface_positively():
    """The brief surface is a daily debrief. Its prompt should name that
    role positively rather than defining itself as 'not the kiosk'."""
    lowered = BRIEF_SYSTEM_PROMPT.lower()
    assert "dashboard" in lowered or "debrief" in lowered
    assert "Jim's coach" in BRIEF_SYSTEM_PROMPT
    # Multi-sentence length spec — taught by saying "prose, 2-4 sentences".
    assert "2-4 sentences" in lowered or "2 to 4 sentences" in lowered


def test_brief_prompt_carries_prose_examples():
    """The brief is also taught by example — multi-sentence reads that
    lead with a data observation. Without these the model defaults to
    the shortest acceptable output and collapses to a glance-line."""
    # Each example is multi-sentence (contains a period followed by space + capital).
    examples = re.findall(r'"([^"]{40,}?)"', BRIEF_SYSTEM_PROMPT)
    long_examples = [e for e in examples if len(e) >= 80]
    assert len(long_examples) >= 2, (
        f"expected ≥2 prose examples, got {long_examples}"
    )
    for ex in long_examples[:2]:
        # Each example has more than one sentence-ending period.
        assert ex.count(". ") + ex.count(".\n") >= 1


def test_brief_and_kiosk_examples_do_not_cross_contaminate():
    """The four kiosk one-liner examples must live in the kiosk prompt
    only. The previous refactor left them in COACH_CORE, where they
    anchored the brief surface and made it produce kiosk-shaped output
    — that's the exact bug this refactor was meant to fix."""
    kiosk_examples = [
        "Protein's holding",
        "Walk 10 after lunch",
        "Hydration's behind",
        "Front-load protein",
    ]
    for ex in kiosk_examples:
        assert ex in KIOSK_SYSTEM_PROMPT
        assert ex not in BRIEF_SYSTEM_PROMPT


def test_voice_is_shared_but_format_is_not():
    """The shared block is COACH_VOICE — persona, second-person voice,
    Attention handling, notes, units. Format/shape lives in each
    surface. The pit-crew identity must be in BOTH renders; the
    surface-specific framings must NOT cross."""
    assert COACH_VOICE in BRIEF_SYSTEM_PROMPT
    assert COACH_VOICE in KIOSK_SYSTEM_PROMPT
    # Format guidance does not cross.
    assert "STRICT JSON" not in BRIEF_SYSTEM_PROMPT
    assert "STRICT JSON" in KIOSK_SYSTEM_PROMPT
    assert "2-4 sentences" in BRIEF_SYSTEM_PROMPT or "2 to 4 sentences" in BRIEF_SYSTEM_PROMPT
    assert "2-4 sentences" not in KIOSK_SYSTEM_PROMPT


def test_main_prompt_inherits_pit_crew_voice():
    """The main brief prompt must carry the pit-crew voice. Pre-refactor
    this was 'no-nonsense health coach' which drifted away from the
    kiosk's voice; now both surfaces import COACH_VOICE."""
    assert "Jim's coach" in BRIEF_SYSTEM_PROMPT
    lowered = BRIEF_SYSTEM_PROMPT.lower()
    assert "pit-crew" in lowered or "pit crew" in lowered
    assert "second person" in lowered


# ---------- day-note + coach-note prompt injection ----------
#
# The voice block itself references "Today's note" and "Standing profile"
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
    """No note set → no injection block. The voice block still mentions
    the concepts as guidance, but no payload is emitted."""
    out = render_brief_prompt(_empty_findings(), history=[])
    assert _DAY_MARKER not in out
    assert _COACH_MARKER not in out


def test_render_injects_day_note_when_set():
    f = _findings_with_notes(day="dinner out tonight, eating late on purpose")
    out = render_brief_prompt(f, history=[])
    assert _DAY_MARKER in out
    assert "dinner out tonight" in out
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


def test_voice_describes_note_handling():
    """COACH_VOICE must teach the model how to USE the notes — defer to
    stated intent (day note), treat low calories as neutral when the
    standing profile frames Jim as cutting. Without this the notes get
    plumbed but ignored."""
    lowered = COACH_VOICE.lower()
    assert "today's note" in lowered or "day note" in lowered
    assert "standing profile" in lowered or "coach note" in lowered
    # Behavioral guidance: defer to stated intent OR treat under-target
    # as neutral.
    assert "defer" in lowered or "neutral" in lowered or "fine" in lowered
