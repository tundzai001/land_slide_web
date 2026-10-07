"""Bounded trend queries; waveform evidence stays out of history sorting."""
from sqlalchemy import JSON, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB


def history_payload(column, dialect):
    """Remove large waveform arrays in SQL before transferring trend rows."""
    if dialect == 'postgresql':
        value = cast(column, JSONB)
        return case((func.jsonb_typeof(value) == 'object', cast(value.op('-')('waveform'), JSON)), else_=column)
    if dialect == 'sqlite':
        return func.json_remove(column, '$.waveform', type_=JSON)
    return column


def build_sensor_history_query(table, station_id, sensor_types, cutoff, limit, dialect):
    c = table.c
    buckets = max(1, min(250, limit // 8))
    # Rank only indexed identifiers/numeric values, never the large JSON column.
    bucketed = select(c.id, c.sensor_type, c.timestamp, c.value_1, c.value_2, c.value_3,
        func.ntile(buckets).over(partition_by=c.sensor_type,
            order_by=(c.timestamp.asc(), c.id.asc())).label('bucket')
    ).where(c.station_id == station_id, c.sensor_type.in_(sorted(sensor_types)), c.timestamp >= cutoff).subquery()
    b = bucketed.c
    ranks = [func.row_number().over(partition_by=(b.sensor_type, b.bucket),
             order_by=(b.timestamp.asc(), b.id.asc())).label('first_rank'),
             func.row_number().over(partition_by=(b.sensor_type, b.bucket),
             order_by=(b.timestamp.desc(), b.id.desc())).label('last_rank')]
    for field in ('value_1', 'value_2', 'value_3'):
        for direction in ('low', 'high'):
            value = getattr(b, field)
            order = value.asc().nulls_last() if direction == 'low' else value.desc().nulls_last()
            ranks.append(func.row_number().over(partition_by=(b.sensor_type, b.bucket),
                order_by=(order, b.timestamp.asc(), b.id.asc())).label(f'{field}_{direction}_rank'))
    sampled = select(b.id, b.sensor_type, b.timestamp, *ranks).subquery()
    candidates = select(sampled.c.id, sampled.c.sensor_type, sampled.c.timestamp).where(
        or_(*(sampled.c[rank.name] == 1 for rank in ranks))).subquery()
    capped = select(candidates.c.id, func.row_number().over(
        partition_by=candidates.c.sensor_type,
        order_by=(candidates.c.timestamp.desc(), candidates.c.id.desc())).label('output_rank')).subquery()
    return select(c.sensor_type, c.timestamp, history_payload(c.data, dialect).label('data')).join(
        capped, c.id == capped.c.id).where(capped.c.output_rank <= limit).order_by(c.sensor_type.asc(), c.timestamp.asc(), c.id.asc())
