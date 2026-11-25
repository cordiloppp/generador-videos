"""Utilidades de caché: huellas de archivos y JSON con escritura segura."""
import hashlib
import json
import os
from pathlib import Path

from .config import CACHE

_BLOQUE = 4 * 1024 * 1024  # 4 MB


def huella_archivo(ruta: Path | str) -> str:
    """Huella rápida de un archivo: tamaño + inicio, mitad y final.

    Es suficiente para detectar cambios y evita leer grabaciones de varios GB enteras.
    """
    ruta = Path(ruta)
    tam = ruta.stat().st_size
    h = hashlib.sha1(str(tam).encode())
    with open(ruta, "rb") as f:
        if tam <= 3 * _BLOQUE:
            h.update(f.read())
        else:
            for pos in (0, tam // 2, tam - _BLOQUE):
                f.seek(pos)
                h.update(f.read(_BLOQUE))
    return h.hexdigest()[:20]


def clave(*partes) -> str:
    """Clave estable a partir de cualquier combinación de valores serializables."""
    texto = json.dumps(partes, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:20]


def carpeta(nombre: str) -> Path:
    ruta = CACHE / nombre
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def leer_json(ruta: Path, por_defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return por_defecto


def escribir_json(ruta: Path, datos) -> None:
    """Escribe a un temporal y luego lo renombra, para no dejar JSON a medias."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)
