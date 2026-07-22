from __future__ import annotations

import os
import multiprocessing
import socket

import uvicorn


def get_port() -> int:
    value = os.getenv("PORT", "7860").strip()

    try:
        return int(value)
    except ValueError:
        return 7860


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = get_port()
    lan_ip = get_lan_ip()

    print("")
    print("CameraApp API")
    print("=============")
    print(f"Local: http://127.0.0.1:{port}")
    print(f"Red local: http://{lan_ip}:{port}")
    print(f"Docs: http://127.0.0.1:{port}/docs")
    print("")
    print("Deja esta ventana abierta mientras uses CameraApp.")
    print("Para cerrar la API, presiona Ctrl+C o cierra esta ventana.")
    print("")

    uvicorn.run("main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
