"""Peticiones HTTP con timeouts cortos, modo --local y red simulada caída.

SIMULAR_SIN_RED=1 hace fallar todas las conexiones (sirve para probar los respaldos).
"""
import os

import requests

from .proveedores.base import ProveedorNoDisponible

_modo_local = False
_verificados: dict[str, str | None] = {}  # url -> None si OK, o el motivo del fallo


def activar_modo_local() -> None:
    global _modo_local
    _modo_local = True


def modo_local() -> bool:
    return _modo_local


def red_simulada_caida() -> bool:
    return os.environ.get("SIMULAR_SIN_RED", "").strip() == "1"


def comprobar_red_permitida(proveedor: str) -> None:
    if _modo_local:
        raise ProveedorNoDisponible(proveedor, "modo --local", marcar_caido=True)
    if red_simulada_caida():
        raise ProveedorNoDisponible(proveedor, "sin internet (simulado con SIMULAR_SIN_RED=1)",
                                    marcar_caido=True)


def peticion(proveedor: str, metodo: str, url: str, timeout, **kwargs) -> requests.Response:
    """requests.request que convierte los fallos de red en ProveedorNoDisponible."""
    comprobar_red_permitida(proveedor)
    try:
        return requests.request(metodo, url, timeout=timeout, **kwargs)
    except requests.exceptions.Timeout:
        raise ProveedorNoDisponible(proveedor, "timeout", marcar_caido=True)
    except requests.exceptions.ConnectionError:
        raise ProveedorNoDisponible(proveedor, "sin conexión", marcar_caido=True)
    except requests.exceptions.RequestException as e:
        raise ProveedorNoDisponible(proveedor, f"error de red: {type(e).__name__}", marcar_caido=True)


def verificar_servicio(proveedor: str, url: str, timeout: float, headers: dict | None = None) -> None:
    """Chequeo rápido (una vez por ejecución) antes de usar un servicio."""
    if url in _verificados:
        if _verificados[url]:
            raise ProveedorNoDisponible(proveedor, _verificados[url], marcar_caido=True)
        return
    try:
        r = peticion(proveedor, "GET", url, timeout=timeout, headers=headers or {})
    except ProveedorNoDisponible as e:
        _verificados[url] = e.motivo
        raise
    motivo = None
    if r.status_code in (401, 403):
        motivo = f"clave rechazada (HTTP {r.status_code})"
    elif r.status_code >= 500:
        motivo = f"servicio con errores (HTTP {r.status_code})"
    _verificados[url] = motivo
    if motivo:
        raise ProveedorNoDisponible(proveedor, motivo, marcar_caido=True)
