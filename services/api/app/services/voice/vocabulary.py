"""The words Whisper is told to expect, generated from the food catalog.

Prompting is the whole accuracy story here. Jim's own `bench-stt` measured
`base.en` going from 0.054 WER to 0.000 once `initial_prompt` and `hotwords`
were set, with no larger model beating it on clean audio. Without "Fairlife"
on the wire the decoder writes "fair life", and the parser then has nothing
a catalog entry can match.

**Generated at request time, from the collections.** A hand-maintained list
is correct on the day it is written and wrong by the end of the week, because
the catalog grows every time something new is logged.

**Eligibility is by `meal_entries` count, not by presence in `foods`.** This
is what makes the loop learn rather than drift: an estimated capture upserts a
Food per unmatched item, so a mis-hearing becomes a permanent catalog row. It is
logged exactly once and never again, so requiring more than one entry starves
it while the correction actually eaten weekly climbs.

**Nothing here case-normalises.** `.title()` turns `RXBAR` into `Rxbar` and
`OIKOS` into `Oikos`. The catalog holds the spelling; it travels unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from pymongo.asynchronous.database import AsyncDatabase

# faster-whisper gives the decoder one 448-token context shared between the
# prompt and the output, so hotwords and `initial_prompt` compete for the same
# space. The number to watch is tokens spent, never how many names fit.
PROMPT_TOKEN_BUDGET = 384

# Whisper's own register hint. Short on purpose — it is spending the same
# budget the hotwords are.
INITIAL_PROMPT = "A spoken food log: quantities, foods, and brand names."

# A food logged exactly once is as likely to be a mis-hearing as a real meal.
MIN_ENTRIES_FOR_HOTWORD = 2

# Rough characters-per-token for English. Deliberately an estimate: the exact
# tokenizer lives in the decoder, and being a little conservative costs one
# name at the tail rather than a truncated prompt.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class SpeechContext:
    hotwords: list[str]
    initial_prompt: str

    @property
    def hotword_text(self) -> str:
        return ", ".join(self.hotwords)


def select_hotwords(
    candidates: list[tuple[str, int]], *, budget_tokens: int,
) -> list[str]:
    """Most-eaten first, until the token budget runs out.

    `candidates` is (name, times_eaten). Ordering by usage is not merely a
    tie-break — it is the mis-hearing defence, because a name heard wrong once
    sorts below everything real.
    """
    ordered = sorted(candidates, key=lambda c: (-c[1], c[0]))
    chosen: list[str] = []
    spent = 0
    for name, _count in ordered:
        cost = max(1, len(name) // _CHARS_PER_TOKEN)
        if spent + cost > budget_tokens:
            continue
        chosen.append(name)
        spent += cost
    return chosen


async def build_speech_context(db: AsyncDatabase) -> SpeechContext:
    counts: dict[str, int] = {}
    async for row in db["meal_entries"].find({}, {"food_name": 1}):
        name = (row.get("food_name") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1

    candidates = [
        (name, n) for name, n in counts.items()
        if n >= MIN_ENTRIES_FOR_HOTWORD
    ]

    # Templates are things Jim named himself, so they are never mis-hearings
    # and do not have to earn their place by frequency.
    async for tpl in db["meal_templates"].find({}, {"name": 1}):
        name = (tpl.get("name") or "").strip()
        if name and name not in counts:
            candidates.append((name, MIN_ENTRIES_FOR_HOTWORD))

    budget = PROMPT_TOKEN_BUDGET - (len(INITIAL_PROMPT) // _CHARS_PER_TOKEN)
    return SpeechContext(
        hotwords=select_hotwords(candidates, budget_tokens=budget),
        initial_prompt=INITIAL_PROMPT,
    )
