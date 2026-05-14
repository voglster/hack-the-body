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
