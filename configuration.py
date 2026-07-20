from __future__ import annotations

import re

from fastapi import HTTPException

from database import database_connection


STORE_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def get_configuration(runtime_camera_config: dict[str, str]) -> dict:
    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                stores.id,
                stores.name,
                stores.code,
                stores.timezone,
                cameras.id AS camera_id,
                cameras.name AS camera_name,
                cameras.channel AS camera_channel,
                cameras.location AS camera_location,
                cameras.is_active AS camera_is_active
            FROM stores
            LEFT JOIN cameras ON cameras.id = (
                SELECT id
                FROM cameras
                WHERE store_id = stores.id
                ORDER BY is_active DESC, id
                LIMIT 1
            )
            WHERE stores.is_active = 1
            ORDER BY stores.name
            """
        ).fetchall()

    stores = []
    for row in rows:
        camera = None
        if row["camera_id"] is not None:
            camera = {
                "id": row["camera_id"],
                "name": row["camera_name"],
                "channel": row["camera_channel"],
                "location": row["camera_location"],
                "is_active": bool(row["camera_is_active"]),
            }

        stores.append(
            {
                "id": row["id"],
                "name": row["name"],
                "code": row["code"],
                "timezone": row["timezone"],
                "primary_camera": camera,
            }
        )

    return {
        "service": {
            "status": "online",
            "runtime_camera_configured": bool(runtime_camera_config),
        },
        "stores": stores,
    }


def create_store(name: str, code: str, timezone: str) -> dict:
    normalized_name = name.strip()
    normalized_code = code.strip().lower()
    normalized_timezone = timezone.strip() or "America/Mazatlan"

    if not normalized_name:
        raise HTTPException(status_code=422, detail="El nombre de la tienda es obligatorio")

    if not STORE_CODE_PATTERN.fullmatch(normalized_code):
        raise HTTPException(
            status_code=422,
            detail="El código debe usar minúsculas, números y guiones",
        )

    try:
        with database_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO stores (name, code, timezone)
                VALUES (?, ?, ?)
                """,
                (normalized_name, normalized_code, normalized_timezone),
            )
            connection.commit()
    except Exception as error:
        if "UNIQUE constraint failed: stores.code" in str(error):
            raise HTTPException(status_code=409, detail="Ese código de tienda ya existe")
        raise

    return {
        "id": cursor.lastrowid,
        "name": normalized_name,
        "code": normalized_code,
        "timezone": normalized_timezone,
        "primary_camera": None,
    }


def save_primary_camera(
    store_id: int,
    name: str,
    channel: str,
    location: str,
    is_active: bool,
) -> dict:
    normalized_name = name.strip()
    normalized_channel = channel.strip()
    normalized_location = location.strip()

    if not normalized_name or not normalized_channel:
        raise HTTPException(
            status_code=422,
            detail="El nombre y canal de la cámara son obligatorios",
        )

    with database_connection() as connection:
        store = connection.execute(
            "SELECT id FROM stores WHERE id = ? AND is_active = 1",
            (store_id,),
        ).fetchone()

        if store is None:
            raise HTTPException(status_code=404, detail="Store not found")

        primary_camera = connection.execute(
            """
            SELECT id
            FROM cameras
            WHERE store_id = ?
            ORDER BY is_active DESC, id
            LIMIT 1
            """,
            (store_id,),
        ).fetchone()

        try:
            if primary_camera:
                connection.execute(
                    """
                    UPDATE cameras
                    SET name = ?, channel = ?, location = ?, is_active = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        normalized_name,
                        normalized_channel,
                        normalized_location,
                        int(is_active),
                        primary_camera["id"],
                    ),
                )
                camera_id = primary_camera["id"]
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO cameras (store_id, name, channel, location, is_active)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        store_id,
                        normalized_name,
                        normalized_channel,
                        normalized_location,
                        int(is_active),
                    ),
                )
                camera_id = cursor.lastrowid
            connection.commit()
        except Exception as error:
            if "UNIQUE constraint failed: cameras.store_id, cameras.channel" in str(error):
                raise HTTPException(
                    status_code=409,
                    detail="Ya existe una cámara con ese canal en esta tienda",
                )
            raise

    return {
        "id": camera_id,
        "name": normalized_name,
        "channel": normalized_channel,
        "location": normalized_location,
        "is_active": is_active,
    }
