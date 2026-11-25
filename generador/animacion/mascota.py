"""Mascota temporal "Webi": una ventanita de navegador con ojos y patitas (sustitúyela cuando tengas la tuya).

Se dibuja con vectores en cada cuadro, así puede parpadear, saltar, mirar y mover la boca al hablar.
"""
import skia

from .dibujo import color

TINTA = color("#2B2118")
CUERPO = color("#FFC93C")
BARRA = color("#F2A13B")
MEJILLA = color("#FF8A80", 150)


def dibujar_mascota(lienzo, x: float, y_pies: float, escala: float = 1.0, salto: float = 0.0,
                    aplastar: float = 0.0, parpadeo: float = 0.0, boca: float = 0.0,
                    expresion: str = "feliz", mirar: tuple[float, float] = (-1.0, 0.0),
                    brazo: float = 0.0) -> None:
    """x, y_pies: punto en la mesa. salto: píxeles hacia arriba. aplastar: -1..1 (estirar/aplastar).
    parpadeo: 0 abierto .. 1 cerrado. boca: 0..1 apertura al hablar. brazo: 0..1 saludo."""
    # Sombra en la mesa (más pequeña cuanto más alto salta)
    s = max(0.4, 1 - salto / 260)
    lienzo.drawOval(skia.Rect(x - 85 * escala * s, y_pies - 8, x + 85 * escala * s, y_pies + 12),
                    skia.Paint(Color=skia.Color(0, 0, 0, int(70 * s)), AntiAlias=True,
                               MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 5)))
    lienzo.save()
    lienzo.translate(x, y_pies - salto)
    lienzo.scale(escala * (1 + 0.12 * aplastar), escala * (1 - 0.12 * aplastar))

    tinta = skia.Paint(Color=TINTA, AntiAlias=True)
    trazo = skia.Paint(Color=TINTA, AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7,
                       StrokeCap=skia.Paint.kRound_Cap, StrokeJoin=skia.Paint.kRound_Join)
    blanco_borde = skia.Paint(Color=skia.ColorWHITE, AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=20,
                              StrokeJoin=skia.Paint.kRound_Join)

    # Patitas
    for px in (-42, 30):
        lienzo.drawRoundRect(skia.Rect(px, -46, px + 14, -4), 7, 7, tinta)
        lienzo.drawRoundRect(skia.Rect(px - 6, -10, px + 22, 2), 6, 6, tinta)

    cuerpo = skia.RRect.MakeRectXY(skia.Rect(-95, -200, 95, -42), 28, 28)
    # Brazos (el derecho saluda)
    lienzo.drawLine(-95, -110, -122, -78, trazo)
    lienzo.save()
    lienzo.translate(95, -112)
    lienzo.rotate(-70 * brazo)
    lienzo.drawLine(0, 0, 28, 32, trazo)
    lienzo.restore()

    lienzo.drawRRect(cuerpo, blanco_borde)          # borde blanco de "papel recortado"
    lienzo.drawRRect(cuerpo, skia.Paint(Color=CUERPO, AntiAlias=True))
    # Barra del navegador con tres puntitos
    lienzo.save()
    lienzo.clipRRect(cuerpo, doAntiAlias=True)
    lienzo.drawRect(skia.Rect(-95, -200, 95, -166), skia.Paint(Color=BARRA))
    lienzo.drawLine(-95, -166, 95, -166, skia.Paint(Color=TINTA, StrokeWidth=5, AntiAlias=True))
    lienzo.restore()
    for i, c in enumerate(("#E5533D", "#FFF4D6", "#3DBE8B")):
        lienzo.drawCircle(-68 + i * 22, -183, 7, skia.Paint(Color=color(c), AntiAlias=True))
    lienzo.drawRRect(cuerpo, trazo)

    # Ojos
    mx, my = mirar
    for ox in (-38, 38):
        cx, cy = ox, -116
        if parpadeo > 0.5:
            lienzo.drawLine(cx - 18, cy, cx + 18, cy, trazo)
            continue
        alto = 24 * (1 - parpadeo)
        lienzo.drawOval(skia.Rect(cx - 23, cy - alto, cx + 23, cy + alto), skia.Paint(Color=skia.ColorWHITE, AntiAlias=True))
        lienzo.drawOval(skia.Rect(cx - 23, cy - alto, cx + 23, cy + alto),
                        skia.Paint(Color=TINTA, AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5))
        pupila_y = -6 if expresion == "pensando" else my * 6
        lienzo.drawCircle(cx + mx * 8, cy + pupila_y, 10, tinta)
        lienzo.drawCircle(cx + mx * 8 - 3, cy + pupila_y - 4, 3, skia.Paint(Color=skia.ColorWHITE, AntiAlias=True))

    # Mejillas
    for ox in (-62, 62):
        lienzo.drawOval(skia.Rect(ox - 12, -84, ox + 12, -72), skia.Paint(Color=MEJILLA, AntiAlias=True))

    # Boca
    if boca > 0.05:
        alto = 5 + 16 * boca
        lienzo.drawOval(skia.Rect(-15, -78 - alto / 2, 15, -78 + alto / 2), tinta)
    elif expresion == "sorpresa":
        lienzo.drawOval(skia.Rect(-11, -90, 11, -66), tinta)
    elif expresion == "triste":
        camino = skia.Path()
        camino.moveTo(-18, -66)
        camino.quadTo(0, -86, 18, -66)
        lienzo.drawPath(camino, trazo)
    elif expresion == "pensando":
        lienzo.drawLine(-14, -76, 16, -80, trazo)
    else:  # feliz
        camino = skia.Path()
        camino.moveTo(-20, -84)
        camino.quadTo(0, -62, 20, -84)
        lienzo.drawPath(camino, trazo)
    lienzo.restore()
