FROM python:3.10-slim

WORKDIR /app

ENV TF_USE_LEGACY_KERAS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip
RUN python -m pip install --no-cache-dir -r requirements.txt

# Fix para Haar Cascades de OpenCV, porque DeepFace los necesita con detector_backend="opencv".
RUN python - <<'PY'
import cv2
from pathlib import Path
import urllib.request

cascade_dir = Path(cv2.data.haarcascades)
cascade_dir.mkdir(parents=True, exist_ok=True)

cascades = {
    "haarcascade_frontalface_default.xml": (
        "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/"
        "haarcascade_frontalface_default.xml"
    ),
    "haarcascade_eye.xml": (
        "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/"
        "haarcascade_eye.xml"
    ),
}

for filename, url in cascades.items():
    cascade_file = cascade_dir / filename

    if not cascade_file.exists():
        urllib.request.urlretrieve(url, cascade_file)

    print(f"{filename} exists:", cascade_file.exists())
PY

COPY . .

EXPOSE 7860

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
