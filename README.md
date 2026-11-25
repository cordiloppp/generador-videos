# Generador de videos verticales (TikTok / Shorts / Reels)

Arma videos verticales 1080x1920 automáticamente a partir de tu voz. Usa servicios
gratuitos cuando hay clave e internet, y si no, hace todo en local. **Nunca se detiene por
un servicio externo**: si uno falla, pasa al siguiente y lo anota en `plan.json`.

> Estado: **estilo animado** (plantilla `animado`: escenario de papel dibujado por código),
> **modo normal con imágenes de IA** (solo tu audio -> una imagen por frase con zoom suave)
> y **modo OBS básico** (jump cuts, vertical, ducking, subtítulos, división en shorts).
> Pendiente: tus clips e imágenes, CLIP, ajustes.txt, música, `--separar-voz` e `--insertar-material`.

## Instalación (Windows, GTX 10xx / Pascal)

```powershell
winget install Python.Python.3.11
py -3.11 -m venv .venv            # o: %LOCALAPPDATA%\Programs\Python\Python311\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe verificar_entorno.py
```

- **ffmpeg**: usa el build *full* 8.0.x de gyan.dev en `herramientas/ffmpeg/bin/`. Las
  versiones 9.x piden el driver 610+, que no existe para Pascal, y NVENC no funcionaría.
  Si NVENC falla, el script usa `libx264` automáticamente.
- **PyTorch**: `requirements.txt` instala la build **cu126** (CUDA 12.8+ ya no soporta Pascal).

## Uso

```powershell
# Modo normal: entrada/voz.mp3 -> salida/AAAA-MM-DD_HHMMSS_proyecto.mp4 (+ .plan.json y .ass)
.\.venv\Scripts\python.exe hacer_video.py --plantilla proyecto

# Cualquier audio tuyo (mp3, wav, m4a, notas de voz .ogg/.opus)
.\.venv\Scripts\python.exe hacer_video.py --entrada entrada/mi_audio.m4a --plantilla pelicula

# Solo subtítulos sobre fondo negro (rápido, para revisar el texto)
.\.venv\Scripts\python.exe hacer_video.py --plantilla proyecto --sin-imagenes

# Todo en local, sin intentar ningún servicio
.\.venv\Scripts\python.exe hacer_video.py --plantilla proyecto --local

# Volver a transcribir aunque esté en caché (p. ej. después de poner la clave de Groq)
.\.venv\Scripts\python.exe hacer_video.py --plantilla proyecto --forzar

# Modo OBS: solo la grabación (sin voz.mp3, clips ni imágenes)
.\.venv\Scripts\python.exe hacer_video.py --modo obs --entrada entrada/obs/partida1.mkv --plantilla juego

# Sin --entrada usa la grabación más reciente de entrada/obs/
.\.venv\Scripts\python.exe hacer_video.py --modo obs --plantilla juego

# Grabación larga: 3 shorts de máximo 60 s con los tramos donde más hablas
.\.venv\Scripts\python.exe hacer_video.py --modo obs --plantilla juego --max-duracion 60 --partes 3
```

## Cortes automáticos y mejora de voz (modo normal y OBS)

**Cortes** (bloque `cortes` de la plantilla; `--sin-cortes` para desactivarlos):
- Silencios de más de `silencio_max_s` (0.45 s), medidos en el audio, dejando `margen_s` (0.12 s)
  antes y después de hablar. (Los timestamps de Whisper/Groq a veces "estiran" una palabra sobre una
  pausa; por eso el silencio se mide en el sonido, no solo en la transcripción.)
- Repeticiones ("está hecho está hecho" -> "está hecho"), muletillas ("eh", "mmm") y arranques
  en falso ("pa- para"). Se respetan dobles intencionales como "muy muy" o "no no".
- Las frases se dividen sobre la grabación original y luego se reubican, así no se mezclan ideas.

**Mejora de voz** (bloque `mejora_voz` de `config.json`; `--sin-mejora` para desactivarla), 100 % local:
1. **DeepFilterNet 3**: red neuronal que quita ruido de fondo (ventilador, calle, zumbidos).
   Respaldo: filtro `afftdn` de ffmpeg. `limite_reduccion_db: 20` hace una limpieza más suave.
2. **Procesado tipo podcast** con ffmpeg: paso alto (80 Hz), ecualización (menos "caja" en 220 Hz,
   más claridad en 3.5 kHz y aire en 10 kHz), de-esser (suaviza las "s"), compresor y limitador.
3. Volumen final normalizado a -14 LUFS (estándar de TikTok/Reels/Shorts).

En modo OBS solo se aplica si el micrófono va en su propia pista (con todo mezclado afectaría al juego).

Consejos que mejoran más que cualquier filtro: micrófono a un palmo de la boca, habitación con
cosas blandas (cortinas, cama, ropa) y grabar en WAV o M4A de buena calidad.

## Estilo animado ("escenario de papel")

```powershell
.\.venv\Scripts\python.exe hacer_video.py --entrada entrada/mi_audio.m4a --plantilla animado
```

Sin imágenes realistas: todo se dibuja por código y se anima al ritmo de tu voz.
- **Título gancho** en papel con cinta adhesiva (línea 2 sobre una barra de color).
- **Un objeto por escena** tipo sticker (biblioteca Fluent Emoji de Microsoft, 1,500+ objetos, MIT),
  que entra con rebote, flota y sale al cambiar de escena.
- **Contador** animado cuando dices un número, y **etiquetas** de colores con palabras clave.
- **Mascota** temporal ("Webi", una ventanita de navegador) que salta en cada escena, parpadea,
  mira el objeto y mueve la boca cuando hablas.
