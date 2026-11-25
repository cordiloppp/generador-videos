"""Cadena de respaldo entre proveedores y registro de cuál se usó.

Regla principal: un servicio externo nunca detiene el video. Si falla, se pasa
al siguiente candidato de la lista (el último siempre es local).
"""
import time

from ..consola import info


class ProveedorNoDisponible(Exception):
    """Un proveedor no puede atender esta petición.

    marcar_caido=True: el problema es general (sin red, sin clave, sin cuota) y no
    vale la pena volver a intentarlo en esta ejecución.
    """

    def __init__(self, proveedor: str, motivo: str, marcar_caido: bool = False):
        super().__init__(f"{proveedor}: {motivo}")
        self.proveedor = proveedor
        self.motivo = motivo
        self.marcar_caido = marcar_caido


class RegistroProveedores:
    """Guarda qué proveedor se usó (o falló) en cada paso, para la consola y plan.json."""

    def __init__(self):
        self.eventos: list[dict] = []
        self.caidos: dict[str, str] = {}

    def esta_caido(self, proveedor: str) -> bool:
        return proveedor in self.caidos

    def marcar_caido(self, proveedor: str, motivo: str) -> None:
        self.caidos.setdefault(proveedor, motivo)

    def anotar(self, paso: str, proveedor: str, estado: str, motivo: str | None = None,
               detalle: str | None = None) -> None:
        evento = {"paso": paso, "proveedor": proveedor, "estado": estado,
                  "hora": time.strftime("%H:%M:%S")}
        if motivo:
            evento["motivo"] = motivo
        if detalle:
            evento["detalle"] = detalle
        self.eventos.append(evento)
        if estado == "usado":
            texto = f"[{paso}] proveedor: {proveedor}" + (f" ({detalle})" if detalle else "")
        elif estado == "fallo":
            texto = f"[{paso}] {proveedor} no disponible: {motivo} -> respaldo"
        else:  # omitido
            texto = f"[{paso}] {proveedor} omitido: {motivo}"
        info(texto)


def ejecutar_con_respaldo(registro: RegistroProveedores, paso: str, candidatos: list):
    """Prueba cada (nombre, función) en orden y devuelve (resultado, nombre_usado).

    Solo lanza error si fallan todos, incluido el respaldo local.
    """
    for nombre, funcion in candidatos:
        if registro.esta_caido(nombre):
            registro.anotar(paso, nombre, "omitido", registro.caidos[nombre])
            continue
        try:
            resultado = funcion()
        except ProveedorNoDisponible as e:
            registro.anotar(paso, nombre, "fallo", e.motivo)
            if e.marcar_caido:
                registro.marcar_caido(nombre, e.motivo)
            continue
        except Exception as e:  # cualquier fallo inesperado de un proveedor
            registro.anotar(paso, nombre, "fallo", f"{type(e).__name__}: {e}")
            continue
        registro.anotar(paso, nombre, "usado")
        return resultado, nombre
    raise RuntimeError(f"Ningún proveedor pudo completar el paso '{paso}'.")
