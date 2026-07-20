from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException

from database import database_connection


AGE_BUCKET_LABELS = {
    "under_18": "Menores de 18",
    "18_24": "18 a 24",
    "25_34": "25 a 34",
    "35_44": "35 a 44",
    "45_54": "45 a 54",
    "55_plus": "55 o más",
    "unknown": "Sin identificar",
}

GENDER_LABELS = {
    "female": "Femenino",
    "male": "Masculino",
    "unknown": "Sin identificar",
}


def list_stores() -> list[dict]:
    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, name, code, timezone
            FROM stores
            WHERE is_active = 1
            ORDER BY name
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_dashboard_summary(
    store_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from no puede ser posterior a date_to",
        )

    selected_start = datetime.combine(date_from, time.min)
    selected_end = datetime.combine(date_to + timedelta(days=1), time.min)
    period_length = selected_end - selected_start
    previous_start = selected_start - period_length
    previous_end = selected_start

    with database_connection() as connection:
        store = connection.execute(
            """
            SELECT id, name, code, timezone
            FROM stores
            WHERE id = ? AND is_active = 1
            """,
            (store_id,),
        ).fetchone()

        if store is None:
            raise HTTPException(status_code=404, detail="Store not found")

        current_count = _count_entries(
            connection,
            store_id,
            selected_start,
            selected_end,
        )
        previous_count = _count_entries(
            connection,
            store_id,
            previous_start,
            previous_end,
        )
        hourly_traffic = _hourly_traffic(
            connection,
            store_id,
            selected_start,
            selected_end,
            previous_start,
            previous_end,
        )
        gender_distribution = _distribution(
            connection,
            store_id,
            selected_start,
            selected_end,
            "gender",
            GENDER_LABELS,
        )
        age_distribution = _distribution(
            connection,
            store_id,
            selected_start,
            selected_end,
            "age_bucket",
            AGE_BUCKET_LABELS,
        )

    peak = max(hourly_traffic, key=lambda item: item["current_count"])
    dominant_gender = max(gender_distribution, key=lambda item: item["count"])
    dominant_age = max(age_distribution, key=lambda item: item["count"])

    return {
        "store": dict(store),
        "period": {
            "date_from": date_from,
            "date_to": date_to,
            "previous_date_from": previous_start.date(),
            "previous_date_to": (previous_end - timedelta(days=1)).date(),
        },
        "metrics": {
            "people_count": current_count,
            "previous_people_count": previous_count,
            "people_count_change_percentage": _percentage_change(
                current_count,
                previous_count,
            ),
            "peak_hour": peak["hour"] if peak["current_count"] else None,
            "dominant_age_bucket": dominant_age["key"],
            "dominant_gender": dominant_gender["key"],
        },
        "hourly_traffic": hourly_traffic,
        "gender_distribution": gender_distribution,
        "age_distribution": age_distribution,
    }


def get_dashboard_daily(
    store_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    _validate_date_range(date_from, date_to, maximum_days=366)
    selected_start = datetime.combine(date_from, time.min)
    selected_end = datetime.combine(date_to + timedelta(days=1), time.min)
    query_start = selected_start - timedelta(days=1)

    with database_connection() as connection:
        store = connection.execute(
            """
            SELECT id, name, code, timezone
            FROM stores
            WHERE id = ? AND is_active = 1
            """,
            (store_id,),
        ).fetchone()

        if store is None:
            raise HTTPException(status_code=404, detail="Store not found")

        daily_counts = _daily_counts(
            connection,
            store_id,
            query_start,
            selected_end,
        )
        peak_hours = _daily_peak_hours(
            connection,
            store_id,
            selected_start,
            selected_end,
        )
        dominant_genders = _daily_dominant_values(
            connection,
            store_id,
            selected_start,
            selected_end,
            "gender",
        )
        dominant_ages = _daily_dominant_values(
            connection,
            store_id,
            selected_start,
            selected_end,
            "age_bucket",
        )

    days = []
    current_date = date_from

    while current_date <= date_to:
        day_key = current_date.isoformat()
        previous_day_key = (current_date - timedelta(days=1)).isoformat()
        people_count = daily_counts.get(day_key, 0)
        previous_people_count = daily_counts.get(previous_day_key, 0)
        peak_hour = peak_hours.get(day_key)
        dominant_gender = dominant_genders.get(day_key)
        dominant_age = dominant_ages.get(day_key)

        days.append(
            {
                "date": current_date,
                "people_count": people_count,
                "previous_people_count": previous_people_count,
                "people_count_change_percentage": _percentage_change(
                    people_count,
                    previous_people_count,
                ),
                "peak_hour": peak_hour["key"] if peak_hour else None,
                "peak_hour_people_count": peak_hour["count"] if peak_hour else 0,
                "dominant_gender": _daily_distribution_value(
                    dominant_gender,
                    GENDER_LABELS,
                    people_count,
                ),
                "dominant_age_bucket": _daily_distribution_value(
                    dominant_age,
                    AGE_BUCKET_LABELS,
                    people_count,
                ),
            }
        )
        current_date += timedelta(days=1)

    return {
        "store": dict(store),
        "period": {
            "date_from": date_from,
            "date_to": date_to,
        },
        "days": list(reversed(days)),
    }


def _validate_date_range(
    date_from: date,
    date_to: date,
    maximum_days: int | None = None,
) -> None:
    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from no puede ser posterior a date_to",
        )

    selected_days = (date_to - date_from).days + 1
    if maximum_days and selected_days > maximum_days:
        raise HTTPException(
            status_code=422,
            detail=f"El rango no puede exceder {maximum_days} días",
        )


