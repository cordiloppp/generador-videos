"""Mejora de voz 100 % local: reducción de ruido con DeepFilterNet + procesado tipo podcast con ffmpeg.

1. DeepFilterNet 3 (red neuronal, MIT): quita ruido de fondo, eco leve, ventiladores, tráfico...
   Respaldo si no está disponible: el filtro afftdn de ffmpeg.
2. ffmpeg: filtro paso alto (rumble), ecualización (menos "caja", más presencia y aire),
   de-esser (suaviza las "s"), compresor (volumen más parejo) y limitador.
El volumen final (-14 LUFS) se ajusta después en el render.
"""
import sys
import types
import wave
from pathlib import Path

import numpy as np

from . import cache
from .consola import aviso, info, titulo
from .entorno import ejecutar_ffmpeg

_VERSION = 1
SR = 48000

_modelo = None


def _cargar_deepfilternet():
    """Carga DeepFilterNet. Sustituye un módulo que ya no existe en torchaudio >= 2.9
    (DeepFilterNet solo lo importa para su lector de archivos, que aquí no se usa)."""
    global _modelo
    if _modelo is not None:
        return _modelo
    if "torchaudio.backend.common" not in sys.modules:
        comun = types.ModuleType("torchaudio.backend.common")
        comun.AudioMetaData = type("AudioMetaData", (), {})
        sys.modules.setdefault("torchaudio.backend", types.ModuleType("torchaudio.backend"))
        sys.modules["torchaudio.backend.common"] = comun
    import logging
    import os
    logging.getLogger("DF").setLevel(logging.ERROR)
    # DeepFilterNet llama a 'git' para saber su versión e imprime "fatal: not a git repository": se silencia
    nulo, stderr_original = os.open(os.devnull, os.O_WRONLY), os.dup(2)
    os.dup2(nulo, 2)
    try:
        from df.enhance import enhance, init_df
        try:
            from loguru import logger
            logger.remove()
        except Exception:
            pass
        modelo, estado, _ = init_df(log_level="ERROR", log_file=None)
    finally:
        os.dup2(stderr_original, 2)
        os.close(nulo)
        os.close(stderr_original)
    _modelo = (modelo, estado, enhance)
    return _modelo


def _leer_wav(ruta: Path) -> np.ndarray:
    with wave.open(str(ruta)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def _escribir_wav(ruta: Path, audio: np.ndarray) -> None:
    datos = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(datos.tobytes())


def _reducir_ruido(entrada: Path, salida: Path, limite_db) -> str:
    try:
        import torch
        modelo, estado, enhance = _cargar_deepfilternet()
        audio = torch.from_numpy(_leer_wav(entrada))[None]
        limpio = enhance(modelo, estado, audio, atten_lim_db=limite_db)
        _escribir_wav(salida, limpio.squeeze(0).numpy())
        return "deepfilternet"
    except Exception as e:
        aviso(f"DeepFilterNet no disponible ({type(e).__name__}: {str(e)[:100]}); uso afftdn de ffmpeg")
        ejecutar_ffmpeg(["-i", entrada, "-af", "afftdn=nr=12:nf=-50:tn=1", "-c:a", "pcm_s16le", salida])
        return "afftdn"


def filtro_podcast(cfg: dict) -> str:
    filtros = ["highpass=f=80"]
    if cfg.get("ecualizar", True):
        filtros += ["equalizer=f=220:t=q:w=1.0:g=-2.5",   # menos "caja"
                    "equalizer=f=3500:t=q:w=1.2:g=2.5",   # presencia / claridad
                    "equalizer=f=10000:t=q:w=0.8:g=1.5"]  # aire
    if cfg.get("de_esser", True):
        filtros.append("deesser=i=0.35")
    if cfg.get("compresor", True):
        filtros.append("acompressor=threshold=0.1:ratio=3:attack=10:release=150:makeup=2")
    filtros.append("alimiter=limit=0.95")
    return ",".join(filtros)


def mejorar_voz(fuente: Path, cfg: dict, pista: int | None = None) -> tuple[Path, dict]:
    """Devuelve (wav mejorado 48 kHz mono, info). Se guarda en caché: no se repite si el audio no cambia."""
    titulo("Mejora de voz")
    clave = cache.clave(cache.huella_archivo(fuente), pista, cfg, _VERSION)
    destino = cache.carpeta("voz_mejorada") / f"{clave}.wav"
    meta_ruta = destino.with_suffix(".json")
    meta = cache.leer_json(meta_ruta)
    if destino.exists() and meta:
        info(f"desde caché ({meta['ruido']} + procesado tipo podcast)")
        return destino, meta

    tmp = cache.carpeta("tmp")
    base = tmp / f"voz_{clave}.wav"
    limpia = tmp / f"voz_{clave}_limpia.wav"
    mapa = ["-map", f"0:a:{pista - 1}"] if pista else ["-map", "0:a:0"]
    ejecutar_ffmpeg(["-i", fuente, *mapa, "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", base])
    if cfg.get("reduccion_ruido", True):
        ruido = _reducir_ruido(base, limpia, cfg.get("limite_reduccion_db"))
    else:
        ruido, limpia = "sin reducción de ruido", base
    ejecutar_ffmpeg(["-i", limpia, "-af", filtro_podcast(cfg), "-ar", str(SR), "-c:a", "pcm_s16le", destino])
    for f in (base, limpia):
        f.unlink(missing_ok=True)
    meta = {"ruido": ruido, "filtros": filtro_podcast(cfg)}
    cache.escribir_json(meta_ruta, meta)
    info(f"ruido: {ruido}; ecualización, de-esser y compresor aplicados")
    return destino, meta
