"""Imágenes de IA de relleno: Pollinations -> Cloudflare -> SD-Turbo local -> desenfoque/degradado.

Cada imagen se guarda en cache/imagenes_ia/ con su prompt; el mismo prompt no se vuelve a pedir.
"""
import io
import time
import zlib
from pathlib import Path

from . import cache
from .consola import info, titulo
from .proveedores import imagen_cloudflare, imagen_local, imagen_pollinations
from .proveedores.base import ProveedorNoDisponible, RegistroProveedores, ejecutar_con_respaldo


def semilla_de(prompt: str) -> int:
    return zlib.crc32(prompt.encode("utf-8")) & 0x7FFFFFFF


def _validar(datos: bytes, proveedor: str):
    from PIL import Image
    try:
        imagen = Image.open(io.BytesIO(datos))
        imagen.load()
    except Exception:
        raise ProveedorNoDisponible(proveedor, "lo recibido no es una imagen válida")
    if min(imagen.size) < 256:
        raise ProveedorNoDisponible(proveedor, f"imagen demasiado pequeña {imagen.size}")
    return imagen.convert("RGB")


def _imagen_de_respaldo(anterior: Path | None, destino: Path, ancho: int, alto: int) -> Path:
    """Si no hay ningún proveedor: la imagen anterior muy desenfocada, o un degradado oscuro."""
    from PIL import Image, ImageFilter, ImageOps
    if anterior and anterior.exists():
        img = ImageOps.fit(Image.open(anterior).convert("RGB"), (ancho // 4, alto // 4)).filter(ImageFilter.GaussianBlur(8))
        img.resize((ancho, alto), Image.BICUBIC).save(destino)
    else:
        degradado = Image.linear_gradient("L").resize((ancho, alto))
        Image.merge("RGB", (degradado.point(lambda v: 20 + v // 6), degradado.point(lambda v: 25 + v // 5),
                            degradado.point(lambda v: 45 + v // 3))).save(destino)
    return destino


def obtener_imagenes(prompts: list[str], cfg: dict, registro: RegistroProveedores, contadores,
                     tmp: Path) -> list[dict]:
    titulo("Imágenes de IA")
    carpeta = cache.carpeta("imagenes_ia")
    resultados = []
    anterior = None
    try:
        for i, prompt in enumerate(prompts, start=1):
            paso = f"imagen {i}/{len(prompts)}"
            semilla = semilla_de(prompt)
            clave = cache.clave(prompt, semilla, 1)
            ruta, ruta_meta = carpeta / f"{clave}.png", carpeta / f"{clave}.json"
            meta = cache.leer_json(ruta_meta)
            if ruta.exists() and meta:
                registro.anotar(paso, "caché", "usado", detalle=f"generada antes con {meta['proveedor']}")
                resultados.append({"archivo": ruta, "proveedor": meta["proveedor"], "prompt": prompt, "cache": True})
                anterior = ruta
                continue

            candidatos = {
                "pollinations": lambda: _validar(imagen_pollinations.generar(prompt, semilla, cfg, contadores),
                                                 "pollinations"),
                "cloudflare": lambda: _validar(imagen_cloudflare.generar(prompt, semilla, cfg, contadores),
                                               "cloudflare"),
                "sd_turbo": lambda: _validar(imagen_local.generar(prompt, semilla, cfg), "sd_turbo"),
            }
            orden = [(n, candidatos[n]) for n in cfg["proveedores"]["imagen"] if n in candidatos]
            info(f"{paso}: {prompt[:90]}...")
            try:
                imagen, proveedor = ejecutar_con_respaldo(registro, paso, orden)
                imagen.save(ruta)
                cache.escribir_json(ruta_meta, {"prompt": prompt, "semilla": semilla, "proveedor": proveedor,
                                                "fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "tamano": imagen.size})
                resultados.append({"archivo": ruta, "proveedor": proveedor, "prompt": prompt, "cache": False})
            except RuntimeError:
                # Ningún proveedor: no se guarda en caché para reintentar la próxima vez
                ruta_r = _imagen_de_respaldo(anterior, tmp / f"respaldo_{i}.png", 1080, 1920)
                tipo = "desenfoque de la anterior" if anterior else "degradado"
                registro.anotar(paso, "respaldo", "usado", detalle=tipo)
                resultados.append({"archivo": ruta_r, "proveedor": f"respaldo ({tipo})", "prompt": prompt,
                                   "cache": False})
                ruta = ruta_r
            anterior = ruta
    finally:
        imagen_local.liberar()
    return resultados
