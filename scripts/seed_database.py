from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import database_connection, get_database_path, initialize_database


STORES = [
    ("Maja Centro", "maja-centro", "America/Mazatlan"),
    ("Maja Marina", "maja-marina", "America/Mazatlan"),
    ("Maja Zona Dorada", "maja-zona-dorada", "America/Mazatlan"),
]

HOURLY_WEIGHTS = {
    9: 0.25,
    10: 0.55,
    11: 0.80,
    12: 1.00,
    13: 0.90,
    14: 0.72,
    15: 0.66,
    16: 0.78,
    17: 1.05,
    18: 1.28,
    19: 1.18,
    20: 0.82,
    21: 0.35,
}

AGE_BUCKETS = [
    ("under_18", 0.08, (13, 17)),
    ("18_24", 0.23, (18, 24)),
    ("25_34", 0.31, (25, 34)),
    ("35_44", 0.20, (35, 44)),
    ("45_54", 0.11, (45, 54)),
    ("55_plus", 0.07, (55, 72)),
]


def seed_database(days: int) -> int:
    initialize_database()
    random_generator = random.Random(20260719)
    today = date.today()
    first_day = today - timedelta(days=days)

    with database_connection() as connection:
        connection.execute("DELETE FROM visitor_events")
        connection.execute("DELETE FROM cameras")
        connection.execute("DELETE FROM stores")
        connection.execute("DELETE FROM sqlite_sequence")

        store_ids = []
        for name, code, timezone in STORES:
            cursor = connection.execute(
                """
                INSERT INTO stores (name, code, timezone)
                VALUES (?, ?, ?)
                """,
                (name, code, timezone),
            )
            store_id = cursor.lastrowid
            camera_cursor = connection.execute(
                """
                INSERT INTO cameras (store_id, name, channel, location)
                VALUES (?, ?, ?, ?)
                """,
                (store_id, "Entrada principal", "101", "Acceso principal"),
            )
            store_ids.append((store_id, camera_cursor.lastrowid, code))

        events = []
        for day_offset in range(days + 1):
            event_date = first_day + timedelta(days=day_offset)
            weekday_factor = 1.18 if event_date.weekday() in (4, 5) else 1.0

            for store_index, (store_id, camera_id, store_code) in enumerate(store_ids):
                store_factor = 1.0 - (store_index * 0.14)
                daily_variation = random_generator.uniform(0.88, 1.12)

                for hour, weight in HOURLY_WEIGHTS.items():
                    expected_count = 48 * weight * weekday_factor * store_factor
                    expected_count *= daily_variation
                    visitor_count = max(1, round(expected_count))

                    for visitor_index in range(visitor_count):
                        captured_at = datetime.combine(event_date, time(hour=hour))
                        captured_at += timedelta(
                            minutes=random_generator.randint(0, 59),
                            seconds=random_generator.randint(0, 59),
                        )
                        age_bucket, age_range = _choose_age(random_generator)
                        gender = random_generator.choices(
                            ["female", "male", "unknown"],
                            weights=[0.54, 0.44, 0.02],
                            k=1,
                        )[0]
                        event_key = (
                            f"{store_code}:{captured_at.isoformat()}:{visitor_index}"
                        )
                        events.append(
                            (
                                store_id,
                                camera_id,
                                str(uuid.uuid5(uuid.NAMESPACE_URL, event_key)),
                                captured_at.strftime("%Y-%m-%d %H:%M:%S"),
                                gender,
                                random_generator.randint(*age_range),
                                age_bucket,
                                round(random_generator.uniform(0.72, 0.99), 4),
                                "entry",
                            )
                        )

        connection.executemany(
            """
            INSERT INTO visitor_events (
                store_id,
                camera_id,
                event_uuid,
                captured_at,
                gender,
                age_estimate,
                age_bucket,
                confidence,
                counting_direction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            events,
        )
        connection.commit()

    return len(events)


def _choose_age(random_generator: random.Random) -> tuple[str, tuple[int, int]]:
    selected = random_generator.choices(
        AGE_BUCKETS,
        weights=[item[1] for item in AGE_BUCKETS],
        k=1,
    )[0]
    return selected[0], selected[2]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera datos simulados para el dashboard de CameraApp.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Número de días anteriores, además del día actual (default: 30).",
    )
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days debe ser mayor o igual a 1")

    inserted_events = seed_database(args.days)
    print(f"Database: {get_database_path()}")
    print(f"Stores: {len(STORES)}")
    print(f"Visitor events: {inserted_events}")


if __name__ == "__main__":
    main()
