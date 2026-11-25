"""Fuentes, biblioteca de objetos (Fluent Emoji, MIT) y stickers con borde blanco."""
import json
import math
import re
from functools import lru_cache
from pathlib import Path

import skia

from ..cache import carpeta, clave
from ..config import RAIZ
from ..texto import normalizar

RECURSOS = RAIZ / "recursos"
FUENTES = {
    "titulo": RECURSOS / "fuentes" / "ArchivoBlack-Regular.ttf",
    "numero": RECURSOS / "fuentes" / "SpaceMono-Bold.ttf",
    "texto": RECURSOS / "fuentes" / "ArchivoBlack-Regular.ttf",
}
EMOJIS = RECURSOS / "fluentui-emoji" / "assets"

# Grupos que no sirven como "objeto" de escena
_GRUPOS_EXCLUIDOS = {"Flags"}


@lru_cache(maxsize=None)
def tipografia(nombre: str) -> skia.Typeface:
    ruta = FUENTES[nombre]
    if not ruta.exists():
        raise FileNotFoundError(f"Falta la fuente {ruta}. Revisa recursos/fuentes/ (ver README).")
    return skia.Typeface.MakeFromFile(str(ruta))


def fuente(nombre: str, tamano: float) -> skia.Font:
    f = skia.Font(tipografia(nombre), tamano)
    f.setEdging(skia.Font.Edging.kAntiAlias)
    f.setSubpixel(True)
    return f


def ancho_texto(texto: str, nombre: str, tamano: float) -> float:
    return fuente(nombre, tamano).measureText(texto)


def tamano_que_cabe(texto: str, nombre: str, ancho_max: float, tam_max: float, tam_min: float) -> float:
    """El tamaño de fuente más grande (entre tam_min y tam_max) con el que el texto cabe en ancho_max."""
    ancho = ancho_texto(texto, nombre, tam_max)
    if ancho <= ancho_max:
        return tam_max
    return max(tam_min, tam_max * ancho_max / ancho)


# --------------------------------------------------------------------------- objetos
class IndiceObjetos:
    """Busca el SVG de Fluent Emoji que mejor encaja con unas palabras clave en inglés."""

    def __init__(self):
        self.objetos = []
        if not EMOJIS.exists():
            return
        for meta in EMOJIS.glob("*/metadata.json"):
            try:
                datos = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if datos.get("group") in _GRUPOS_EXCLUIDOS:
                continue
            svgs = sorted(meta.parent.glob("Flat/*.svg")) or sorted(meta.parent.glob("Default/Flat/*.svg"))
            if not svgs:
                continue
            nombre = normalizar(datos.get("cldr", meta.parent.name))
            claves = {normalizar(k) for k in datos.get("keywords", [])}
            self.objetos.append({"nombre": nombre, "palabras": set(nombre.split()), "claves": claves,
                                 "grupo": datos.get("group", ""), "svg": svgs[0]})

    def buscar(self, terminos: list[str]) -> Path | None:
        """Prueba cada término en orden; devuelve el primer objeto con buena coincidencia."""
        for termino in terminos:
            t = normalizar(termino)
            if not t:
                continue
            palabras = set(t.split())
            mejor, mejor_puntos = None, 0.0
            for o in self.objetos:
                if o["nombre"] == t:
                    puntos = 100
                elif t in o["claves"]:
                    puntos = 60
                else:
                    comunes = len(palabras & o["palabras"])
                    puntos = 0
                    if comunes:
                        puntos = 30 * comunes / max(len(o["palabras"]), len(palabras))
                    if palabras & o["claves"]:
                        puntos = max(puntos, 20)
                # Los objetos ilustran mejor que las caras y las personas
                if o["grupo"] in ("Objects", "Travel & Places", "Food & Drink", "Animals & Nature", "Activities"):
                    puntos *= 1.15
                if puntos > mejor_puntos:
                    mejor, mejor_puntos = o, puntos
            if mejor and mejor_puntos >= 20:
                return mejor["svg"]
        return None


