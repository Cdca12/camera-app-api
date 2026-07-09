from __future__ import annotations

from fastapi import FastAPI, File, UploadFile, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from deepface import DeepFace
from pydantic import BaseModel
from PIL import Image
import numpy as np
import cv2
import io
import os
from urllib.parse import quote
from typing import Optional


def load_local_env() -> None:
    env_path = ".env"

    if not os.path.exists(env_path):
        return

    with open(env_path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_local_env()


class CameraConfig(BaseModel):
    host: str
    username: str
    password: str
    port: str = "554"
    path_template: str = "/Streaming/Channels/{channel}"


runtime_camera_config: dict[str, str] = {}


app = FastAPI(
    title="CameraApp API",
    description="API local para analizar edad y género usando DeepFace.",
    version="0.1.0",
)


def get_allowed_origins() -> list[str]:
    default_origins = [
        "https://camera-app-front.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    extra_origins = os.getenv("CORS_ORIGINS", "")

    return default_origins + [
        origin.strip()
        for origin in extra_origins.split(",")
        if origin.strip()
    ]


def get_allowed_origin_regex() -> str:
    return os.getenv("CORS_ORIGIN_REGEX") or None


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=get_allowed_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "camera-app-api",
    }


@app.get("/")
def root():
    return {
        "service": "camera-app-api",
        "health": "/health",
        "camera_config": "/camera-config",
        "analyze_frame": "/analyze-frame",
        "camera_frame": "/camera-frame",
        "analyze_camera_frame": "/analyze-camera-frame",
    }


@app.post("/camera-config")
def camera_config(config: CameraConfig):
    global runtime_camera_config
    runtime_camera_config = normalize_runtime_camera_config(config)

    return {
        "success": True,
        "config": get_public_camera_config(runtime_camera_config),
    }


@app.post("/analyze-frame")
async def analyze_frame(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="El archivo debe ser una imagen.",
        )

    image_bytes = await file.read()

    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="La imagen está vacía.",
        )

    try:
        image_np = load_image_as_numpy(image_bytes)
        return analyze_image(image_np)

    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "people_count": 0,
            "faces": [],
        }


@app.get("/camera-frame")
def camera_frame(channel: Optional[str] = None):
    frame = capture_camera_frame(channel)
    success, encoded_frame = cv2.imencode(".jpg", frame)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="No se pudo convertir el frame de la cámara a JPEG.",
        )

    return Response(
        content=encoded_frame.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/analyze-camera-frame")
def analyze_camera_frame(
    channel: Optional[str] = None,
    camera_name: Optional[str] = None,
):
    try:
        frame = capture_camera_frame(channel)
        image_np = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = analyze_image(image_np)
        result["source"] = "Red"
        result["camera_name"] = camera_name
        result["channel"] = channel
        return result

    except HTTPException:
        raise
    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "people_count": 0,
            "faces": [],
        }


def load_image_as_numpy(image_bytes: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.array(image)


def analyze_image(image_np: np.ndarray) -> dict:
    result = DeepFace.analyze(
        img_path=image_np,
        actions=["age", "gender"],
        detector_backend="opencv",
        enforce_detection=False,
        silent=True,
    )

    faces = result if isinstance(result, list) else [result]
    normalized_faces = [normalize_face(face) for face in faces]

    return {
        "success": True,
        "people_count": len(normalized_faces),
        "faces": normalized_faces,
    }


def capture_camera_frame(channel: Optional[str] = None) -> np.ndarray:
    camera_source = get_camera_source(channel)
    timeout_ms = get_camera_timeout_ms()
    capture = cv2.VideoCapture()
    capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms)
    capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_ms)

    try:
        if not capture.open(camera_source):
            raise HTTPException(
                status_code=503,
                detail="No se pudo abrir la cámara de vigilancia.",
            )

        success, frame = capture.read()

        if not success or frame is None:
            raise HTTPException(
                status_code=503,
                detail="No se pudo leer un frame de la cámara de vigilancia.",
            )

        return frame
    finally:
        capture.release()


def get_camera_source(channel: Optional[str] = None):
    channel = normalize_channel(channel)

    if channel:
        channel_source = get_explicit_channel_camera_source(channel)

        if channel_source:
            return normalize_camera_source(channel_source)

    runtime_source = get_runtime_camera_source(channel)

    if runtime_source:
        return normalize_camera_source(runtime_source)

    template_source = get_template_camera_source(channel)

    if template_source:
        return normalize_camera_source(template_source)

    camera_source = os.getenv("CAMERA_SOURCE", "").strip()

    if not camera_source:
        raise HTTPException(
            status_code=503,
            detail=(
                "No hay configuración suficiente para abrir la cámara. "
                "Configura /camera-config, CAMERA_SOURCE_CHANNEL_<canal>, "
                "CAMERA_SOURCE_TEMPLATE o CAMERA_SOURCE."
            ),
        )

    return normalize_camera_source(camera_source)


