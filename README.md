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

## Ejecutable Windows

Para correr la API en una PC remota del negocio como `CameraAppAPI.exe`, revisa
[`README_EXE.md`](README_EXE.md).

## Endpoints

- `GET /health`
- `POST /camera-config`
- `POST /analyze-frame`
- `GET /camera-frame`
- `POST /analyze-camera-frame`
- `POST /watch-camera-frame`
- `POST /watch-uploaded-frame`

## Cámara de vigilancia

El frontend puede configurar el NVR/cámara en runtime:

```http
POST /camera-config
Content-Type: application/json
```

```json
{
  "host": "192.168.1.64",
  "username": "usuario",
  "password": "password",
  "port": "554",
  "path_template": "/Streaming/Channels/{channel}"
}
```

La contraseña se usa solo para construir la URL RTSP dentro del backend. No se
regresa en la respuesta del endpoint.

El frontend puede seguir usando:

```http
GET /camera-frame?channel=<canal>&t=<timestamp>
POST /analyze-camera-frame?channel=<canal>&camera_name=<nombre>
```

La API resuelve la fuente de la cámara con esta prioridad:

1. `CAMERA_SOURCE_CHANNEL_<canal>`
2. Configuración runtime recibida en `POST /camera-config`
3. `CAMERA_SOURCE_TEMPLATE`
4. `CAMERA_SOURCE`

También puedes configurar la fuente de video directamente con
`CAMERA_SOURCE`. Puede ser una URL RTSP/HTTP de la cámara o DVR/NVR:

```env
CAMERA_SOURCE=rtsp://usuario:password@192.168.1.64:554/Streaming/Channels/101
```

Para usar canales de un NVR desde el frontend, puedes configurar una plantilla:

```env
CAMERA_SOURCE_TEMPLATE=rtsp://usuario:password@192.168.1.64:554/Streaming/Channels/{channel}
```

También puedes configurar fuentes por canal:

```env
CAMERA_SOURCE_CHANNEL_502=rtsp://usuario:password@192.168.1.64:554/Streaming/Channels/502
CAMERA_SOURCE_CHANNEL_302=rtsp://usuario:password@192.168.1.64:554/Streaming/Channels/302
```

También puedes inicializar la configuración runtime desde variables separadas:

```env
CAMERA_HOST=192.168.1.64
CAMERA_USERNAME=usuario
CAMERA_PASSWORD=password
CAMERA_RTSP_PORT=554
CAMERA_PATH_TEMPLATE=/Streaming/Channels/{channel}
```

Opcionalmente puedes ajustar el tiempo de espera:

```env
CAMERA_TIMEOUT_MS=5000
```

`GET /camera-frame` devuelve un JPEG del frame actual. También acepta
`?channel=<canal>`. `POST /analyze-camera-frame` captura un frame y lo analiza
con DeepFace; también acepta `?channel=<canal>&camera_name=<nombre>`.

## Monitoreo ligero de caras nuevas

Para revisar la cámara con menor costo, usa:

```http
POST /watch-camera-frame?channel=<canal>&camera_name=<nombre>
```

Para revisar frames enviados desde la cámara del dispositivo, usa:

```http
POST /watch-uploaded-frame
Content-Type: multipart/form-data
```

```text
file=<imagen jpg/png>
```

Este endpoint captura un frame, detecta caras con OpenCV y mantiene un cache en
memoria por cámara/canal o por cámara del dispositivo. Si no hay caras nuevas
responde:

```json
{
  "success": true,
  "has_new_faces": false,
  "faces": []
}
```

Si detecta una cara nueva, entonces corre DeepFace para edad/género y responde:

```json
{
  "success": true,
  "has_new_faces": true,
  "faces": []
}
```

Variables opcionales:

```env
FACE_CACHE_TTL_SECONDS=300
FACE_MATCH_THRESHOLD=0.18
FACE_DETECT_WIDTH=640
```

`FACE_CACHE_TTL_SECONDS` define cuánto tiempo una cara vista queda en cache.
`FACE_MATCH_THRESHOLD` ajusta qué tan parecidas deben ser dos caras para tratarse
como la misma persona. `FACE_DETECT_WIDTH` reduce el frame antes de detectar
caras para que el monitoreo sea más ligero.

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
