"""Piezas del estilo "escenario de papel": se dibujan una vez como imágenes y luego se animan."""
import math
import random

import numpy as np
import skia

from .recursos import fuente, tamano_que_cabe

ANCHO, ALTO = 1080, 1920
Y_MESA = 1290          # borde superior de la mesa
CENTRO_ESCENA = (540, 850)

TINTA = skia.Color(36, 28, 21)
PAPEL = skia.Color(244, 235, 221)


def color(hex_rgb: str, alfa: int = 255) -> int:
    h = hex_rgb.lstrip("#")
    return skia.Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alfa)


def mezclar(c1: int, c2: int, t: float) -> int:
    return skia.Color(*(int(a + (b - a) * t) for a, b in zip(
        (skia.ColorGetR(c1), skia.ColorGetG(c1), skia.ColorGetB(c1)),
        (skia.ColorGetR(c2), skia.ColorGetG(c2), skia.ColorGetB(c2)))))


PALETAS = {
    "verde":    {"fondo": "#2C7466", "acento": "#FFD447"},
    "morado":   {"fondo": "#5A3D8A", "acento": "#FFB4C8"},
    "rojo":     {"fondo": "#A63D40", "acento": "#FFD447"},
    "azul":     {"fondo": "#2C4F8C", "acento": "#FFB347"},
    "mostaza":  {"fondo": "#B8862B", "acento": "#FF7A6B"},
    "turquesa": {"fondo": "#1F7F86", "acento": "#FFD447"},
    "rosa":     {"fondo": "#B4506F", "acento": "#FFE07A"},
}
COLORES_ETIQUETA = ["#FFD447", "#FF8FA3", "#8FE3C3", "#8FC1FF", "#FFB066", "#C9A7FF"]


def _ruido(alfa: float, frecuencia: float = 0.9, modo=skia.BlendMode.kOverlay, semilla: int = 3) -> skia.Paint:
    return skia.Paint(Shader=skia.PerlinNoiseShader.MakeFractalNoise(frecuencia, frecuencia, 3, semilla),
                      BlendMode=modo, Alphaf=alfa)


def contorno_papel(ancho: float, alto: float, semilla: int, irregular: float = 3.5, paso: float = 26) -> skia.Path:
    """Rectángulo con bordes ligeramente irregulares, como papel cortado a mano."""
    rnd = random.Random(semilla)
    esquinas = [(0, 0), (ancho, 0), (ancho, alto), (0, alto)]
    camino = skia.Path()
    primero = True
    for (x0, y0), (x1, y1) in zip(esquinas, esquinas[1:] + esquinas[:1]):
        largo = math.hypot(x1 - x0, y1 - y0)
        n = max(2, int(largo / paso))
        nx, ny = -(y1 - y0) / largo, (x1 - x0) / largo
        for i in range(n):
            t = i / n
            j = rnd.uniform(-irregular, irregular) if i else 0
            x, y = x0 + (x1 - x0) * t + nx * j, y0 + (y1 - y0) * t + ny * j
            if primero:
                camino.moveTo(x, y)
                primero = False
            else:
                camino.lineTo(x, y)
    camino.close()
    return camino


def _lienzo(ancho: int, alto: int):
    superficie = skia.Surface(int(ancho), int(alto))
    lienzo = superficie.getCanvas()
    lienzo.clear(skia.ColorTRANSPARENT)
    return superficie, lienzo


def _papel(lienzo, x, y, ancho, alto, color_papel, semilla, sombra=True, textura=0.22):
    camino = contorno_papel(ancho, alto, semilla)
    lienzo.save()
    lienzo.translate(x, y)
    if sombra:
        lienzo.save()
        lienzo.translate(4, 10)
        lienzo.drawPath(camino, skia.Paint(Color=skia.Color(0, 0, 0, 90), AntiAlias=True,
                                           MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 7)))
        lienzo.restore()
    lienzo.drawPath(camino, skia.Paint(Color=color_papel, AntiAlias=True))
    if textura:
        lienzo.save()
        lienzo.clipPath(camino, doAntiAlias=True)
        lienzo.drawRect(skia.Rect(0, 0, ancho, alto), _ruido(textura, 0.6, skia.BlendMode.kMultiply, semilla))
        lienzo.restore()
    lienzo.restore()


def _cinta(lienzo, cx, cy, angulo, ancho=150, alto=46):
    lienzo.save()
    lienzo.translate(cx, cy)
    lienzo.rotate(angulo)
    camino = contorno_papel(ancho, alto, int(cx + cy), irregular=2.5, paso=12)
    lienzo.translate(-ancho / 2, -alto / 2)
    lienzo.drawPath(camino, skia.Paint(Color=skia.Color(232, 214, 160, 205), AntiAlias=True))
    lienzo.restore()


