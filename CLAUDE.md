# Generador de videos verticales

Generador automático de shorts 1080x1920 (TikTok/Reels/Shorts) en Python. Todo el código, los
comentarios y los mensajes van **en español**. Ver `README.md` (uso) y `PENDIENTES.md` (qué falta).

## Ejecutar
- Python del proyecto: `.\.venv\Scripts\python.exe` (Python 3.11; no hay Python global).
- `hacer_video.py --entrada entrada/x.m4a --plantilla animado` (modo normal, estilo animado)
- `hacer_video.py --modo obs --entrada entrada/obs/x.mkv --plantilla juego`
- Opciones: `--local` (sin servicios), `--forzar` (ignora caché de transcripción/guion/prompts),
  `--sin-cortes`, `--sin-mejora`, `--sin-imagenes`, `--max-duracion`, `--partes`.
- `verificar_entorno.py` comprueba ffmpeg/NVENC/CUDA/claves. `hacer_video.bat`: arrastrar y soltar.

## Estructura (`generador/`)
- `transcripcion.py` (Groq -> faster-whisper local, partes con traslape, caché), `frases.py`
- `proveedores/`: `base.py` (cadena de respaldo + `RegistroProveedores`), Groq (whisper y LLM),
  traductor local, Pollinations, Cloudflare, SD-Turbo. Regla: un servicio externo NUNCA detiene el video.
- `cortes.py` (silencios medidos con silencedetect + repeticiones/muletillas, `reubicar_frases`,
  `cortar_audio` exacto a la muestra), `mejora_voz.py` (DeepFilterNet + cadena ffmpeg tipo podcast)
- `animacion/`: estilo "escenario de papel" (`guion_visual.py` LLM -> reglas, `dibujo.py`, `mascota.py`,
  `recursos.py` stickers Fluent Emoji, `motor.py` compositor OpenCV + tubería a NVENC)
- `obs.py` (pistas, jump cuts, blur/crop/split, partes), `visual.py` + `relleno.py` + `prompts.py`
  (imágenes de IA con Ken Burns), `subtitulos.py` (.ass), `render.py`, `plan.py`
- Config: `config.json` (proveedores, límites, mejora de voz), `plantillas/*.json` (estilo por plantilla),
  claves en `.env` (no se sube; ver `.env.example`). Recursos locales en `recursos/` (emoji MIT, fuentes OFL).

## Cosas no obvias del equipo (GTX 1070 Pascal, Windows 10)
- **ffmpeg**: usar `herramientas/ffmpeg/` (8.0.1). ffmpeg 9.x pide NVENC API 13.1 / driver 610+, que no existe para Pascal.
- **PyTorch**: solo wheels **cu126** (cu128+ quitaron sm_61). Modelos en fp32; Whisper en int8.
- **skia-python** es ~100x más lento mezclando transparencias en esta CPU: dibujar piezas una vez con
  skia y componer cada cuadro con OpenCV (`motor.poner/mezclar`). No volver a dibujar por cuadro con skia.
- **aselect** de ffmpeg no recorta audio de forma fiable: el audio se corta en Python (`cortes.cortar_audio`).
- **Groq** estira palabras sobre las pausas y a veces da inicios desordenados: por eso los silencios se
  miden en el audio y las palabras no se reordenan por tiempo (`_sanear_tiempos`).
- **DeepFilterNet 0.5.6** se instaló con `--no-deps` y necesita un módulo sustituto de
  `torchaudio.backend.common` (ver `mejora_voz._cargar_deepfilternet`).
- Pollinations anónimo: 1 imagen/45 s por IP, máx. 576x1024 (402 FREE_LIMIT).

## Cómo probar cambios
- Generar con el audio de prueba y revisar cuadros: extraer con
  `herramientas\ffmpeg\bin\ffmpeg.exe -i salida\X.mp4 -vf "select='eq(n\,90)',scale=360:-1" -frames:v 1 c.png`.
- Comprobar que audio y video duran lo mismo (`ffprobe -show_entries stream=codec_type,duration`).
- Tras tocar modo normal, probar también `--modo obs` (y viceversa).
