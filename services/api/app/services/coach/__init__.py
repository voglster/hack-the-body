"""Coach package — brief generation, (future) chat agent loop, tools, memory.

For now this is a thin re-export layer over `brief.py` so existing callers
(router, scheduler, tests) keep working while the package fills out.
"""
from app.services.coach.brief import (  # noqa: F401
    RECENT_LIMIT,
    SYSTEM_PROMPT,
    USER_PROFILE,
    Insight,
    gather_context,
    generate_insight,
    recent_insights,
    resolve_day_window,
    save_insight,
    today_food_totals,
)