def _texto(lienzo, texto, cx, base_y, nombre_fuente, tamano, color_texto=TINTA):
    f = fuente(nombre_fuente, tamano)
    lienzo.drawString(texto, cx - f.measureText(texto) / 2, base_y, f, skia.Paint(Color=color_texto, AntiAlias=True))


# --------------------------------------------------------------------------- escenario
def fondo_escenario(paleta: dict, semilla: int = 7) -> np.ndarray:
    """Pared con franjas, motas y viñeta + mesa de madera. Devuelve un array BGRA listo para copiar."""
    arr = np.zeros((ALTO, ANCHO, 4), np.uint8)
    lienzo = skia.Surface(arr).getCanvas()
    base = color(paleta["fondo"])
    claro = mezclar(base, skia.ColorWHITE, 0.07)
    oscuro = mezclar(base, skia.ColorBLACK, 0.35)
    lienzo.clear(base)

    # Franjas verticales suaves (papel pintado)
    for x in range(0, ANCHO, 120):
        lienzo.drawRect(skia.Rect(x, 0, x + 60, Y_MESA), skia.Paint(Color=claro))
    # Motas
    rnd = random.Random(semilla)
    for _ in range(26):
        x, y, r = rnd.uniform(40, ANCHO - 40), rnd.uniform(380, Y_MESA - 60), rnd.uniform(6, 11)
        lienzo.drawCircle(x, y, r, skia.Paint(Color=mezclar(base, skia.ColorWHITE, 0.22), AntiAlias=True))
    # Viñeta
    lienzo.drawRect(skia.Rect(0, 0, ANCHO, Y_MESA), skia.Paint(Shader=skia.GradientShader.MakeRadial(
        (ANCHO / 2, 760), 1050, [skia.Color(0, 0, 0, 0), skia.Color(0, 0, 0, 120)], [0.45, 1.0])))
    lienzo.drawRect(skia.Rect(0, 0, ANCHO, Y_MESA), _ruido(0.12, 0.9, skia.BlendMode.kOverlay, semilla))

    # Mesa: canto superior claro + frente con tablones y vetas
    madera_top, madera, veta = color("#DDA36A"), color("#B8793F"), color("#98602F")
    lienzo.drawRect(skia.Rect(0, Y_MESA, ANCHO, Y_MESA + 46), skia.Paint(Color=madera_top))
    lienzo.drawRect(skia.Rect(0, Y_MESA - 3, ANCHO, Y_MESA + 2), skia.Paint(Color=skia.Color(250, 240, 220)))
    lienzo.drawRect(skia.Rect(0, Y_MESA + 46, ANCHO, ALTO), skia.Paint(Color=madera))
    lapiz = skia.Paint(Color=veta, AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3)
    for y0 in range(Y_MESA + 70, ALTO, 34):
        camino = skia.Path()
        fase = rnd.uniform(0, 6.28)
        camino.moveTo(0, y0)
        for x in range(0, ANCHO + 30, 30):
            camino.lineTo(x, y0 + 4 * math.sin(x / 90 + fase))
        lienzo.drawPath(camino, lapiz)
    for y0 in (Y_MESA + 46, Y_MESA + 330):  # juntas entre tablones
        lienzo.drawRect(skia.Rect(0, y0, ANCHO, y0 + 6), skia.Paint(Color=mezclar(veta, skia.ColorBLACK, 0.25)))
    lienzo.drawRect(skia.Rect(0, Y_MESA + 46, ANCHO, ALTO), skia.Paint(Shader=skia.GradientShader.MakeLinear(
        [(0, Y_MESA + 46), (0, ALTO)], [skia.Color(0, 0, 0, 0), skia.Color(0, 0, 0, 150)])))
    lienzo.drawRect(skia.Rect(0, Y_MESA, ANCHO, ALTO), _ruido(0.18, 0.7, skia.BlendMode.kOverlay, semilla + 1))
    # Sombra de la pared sobre la mesa
    lienzo.drawRect(skia.Rect(0, Y_MESA, ANCHO, Y_MESA + 40), skia.Paint(Shader=skia.GradientShader.MakeLinear(
        [(0, Y_MESA), (0, Y_MESA + 40)], [skia.Color(0, 0, 0, 60), skia.Color(0, 0, 0, 0)])))
    return arr


