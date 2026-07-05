from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from deepface import DeepFace
from PIL import Image
import numpy as np
import io
import os


app = FastAPI(
    title="CameraApp API",
    description="API local para analizar edad y género usando DeepFace.",
    version="0.1.0",
)


def get_allowed_origins() -> list[str]:
    default_origins = [
        "https://camera-app-front.vercel.app",
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
        "analyze_frame": "/analyze-frame",
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
