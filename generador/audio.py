"""Lectura de pistas y extracción de audio con ffmpeg/ffprobe."""
import json
import subprocess
from pathlib import Path

from .entorno import ErrorFFmpeg, ejecutar_ffmpeg, ruta_ffprobe


def _ffprobe(argumentos: list) -> dict:
    comando = [ruta_ffprobe(), "-v", "error", "-of", "json", *map(str, argumentos)]
    r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ErrorFFmpeg(f"ffprobe falló: {r.stderr.strip()[-400:]}")
    return json.loads(r.stdout or "{}")


def duracion(ruta: Path | str) -> float:
    datos = _ffprobe(["-show_entries", "format=duration", str(ruta)])
    return float(datos.get("format", {}).get("duration", 0.0))


def pistas_audio(ruta: Path | str) -> list[dict]:
    """Lista de pistas de audio: [{'indice': 1, 'codec': 'aac', 'canales': 2, 'titulo': ...}]"""
    datos = _ffprobe(["-select_streams", "a",
                      "-show_entries", "stream=index,codec_name,channels:stream_tags=title", str(ruta)])
    pistas = []
    for n, s in enumerate(datos.get("streams", []), start=1):
        pistas.append({
            "indice": n,  # 1 = primera pista de audio (como en OBS)
            "codec": s.get("codec_name"),
            "canales": s.get("channels"),
            "titulo": (s.get("tags") or {}).get("title"),
        })
    return pistas


def info_video(ruta: Path | str) -> dict:
    """Ancho, alto, fps y duración del primer stream de video."""
    datos = _ffprobe(["-select_streams", "v:0",
                      "-show_entries", "stream=width,height,avg_frame_rate:format=duration", str(ruta)])
    streams = datos.get("streams") or []
    if not streams:
        raise ErrorFFmpeg(f"{Path(ruta).name} no tiene video")
    s = streams[0]
    num, _, den = (s.get("avg_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {"ancho": int(s["width"]), "alto": int(s["height"]), "fps": round(fps, 3),
            "duracion": float(datos.get("format", {}).get("duration", 0.0))}


def volumen_medio(ruta: Path | str, pista: int, segundos: float = 300) -> float:
    """Volumen medio (dB) de una pista en sus primeros minutos; -91 si está en silencio."""
    from .entorno import ruta_ffmpeg
    comando = [ruta_ffmpeg(), "-hide_banner", "-nostats", "-t", str(segundos), "-i", str(ruta),
               "-map", f"0:a:{pista - 1}", "-af", "volumedetect", "-f", "null", "-"]
    r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for linea in r.stderr.splitlines():
        if "mean_volume:" in linea:
            try:
                return float(linea.split("mean_volume:")[1].split("dB")[0])
            except ValueError:
                break
    return -91.0


def _mapa_pista(pista: int | None) -> list[str]:
    return ["-map", f"0:a:{pista - 1}"] if pista else ["-map", "0:a:0"]


def extraer_wav16k(entrada: Path, salida: Path, pista: int | None = None) -> Path:
    """Audio mono 16 kHz (lo que usa Whisper)."""
    ejecutar_ffmpeg(["-i", entrada, *_mapa_pista(pista), "-vn", "-ac", "1", "-ar", "16000",
                     "-c:a", "pcm_s16le", salida])
    return salida


def extraer_mp3(entrada: Path, salida: Path, inicio: float | None = None,
                dur: float | None = None, kbps: int = 64) -> Path:
    """MP3 mono a baja tasa para subir a la API (opcionalmente un tramo)."""
    args = []
    if inicio is not None:
        args += ["-ss", f"{inicio:.3f}"]
    args += ["-i", entrada]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", f"{kbps}k", salida]
    ejecutar_ffmpeg(args)
    return salida


def recortar(entrada: Path, salida: Path, inicio: float, dur: float) -> Path:
    """Copia un tramo de un WAV (recodificando para que el corte sea exacto)."""
    ejecutar_ffmpeg(["-ss", f"{inicio:.3f}", "-i", entrada, "-t", f"{dur:.3f}",
                     "-c:a", "pcm_s16le", salida])
    return salida
