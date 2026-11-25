"""Normalización de texto y utilidades de tiempo."""
import re
import unicodedata

_PUNTUACION_FINAL = ".?!…"


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, '_' y '-' como espacio, solo letras y números."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().replace("_", " ").replace("-", " ")
    texto = re.sub(r"[^a-z0-9ñ ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def termina_frase(palabra: str) -> bool:
    return palabra.rstrip("\"'»”)").endswith(tuple(_PUNTUACION_FINAL))


def termina_con_coma(palabra: str) -> bool:
    return palabra.rstrip("\"'»”)").endswith((",", ";", ":"))


def transferir_puntuacion(palabras: list[dict], texto_completo: str) -> list[dict]:
    """Pone la puntuación del texto completo en las palabras con timestamps.

    Groq devuelve las palabras sin puntuación; el texto de los segmentos sí la trae.
    Se recorren ambos en orden y se emparejan por su forma normalizada.
    """
    tokens = texto_completo.split()
    j = 0
    for palabra in palabras:
        objetivo = normalizar(palabra["texto"])
        if not objetivo:
            continue
        for k in range(j, min(j + 4, len(tokens))):
            if normalizar(tokens[k]) == objetivo:
                palabra["texto"] = tokens[k]
                j = k + 1
                break
    return palabras


def parsear_tiempo(texto: str) -> float:
    """'1:02:03.5', '2:03' o '75' -> segundos."""
    partes = [float(p) for p in texto.strip().split(":")]
    segundos = 0.0
    for p in partes:
        segundos = segundos * 60 + p
    return segundos


def formato_tiempo(segundos: float) -> str:
    """Segundos -> 'm:ss.s' (para mensajes y plan.json)."""
    m, s = divmod(max(0.0, segundos), 60)
    return f"{int(m)}:{s:04.1f}"
