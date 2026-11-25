# Pendientes (actualizado 2026-11-24)

## Hecho
- Entorno: Python 3.11 + `.venv`, ffmpeg 8.0.1 con NVENC, PyTorch cu126 en GPU.
- Transcripción Groq -> faster-whisper local, con caché, división en partes y respaldo por parte.
- Subtítulos .ass estilo shorts (palabra actual en amarillo, nunca en dos líneas).
- Modo OBS: pistas, jump cuts, blur/crop/split, ducking del juego, `--max-duracion` / `--partes`.
- Modo normal con imágenes de IA (Pollinations -> Cloudflare -> SD-Turbo local) y Ken Burns.
- **Estilo animado "escenario de papel"** (plantilla `animado`): título en papel, objetos sticker,
  contador, etiquetas, mascota temporal "Webi", subtítulos en tarjetas. Guion visual con Groq LLM.
- Cortes automáticos: silencios reales, repeticiones, muletillas, arranques en falso.
- Mejora de voz local: DeepFilterNet + ecualización, de-esser, compresor, -14 LUFS.
- `hacer_video.bat` para arrastrar y soltar.

## Pendiente del plan original
- [ ] Fase 2: usar mis clips e imágenes de `entrada/clips/` y `entrada/imagenes/` (por nombre de archivo).
- [ ] Modo normal aceptando una grabación de OBS como `--entrada` (solo su pista de voz + mi material).
- [ ] Fase 3: CLIP multilingüe + PySceneDetect para elegir material por contenido.
- [ ] `entrada/ajustes.txt` (`0:12 -> captura3.png`, `saltar`, `siguiente`, `mantener`).
- [ ] Música de fondo `entrada/musica.mp3` con ducking.
- [ ] `--separar-voz` (Demucs) e `--insertar-material` (b-roll) en modo OBS.

## Esperando de mí (el usuario)
- [ ] Logo (PNG transparente), @usuario, mascota propia y colores de marca para el estilo animado.
- [ ] Clips e imágenes con nombres descriptivos; grabación de OBS con micrófono en pista 2.
- [ ] Rotar la clave de Groq (se pegó en el chat) y ponerla nueva en `.env`.
- [ ] Opcional: claves gratis de Pollinations / Cloudflare (ver README).

## Ideas de mejora anotadas
- Opción para escribir yo el título del video animado en vez de que lo invente el LLM.
- Subir el límite de letras de las etiquetas (salió "REST" por "RESTAURANTES").
- Que lo local vaya primero por defecto en `config.json` si quiero que nada salga del equipo.
