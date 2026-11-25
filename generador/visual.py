"""Fragmentos visuales del modo normal, composición vertical de imágenes y Ken Burns."""
import math
from pathlib import Path

from .entorno import ErrorFFmpeg, argumentos_codec, ejecutar_ffmpeg, nvenc_disponible


def segmentos_visuales(frases: list[dict], duracion: float, max_fragmento: float, fps: int) -> list[dict]:
    """Un fragmento por frase (o varios si la frase dura más que max_fragmento).

    Cada fragmento cubre desde su inicio hasta el inicio del siguiente (sin huecos negros),
    con los bordes alineados a cuadros para que la suma cuadre exactamente con el audio.
    """
    piezas = []  # (inicio, palabras)
    for f in frases:
        palabras = f["palabras"]
        dur = f["fin"] - f["inicio"]
        n = max(1, math.ceil(dur / max_fragmento))
        if n == 1 or len(palabras) < 2 * n:
            piezas.append((f["inicio"], palabras))
            continue
        # Cortes cerca de inicio + k*dur/n, siempre al inicio de una palabra
        cortes = [0]
        for k in range(1, n):
            objetivo = f["inicio"] + k * dur / n
            j = min(range(cortes[-1] + 1, len(palabras)), key=lambda x: abs(palabras[x]["inicio"] - objetivo))
            if j > cortes[-1]:
                cortes.append(j)
        cortes.append(len(palabras))
        for a, b in zip(cortes, cortes[1:]):
            piezas.append((palabras[a]["inicio"], palabras[a:b]))

    total_cuadros = math.ceil(duracion * fps)
    segmentos = []
    for i, (inicio, palabras) in enumerate(piezas):
        c_ini = 0 if i == 0 else round(inicio * fps)
        c_fin = total_cuadros if i == len(piezas) - 1 else round(piezas[i + 1][0] * fps)
        if c_fin <= c_ini:
            continue
        segmentos.append({
            "indice": len(segmentos) + 1,
            "inicio": c_ini / fps,
            "fin": c_fin / fps,
            "cuadros": c_fin - c_ini,
            "texto": " ".join(p["texto"] for p in palabras),
        })
    # Si alguno se descartó, el anterior se estira para no dejar huecos
    for a, b in zip(segmentos, segmentos[1:]):
        if a["fin"] != b["inicio"]:
            a["fin"] = b["inicio"]
            a["cuadros"] = round((a["fin"] - a["inicio"]) * fps)
    return segmentos


def componer_vertical(origen: Path, destino: Path, ancho: int, alto: int, factor: int = 2) -> Path:
    """Imagen a pantalla vertical: si no tiene la proporción, va centrada sobre una copia desenfocada.

    Se genera al doble de resolución para que el zoom posterior sea suave.
    """
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    W, H = ancho * factor, alto * factor
    img = Image.open(origen).convert("RGB")
    proporcion, objetivo = img.width / img.height, W / H
    if abs(proporcion - objetivo) / objetivo < 0.04:
        lienzo = ImageOps.fit(img, (W, H), Image.LANCZOS)
    else:
        fondo = ImageOps.fit(img, (W // 10, H // 10), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5))
        lienzo = ImageEnhance.Brightness(fondo.resize((W, H), Image.BICUBIC)).enhance(0.65)
        frente = ImageOps.contain(img, (W, H), Image.LANCZOS)
        lienzo.paste(frente, ((W - frente.width) // 2, (H - frente.height) // 2))
    lienzo.save(destino, quality=95)
    return destino


def render_ken_burns(imagen: Path, destino: Path, cuadros: int, zoom: float, acercar: bool,
                     cfg_video: dict) -> None:
    """Zoom suave hacia el centro (acercar) o alejándose, a 1080x1920 y 30 fps."""
    ancho, alto, fps = cfg_video["ancho"], cfg_video["alto"], cfg_video["fps"]
    if acercar:
        z = f"1+{zoom}*on/{cuadros}"
    else:
        z = f"1+{zoom}-{zoom}*on/{cuadros}"
    filtro = (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={cuadros}"
              f":s={ancho}x{alto}:fps={fps},setsar=1")
    intermedio = dict(cfg_video, nvenc_cq=18, x264_crf=17)  # alta calidad: se recodifica al final
    usar_nvenc = nvenc_disponible()
    for nvenc in ([True, False] if usar_nvenc else [False]):
        try:
            ejecutar_ffmpeg(["-i", imagen, "-vf", filtro, "-frames:v", str(cuadros),
                             *argumentos_codec(intermedio, nvenc), "-an", destino])
            return
        except ErrorFFmpeg:
            if not nvenc:
                raise
