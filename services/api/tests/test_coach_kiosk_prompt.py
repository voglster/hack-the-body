from app.services.coach.brief import (
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
