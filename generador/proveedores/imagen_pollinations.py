"""Imágenes con Pollinations (gratis).

- Con POLLINATIONS_TOKEN en .env: gen.pollinations.ai con 'Authorization: Bearer', a 1080x1920.
- Sin token: endpoint anónimo. Límite actual: 1 imagen cada 45 s por IP y máximo 576x1024.
  Si responde 402 FREE_LIMIT, espera lo que indique y reintenta una vez.
"""
import re
import time
from urllib.parse import quote

from .. import red
from ..config import clave
from ..consola import info
from ..limites import Contadores
from .base import ProveedorNoDisponible

NOMBRE = "pollinations"
URL_CON_TOKEN = "https://gen.pollinations.ai/image/"
URL_ANONIMA = "https://image.pollinations.ai/prompt/"


def generar(prompt: str, semilla: int, cfg: dict, contadores: Contadores) -> bytes:
    p, t = cfg["pollinations"], cfg["timeouts"]
    red.comprobar_red_permitida(NOMBRE)
    token = clave("POLLINATIONS_TOKEN")
    cabeceras = {}
    if token:
        base = URL_CON_TOKEN
        parametros = {"width": p["ancho"], "height": p["alto"], "seed": semilla}
        cabeceras["Authorization"] = f"Bearer {token}"
        if p.get("modelo"):
            parametros["model"] = p["modelo"]
    else:
        base = URL_ANONIMA
        parametros = {"width": p["ancho_anonimo"], "height": p["alto_anonimo"], "seed": semilla, "nologo": "true"}

    red.verificar_servicio(NOMBRE, base.rsplit("/", 2)[0] + "/", timeout=t["verificacion_s"])
    for intento in range(2):
        if not token:
            contadores.espaciar(NOMBRE, "pollinations_anonimo", p["intervalo_anonimo_s"], p["max_espera_s"])
        r = red.peticion(NOMBRE, "GET", base + quote(prompt, safe=""), timeout=(t["conexion_s"], p["timeout_s"]),
                         params=parametros, headers=cabeceras)
        if not token:
            contadores.registrar("pollinations_anonimo")
        if r.status_code == 402 and "FREE_LIMIT" in r.text and intento == 0:
            m = re.search(r"Retry after (\d+)", r.text)
            espera = int(m.group(1)) + 1 if m else p["intervalo_anonimo_s"]
            if espera <= p["max_espera_s"]:
                info(f"[{NOMBRE}] límite gratis: espero {espera} s y reintento")
                time.sleep(espera)
                continue
        break

    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and len(r.content) > 5000:
        return r.content
    if r.status_code in (401, 403):
        raise ProveedorNoDisponible(NOMBRE, f"token rechazado (HTTP {r.status_code})", marcar_caido=True)
    if r.status_code == 402:
        if "FREE_LIMIT" in r.text:
            raise ProveedorNoDisponible(NOMBRE, "límite gratis por IP (402 FREE_LIMIT)")
        raise ProveedorNoDisponible(NOMBRE, "sin saldo (HTTP 402)", marcar_caido=True)
    if r.status_code == 429:
        raise ProveedorNoDisponible(NOMBRE, "límite de peticiones (429)")
    raise ProveedorNoDisponible(NOMBRE, f"HTTP {r.status_code} ({r.headers.get('content-type', '?')})")
