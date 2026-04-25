from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import Settings

TIMESERIES_COLLECTIONS: dict[str, dict] = {
    "metrics_weight": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_sleep": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_hrv": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_rhr": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_body_comp": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_vo2max": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_daily_summary": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "meal_entries": {"timeField": "ts", "metaField": "meta", "granularity": "minutes"},
}

REGULAR_COLLECTIONS = ["workouts", "user_profile", "ingestion_log",
                       "foods", "meal_templates"]


async def ensure_collections(db: AsyncIOMotorDatabase) -> None:
    existing = set(await db.list_collection_names())
    for name, opts in TIMESERIES_COLLECTIONS.items():
        if name in existing:
            continue
        try:
            await db.create_collection(name, timeseries=opts)
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


def make_client(settings: Settings) -> AsyncIOMotorClient:
    return AsyncIOMotorClient(settings.mongo_url)


def get_db(client: AsyncIOMotorClient, settings: Settings) -> AsyncIOMotorDatabase:
    return client[settings.mongo_db]
