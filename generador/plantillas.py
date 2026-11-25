"""Carga de plantillas (plantillas/*.json) con valores por defecto."""
import json

from .config import PLANTILLAS, _fusionar

PLANTILLA_POR_DEFECTO = {
    "nombre": "generica",
    "descripcion": "",
    "subtitulos": {
        "fuente": "Arial Black",
        "tamano": 92,
        "color": "#FFFFFF",
        "color_resaltado": "#FFE600",
        "color_contorno": "#000000",
        "contorno": 6,
        "sombra": 2,
        "margen_inferior": 420,
        "mayusculas": True,
        "quitar_puntuacion": True,
        "palabras_por_pantalla": 3,
        "escala_resaltado": 108,
    },
    "cortes": {
        "activar": True,
        "silencio_max_s": 0.45,      # pausas más largas que esto se cortan
        "margen_s": 0.12,            # se deja este margen antes y después de hablar
        "quitar_repeticiones": True, # "está hecho está hecho" -> "está hecho"; también "eh", "mmm"
        "umbral_silencio_db": "auto",
    },
    "visual": {
        "max_fragmento_s": 6.0,     # cada imagen dura como máximo esto (las frases largas se dividen)
        "ken_burns_zoom": 0.10,     # 0.10 = 10 % de zoom durante el fragmento
        "alternar_zoom": True,      # alterna acercar / alejar entre fragmentos
        "estilo_imagen": "photorealistic, cinematic lighting, high detail, vertical composition",
    },
    "obs": {
        "pista_voz": 2,             # número de pista de audio dentro del archivo (1 = la primera)
        "volumen_juego": 0.25,      # 0.2-0.3 = 20-30 %
        "ducking": True,            # baja aún más el juego mientras hablas
        "ducking_umbral": 0.02,
        "ducking_ratio": 6,
        "silencio_max_s": 0.7,      # pausas más largas que esto se cortan
        "margen_s": 0.15,           # margen alrededor de cada palabra para no cortarla
        "quitar_repeticiones": True,
        "formato": "blur",          # blur | crop | split
        "zoom_blur": 1.0,           # >1 agranda el video central en 'blur'
        "crop_x": 0.5,              # 'crop': 0 izquierda, 0.5 centro, 1 derecha
        "facecam": None,            # 'split': [x, y, ancho, alto] en fracciones del cuadro (0-1)
        "split_alto_juego": 0.6,    # 'split': parte de la altura para el juego
    },
}


def cargar_plantilla(nombre: str) -> dict:
    ruta = PLANTILLAS / f"{nombre}.json"
    if not ruta.exists():
        disponibles = ", ".join(sorted(p.stem for p in PLANTILLAS.glob("*.json"))) or "ninguna"
        raise FileNotFoundError(f"No existe la plantilla '{nombre}'. Disponibles: {disponibles}")
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    plantilla = _fusionar(PLANTILLA_POR_DEFECTO, datos)
    plantilla["nombre"] = nombre
    return plantilla
