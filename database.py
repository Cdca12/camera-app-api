from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "camera_app_operational.db"
DEFAULT_TEST_DATABASE_PATH = PROJECT_ROOT / "data" / "camera_app_test.db"
LEGACY_DATABASE_PATH = PROJECT_ROOT / "data" / "camera_app.db"


def get_database_path() -> Path:
    configured_path = os.getenv("CAMERA_APP_DB_PATH")
    return Path(configured_path).expanduser() if configured_path else DEFAULT_DATABASE_PATH


def get_test_database_path() -> Path:
    configured_path = os.getenv("CAMERA_APP_TEST_DB_PATH")
    return (
        Path(configured_path).expanduser()
        if configured_path
        else DEFAULT_TEST_DATABASE_PATH
    )


def connect_database(database_path: Path | None = None) -> sqlite3.Connection:
    database_path = database_path or get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database_connection(
    database_path: Path | None = None,
) -> Iterator[sqlite3.Connection]:
    connection = connect_database(database_path)

    try:
        yield connection
    finally:
        connection.close()


def initialize_database(database_path: Path | None = None) -> None:
    with database_connection(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                timezone TEXT NOT NULL DEFAULT 'America/Mazatlan',
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                channel TEXT NOT NULL,
                location TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                collection_enabled INTEGER NOT NULL DEFAULT 0 CHECK (collection_enabled IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (store_id, channel),
                FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS store_camera_configs (
                store_id INTEGER PRIMARY KEY,
                host TEXT NOT NULL,
                username TEXT NOT NULL,
                password_ciphertext TEXT,
                port TEXT NOT NULL DEFAULT '554',
                path_template TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS visitor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                camera_id INTEGER NOT NULL,
                event_uuid TEXT NOT NULL UNIQUE,
                captured_at TEXT NOT NULL,
                gender TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (gender IN ('female', 'male', 'unknown')),
                age_estimate INTEGER,
                age_bucket TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (
                        age_bucket IN (
                            'under_18',
                            '18_24',
                            '25_34',
                            '35_44',
                            '45_54',
                            '55_plus',
                            'unknown'
                        )
                    ),
                confidence REAL,
                data_source TEXT NOT NULL DEFAULT 'simulated'
                    CHECK (data_source IN ('simulated', 'captured')),
                counting_direction TEXT NOT NULL DEFAULT 'entry'
                    CHECK (counting_direction IN ('entry', 'exit', 'unknown')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
                FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_visitor_events_store_captured_at
                ON visitor_events (store_id, captured_at);
            CREATE INDEX IF NOT EXISTS idx_visitor_events_camera_captured_at
                ON visitor_events (camera_id, captured_at);
            """
        )
        event_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(visitor_events)").fetchall()
        }
        if "data_source" not in event_columns:
            connection.execute(
                """
                ALTER TABLE visitor_events
                ADD COLUMN data_source TEXT NOT NULL DEFAULT 'simulated'
                """
            )
        config_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(store_camera_configs)").fetchall()
        }
        if "password_ciphertext" not in config_columns:
            connection.execute(
                """
                ALTER TABLE store_camera_configs
                ADD COLUMN password_ciphertext TEXT
                """
            )
        camera_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(cameras)").fetchall()
        }
        if "collection_enabled" not in camera_columns:
            connection.execute(
                """
                ALTER TABLE cameras
                ADD COLUMN collection_enabled INTEGER NOT NULL DEFAULT 0
                """
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_visitor_events_store_source_captured_at
            ON visitor_events (store_id, data_source, captured_at)
            """
        )
        connection.commit()


def initialize_test_database() -> Path:
    test_database_path = get_test_database_path()
    initialize_database(test_database_path)

    with database_connection(test_database_path) as connection:
        test_event_count = connection.execute(
            "SELECT COUNT(*) FROM visitor_events"
        ).fetchone()[0]

    if test_event_count:
        _ensure_test_data_for_today(test_database_path)
        return test_database_path

    source_paths = [LEGACY_DATABASE_PATH, get_database_path()]
    for source_path in source_paths:
        if source_path.exists():
            _copy_simulated_data(source_path, test_database_path)

            with database_connection(test_database_path) as connection:
                if connection.execute("SELECT COUNT(*) FROM visitor_events").fetchone()[0]:
                    break

    _ensure_test_data_for_today(test_database_path)
    return test_database_path


def initialize_operational_database() -> Path:
    operational_database_path = get_database_path()
    is_new_database = not operational_database_path.exists()
    initialize_database(operational_database_path)

    if is_new_database and LEGACY_DATABASE_PATH.exists():
        _copy_captured_data(LEGACY_DATABASE_PATH, operational_database_path)

    ensure_local_store(operational_database_path)
    purge_incomplete_captured_events(operational_database_path)

    return operational_database_path


def ensure_local_store(database_path: Path | None = None) -> int:
    """Creates the store used by device-local captures when it is missing."""
    with database_connection(database_path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO stores (name, code, timezone)
            VALUES ('Local', 'local', 'America/Mazatlan')
            """
        )
        store = connection.execute(
            "SELECT id FROM stores WHERE code = 'local'"
        ).fetchone()
        connection.commit()

    return int(store["id"])


def purge_incomplete_captured_events(database_path: Path | None = None) -> None:
    """Removes old operational captures that lack age or gender data."""
    with database_connection(database_path) as connection:
        connection.execute(
            """
            DELETE FROM visitor_events
            WHERE data_source = 'captured'
              AND (gender = 'unknown' OR age_estimate IS NULL OR age_bucket = 'unknown')
            """
        )
        connection.commit()


def _copy_simulated_data(source_path: Path, target_path: Path) -> None:
    _copy_data_by_source(source_path, target_path, "simulated")


def _ensure_test_data_for_today(test_database_path: Path) -> None:
    today = date.today().isoformat()
    with database_connection(test_database_path) as connection:
        has_today_data = connection.execute(
            "SELECT 1 FROM visitor_events WHERE data_source = 'simulated' AND captured_at LIKE ? LIMIT 1",
            (f"{today}%",),
        ).fetchone()
        if has_today_data:
            return

        source_date_row = connection.execute(
            "SELECT MAX(substr(captured_at, 1, 10)) AS date FROM visitor_events WHERE data_source = 'simulated'"
        ).fetchone()
        source_date = source_date_row["date"]
        if not source_date:
            return

        rows = connection.execute(
            """
            SELECT store_id, camera_id, captured_at, gender, age_estimate, age_bucket,
                   confidence, counting_direction
            FROM visitor_events
            WHERE data_source = 'simulated' AND captured_at LIKE ?
            """,
            (f"{source_date}%",),
        ).fetchall()
        events = [
            (
                row["store_id"], row["camera_id"],
                str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-today:{today}:{index}")),
                f"{today}{row['captured_at'][10:]}", row["gender"], row["age_estimate"],
                row["age_bucket"], row["confidence"], "simulated", row["counting_direction"],
            )
            for index, row in enumerate(rows)
        ]
        connection.executemany(
            """INSERT INTO visitor_events (store_id, camera_id, event_uuid, captured_at, gender,
            age_estimate, age_bucket, confidence, data_source, counting_direction)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            events,
        )
        connection.commit()


def _copy_captured_data(source_path: Path, target_path: Path) -> None:
    _copy_data_by_source(source_path, target_path, "captured")


def _copy_data_by_source(
    source_path: Path,
    target_path: Path,
    data_source: str,
) -> None:
    with database_connection(source_path) as source_connection:
        stores = source_connection.execute(
            "SELECT * FROM stores ORDER BY id"
        ).fetchall()
        cameras = source_connection.execute(
            "SELECT * FROM cameras ORDER BY id"
        ).fetchall()
        events = source_connection.execute(
            """
            SELECT
                id, store_id, camera_id, event_uuid, captured_at, gender,
                age_estimate, age_bucket, confidence, data_source,
                counting_direction, created_at
            FROM visitor_events
            WHERE data_source = ?
            ORDER BY id
            """,
            (data_source,),
        ).fetchall()

    with database_connection(target_path) as target_connection:
        target_connection.executemany(
            """
            INSERT OR IGNORE INTO stores (
                id, name, code, timezone, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [tuple(store) for store in stores],
        )
        target_connection.executemany(
            """
            INSERT OR IGNORE INTO cameras (
                id, store_id, name, channel, location, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [tuple(camera) for camera in cameras],
        )
        target_connection.executemany(
            """
            INSERT OR IGNORE INTO visitor_events (
                id, store_id, camera_id, event_uuid, captured_at, gender,
                age_estimate, age_bucket, confidence, data_source,
                counting_direction, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [tuple(event) for event in events],
        )
        target_connection.commit()
