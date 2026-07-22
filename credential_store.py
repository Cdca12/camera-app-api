from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def encrypt_local_secret(value: str, database_path: Path) -> str:
    return _get_fernet(database_path).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_local_secret(value: str, database_path: Path) -> str:
    try:
        return _get_fernet(database_path).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise ValueError("No fue posible descifrar la contraseña RTSP guardada.") from error


def _get_fernet(database_path: Path) -> Fernet:
    key_path = database_path.with_suffix(f"{database_path.suffix}.key")
    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        key = key_path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass

    return Fernet(key)
