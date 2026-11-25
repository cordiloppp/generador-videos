"""Guion visual del video animado: título gancho, paleta y qué aparece en cada escena.

Groq LLM (gratis) -> reglas locales (traductor es->en + números del texto) -> reglas simples.
"""
import re

from .. import cache
from ..consola import titulo
from ..proveedores import llm_groq, traductor_local
from ..proveedores.base import ProveedorNoDisponible, RegistroProveedores, ejecutar_con_respaldo
from ..texto import normalizar
from .dibujo import PALETAS
from .recursos import EMOJIS, indice_objetos, limpiar_etiqueta

_VERSION = 1
EXPRESIONES = ("feliz", "sorpresa", "triste", "pensando")
OBJETOS_GENERICOS = ["light bulb", "rocket", "sparkles", "direct hit", "gear", "star", "megaphone", "trophy"]

_SISTEMA = """You design animated explainer shorts in a flat "paper cut-out" style: a title on paper at the top,
one big flat object (an emoji-like sticker) in the center of the stage, optional counter card and sticky labels,
and a small mascot that reacts. The narration is in Spanish; all on-screen text must be in SPANISH.

Return ONLY JSON:
{{
  "titulo": {{"linea1": "SHORT HOOK LINE (max 28 chars)", "linea2": "KEY WORDS (max 16 chars)"}},
  "paleta": one of {paletas},
  "escenas": [
    {{
      "objeto": ["english emoji name", "alternative", "alternative"],
      "contador": null or {{"etiqueta": "LABEL (max 14 chars)", "valor": 1234, "prefijo": "", "sufijo": ""}},
      "etiquetas": ["MAX 12 CHARS", ...],
      "mascota": one of ["feliz", "sorpresa", "triste", "pensando"]
    }}
  ]
}}
Rules:
- Exactly {n} scenes, one per numbered fragment, same order.
- "titulo" is a catchy hook for the WHOLE video, uppercase Spanish (like a YouTube thumbnail), linea2 is the punchline.
- "objeto": concrete things that exist as emoji (e.g. "laptop", "money bag", "calendar", "rocket", "wedding",
  "world map", "camera", "mobile phone", "chart increasing", "locked", "hourglass done", "party popper").
  Give 3 options, most specific first.
- "contador" ONLY when the fragment mentions a number, price, percentage or quantity; "valor" must be a number.
- "etiquetas": 0 to 3 very short uppercase Spanish words taken from the fragment (keywords, benefits, prices).
  Leave empty in about half of the scenes so the stage is not overloaded.
- "mascota": the mascot's reaction to that fragment."""


def _guion_llm(textos, cfg, contadores):
    usuario = ("Fragments:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(textos, 1))
               + f"\n\nReturn exactly {len(textos)} scenes.")
    sistema = _SISTEMA.format(paletas=list(PALETAS), n=len(textos))
    for intento in range(2):
        datos = llm_groq.pedir_json(sistema, usuario, cfg, contadores)
        if len(datos.get("escenas") or []) == len(textos):
            return datos
    raise ProveedorNoDisponible("groq", f"devolvió {len(datos.get('escenas') or [])} escenas en vez de {len(textos)}")


def _numero(texto: str):
    m = re.search(r"(\$)?\s?(\d[\d.,]*)\s?(%|mil|millones)?", texto)
    if not m:
        return None
    digitos = m.group(2).replace(".", "").replace(",", "")
    if not digitos.isdigit():
        return None
    valor = int(digitos) * (1000 if m.group(3) == "mil" else 1_000_000 if m.group(3) == "millones" else 1)
    return {"etiqueta": "", "valor": valor, "prefijo": m.group(1) or "", "sufijo": "%" if m.group(3) == "%" else ""}


