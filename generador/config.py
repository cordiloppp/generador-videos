"""Rutas del proyecto, config.json y claves de .env."""
import copy
import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "entrada"
SALIDA = RAIZ / "salida"
CACHE = RAIZ / "cache"
PLANTILLAS = RAIZ / "plantillas"
HERRAMIENTAS = RAIZ / "herramientas"

# Valores por defecto: config.json solo necesita incluir lo que quieras cambiar.
CONFIG_POR_DEFECTO = {
    "proveedores": {
        "transcripcion": ["groq", "local"],
        "prompt": ["groq", "traductor_local"],
        "imagen": ["pollinations", "cloudflare", "sd_turbo"],
    },
    "pollinations": {"ancho": 1080, "alto": 1920, "modelo": None, "ancho_anonimo": 576, "alto_anonimo": 1024,
                     "intervalo_anonimo_s": 45, "max_espera_s": 50, "timeout_s": 60},
    "cloudflare": {"modelo": "@cf/black-forest-labs/flux-1-schnell", "pasos": 4,
                   "neurons_por_imagen": 60, "limite_diario": 9000},
    "sd_turbo": {"modelo": "stabilityai/sd-turbo", "pasos": 2, "ancho": 512, "alto": 912},
    "timeouts": {
        "verificacion_s": 5,      # chequeo rápido antes de usar un servicio
        "conexion_s": 10,         # tiempo máximo para conectar
        "subida_base_s": 60,      # lectura: base + segundos por MB subido
        "subida_por_mb_s": 6,
    },
    "groq": {
        "modelo_transcripcion": "whisper-large-v3",
        "idioma": "es",
        "max_mb_por_parte": 24,           # el plan gratis acepta hasta 25 MB
        "traslape_s": 2.0,                # traslape entre partes al dividir
        "kbps": 64,
        "peticiones_por_minuto": 20,
        "segundos_audio_por_hora": 7200,
        "segundos_audio_por_dia": 28800,
        "reintentos_429": 2,
        "max_espera_429_s": 60,
        "modelos_llm": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
        "llm_peticiones_por_minuto": 30,
    },
    "whisper_local": {
        "modelo": "medium",
        "idioma": "es",
        "beam_size": 5,
        "compute_type_gpu": "int8",
        "compute_type_cpu": "int8",
    },
    "mejora_voz": {
        "activar": True,
        "reduccion_ruido": True,         # DeepFilterNet (respaldo: afftdn de ffmpeg)
        "limite_reduccion_db": None,     # p. ej. 20 para una limpieza más suave; None = máxima
        "ecualizar": True,
        "de_esser": True,
        "compresor": True,
    },
    "frases": {
        "min_s": 2.0,
        "max_s": 8.0,
        "pausa_s": 0.45,          # una pausa de al menos esto puede cerrar frase
        "pausa_fuerte_s": 0.9,    # una pausa así cierra frase aunque sea corta
    },
    "video": {
        "ancho": 1080,
        "alto": 1920,
        "fps": 30,
        "nvenc_cq": 21,
        "x264_crf": 20,
        "audio_kbps": 192,
        "normalizar_volumen": True,
        "lufs": -14,
    },
}


def _fusionar(base: dict, extra: dict) -> dict:
    """Mezcla recursiva: los valores de 'extra' sustituyen a los de 'base'."""
    resultado = copy.deepcopy(base)
    for clave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = _fusionar(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


def cargar_config() -> dict:
    ruta = RAIZ / "config.json"
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            return _fusionar(CONFIG_POR_DEFECTO, json.load(f))
    return copy.deepcopy(CONFIG_POR_DEFECTO)


def cargar_env() -> None:
    """Carga .env si existe (sin pisar variables ya definidas en el sistema)."""
    ruta = RAIZ / ".env"
    if not ruta.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(ruta, override=False)
    except ImportError:
        # Lector mínimo por si falta python-dotenv
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def clave(nombre: str) -> str | None:
    """Devuelve una clave de .env o None si está vacía o no existe."""
    valor = os.environ.get(nombre, "").strip()
    return valor or None


def crear_carpetas() -> None:
    for carpeta in (ENTRADA / "clips", ENTRADA / "imagenes", ENTRADA / "obs", SALIDA, CACHE, PLANTILLAS):
        carpeta.mkdir(parents=True, exist_ok=True)
