"""Prompts de imagen con un LLM gratuito de Groq: traduce al inglés y describe una escena concreta."""
import json

from .. import red
from ..config import clave
from ..limites import Contadores
from .base import ProveedorNoDisponible

NOMBRE = "groq"
URL_CHAT = "https://api.groq.com/openai/v1/chat/completions"
URL_MODELOS = "https://api.groq.com/openai/v1/models"

_modelos_disponibles: list[str] | None = None

# En inglés: estos modelos siguen mejor las instrucciones así (la narración puede venir en español)
_INSTRUCCIONES = """You are the art director of short vertical videos (TikTok/Reels/Shorts).
For each numbered fragment of the narration (usually in Spanish), write ONE English prompt for an image generator.

HARD RULE - NO SCREENS: never include laptops, phones, tablets, monitors, websites, apps, documents,
signs, menus or any visible text. Image generators render them as gibberish letters.
When the narration talks about something digital (a website, an app, an online invitation, a booking),
show the REAL-WORLD scene it represents: the people, the place, the event or the result.
Example: "my website for a beach wedding" -> "a joyful couple exchanging vows on a white-sand beach at sunset".

Other rules:
- A concrete visual scene that illustrates what is said: subject, action, setting, light, vertical framing.
- 15 to 45 words per prompt. No famous real people. No logos or brands.
- Keep visual coherence across fragments (same place and characters when it is the same story).
- Overall style: {estilo}

Reply ONLY with JSON: {{"prompts": ["...", "..."]}} with exactly {n} items, in the same order as the fragments."""


def _cabeceras() -> dict:
    k = clave("GROQ_API_KEY")
    if not k:
        raise ProveedorNoDisponible(NOMBRE, "falta GROQ_API_KEY en .env", marcar_caido=True)
    return {"Authorization": f"Bearer {k}"}


def _elegir_modelo(cfg: dict) -> str:
    """Primer modelo de la lista de preferencia que Groq ofrezca hoy."""
    global _modelos_disponibles
    if _modelos_disponibles is None:
        r = red.peticion(NOMBRE, "GET", URL_MODELOS, timeout=cfg["timeouts"]["verificacion_s"], headers=_cabeceras())
        if r.status_code in (401, 403):
            raise ProveedorNoDisponible(NOMBRE, f"clave rechazada (HTTP {r.status_code})", marcar_caido=True)
        if r.status_code != 200:
            raise ProveedorNoDisponible(NOMBRE, f"no pude listar modelos (HTTP {r.status_code})", marcar_caido=True)
        _modelos_disponibles = [m["id"] for m in r.json().get("data", [])]
    for modelo in cfg["groq"]["modelos_llm"]:
        if modelo in _modelos_disponibles:
            return modelo
    raise ProveedorNoDisponible(NOMBRE, "ninguno de los modelos_llm de config.json está disponible", marcar_caido=True)


def pedir_json(sistema: str, usuario: str, cfg: dict, contadores: Contadores, temperatura: float = 0.7) -> dict:
    """Llamada genérica al LLM de Groq que devuelve un objeto JSON."""
    red.comprobar_red_permitida(NOMBRE)
    cabeceras = _cabeceras()
    modelo = _elegir_modelo(cfg)
    contadores.esperar_turno(NOMBRE, "groq_llm_peticiones", cfg["groq"]["llm_peticiones_por_minuto"], max_espera_s=65)
    cuerpo = {
        "model": modelo,
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        "temperature": temperatura,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 8000,
    }
    if modelo.startswith("openai/gpt-oss"):
        cuerpo["reasoning_effort"] = "low"
    t = cfg["timeouts"]
    r = red.peticion(NOMBRE, "POST", URL_CHAT, timeout=(t["conexion_s"], 90), headers=cabeceras, json=cuerpo)
    contadores.registrar("groq_llm_peticiones")
    if r.status_code == 429:
        raise ProveedorNoDisponible(NOMBRE, "límite del plan gratis (429)", marcar_caido=True)
    if r.status_code in (401, 403):
        raise ProveedorNoDisponible(NOMBRE, f"clave rechazada (HTTP {r.status_code})", marcar_caido=True)
    if r.status_code != 200:
        raise ProveedorNoDisponible(NOMBRE, f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise ProveedorNoDisponible(NOMBRE, f"respuesta no válida ({type(e).__name__})")


def generar_prompts(textos: list[str], contexto: str, estilo: str, cfg: dict, contadores: Contadores) -> list[str]:
    """Pide los prompts; si el número no cuadra (pasa a veces), reintenta una vez."""
    try:
        return _pedir(textos, contexto, estilo, cfg, contadores)
    except ProveedorNoDisponible as e:
        if e.marcar_caido:
            raise
        return _pedir(textos, contexto, estilo, cfg, contadores)


def _pedir(textos: list[str], contexto: str, estilo: str, cfg: dict, contadores: Contadores) -> list[str]:
    red.comprobar_red_permitida(NOMBRE)
    cabeceras = _cabeceras()
    modelo = _elegir_modelo(cfg)
    contadores.esperar_turno(NOMBRE, "groq_llm_peticiones", cfg["groq"]["llm_peticiones_por_minuto"], max_espera_s=65)

    usuario = (f"Full script (context):\n{contexto}\n\nFragments ({len(textos)}):\n"
               + "\n".join(f"{i}. {t}" for i, t in enumerate(textos, start=1))
               + f"\n\nReturn exactly {len(textos)} prompts.")
    cuerpo = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": _INSTRUCCIONES.format(estilo=estilo, n=len(textos))},
            {"role": "user", "content": usuario},
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 8000,
    }
    if modelo.startswith("openai/gpt-oss"):
        cuerpo["reasoning_effort"] = "low"

    t = cfg["timeouts"]
    r = red.peticion(NOMBRE, "POST", URL_CHAT, timeout=(t["conexion_s"], 90), headers=cabeceras, json=cuerpo)
    contadores.registrar("groq_llm_peticiones")
    if r.status_code == 429:
        raise ProveedorNoDisponible(NOMBRE, "límite del plan gratis (429)", marcar_caido=True)
    if r.status_code in (401, 403):
        raise ProveedorNoDisponible(NOMBRE, f"clave rechazada (HTTP {r.status_code})", marcar_caido=True)
    if r.status_code != 200:
        raise ProveedorNoDisponible(NOMBRE, f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        contenido = r.json()["choices"][0]["message"]["content"]
        prompts = [str(p).strip() for p in json.loads(contenido)["prompts"]]
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise ProveedorNoDisponible(NOMBRE, f"respuesta no válida ({type(e).__name__})")
    if len(prompts) != len(textos) or not all(prompts):
        raise ProveedorNoDisponible(NOMBRE, f"devolvió {len(prompts)} prompts en vez de {len(textos)}")
    return prompts
