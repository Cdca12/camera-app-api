---
title: CameraApp API
emoji: 📷
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# CameraApp API

FastAPI + DeepFace API para estimar edad y género desde un frame enviado por multipart/form-data.

## Endpoints

- `GET /health`
- `POST /analyze-frame`