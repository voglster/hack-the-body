"""Coach conversation threads — short-lived Mongo docs with inline turns.

Each brief generates a new thread (turn 1 = the brief). User replies and
coach responses append turns inline. Threads close on idle >2h (handled
elsewhere); for now they're effectively per-day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase


@dataclass
class Turn:
    role: str  # "coach" | "user"
    text: str
    tool_calls: list[dict[str, Any]] | None = None
    findings_snapshot: dict[str, Any] | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "text": self.text, "ts": self.ts}
        if self.tool_calls is not None:
            out["tool_calls"] = self.tool_calls
        if self.findings_snapshot is not None:
            out["findings_snapshot"] = self.findings_snapshot
        return out


async def create_thread(
    db: AsyncDatabase, *, initial_turn: Turn, surface: str = "web",
) -> str:
    now = datetime.now(UTC)
    doc = {
        "started_at": now,
        "last_activity_at": now,
        "closed_at": None,
        "surface": surface,
        "turns": [initial_turn.to_dict()],
    }
    res = await db["coach_threads"].insert_one(doc)
    return str(res.inserted_id)


async def append_turn(db: AsyncDatabase, thread_id: str, turn: Turn) -> None:
    await db["coach_threads"].update_one(
        {"_id": ObjectId(thread_id)},
        {
            "$push": {"turns": turn.to_dict()},
            "$set": {"last_activity_at": datetime.now(UTC)},
        },
    )


async def get_thread(db: AsyncDatabase, thread_id: str) -> dict[str, Any] | None:
    return await db["coach_threads"].find_one({"_id": ObjectId(thread_id)})


async def get_active_thread(db: AsyncDatabase) -> dict[str, Any] | None:
    """Return the most recent non-closed thread, or None if none exists."""
    return await db["coach_threads"].find_one(
        {"closed_at": None},
        sort=[("started_at", -1), ("_id", -1)],
    )
