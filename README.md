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

## Deploy con frontend en Vercel

Configura el frontend para llamar a la URL publica del backend, no a una ruta relativa de Vercel.
Por ejemplo:

```env
VITE_API_BASE_URL=https://cdca12-camera-app-api.hf.space
```

El backend acepta por default solo el dominio del frontend:

```env
CORS_ORIGINS=https://camera-app-front.vercel.app
```