def _daily_counts(
    connection,
    store_id: int,
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT date(captured_at) AS event_date, COUNT(*) AS total
        FROM visitor_events
        WHERE store_id = ?
          AND counting_direction = 'entry'
          AND captured_at >= ?
          AND captured_at < ?
        GROUP BY event_date
        """,
        (store_id, _timestamp(start), _timestamp(end)),
    ).fetchall()
    return {row["event_date"]: int(row["total"]) for row in rows}


def _daily_peak_hours(
    connection,
    store_id: int,
    start: datetime,
    end: datetime,
) -> dict[str, dict]:
    rows = connection.execute(
        """
        SELECT date(captured_at) AS event_date,
               strftime('%H:00', captured_at) AS value,
               COUNT(*) AS total
        FROM visitor_events
        WHERE store_id = ?
          AND counting_direction = 'entry'
          AND captured_at >= ?
          AND captured_at < ?
        GROUP BY event_date, value
        ORDER BY event_date, total DESC, value
        """,
        (store_id, _timestamp(start), _timestamp(end)),
    ).fetchall()
    return _first_value_per_day(rows)


def _daily_dominant_values(
    connection,
    store_id: int,
    start: datetime,
    end: datetime,
    field: str,
) -> dict[str, dict]:
    rows = connection.execute(
        f"""
        SELECT date(captured_at) AS event_date,
               {field} AS value,
               COUNT(*) AS total
        FROM visitor_events
        WHERE store_id = ?
          AND counting_direction = 'entry'
          AND captured_at >= ?
          AND captured_at < ?
        GROUP BY event_date, {field}
        ORDER BY event_date, total DESC, value
        """,
        (store_id, _timestamp(start), _timestamp(end)),
    ).fetchall()
    return _first_value_per_day(rows)


def _first_value_per_day(rows) -> dict[str, dict]:
    values = {}

    for row in rows:
        values.setdefault(
            row["event_date"],
            {
                "key": row["value"],
                "count": int(row["total"]),
            },
        )

    return values


def _daily_distribution_value(
    value: dict | None,
    labels: dict[str, str],
    total: int,
) -> dict:
    key = value["key"] if value else "unknown"
    count = value["count"] if value else 0
    return {
        "key": key,
        "label": labels.get(key, labels["unknown"]),
        "count": count,
        "percentage": round(count * 100 / total, 1) if total else 0,
    }


def _count_entries(connection, store_id: int, start: datetime, end: datetime) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM visitor_events
        WHERE store_id = ?
          AND counting_direction = 'entry'
          AND captured_at >= ?
          AND captured_at < ?
        """,
        (store_id, _timestamp(start), _timestamp(end)),
    ).fetchone()
    return int(row["total"])


def _hourly_traffic(
    connection,
    store_id: int,
    current_start: datetime,
    current_end: datetime,
    previous_start: datetime,
    previous_end: datetime,
) -> list[dict]:
    current = _counts_by_hour(connection, store_id, current_start, current_end)
    previous = _counts_by_hour(connection, store_id, previous_start, previous_end)

    return [
        {
            "hour": f"{hour:02d}:00",
            "current_count": current.get(hour, 0),
            "previous_count": previous.get(hour, 0),
        }
        for hour in range(24)
    ]


def _counts_by_hour(
    connection,
    store_id: int,
    start: datetime,
    end: datetime,
) -> dict[int, int]:
    rows = connection.execute(
        """
        SELECT CAST(strftime('%H', captured_at) AS INTEGER) AS hour,
               COUNT(*) AS total
        FROM visitor_events
        WHERE store_id = ?
          AND counting_direction = 'entry'
          AND captured_at >= ?
          AND captured_at < ?
        GROUP BY hour
        ORDER BY hour
        """,
        (store_id, _timestamp(start), _timestamp(end)),
    ).fetchall()
    return {int(row["hour"]): int(row["total"]) for row in rows}


def _distribution(
    connection,
    store_id: int,
    start: datetime,
    end: datetime,
    field: str,
    labels: dict[str, str],
) -> list[dict]:
    rows = connection.execute(
        f"""
        SELECT {field} AS key, COUNT(*) AS total
        FROM visitor_events
        WHERE store_id = ?
          AND counting_direction = 'entry'
          AND captured_at >= ?
          AND captured_at < ?
        GROUP BY {field}
        """,
        (store_id, _timestamp(start), _timestamp(end)),
    ).fetchall()
    counts = {row["key"]: int(row["total"]) for row in rows}
    total = sum(counts.values())

    return [
        {
            "key": key,
            "label": label,
            "count": counts.get(key, 0),
            "percentage": round(counts.get(key, 0) * 100 / total, 1) if total else 0,
        }
        for key, label in labels.items()
    ]


def _percentage_change(current: int, previous: int) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) * 100 / previous, 1)


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")
