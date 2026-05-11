"""Coach package — brief generation, chat agent loop, tools, threads.

The router and scheduler import everything they need from this top-level
namespace so that callers don't have to know which submodule a thing
lives in.
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
from app.services.coach.chat import MAX_ITERATIONS, reply  # noqa: F401
from app.services.coach.threads import (  # noqa: F401
    Turn,
    append_turn,
    create_thread,
    get_active_thread,
    get_thread,
)
from app.services.coach.tools import (  # noqa: F401
    REGISTRY,
    ToolError,
    dispatch,
    schema_for_llm,
)
