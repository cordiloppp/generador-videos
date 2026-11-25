"""Subtítulos .ass estilo shorts: 3-4 palabras por pantalla y la palabra actual resaltada."""
import re
from pathlib import Path

_QUITAR = re.compile(r"[.,;:…\"“”«»()]")


def _color_ass(hex_rgb: str) -> str:
    """'#FFE600' -> '&H0000E6FF' (ASS usa el orden AABBGGRR)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _tiempo_ass(s: float) -> str:
    s = max(0.0, s)
    cs = int(round(s * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    seg, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{seg:02d}.{cs:02d}"


def _limpiar(palabra: str, estilo: dict) -> str:
    if estilo.get("quitar_puntuacion", True):
        palabra = _QUITAR.sub("", palabra)
    if estilo.get("mayusculas", True):
        palabra = palabra.upper()
    # Caracteres especiales de ASS
    return palabra.replace("\\", "").replace("{", "(").replace("}", ")")


def max_caracteres(estilo: dict, ancho: int) -> int:
    """Caracteres que caben en una línea (estimado para fuentes gruesas en mayúsculas)."""
    if estilo.get("max_caracteres"):
        return int(estilo["max_caracteres"])
    util = ancho - 2 * 80  # márgenes laterales del estilo
    ancho_letra = float(estilo.get("tamano", 92)) * 0.72 * int(estilo.get("escala_resaltado", 108)) / 100
    return max(6, int(util / ancho_letra))


def _agrupar(frases: list[dict], max_palabras: int, max_chars: int, estilo: dict) -> list[list[dict]]:
    """Grupos de palabras para cada pantalla, sin cruzar frases ni pausas largas, y que quepan en una línea."""
    grupos = []
    for frase in frases:
        actual = []
        for p in frase["palabras"]:
            largo = len(" ".join(_limpiar(x["texto"], estilo) for x in actual + [p]))
            if actual and (len(actual) >= max_palabras or p["inicio"] - actual[-1]["fin"] > 0.5
                           or largo > max_chars):
                grupos.append(actual)
                actual = []
            actual.append(p)
            # Cortar tras puntuación si ya hay al menos 2 palabras
            if len(actual) >= 2 and re.search(r"[.?!,;:]$", p["texto"]):
                grupos.append(actual)
                actual = []
        if actual:
            grupos.append(actual)
    return grupos


def generar_ass(frases: list[dict], estilo: dict, salida: Path, ancho: int = 1080, alto: int = 1920) -> Path:
    blanco = _color_ass(estilo.get("color", "#FFFFFF"))
    resaltado = _color_ass(estilo.get("color_resaltado", "#FFE600"))
    contorno_color = _color_ass(estilo.get("color_contorno", "#000000"))
    escala = int(estilo.get("escala_resaltado", 108))
    max_palabras = max(1, min(4, int(estilo.get("palabras_por_pantalla", 3))))

    cabecera = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {ancho}
PlayResY: {alto}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Shorts,{estilo.get('fuente', 'Arial Black')},{estilo.get('tamano', 92)},{blanco},{blanco},{contorno_color},&H80000000,-1,0,0,0,100,100,0,0,1,{estilo.get('contorno', 6)},{estilo.get('sombra', 2)},2,80,80,{estilo.get('margen_inferior', 420)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = [cabecera]
    limite = max_caracteres(estilo, ancho)
    tamano = int(estilo.get("tamano", 92))
    grupos = _agrupar(frases, max_palabras, limite, estilo)
    for gi, grupo in enumerate(grupos):
        # El grupo se ve hasta el inicio del siguiente (si está cerca) o un poco después de su última palabra
        fin_grupo = grupo[-1]["fin"] + 0.25
        if gi + 1 < len(grupos):
            fin_grupo = min(fin_grupo, grupos[gi + 1][0]["inicio"])
            if grupos[gi + 1][0]["inicio"] - grupo[-1]["fin"] < 0.3:
                fin_grupo = grupos[gi + 1][0]["inicio"]
        textos = [_limpiar(p["texto"], estilo) for p in grupo]
        largo = len(" ".join(textos))
        # Una palabra suelta demasiado larga no se puede partir: se reduce la fuente para que quepa
        prefijo = f"{{\\fs{int(tamano * limite / largo)}}}" if largo > limite else ""
        for k, p in enumerate(grupo):
            ini = grupo[0]["inicio"] if k == 0 else p["inicio"]
            fin = grupo[k + 1]["inicio"] if k + 1 < len(grupo) else fin_grupo
            if fin <= ini:
                continue
            piezas = []
            for j, t in enumerate(textos):
                if j == k:
                    piezas.append(f"{{\\c{resaltado}\\fscx{escala}\\fscy{escala}}}{t}{{\\c{blanco}\\fscx100\\fscy100}}")
                else:
                    piezas.append(t)
            lineas.append(f"Dialogue: 0,{_tiempo_ass(ini)},{_tiempo_ass(fin)},Shorts,,0,0,0,,{prefijo}{' '.join(piezas)}\n")

    salida.parent.mkdir(parents=True, exist_ok=True)
    # utf-8 con BOM: libass lo lee bien y evita problemas con acentos
    salida.write_text("".join(lineas), encoding="utf-8-sig")
    return salida
