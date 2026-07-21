from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from database import database_connection


STORE_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def get_configuration(
    runtime_camera_config: dict[str, str],
    database_path: Path | None = None,
) -> dict:
    with database_connection(database_path) as connection:
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


def create_store(
    name: str,
    code: str,
    timezone: str,
    database_path: Path | None = None,
) -> dict:
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
        with database_connection(database_path) as connection:
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


def update_store(
    store_id: int,
    name: str,
    code: str,
    timezone: str,
    database_path: Path | None = None,
) -> dict:
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
        with database_connection(database_path) as connection:
            store = connection.execute(
                "SELECT id FROM stores WHERE id = ? AND is_active = 1",
                (store_id,),
            ).fetchone()
            if store is None:
                raise HTTPException(status_code=404, detail="Tienda no encontrada")

            connection.execute(
                """
                UPDATE stores
                SET name = ?, code = ?, timezone = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_name, normalized_code, normalized_timezone, store_id),
            )
            connection.commit()
    except HTTPException:
        raise
    except Exception as error:
        if "UNIQUE constraint failed: stores.code" in str(error):
            raise HTTPException(status_code=409, detail="Ese código de tienda ya existe")
        raise

    return {
        "id": store_id,
        "name": normalized_name,
        "code": normalized_code,
        "timezone": normalized_timezone,
    }


def delete_store(store_id: int, database_path: Path | None = None) -> None:
    with database_connection(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE stores
            SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND is_active = 1
            """,
            (store_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Tienda no encontrada")
        connection.commit()


def get_store_camera_config(store_id: int, database_path: Path | None = None) -> dict | None:
    with database_connection(database_path) as connection:
        _require_active_store(connection, store_id)
        row = connection.execute(
            "SELECT host, username, port, path_template FROM store_camera_configs WHERE store_id = ?",
            (store_id,),
        ).fetchone()
    return dict(row) if row else None


def save_store_camera_config(store_id: int, host: str, username: str, port: str, path_template: str, database_path: Path | None = None) -> dict:
    values = {"host": host.strip(), "username": username.strip(), "port": str(port).strip() or "554", "path_template": path_template.strip()}
    if not all([values["host"], values["username"], values["path_template"]]):
        raise HTTPException(status_code=422, detail="Host, usuario y ruta RTSP son obligatorios")
    if not values["path_template"].startswith("/"):
        values["path_template"] = "/" + values["path_template"]
    with database_connection(database_path) as connection:
        _require_active_store(connection, store_id)
        connection.execute(
            """INSERT INTO store_camera_configs (store_id, host, username, port, path_template)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(store_id) DO UPDATE SET host=excluded.host, username=excluded.username,
            port=excluded.port, path_template=excluded.path_template, updated_at=CURRENT_TIMESTAMP""",
            (store_id, values["host"], values["username"], values["port"], values["path_template"]),
        )
        connection.commit()
    return values


def list_cameras(store_id: int, database_path: Path | None = None) -> list[dict]:
    with database_connection(database_path) as connection:
        _require_active_store(connection, store_id)
        rows = connection.execute(
            """
            SELECT id, store_id, name, channel, location, is_active
            FROM cameras
            WHERE store_id = ?
            ORDER BY id
            """,
            (store_id,),
        ).fetchall()
    return [_camera_payload(row) for row in rows]


def create_camera(
    store_id: int,
    name: str,
    channel: str,
    location: str = "",
    is_active: bool = True,
    database_path: Path | None = None,
) -> dict:
    normalized_name, normalized_channel, normalized_location = _normalize_camera_fields(name, channel, location)
    try:
        with database_connection(database_path) as connection:
            _require_active_store(connection, store_id)
            cursor = connection.execute(
                """
                INSERT INTO cameras (store_id, name, channel, location, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (store_id, normalized_name, normalized_channel, normalized_location, int(is_active)),
            )
            connection.commit()
    except Exception as error:
        if "UNIQUE constraint failed: cameras.store_id, cameras.channel" in str(error):
            raise HTTPException(status_code=409, detail="Ya existe una cámara con ese canal en esta tienda")
        raise

    return {
        "id": cursor.lastrowid,
        "store_id": store_id,
        "name": normalized_name,
        "channel": normalized_channel,
        "location": normalized_location,
        "is_active": is_active,
    }


def update_camera(
    store_id: int,
    camera_id: int,
    name: str,
    channel: str,
    location: str = "",
    is_active: bool = True,
    database_path: Path | None = None,
) -> dict:
    normalized_name, normalized_channel, normalized_location = _normalize_camera_fields(name, channel, location)
    try:
        with database_connection(database_path) as connection:
            _require_active_store(connection, store_id)
            cursor = connection.execute(
                """
                UPDATE cameras
                SET name = ?, channel = ?, location = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND store_id = ?
                """,
                (normalized_name, normalized_channel, normalized_location, int(is_active), camera_id, store_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Cámara no encontrada")
            connection.commit()
    except HTTPException:
        raise
    except Exception as error:
        if "UNIQUE constraint failed: cameras.store_id, cameras.channel" in str(error):
            raise HTTPException(status_code=409, detail="Ya existe una cámara con ese canal en esta tienda")
        raise

    return {
        "id": camera_id,
        "store_id": store_id,
        "name": normalized_name,
        "channel": normalized_channel,
        "location": normalized_location,
        "is_active": is_active,
    }


def delete_camera(store_id: int, camera_id: int, database_path: Path | None = None) -> None:
    with database_connection(database_path) as connection:
        _require_active_store(connection, store_id)
        cursor = connection.execute(
            "DELETE FROM cameras WHERE id = ? AND store_id = ?",
            (camera_id, store_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cámara no encontrada")
        connection.commit()


def _require_active_store(connection, store_id: int) -> None:
    store = connection.execute(
        "SELECT id FROM stores WHERE id = ? AND is_active = 1",
        (store_id,),
    ).fetchone()
    if store is None:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")


def _normalize_camera_fields(name: str, channel: str, location: str) -> tuple[str, str, str]:
    normalized_name = name.strip()
    normalized_channel = channel.strip()
    normalized_location = location.strip()
    if not normalized_name or not normalized_channel:
        raise HTTPException(status_code=422, detail="El nombre y canal de la cámara son obligatorios")
    return normalized_name, normalized_channel, normalized_location


def _camera_payload(row) -> dict:
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "name": row["name"],
        "channel": row["channel"],
        "location": row["location"],
        "is_active": bool(row["is_active"]),
    }


def save_primary_camera(
    store_id: int,
    name: str,
    channel: str,
    location: str,
    is_active: bool,
    database_path: Path | None = None,
) -> dict:
    normalized_name = name.strip()
    normalized_channel = channel.strip()
    normalized_location = location.strip()

    if not normalized_name or not normalized_channel:
        raise HTTPException(
            status_code=422,
            detail="El nombre y canal de la cámara son obligatorios",
        )

    with database_connection(database_path) as connection:
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
