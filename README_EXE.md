# CameraAppAPI.exe

Guia para generar y usar la API de CameraApp como ejecutable de Windows.

## Idea general

El ejecutable corre FastAPI dentro de la PC del negocio. Esa PC debe estar en la
misma red que el NVR/camaras.

Flujo:

```text
Frontend -> CameraAppAPI.exe en PC del negocio -> NVR/camaras RTSP
```

La configuracion de camara no tiene que vivir en `.env`: el frontend la manda a
`POST /camera-config`.

## Generar el ejecutable con GitHub Actions

Cada push a `main` ejecuta el workflow `Build Windows EXE` en GitHub Actions.
Tambien puedes correrlo manualmente desde la pestaña Actions.

Pasos:

1. Sube tus cambios a GitHub en la rama `main`.
2. Abre `https://github.com/Cdca12/camera-app-api/actions`.
3. Entra al run llamado `Build Windows EXE`.
4. Cuando termine en verde, descarga el artifact `CameraAppAPI-windows`.
5. Descomprime `CameraAppAPI-windows.zip`.
6. Copia la carpeta descomprimida completa a la PC remota.
7. Ejecuta `CameraAppAPI.exe`.

No copies solo `CameraAppAPI.exe`; copia todos los archivos que vienen en el
`.zip`, porque el ejecutable necesita sus librerias internas.

Archivos usados por el build automatico:

- `.github/workflows/build-windows-exe.yml`: ejecuta el build en Windows.
- `run_api.py`: arranca FastAPI dentro del ejecutable.
- `CameraAppAPI.spec`: le dice a PyInstaller que incluir.
- `requirements-build.txt`: instala PyInstaller y dependencias de la API.

No necesitas correr ningun build manual en tu Mac ni en la PC remota.

## Ejecutar en la PC remota

En la PC del negocio, abre la carpeta `CameraAppAPI` y ejecuta:

```bat
CameraAppAPI.exe
```

La ventana mostrara direcciones parecidas a:

```text
Local: http://127.0.0.1:7860
Red local: http://192.168.100.50:7860
Docs: http://127.0.0.1:7860/docs
```

Deja esa ventana abierta mientras uses CameraApp.

## Configurar el frontend

Si el frontend corre dentro de la misma red del negocio, apunta su API base a:

```env
VITE_API_BASE_URL=http://IP_DE_LA_PC_REMOTA:7860
```

Ejemplo:

```env
VITE_API_BASE_URL=http://192.168.100.50:7860
```

Si el frontend esta publicado en Vercel, no podra llamar directo a una IP
privada `192.168.x.x`. En ese caso necesitas exponer la API con HTTPS mediante
Cloudflare Tunnel, Tailscale Funnel, ngrok o una VPN/proxy equivalente.

## Probar

Desde la PC remota:

```text
http://127.0.0.1:7860/health
```

Desde otra maquina en la misma red:

```text
http://IP_DE_LA_PC_REMOTA:7860/health
```

El frontend debe mandar la configuracion:

```json
{
  "host": "192.168.100.89",
  "username": "usuario",
  "password": "password",
  "port": "554",
  "path_template": "/Streaming/Channels/{channel}"
}
```

Luego puede consumir:

```text
GET /camera-frame?channel=101
POST /analyze-camera-frame?channel=101&camera_name=Entrada
```

## Cambiar puerto

Por default usa el puerto `7860`. Para usar otro puerto:

```bat
set PORT=7870
CameraAppAPI.exe
```