def _guion_reglas(textos, traducir: bool):
    """Sin LLM: objeto por palabras traducidas, contador si hay números, etiquetas con palabras largas."""
    traducciones = traductor_local.traducir(textos) if traducir else [""] * len(textos)
    escenas = []
    for i, (es, en) in enumerate(zip(textos, traducciones)):
        palabras_en = [w for w in normalizar(en).split() if len(w) > 3]
        objeto = palabras_en[::-1] + [OBJETOS_GENERICOS[i % len(OBJETOS_GENERICOS)]]
        largas = sorted({w for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{6,}", es)}, key=len, reverse=True)
        escenas.append({
            "objeto": objeto,
            "contador": _numero(es),
            "etiquetas": largas[:2] if i % 2 == 0 else [],
            "mascota": "pensando" if "?" in es else "sorpresa" if "!" in es else "feliz",
        })
    palabras = textos[0].split() if textos else ["VIDEO"]
    corte = max(1, len(palabras) - 2)
    return {"titulo": {"linea1": " ".join(palabras[:corte])[:28], "linea2": " ".join(palabras[corte:])[:16]},
            "paleta": list(PALETAS)[len(textos[0]) % len(PALETAS)] if textos else "verde",
            "escenas": escenas}


_NUMEROS_ES = re.compile(
    r"\d|\b(dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|veinte|treinta|cuarenta|"
    r"cincuenta|sesenta|setenta|ochenta|noventa|cien|ciento|doscientos|quinientos|mil|millón|millones|"
    r"por ciento|mitad|doble|triple)\b", re.IGNORECASE)


def _sanear(datos: dict, n: int, paleta_fija: str | None, textos: list[str]) -> dict:
    t = datos.get("titulo") or {}
    linea1 = limpiar_etiqueta(t.get("linea1", ""), 34)
    linea2 = limpiar_etiqueta(t.get("linea2", ""), 26) or "MIRA ESTO"  # si es larga, la fuente se achica
    paleta = paleta_fija if paleta_fija in PALETAS else datos.get("paleta")
    if paleta not in PALETAS:
        paleta = "verde"
    escenas = []
    for i, e in enumerate((datos.get("escenas") or [])[:n]):
        contador = e.get("contador")
        # El contador solo si en el fragmento se dice de verdad un número (el LLM a veces lo inventa)
        if isinstance(contador, dict) and i < len(textos) and _NUMEROS_ES.search(textos[i]):
            try:
                contador = {"etiqueta": limpiar_etiqueta(contador.get("etiqueta", ""), 16),
                            "valor": float(str(contador.get("valor", "")).replace(",", "")),
                            "prefijo": str(contador.get("prefijo") or "")[:3],
                            "sufijo": str(contador.get("sufijo") or "")[:4]}
            except ValueError:
                contador = None
        else:
            contador = None
        objeto = e.get("objeto") or []
        escenas.append({
            "objeto": [str(o) for o in (objeto if isinstance(objeto, list) else [objeto])][:4],
            "contador": contador,
            "etiquetas": [limpiar_etiqueta(x, 16) for x in (e.get("etiquetas") or [])[:3] if str(x).strip()],
            "mascota": e.get("mascota") if e.get("mascota") in EXPRESIONES else "feliz",
        })
    while len(escenas) < n:
        escenas.append({"objeto": [OBJETOS_GENERICOS[len(escenas) % 8]], "contador": None, "etiquetas": [],
                        "mascota": "feliz"})
    return {"titulo": {"linea1": linea1, "linea2": linea2}, "paleta": paleta, "escenas": escenas}


def resolver_objetos(guion: dict) -> None:
    """Asigna a cada escena el SVG de la biblioteca que mejor encaja (o uno genérico)."""
    indice = indice_objetos()
    for i, e in enumerate(guion["escenas"]):
        svg = indice.buscar(e["objeto"]) or indice.buscar([OBJETOS_GENERICOS[i % len(OBJETOS_GENERICOS)]])
        e["svg"] = svg
        e["objeto_elegido"] = svg.relative_to(EMOJIS).parts[0] if svg else None


def generar_guion(segmentos: list[dict], plantilla: dict, cfg: dict, registro: RegistroProveedores,
                  contadores, forzar: bool = False) -> dict:
    titulo("Guion visual")
    textos = [s["texto"] for s in segmentos]
    paleta_fija = plantilla["visual"].get("paleta")
    paleta_fija = None if paleta_fija in (None, "auto") else paleta_fija
    clave = cache.clave(textos, _VERSION, cfg["groq"]["modelos_llm"])
    ruta = cache.carpeta("guiones") / f"{clave}.json"
    guardado = None if forzar else cache.leer_json(ruta)
    if guardado:
        registro.anotar("guion", "caché", "usado", detalle=f"generado antes con {guardado['proveedor']}")
        datos, proveedor = guardado["guion"], guardado["proveedor"]
    else:
        candidatos = {
            "groq": lambda: _guion_llm(textos, cfg, contadores),
            "traductor_local": lambda: _guion_reglas(textos, traducir=True),
        }
        orden = [(n, candidatos[n]) for n in cfg["proveedores"]["prompt"] if n in candidatos]
        orden.append(("reglas", lambda: _guion_reglas(textos, traducir=False)))
        datos, proveedor = ejecutar_con_respaldo(registro, "guion", orden)
        traductor_local.liberar()
        cache.escribir_json(ruta, {"proveedor": proveedor, "guion": datos})
    guion = _sanear(datos, len(textos), paleta_fija, textos)
    guion["proveedor"] = proveedor
    resolver_objetos(guion)
    return guion
