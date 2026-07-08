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
- `GET /camera-frame`
- `POST /analyze-camera-frame`

## Cámara de vigilancia

Configura la fuente de video con `CAMERA_SOURCE`. Puede ser una URL RTSP/HTTP
de la cámara o DVR/NVR:

```env
CAMERA_SOURCE=rtsp://usuario:password@192.168.1.64:554/Streaming/Channels/101
```

Opcionalmente puedes ajustar el tiempo de espera:

```env
CAMERA_TIMEOUT_MS=5000
```

`GET /camera-frame` devuelve un JPEG del frame actual. `POST
/analyze-camera-frame` captura un frame desde `CAMERA_SOURCE` y lo analiza con
DeepFace.

Para desarrollo local puedes guardar `CAMERA_SOURCE` en un archivo `.env`.

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