- **Subtítulos** como tarjetitas de papel que aparecen palabra por palabra sobre la mesa.

Un LLM gratis de Groq escribe el guion visual (título, objeto, contador, etiquetas y reacción de la
mascota por escena); sin Groq se usan reglas locales. En `plantillas/animado.json` puedes fijar la
`paleta` (verde, morado, rojo, azul, mostaza, turquesa, rosa o `auto`) y tu `marca` (`@tu_cuenta`).

Recursos en `recursos/`: `fluentui-emoji/` (MIT) y `fuentes/` (Archivo Black y Space Mono, OFL).
`fluentui-emoji/` no está en el repositorio; descárgalo una vez con:

```powershell
git clone --depth 1 https://github.com/microsoft/fluentui-emoji.git recursos/fluentui-emoji
```

## Modo normal: imágenes de IA

Con solo tu audio, el script:
1. Transcribe y divide en frases (las largas se parten según `max_fragmento_s` de la plantilla).
2. Pide a un LLM gratis de Groq un prompt en inglés por fragmento, con el guion completo como
   contexto (respaldo: traductor local es→en; último recurso: el texto tal cual).
3. Genera cada imagen: Pollinations → Cloudflare → **SD-Turbo en tu GPU** → desenfoque de la
   anterior. Se guardan en `cache/imagenes_ia/` con su prompt: regenerar el video no las vuelve a pedir.
4. Las pasa a vertical (fondo desenfocado si no son 9:16), con zoom suave (Ken Burns), y quema subtítulos.

En `plan.json`, `segmentos_visuales` dice qué prompt, imagen y proveedor se usó en cada tramo.
El estilo de las imágenes se cambia en `"visual" → "estilo_imagen"` de cada plantilla.

## Modo OBS

1. **Pistas**: en OBS (Configuración → Salida → Grabación) marca las pistas 1 y 2, y en
   *Configuración de audio avanzada* deja el micrófono solo en la pista 2 y el escritorio/juego
   en la 1. El script detecta las pistas; si la de voz parece vacía, prueba con otra y avisa.
   Con una sola pista mezclada, transcribe esa directamente.
2. **Jump cuts**: quita las pausas de más de `silencio_max_s` (0.5 s en `juego`), dejando
   `margen_s` (0.15 s) alrededor de cada palabra para no cortarlas.
3. **Audio**: tu voz normalizada + el juego al 25 % (`volumen_juego`), que baja más cuando hablas.
4. **Vertical** (`formato` en la plantilla, bloque `obs`):
   - `blur`: video completo al centro con fondo desenfocado (`zoom_blur` > 1 lo agranda).
   - `crop`: recorte del centro (`crop_x` lo mueve a la izquierda/derecha).
   - `split`: juego arriba y facecam abajo. Define la facecam en fracciones del cuadro:
     `"facecam": [x, y, ancho, alto]`; p. ej. una facecam de 480x324 en la esquina inferior
     derecha de un video 1920x1080 es `[0.75, 0.70, 0.25, 0.30]`.

## Claves gratis (.env)

Copia `.env.example` como `.env` y rellena solo las que tengas.

- **Groq** (transcripción con whisper-large-v3): entra en https://console.groq.com, crea una
  cuenta (sin tarjeta) y en *API Keys* genera una clave. Ponla en `GROQ_API_KEY`.
  El plan gratis permite 20 peticiones/min y archivos de hasta 25 MB; el script lo respeta,
  divide audios largos y lleva la cuenta de los segundos de audio por hora y por día.
- **Pollinations** (imágenes): sin token funciona, pero solo 1 imagen cada 45 s y a 576x1024.
  Con una clave gratuita de https://enter.pollinations.ai (empieza por `sk_`) las imágenes salen
  a 1080x1920 y sin esperas. Ponla en `POLLINATIONS_TOKEN`.
- **Cloudflare Workers AI** (imágenes, flux-1-schnell): crea una cuenta gratis en
  https://dash.cloudflare.com, copia tu *Account ID* (barra lateral de Workers AI) a `CF_ACCOUNT_ID`
  y crea un token en *My Profile → API Tokens* con la plantilla **Workers AI** → `CF_API_TOKEN`.
  El plan gratis da 10,000 neurons al día (~150 imágenes); el script lleva la cuenta y para antes.

Sin claves todo funciona igual con los respaldos locales (faster-whisper en tu GPU).
Con Groq, tu audio se sube a sus servidores; con `--local` nada sale de tu equipo.

## Caché

`cache/` guarda las transcripciones (y más adelante embeddings e imágenes generadas). Si el
audio no cambia, no se vuelve a transcribir. Borra `cache/` o usa `--forzar` para rehacerlo.

## Pruebas de respaldo

| Variable | Efecto |
|---|---|
| `SIMULAR_SIN_RED=1` | todas las conexiones fallan como si no hubiera internet |
| `SIMULAR_FALLO_GROQ_PARTE=2` | la parte 2 de un audio dividido falla en Groq y se hace en local |
| `GROQ_MAX_MB_PRUEBA=0.12` | fuerza partes muy pequeñas para probar la división |

```powershell
$env:SIMULAR_SIN_RED='1'; .\.venv\Scripts\python.exe hacer_video.py --forzar; Remove-Item Env:SIMULAR_SIN_RED
```

## Configuración

- `config.json`: orden de proveedores, timeouts, límites del plan gratis, división en frases, calidad de video.
- `plantillas/*.json`: estilo de subtítulos (y en fases siguientes: ritmo, formato, pista de voz, facecam...).