def get_explicit_channel_camera_source(channel: str) -> str:
    safe_channel = "".join(
        character if character.isalnum() else "_"
        for character in str(channel).strip()
    ).upper()
    return os.getenv(f"CAMERA_SOURCE_CHANNEL_{safe_channel}", "").strip()


def get_runtime_camera_source(channel: Optional[str]) -> str:
    if not runtime_camera_config:
        return ""

    return build_rtsp_source(runtime_camera_config, channel)


def get_template_camera_source(channel: Optional[str]) -> str:
    source_template = os.getenv("CAMERA_SOURCE_TEMPLATE", "").strip()

    if not source_template:
        return ""

    return format_camera_path(source_template, channel)


def build_rtsp_source(config: dict[str, str], channel: Optional[str]) -> str:
    path = format_camera_path(config["path_template"], channel)

    if not path:
        return ""

    username = quote(config["username"], safe="")
    password = quote(config["password"], safe="")
    host = config["host"]
    port = config["port"]

    return f"rtsp://{username}:{password}@{host}:{port}{path}"


def format_camera_path(path_template: str, channel: Optional[str]) -> str:
    if "{channel}" in path_template:
        if not channel:
            return ""

        return path_template.format(channel=channel)

    return path_template


def normalize_runtime_camera_config(config: CameraConfig) -> dict[str, str]:
    values = {
        "host": config.host.strip(),
        "username": config.username.strip(),
        "password": config.password,
        "port": str(config.port).strip() or "554",
        "path_template": config.path_template.strip(),
    }

    missing_fields = [
        field
        for field, value in values.items()
        if not value and field != "port"
    ]

    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "Faltan campos de configuración de cámara: "
                + ", ".join(missing_fields)
            ),
        )

    if not values["path_template"].startswith("/"):
        values["path_template"] = "/" + values["path_template"]

    return values


def get_initial_runtime_camera_config() -> dict[str, str]:
    host = os.getenv("CAMERA_HOST", "").strip()
    username = os.getenv("CAMERA_USERNAME", "").strip()
    password = os.getenv("CAMERA_PASSWORD", "")
    path_template = os.getenv("CAMERA_PATH_TEMPLATE", "").strip()

    if not any([host, username, password, path_template]):
        return {}

    if not all([host, username, password, path_template]):
        return {}

    return normalize_runtime_camera_config(
        CameraConfig(
            host=host,
            username=username,
            password=password,
            port=os.getenv("CAMERA_RTSP_PORT", "554"),
            path_template=path_template,
        )
    )


def get_public_camera_config(config: dict[str, str]) -> dict[str, str]:
    return {
        "host": config["host"],
        "username": config["username"],
        "port": config["port"],
        "path_template": config["path_template"],
    }


def normalize_channel(channel: Optional[str]) -> Optional[str]:
    if channel is None:
        return None

    channel = str(channel).strip()
    return channel or None


runtime_camera_config = get_initial_runtime_camera_config()


def normalize_camera_source(camera_source: str):
    if camera_source.isdigit():
        return int(camera_source)

    return camera_source


def get_camera_timeout_ms() -> int:
    timeout = os.getenv("CAMERA_TIMEOUT_MS", "5000")

    try:
        return int(timeout)
    except ValueError:
        return 5000


def normalize_face(face: dict) -> dict:
    age = face.get("age")
    gender_raw = face.get("dominant_gender")
    gender_scores = face.get("gender", {})
    region = face.get("region", {})

    return {
        "age": to_json_value(age),
        "age_bucket": get_age_bucket(age),
        "gender": normalize_gender(gender_raw),
        "gender_raw": gender_raw,
        "gender_scores": to_json_value(gender_scores),
        "region": normalize_region(region),
    }


def get_age_bucket(age):
    if age is None:
        return "N/A"

    age = int(round(age))

    if age < 18:
        return "Menor de 18"
    if age <= 24:
        return "18-24"
    if age <= 34:
        return "25-34"
    if age <= 44:
        return "35-44"
    if age <= 54:
        return "45-54"

    return "55+"


def normalize_gender(gender):
    if gender is None:
        return "N/A"

    gender = str(gender).lower()

    if gender == "man":
        return "Masculino"

    if gender == "woman":
        return "Femenino"

    return gender


def normalize_region(region: dict) -> dict:
    return {
        "x": to_json_value(region.get("x")),
        "y": to_json_value(region.get("y")),
        "w": to_json_value(region.get("w")),
        "h": to_json_value(region.get("h")),
    }


def to_json_value(value):
    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, np.ndarray):
        return value.tolist()

    if isinstance(value, dict):
        return {key: to_json_value(nested_value) for key, nested_value in value.items()}

    if isinstance(value, list):
        return [to_json_value(item) for item in value]

    if isinstance(value, tuple):
        return [to_json_value(item) for item in value]

    return value
