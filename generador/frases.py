"""División de la transcripción en frases (por pausas y puntuación)."""
from .texto import normalizar, termina_con_coma, termina_frase

# Palabras tras las que casi nunca termina una idea: una pausa aquí no cierra la frase
_NO_CERRAR = {
    "a", "al", "el", "la", "los", "las", "lo", "un", "una", "unos", "unas", "de", "del", "en",
    "y", "e", "o", "u", "que", "por", "para", "con", "sin", "mi", "mis", "tu", "tus", "su", "sus",
    "muy", "mas", "pero", "como", "se", "me", "te", "le", "les", "nos",
}


def dividir_en_frases(palabras: list[dict], cfg_frases: dict) -> list[dict]:
    """Agrupa palabras en frases de entre min_s y max_s segundos.

    Se cierra una frase cuando:
      - añadir la siguiente palabra superaría max_s, o
      - hay puntuación final (. ? !) y la frase ya dura min_s, o
      - hay una pausa >= pausa_s y la frase ya dura min_s, o
      - hay una pausa muy larga (pausa_fuerte_s), o una coma con la frase ya larga.
    """
    min_s, max_s = cfg_frases["min_s"], cfg_frases["max_s"]
    pausa, pausa_fuerte = cfg_frases["pausa_s"], cfg_frases["pausa_fuerte_s"]

    grupos: list[list[dict]] = []
    actual: list[dict] = []
    for i, p in enumerate(palabras):
        if actual and p["fin"] - actual[0]["inicio"] > max_s:
            grupos.append(actual)
            actual = []
        actual.append(p)
        if i == len(palabras) - 1:
            break
        siguiente = palabras[i + 1]
        hueco = siguiente["inicio"] - p["fin"]
        dur = p["fin"] - actual[0]["inicio"]
        puede_pausar = normalizar(p["texto"]) not in _NO_CERRAR
        if ((hueco >= pausa_fuerte and puede_pausar)
                or (dur >= min_s and termina_frase(p["texto"]))
                or (dur >= min_s and hueco >= pausa and puede_pausar)
                or (dur >= max_s * 0.6 and termina_con_coma(p["texto"]))):
            grupos.append(actual)
            actual = []
    if actual:
        grupos.append(actual)

    # Une las frases demasiado cortas con la anterior si cabe
    unidos: list[list[dict]] = []
    for g in grupos:
        dur = g[-1]["fin"] - g[0]["inicio"]
        if unidos and dur < min_s and g[-1]["fin"] - unidos[-1][0]["inicio"] <= max_s:
            unidos[-1].extend(g)
        else:
            unidos.append(g)
    if len(unidos) > 1:
        primera = unidos[0]
        if primera[-1]["fin"] - primera[0]["inicio"] < min_s and \
                unidos[1][-1]["fin"] - primera[0]["inicio"] <= max_s:
            unidos[1] = primera + unidos[1]
            unidos.pop(0)

    return [
        {
            "indice": n,
            "inicio": g[0]["inicio"],
            "fin": g[-1]["fin"],
            "texto": " ".join(p["texto"] for p in g),
            "palabras": g,
        }
        for n, g in enumerate(unidos, start=1)
    ]
