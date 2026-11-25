"""Contadores de uso de los planes gratuitos (persisten en cache/contadores.json)."""
import time

from .cache import escribir_json, leer_json
from .config import CACHE
from .consola import info
from .proveedores.base import ProveedorNoDisponible

_RUTA = CACHE / "contadores.json"


class Contadores:
    def __init__(self):
        self.datos = leer_json(_RUTA, {}) or {}

    def _guardar(self) -> None:
        escribir_json(_RUTA, self.datos)

    def _lista(self, clave: str, ventana_s: float) -> list:
        """Eventos [marca_tiempo, cantidad] dentro de la ventana (y limpia los viejos)."""
        ahora = time.time()
        lista = [e for e in self.datos.get(clave, []) if ahora - e[0] < ventana_s]
        self.datos[clave] = lista
        return lista

    def total_en(self, clave: str, ventana_s: float) -> float:
        return sum(e[1] for e in self._lista(clave, ventana_s))

    def registrar(self, clave: str, cantidad: float = 1.0) -> None:
        # Se guarda un día de historia como máximo
        self._lista(clave, 86400).append([time.time(), cantidad])
        self._guardar()

    def esperar_turno(self, proveedor: str, clave: str, max_por_minuto: int, max_espera_s: float) -> None:
        """Respeta N peticiones por minuto; espera si hace falta (o se rinde si es demasiado)."""
        while True:
            eventos = self._lista(clave, 60)
            if len(eventos) < max_por_minuto:
                return
            espera = 60 - (time.time() - eventos[0][0]) + 0.5
            if espera > max_espera_s:
                raise ProveedorNoDisponible(proveedor, "límite de peticiones por minuto")
            info(f"[{proveedor}] límite de {max_por_minuto}/min alcanzado, espero {espera:.0f} s")
            time.sleep(espera)

    def uso_diario(self, clave: str) -> float:
        """Uso acumulado del día UTC actual (las cuotas diarias de Cloudflare se reinician a las 00:00 UTC)."""
        hoy = time.strftime("%Y-%m-%d", time.gmtime())
        registro = self.datos.get(f"diario_{clave}", {})
        return registro.get("uso", 0.0) if registro.get("fecha") == hoy else 0.0

    def sumar_diario(self, clave: str, cantidad: float) -> None:
        hoy = time.strftime("%Y-%m-%d", time.gmtime())
        self.datos[f"diario_{clave}"] = {"fecha": hoy, "uso": self.uso_diario(clave) + cantidad}
        self._guardar()

    def espaciar(self, proveedor: str, clave: str, intervalo_s: float, max_espera_s: float) -> None:
        """Deja al menos 'intervalo_s' entre peticiones (p. ej. Pollinations anónimo: 15 s)."""
        eventos = self._lista(clave, 86400)
        if not eventos:
            return
        espera = intervalo_s - (time.time() - eventos[-1][0])
        if espera <= 0:
            return
        if espera > max_espera_s:
            raise ProveedorNoDisponible(proveedor, f"hay que esperar {espera:.0f} s entre peticiones")
        info(f"[{proveedor}] espero {espera:.0f} s entre peticiones")
        time.sleep(espera)
