from __future__ import annotations

from datetime import date

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from deepface import DeepFace
from pydantic import BaseModel
from PIL import Image
import numpy as np
import cv2
import io
import os
from contextlib import contextmanager
from urllib.parse import quote
from typing import Optional
import time

from dashboard import get_dashboard_daily, get_dashboard_summary, list_stores
from configuration import create_store, get_configuration, save_primary_camera
from database import initialize_database

cv2.setLogLevel(0)


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
initialize_database()


class CameraConfig(BaseModel):
    host: str
    username: str
    password: str
    port: str = "554"
    path_template: str = "/Streaming/Channels/{channel}"


class StoreSettings(BaseModel):
    name: str
    code: str
    timezone: str = "America/Mazatlan"


class PrimaryCameraSettings(BaseModel):
    name: str
    channel: str
    location: str = "Entrada principal"
    is_active: bool = True


runtime_camera_config: dict[str, str] = {}
face_cache: dict[str, list[dict]] = {}
face_detector = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


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
        "stores": "/stores",
        "configuration": "/configuration",
        "dashboard_daily": "/dashboard/daily",
        "dashboard_summary": "/dashboard/summary",
        "camera_config": "/camera-config",
        "analyze_frame": "/analyze-frame",
        "camera_frame": "/camera-frame",
        "analyze_camera_frame": "/analyze-camera-frame",
        "watch_camera_frame": "/watch-camera-frame",
        "watch_uploaded_frame": "/watch-uploaded-frame",
    }


@app.get("/stores")
def stores():
    return {"stores": list_stores()}


@app.get("/configuration")
def configuration():
    return get_configuration(runtime_camera_config)


@app.post("/configuration/stores", status_code=status.HTTP_201_CREATED)
def configuration_store(store: StoreSettings):
    return create_store(store.name, store.code, store.timezone)


@app.put("/configuration/stores/{store_id}/primary-camera")
def configuration_primary_camera(
    store_id: int,
    camera: PrimaryCameraSettings,
):
    return save_primary_camera(
        store_id,
        camera.name,
        camera.channel,
        camera.location,
        camera.is_active,
    )


@app.get("/dashboard/summary")
def dashboard_summary(
    store_id: int = Query(..., gt=0),
    date_from: date = Query(default_factory=date.today),
    date_to: date = Query(default_factory=date.today),
):
    return get_dashboard_summary(store_id, date_from, date_to)


@app.get("/dashboard/daily")
def dashboard_daily(
    store_id: int = Query(..., gt=0),
    date_from: date = Query(default_factory=date.today),
    date_to: date = Query(default_factory=date.today),
):
    return get_dashboard_daily(store_id, date_from, date_to)


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


@app.post("/watch-camera-frame")
def watch_camera_frame(
    channel: Optional[str] = None,
    camera_name: Optional[str] = None,
):
    try:
        frame = capture_camera_frame(channel)
        cache_key = get_face_cache_key(channel, camera_name)
        return watch_frame_for_new_faces(
            frame=frame,
            cache_key=cache_key,
            source="Red",
            camera_name=camera_name,
            channel=channel,
        )

    except HTTPException:
        raise
    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "has_new_faces": False,
            "people_count": 0,
            "faces": [],
        }


@app.post("/watch-uploaded-frame")
async def watch_uploaded_frame(file: UploadFile = File(...)):
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
        frame = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

        return watch_frame_for_new_faces(
            frame=frame,
            cache_key="uploaded:device-camera",
            source="Dispositivo",
            camera_name="Dispositivo",
            channel=None,
        )

    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "has_new_faces": False,
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
        with suppress_stderr():
            is_opened = capture.open(camera_source)

            if not is_opened:
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


def detect_light_faces(frame: np.ndarray) -> list[dict]:
    if face_detector.empty():
        raise HTTPException(
            status_code=500,
            detail="No se pudo cargar el detector ligero de caras de OpenCV.",
        )

    detection_frame, scale = resize_frame_for_detection(frame)
    gray_frame = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2GRAY)
    equalized_frame = cv2.equalizeHist(gray_frame)
    detections = face_detector.detectMultiScale(
        equalized_frame,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(50, 50),
    )

    return [
        {
            "region": {
                "x": int(x / scale),
                "y": int(y / scale),
                "w": int(w / scale),
                "h": int(h / scale),
            },
            "signature": build_face_signature(
                frame,
                int(x / scale),
                int(y / scale),
                int(w / scale),
                int(h / scale),
            ),
        }
        for (x, y, w, h) in detections
    ]


def resize_frame_for_detection(frame: np.ndarray) -> tuple[np.ndarray, float]:
    target_width = get_face_detect_width()
    height, width = frame.shape[:2]

    if target_width <= 0 or width <= target_width:
        return frame, 1.0

    scale = target_width / float(width)
    target_height = int(height * scale)
    resized_frame = cv2.resize(
        frame,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )
    return resized_frame, scale


