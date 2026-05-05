from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings

TIMESERIES_COLLECTIONS: dict[str, dict] = {
    "metrics_weight": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_sleep": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_hrv": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_rhr": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_body_comp": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_vo2max": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_daily_summary": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_steps_intraday": {"timeField": "ts", "metaField": "meta", "granularity": "minutes"},
    "meal_entries": {"timeField": "ts", "metaField": "meta", "granularity": "minutes"},
    "treadmill_samples": {
        "timeField": "ts", "metaField": "source", "granularity": "seconds",
        "expireAfterSeconds": 90 * 24 * 3600,
    },
}

REGULAR_COLLECTIONS = ["workouts", "user_profile", "ingestion_log",
                       "foods", "meal_templates", "coach_insights",
                       "push_subscriptions", "parse_feedback",
                       "strength_sets"]


async def ensure_collections(db: AsyncDatabase) -> None:
    existing = set(await db.list_collection_names())
    for name, raw_opts in TIMESERIES_COLLECTIONS.items():
        if name in existing:
            continue
        opts = dict(raw_opts)
        ttl = opts.pop("expireAfterSeconds", None)
        kwargs = {"timeseries": opts}
        if ttl is not None:
            kwargs["expireAfterSeconds"] = ttl
        try:
            await db.create_collection(name, **kwargs)
        except Exception:
            await db.create_collection(name)
    for name in REGULAR_COLLECTIONS:
        if name not in existing:
            await db.create_collection(name)

    await db["workouts"].create_index("source_id", unique=True, sparse=True)
    await db["ingestion_log"].create_index([("source", 1), ("started_at", -1)])
    # Foods: barcode-keyed lookups + text search
    await db["foods"].create_index("barcode", unique=True, sparse=True)
    await db["foods"].create_index([("name", "text"), ("brand", "text")])
    await db["meal_templates"].create_index("name", unique=True)
    # Coach insights are time-stamped; index for fast 'recent' lookups.
    await db["coach_insights"].create_index([("generated_at", -1)])
    # Push subscriptions: dedupe by endpoint URL.
    await db["push_subscriptions"].create_index("endpoint", unique=True)
    # Parse feedback: time-ordered for review.
    await db["parse_feedback"].create_index([("ts", -1)])
    await db["strength_sets"].create_index(
        [("workout_source_id", 1), ("exercise_index", 1), ("set_index", 1)],
        name="strength_sets_parent_order",
    )
    await db["strength_sets"].create_index(
        [("exercise_template_id", 1), ("ts", -1)],
        name="strength_sets_exercise_ts",
    )


def make_client(settings: Settings) -> AsyncMongoClient:
    # tz_aware=True makes every datetime read from Mongo come back as a
    # timezone-aware UTC datetime. Without this, FastAPI's default JSON
    # encoder emits ISO strings without a timezone suffix and the browser
    # interprets them as local time — see issue with intraday step buckets
    # being displayed in the wrong hours.
    return AsyncMongoClient(settings.mongo_url, tz_aware=True)


def get_db(client: AsyncMongoClient, settings: Settings) -> AsyncDatabase:
    return client[settings.mongo_db]
