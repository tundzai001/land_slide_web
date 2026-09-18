"""Validation helpers for globally unique MQTT device topics."""

from collections import Counter
from typing import Iterable, Optional


def normalize_mqtt_topic(value: object) -> str:
    return str(value or "").strip()


def duplicate_mqtt_topics(values: Iterable[object]) -> list[str]:
    topics = [normalize_mqtt_topic(value) for value in values]
    counts = Counter(topic for topic in topics if topic)
    return sorted(topic for topic, count in counts.items() if count > 1)


async def find_mqtt_topic_conflicts(db, topics: Iterable[object], exclude_station_id: Optional[int] = None):
    """Return devices already owning requested topics, optionally excluding one station."""
    from sqlalchemy import select
    from ...models import config as model_config

    normalized = sorted({normalize_mqtt_topic(topic) for topic in topics if normalize_mqtt_topic(topic)})
    if not normalized:
        return []
    stmt = select(model_config.Device).where(model_config.Device.mqtt_topic.in_(normalized))
    if exclude_station_id is not None:
        stmt = stmt.where(model_config.Device.station_id != exclude_station_id)
    return list((await db.execute(stmt)).scalars().all())