# --------------------------------------------------------------------------- piezas
def imagen_titulo(linea1: str, linea2: str, paleta: dict, ancho: int = 960) -> skia.Image:
    """Título en papel con dos cintas: línea 1 en tinta, línea 2 grande sobre una barra de color."""
    t1 = tamano_que_cabe(linea1, "titulo", ancho - 110, 64, 34) if linea1 else 0
    t2 = tamano_que_cabe(linea2, "titulo", ancho - 150, 120, 52)
    alto_barra = t2 * 1.12
    alto = 44 + (t1 * 1.08 + 18 if linea1 else 0) + alto_barra + 46
    margen = 40
    superficie, lienzo = _lienzo(ancho + 2 * margen, alto + 2 * margen)
    _papel(lienzo, margen, margen, ancho, alto, PAPEL, 11)
    cx = margen + ancho / 2
    y = margen + 44
    if linea1:
        _texto(lienzo, linea1, cx, y + t1 * 0.82, "titulo", t1)
        y += t1 * 1.08 + 18
    ancho2 = fuente("titulo", t2).measureText(linea2)
    barra = skia.Rect(cx - ancho2 / 2 - 26, y, cx + ancho2 / 2 + 26, y + alto_barra)
    lienzo.drawRect(barra, skia.Paint(Color=color(paleta["acento"]), AntiAlias=True))
    _texto(lienzo, linea2, cx, y + alto_barra * 0.80, "titulo", t2)
    _cinta(lienzo, margen + 40, margen + 10, -32)
    _cinta(lienzo, margen + ancho - 40, margen + 10, 32)
    return superficie.makeImageSnapshot()


def imagen_palabra(texto: str, semilla: int, tamano: int = 78) -> skia.Image:
    """Una palabra del subtítulo en su tarjetita de papel."""
    f = fuente("texto", tamano)
    ancho = f.measureText(texto) + 44
    alto = tamano * 1.25
    margen = 24
    superficie, lienzo = _lienzo(ancho + 2 * margen, alto + 2 * margen)
    _papel(lienzo, margen, margen, ancho, alto, PAPEL, semilla, textura=0.18)
    _texto(lienzo, texto, margen + ancho / 2, margen + alto * 0.76, "texto", tamano)
    return superficie.makeImageSnapshot()


def imagen_tarjeta_contador(etiqueta: str, semilla: int = 5, ancho: int = 330, alto: int = 210) -> skia.Image:
    """Fondo de la tarjeta del contador (el número se dibuja en cada cuadro)."""
    margen = 30
    superficie, lienzo = _lienzo(ancho + 2 * margen, alto + 2 * margen)
    _papel(lienzo, margen, margen, ancho, alto, color("#EFE6D6"), semilla)
    t = tamano_que_cabe(etiqueta, "titulo", ancho - 50, 34, 20)
    _texto(lienzo, etiqueta, margen + ancho / 2, margen + 58, "titulo", t)
    return superficie.makeImageSnapshot()


def imagen_etiqueta(texto: str, color_hex: str, semilla: int) -> skia.Image:
    """Etiqueta de color tipo nota adhesiva con una marca pequeña."""
    t = tamano_que_cabe(texto, "titulo", 330, 52, 30)
    ancho = fuente("titulo", t).measureText(texto) + 70
    alto = t * 1.7
    margen = 30
    superficie, lienzo = _lienzo(ancho + 2 * margen, alto + 2 * margen)
    _papel(lienzo, margen, margen, ancho, alto, color(color_hex), semilla, textura=0.15)
    lienzo.drawCircle(margen + 24, margen + 22, 8, skia.Paint(Color=skia.Color(0, 0, 0, 70), AntiAlias=True))
    _texto(lienzo, texto, margen + ancho / 2 + 8, margen + alto * 0.66, "titulo", t)
    return superficie.makeImageSnapshot()


def imagen_marca(texto: str) -> skia.Image:
    """Firma temporal: insignia redonda + @usuario, para sustituir por tu logo."""
    f = fuente("titulo", 30)
    ancho = f.measureText(texto) + 80
    superficie, lienzo = _lienzo(ancho, 60)
    lienzo.drawCircle(26, 30, 22, skia.Paint(Color=skia.Color(255, 255, 255, 150), AntiAlias=True))
    lienzo.drawCircle(26, 30, 14, skia.Paint(Color=skia.Color(0, 0, 0, 90), AntiAlias=True))
    lienzo.drawString(texto, 62, 41, f, skia.Paint(Color=skia.Color(255, 255, 255, 150), AntiAlias=True))
    return superficie.makeImageSnapshot()
