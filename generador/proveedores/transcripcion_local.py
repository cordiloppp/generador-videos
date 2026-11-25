"""Transcripción local con faster-whisper (int8 en GPU, con respaldo en CPU)."""
import gc
import os
from pathlib import Path

from ..consola import aviso, fin_progreso, info, progreso
from ..entorno import preparar_dlls_cuda

NOMBRE = "local"

_modelo = None
_dispositivo = None


def _ruta_modelo(nombre: str) -> str:
    """Busca el modelo en disco primero (funciona sin internet); si no está, lo descarga."""
    from faster_whisper.utils import download_model
    try:
        return download_model(nombre, local_files_only=True)
    except Exception:
        info(f"descargando el modelo '{nombre}' (solo la primera vez, ~1.5 GB)...")
        return download_model(nombre)


def _cargar(cfg: dict, dispositivo: str):
    global _modelo, _dispositivo
    if _modelo is not None and _dispositivo == dispositivo:
        return _modelo
    liberar()
    preparar_dlls_cuda()
    from faster_whisper import WhisperModel
    w = cfg["whisper_local"]
    tipo = w["compute_type_gpu"] if dispositivo == "cuda" else w["compute_type_cpu"]
    info(f"cargando faster-whisper '{w['modelo']}' en {dispositivo.upper()} ({tipo})...")
    _modelo = WhisperModel(_ruta_modelo(w["modelo"]), device=dispositivo, compute_type=tipo,
                           cpu_threads=os.cpu_count() or 4)
    _dispositivo = dispositivo
    return _modelo


def _transcribir_con(modelo, ruta: Path, cfg: dict) -> dict:
    w = cfg["whisper_local"]
    segmentos, datos = modelo.transcribe(
        str(ruta), language=w["idioma"], beam_size=w["beam_size"], word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    palabras, textos = [], []
    total = max(datos.duration, 0.01)
    for seg in segmentos:  # el generador es perezoso: aquí es donde trabaja la GPU
        textos.append(seg.text.strip())
        for p in seg.words or []:
            if p.word.strip():
                palabras.append({"texto": p.word.strip(), "inicio": float(p.start), "fin": float(p.end)})
        progreso("whisper local", seg.end / total)
    fin_progreso()
    return {"palabras": palabras, "texto": " ".join(textos)}


def transcribir(ruta: Path, cfg: dict) -> dict:
    """Intenta en GPU; si algo falla (DLL, memoria...), repite en CPU."""
    try:
        return _transcribir_con(_cargar(cfg, "cuda"), ruta, cfg)
    except Exception as e:
        fin_progreso()
        aviso(f"whisper en GPU falló ({type(e).__name__}: {str(e)[:120]}); sigo en CPU")
        return _transcribir_con(_cargar(cfg, "cpu"), ruta, cfg)


def liberar() -> None:
    """Libera el modelo (y la VRAM) para dejar sitio a CLIP o SD-Turbo."""
    global _modelo, _dispositivo
    if _modelo is None:
        return
    _modelo, _dispositivo = None, None
    gc.collect()
