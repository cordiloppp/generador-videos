"""Transcripción con Groq (whisper-large-v3, plan gratis, endpoint compatible con OpenAI)."""
import time
from pathlib import Path

from .. import red
from ..config import clave
from ..consola import info
from ..limites import Contadores
from ..texto import transferir_puntuacion
from .base import ProveedorNoDisponible

NOMBRE = "groq"
URL_TRANSCRIPCION = "https://api.groq.com/openai/v1/audio/transcriptions"
URL_MODELOS = "https://api.groq.com/openai/v1/models"


def _cabeceras() -> dict:
    k = clave("GROQ_API_KEY")
    if not k:
        raise ProveedorNoDisponible(NOMBRE, "falta GROQ_API_KEY en .env", marcar_caido=True)
    return {"Authorization": f"Bearer {k}"}


def comprobar(cfg: dict) -> None:
    """Chequeo rápido: hay red, hay clave y el servicio responde (timeout corto)."""
    red.comprobar_red_permitida(NOMBRE)
    cabeceras = _cabeceras()
    red.verificar_servicio(NOMBRE, URL_MODELOS, timeout=cfg["timeouts"]["verificacion_s"], headers=cabeceras)


def _espera_429(respuesta) -> float:
    try:
        return float(respuesta.headers.get("retry-after", "10"))
    except ValueError:
        return 10.0


def transcribir_parte(ruta_mp3: Path, segundos_audio: float, cfg: dict, contadores: Contadores) -> dict:
    """Sube un MP3 (<25 MB) y devuelve {'palabras': [...], 'texto': str} con tiempos relativos."""
    g, t = cfg["groq"], cfg["timeouts"]
    cabeceras = _cabeceras()
    comprobar(cfg)

    tam_mb = ruta_mp3.stat().st_size / 1e6
    if tam_mb > 25:
        raise ProveedorNoDisponible(NOMBRE, f"la parte pesa {tam_mb:.1f} MB (máximo 25)")

    # Cuotas de audio del plan gratis
    if contadores.total_en("groq_audio_s", 3600) + segundos_audio > g["segundos_audio_por_hora"]:
        raise ProveedorNoDisponible(NOMBRE, "cuota de audio por hora agotada", marcar_caido=True)
    if contadores.total_en("groq_audio_s", 86400) + segundos_audio > g["segundos_audio_por_dia"]:
        raise ProveedorNoDisponible(NOMBRE, "cuota de audio diaria agotada", marcar_caido=True)

    datos = [
        ("model", g["modelo_transcripcion"]),
        ("language", g["idioma"]),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("timestamp_granularities[]", "segment"),
        ("temperature", "0"),
    ]
    timeout = (t["conexion_s"], t["subida_base_s"] + t["subida_por_mb_s"] * tam_mb)

    for intento in range(g["reintentos_429"] + 1):
        contadores.esperar_turno(NOMBRE, "groq_peticiones", g["peticiones_por_minuto"], max_espera_s=65)
        with open(ruta_mp3, "rb") as f:
            r = red.peticion(NOMBRE, "POST", URL_TRANSCRIPCION, timeout=timeout, headers=cabeceras,
                             files={"file": (ruta_mp3.name, f, "audio/mpeg")}, data=datos)
        contadores.registrar("groq_peticiones")

        if r.status_code == 200:
            contadores.registrar("groq_audio_s", segundos_audio)
            return _interpretar(r.json())
        if r.status_code == 429:
            espera = _espera_429(r)
            if intento < g["reintentos_429"] and espera <= g["max_espera_429_s"]:
                info(f"[groq] 429 (límite), reintento {intento + 1}/{g['reintentos_429']} en {espera:.0f} s")
                time.sleep(espera)
                continue
            raise ProveedorNoDisponible(NOMBRE, "límite del plan gratis (429)", marcar_caido=True)
        if r.status_code in (401, 403):
            raise ProveedorNoDisponible(NOMBRE, f"clave rechazada (HTTP {r.status_code})", marcar_caido=True)
        raise ProveedorNoDisponible(NOMBRE, f"HTTP {r.status_code}: {r.text[:200]}")
    raise ProveedorNoDisponible(NOMBRE, "sin respuesta válida")


def _interpretar(respuesta: dict) -> dict:
    palabras = [
        {"texto": w["word"].strip(), "inicio": float(w["start"]), "fin": float(w["end"])}
        for w in respuesta.get("words") or []
        if w.get("word", "").strip()
    ]
    if not palabras and (respuesta.get("text") or "").strip():
        raise ProveedorNoDisponible(NOMBRE, "la respuesta no trae timestamps por palabra")
    # Groq da las palabras sin puntuación: se recupera del texto de los segmentos
    texto = " ".join(s.get("text", "").strip() for s in respuesta.get("segments") or []) or respuesta.get("text", "")
    transferir_puntuacion(palabras, texto)
    return {"palabras": palabras, "texto": texto.strip()}