@lru_cache(maxsize=1)
def indice_objetos() -> IndiceObjetos:
    return IndiceObjetos()


def _svg_a_imagen(svg: Path, lado: int) -> skia.Image:
    dom = skia.SVGDOM.MakeFromStream(skia.Stream.MakeFromFile(str(svg)))
    tam = dom.containerSize()
    escala = lado / max(tam.width(), tam.height(), 1)
    superficie = skia.Surface(lado, lado)
    lienzo = superficie.getCanvas()
    lienzo.clear(skia.ColorTRANSPARENT)
    lienzo.translate((lado - tam.width() * escala) / 2, (lado - tam.height() * escala) / 2)
    lienzo.scale(escala, escala)
    dom.render(lienzo)
    return superficie.makeImageSnapshot()


def sticker(svg: Path, lado: int, borde: int = 14):
    """Objeto con borde blanco y sombra suave (aspecto de papel recortado).

    Devuelve un array BGRA premultiplicado; se guarda en cache/stickers/ como .npy (carga instantánea).
    """
    import numpy as np
    ruta = carpeta("stickers") / f"{clave(str(svg.relative_to(RECURSOS)), lado, borde, 3)}.npy"
    if ruta.exists():
        return np.load(ruta)
    img = _svg_a_imagen(svg, lado)
    total = lado + 8 * borde  # margen para el borde blanco y la sombra
    origen = 4 * borde
    muestreo = skia.SamplingOptions(skia.FilterMode.kLinear)

    # 1) Recorte: la silueta en blanco desplazada en círculo (mucho más rápido que un filtro de dilatación)
    capa = skia.Surface(total, total)
    lienzo = capa.getCanvas()
    lienzo.clear(skia.ColorTRANSPARENT)
    blanco = skia.Paint(ColorFilter=skia.ColorFilters.Blend(skia.ColorWHITE, skia.BlendMode.kSrcIn))
    for radio in (borde, borde * 0.55):
        for k in range(24):
            a = 2 * math.pi * k / 24
            lienzo.drawImage(img, origen + radio * math.cos(a), origen + radio * math.sin(a), muestreo, blanco)
    lienzo.drawImage(img, origen, origen, muestreo)
    recorte = capa.makeImageSnapshot()

    # 2) Sombra una sola vez debajo del recorte
    superficie = skia.Surface(total, total)
    lienzo = superficie.getCanvas()
    lienzo.clear(skia.ColorTRANSPARENT)
    sombra = skia.Paint(ColorFilter=skia.ColorFilters.Blend(skia.Color(0, 0, 0, 80), skia.BlendMode.kSrcIn),
                        ImageFilter=skia.ImageFilters.Blur(7, 7))
    lienzo.drawImage(recorte, 5, 12, muestreo, sombra)
    lienzo.drawImage(recorte, 0, 0, muestreo)
    capa = superficie.makeImageSnapshot().toarray(colorType=skia.kBGRA_8888_ColorType,
                                                  alphaType=skia.kPremul_AlphaType)
    np.save(ruta, capa)
    return capa


def limpiar_etiqueta(texto: str, max_chars: int) -> str:
    """Mayúsculas y recorte por palabras completas (nunca 'CUENTA REGRESI')."""
    texto = re.sub(r"\s+", " ", str(texto)).strip().upper()
    if len(texto) > max_chars:
        palabras, resultado = texto.split(" "), ""
        for p in palabras:
            if len((resultado + " " + p).strip()) > max_chars:
                break
            resultado = (resultado + " " + p).strip()
        texto = resultado or palabras[0]  # una sola palabra larga se deja entera (la fuente se ajusta)
    # Signos de apertura/cierre equilibrados tras recortar: "¡HOLA" -> "¡HOLA!"
    for abre, cierra in (("¡", "!"), ("¿", "?")):
        if texto.startswith(abre) and not texto.endswith(cierra):
            texto = texto.rstrip(".,;:") + cierra
        elif texto.endswith(cierra) and abre not in texto:
            texto = abre + texto
    return texto
