from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "camera_app.db"


def get_database_path() -> Path:
    configured_path = os.getenv("CAMERA_APP_DB_PATH")
    return Path(configured_path).expanduser() if configured_path else DEFAULT_DATABASE_PATH


def connect_database() -> sqlite3.Connection:
    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database_connection() -> Iterator[sqlite3.Connection]:
    connection = connect_database()

    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with database_connection() as connection:
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (store_id, channel),
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
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_visitor_events_store_source_captured_at
            ON visitor_events (store_id, data_source, captured_at)
            """
        )
        connection.commit()