def watch_frame_for_new_faces(
    frame: np.ndarray,
    cache_key: str,
    source: str,
    camera_name: Optional[str],
    channel: Optional[str],
) -> dict:
    detected_faces = detect_light_faces(frame)

    if not detected_faces:
        return {
            "success": True,
            "has_new_faces": False,
            "faces": [],
        }

    new_faces = get_new_light_faces(frame, detected_faces, cache_key)

    if not new_faces:
        return {
            "success": True,
            "has_new_faces": False,
            "faces": [],
        }

    analyzed_faces = []

    for detected_face in new_faces:
        face_crop = crop_detected_face(frame, detected_face)

        if face_crop.size == 0:
            continue

        image_np = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        analysis = analyze_image(image_np)
        remember_light_face(cache_key, detected_face)

        for analyzed_face in analysis["faces"]:
            analyzed_face["source"] = source
            analyzed_face["camera_name"] = camera_name
            analyzed_face["channel"] = channel
            analyzed_face["region"] = detected_face["region"]
            analyzed_faces.append(analyzed_face)

    return {
        "success": True,
        "has_new_faces": bool(analyzed_faces),
        "people_count": len(analyzed_faces),
        "faces": analyzed_faces,
    }


def get_new_light_faces(
    frame: np.ndarray,
    detected_faces: list[dict],
    cache_key: str,
) -> list[dict]:
    now = time.time()
    ttl_seconds = get_face_cache_ttl_seconds()
    cached_faces = prune_face_cache(cache_key, now, ttl_seconds)
    new_faces = []

    for detected_face in detected_faces:
        signature = detected_face["signature"]

        if is_known_face(signature, cached_faces):
            continue

        new_faces.append(detected_face)

    face_cache[cache_key] = cached_faces
    return new_faces


def remember_light_face(cache_key: str, detected_face: dict) -> None:
    now = time.time()
    ttl_seconds = get_face_cache_ttl_seconds()
    cached_faces = prune_face_cache(cache_key, now, ttl_seconds)
    cached_faces.append(
        {
            "signature": detected_face["signature"],
            "last_seen": now,
            "region": detected_face["region"],
        }
    )
    face_cache[cache_key] = cached_faces


def prune_face_cache(cache_key: str, now: float, ttl_seconds: int) -> list[dict]:
    cached_faces = face_cache.get(cache_key, [])

    if ttl_seconds <= 0:
        return []

    return [
        cached_face
        for cached_face in cached_faces
        if now - cached_face["last_seen"] <= ttl_seconds
    ]


def is_known_face(signature: np.ndarray, cached_faces: list[dict]) -> bool:
    threshold = get_face_match_threshold()

    for cached_face in cached_faces:
        distance = float(np.mean(np.abs(signature - cached_face["signature"])))

        if distance <= threshold:
            cached_face["last_seen"] = time.time()
            return True

    return False


def build_face_signature(
    frame: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> np.ndarray:
    face_crop = crop_face_region(frame, x, y, w, h, margin_ratio=0.15)
    gray_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    resized_face = cv2.resize(gray_face, (32, 32), interpolation=cv2.INTER_AREA)
    normalized_face = resized_face.astype("float32") / 255.0
    normalized_face = cv2.equalizeHist((normalized_face * 255).astype("uint8"))
    return normalized_face.astype("float32") / 255.0


def crop_detected_face(frame: np.ndarray, detected_face: dict) -> np.ndarray:
    region = detected_face["region"]
    return crop_face_region(
        frame,
        region["x"],
        region["y"],
        region["w"],
        region["h"],
        margin_ratio=0.35,
    )


def crop_face_region(
    frame: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    margin_ratio: float,
) -> np.ndarray:
    height, width = frame.shape[:2]
    margin_x = int(w * margin_ratio)
    margin_y = int(h * margin_ratio)
    x1 = max(0, x - margin_x)
    y1 = max(0, y - margin_y)
    x2 = min(width, x + w + margin_x)
    y2 = min(height, y + h + margin_y)
    return frame[y1:y2, x1:x2]


def get_face_cache_key(
    channel: Optional[str],
    camera_name: Optional[str],
) -> str:
    channel_key = normalize_channel(channel) or "default"
    camera_key = (camera_name or "camera").strip() or "camera"
    return f"{camera_key}:{channel_key}"


def get_face_cache_ttl_seconds() -> int:
    value = os.getenv("FACE_CACHE_TTL_SECONDS", "300")

    try:
        return int(value)
    except ValueError:
        return 300


def get_face_match_threshold() -> float:
    value = os.getenv("FACE_MATCH_THRESHOLD", "0.18")

    try:
        return float(value)
    except ValueError:
        return 0.18


def get_face_detect_width() -> int:
    value = os.getenv("FACE_DETECT_WIDTH", "640")

    try:
        return int(value)
    except ValueError:
        return 640


@contextmanager
def suppress_stderr():
    stderr_fd = 2
    saved_stderr_fd = os.dup(stderr_fd)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)

    try:
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        os.dup2(saved_stderr_fd, stderr_fd)
        os.close(saved_stderr_fd)
        os.close(devnull_fd)


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
