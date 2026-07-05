FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip
RUN python -m pip install --no-cache-dir -r requirements.txt

# Fix para el Haar Cascade de OpenCV, porque en tu Mac ya vimos que podía faltar.
RUN python - <<'PY'
import cv2
from pathlib import Path
import urllib.request

cascade_dir = Path(cv2.data.haarcascades)
cascade_dir.mkdir(parents=True, exist_ok=True)

cascade_file = cascade_dir / "haarcascade_frontalface_default.xml"

if not cascade_file.exists():
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml",
        cascade_file,
    )

print("Cascade file exists:", cascade_file.exists())
PY

COPY . .

EXPOSE 7860

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]