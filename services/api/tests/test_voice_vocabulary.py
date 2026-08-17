"""Hotwords generated from the live food catalog."""
from app.services.voice.vocabulary import (
    SpeechContext,
    build_speech_context,
    select_hotwords,
)


async def _log(db, name: str, times: int) -> None:
    await db["foods"].insert_one({"name": name, "category": "food"})
    for _ in range(times):
        await db["meal_entries"].insert_one({"food_name": name})


async def test_food_eaten_once_contributes_no_hotword(mock_db):
    """A mis-hearing is logged once and never again. If one entry were enough,
    the decoder would be taught its own mistake permanently."""
    await _log(mock_db, "fair life", 1)
    await _log(mock_db, "Fairlife", 4)
    ctx = await build_speech_context(mock_db)
    assert "Fairlife" in ctx.hotwords
    assert "fair life" not in ctx.hotwords


async def test_orders_by_logging_frequency(mock_db):
    await _log(mock_db, "Rare Thing", 2)
    await _log(mock_db, "Daily Staple", 30)
    ctx = await build_speech_context(mock_db)
    assert ctx.hotwords.index("Daily Staple") < ctx.hotwords.index("Rare Thing")


async def test_does_not_case_normalise(mock_db):
    await _log(mock_db, "RXBAR", 5)
    ctx = await build_speech_context(mock_db)
    assert "RXBAR" in ctx.hotwords


async def test_includes_meal_template_names(mock_db):
    await mock_db["meal_templates"].insert_one({"name": "Post-Lift Shake"})
    ctx = await build_speech_context(mock_db)
    assert "Post-Lift Shake" in ctx.hotwords


async def test_reflects_a_food_added_after_startup(mock_db):
    before = await build_speech_context(mock_db)
    await _log(mock_db, "Skyr", 3)
    after = await build_speech_context(mock_db)
    assert "Skyr" not in before.hotwords
    assert "Skyr" in after.hotwords


def test_select_hotwords_respects_the_token_budget():
    """Budget is in tokens because hotwords share the decoder's 448-token
    context with initial_prompt — counting names would overrun it."""
    names = [(f"Food Number {i}", 100 - i) for i in range(500)]
    chosen = select_hotwords(names, budget_tokens=20)
    assert len(chosen) < 500
    assert sum(max(1, len(n) // 4) for n in chosen) <= 20


def test_select_hotwords_keeps_the_most_eaten_first():
    chosen = select_hotwords([("Rare", 1), ("Common", 99)], budget_tokens=100)
    assert chosen[0] == "Common"


def test_speech_context_hotword_text_is_comma_joined():
    ctx = SpeechContext(hotwords=["A", "B"], initial_prompt="p")
    assert ctx.hotword_text == "A, B"


def test_speech_context_hotword_text_is_empty_when_no_hotwords():
    assert SpeechContext(hotwords=[], initial_prompt="p").hotword_text == ""
