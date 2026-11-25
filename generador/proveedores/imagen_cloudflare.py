"""Imágenes con Cloudflare Workers AI (flux-1-schnell, plan gratis de 10,000 neurons/día).

flux-1-schnell genera imágenes cuadradas; luego se adaptan a vertical con fondo desenfocado.
"""
import base64

from .. import red
from ..config import clave
from ..limites import Contadores
from .base import ProveedorNoDisponible

NOMBRE = "cloudflare"


def generar(prompt: str, semilla: int, cfg: dict, contadores: Contadores) -> bytes:
    c, t = cfg["cloudflare"], cfg["timeouts"]
    red.comprobar_red_permitida(NOMBRE)
    cuenta, token = clave("CF_ACCOUNT_ID"), clave("CF_API_TOKEN")
    if not cuenta or not token:
        raise ProveedorNoDisponible(NOMBRE, "faltan CF_ACCOUNT_ID / CF_API_TOKEN en .env", marcar_caido=True)

    usados = contadores.uso_diario("cloudflare_neurons")
    if usados + c["neurons_por_imagen"] > c["limite_diario"]:
        raise ProveedorNoDisponible(NOMBRE, f"cuota diaria casi agotada ({usados:.0f} neurons hoy)", marcar_caido=True)

    cabeceras = {"Authorization": f"Bearer {token}"}
    red.verificar_servicio(NOMBRE, "https://api.cloudflare.com/client/v4/user/tokens/verify",
                           timeout=t["verificacion_s"], headers=cabeceras)
    url = f"https://api.cloudflare.com/client/v4/accounts/{cuenta}/ai/run/{c['modelo']}"
    r = red.peticion(NOMBRE, "POST", url, timeout=(t["conexion_s"], 60), headers=cabeceras,
                     json={"prompt": prompt[:2048], "steps": c["pasos"]})
    if r.status_code in (401, 403):
        raise ProveedorNoDisponible(NOMBRE, f"token rechazado (HTTP {r.status_code})", marcar_caido=True)
    if r.status_code == 429:
        raise ProveedorNoDisponible(NOMBRE, "límite o cuota (429)", marcar_caido=True)
    if r.status_code != 200:
        raise ProveedorNoDisponible(NOMBRE, f"HTTP {r.status_code}: {r.text[:200]}")
    contadores.sumar_diario("cloudflare_neurons", c["neurons_por_imagen"])

    if r.headers.get("content-type", "").startswith("image/"):
        return r.content
    try:
        return base64.b64decode(r.json()["result"]["image"])
    except (KeyError, ValueError, TypeError):
        raise ProveedorNoDisponible(NOMBRE, "respuesta sin imagen")
