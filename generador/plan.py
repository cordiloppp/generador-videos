"""plan.json: qué material, qué cortes y qué proveedor se usaron."""
import time
from pathlib import Path

from .cache import escribir_json


def escribir_plan(ruta: Path, *, modo: str, plantilla: str, entrada: str, salida: str,
                  transcripcion: dict, frases: list[dict], registro, codificador: str,
                  extra: dict | None = None) -> Path:
    plan = {
        "creado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "modo": modo,
        "plantilla": plantilla,
        "entrada": entrada,
        "salida": salida,
        "codificador_video": codificador,
        "transcripcion": {
            "proveedor": transcripcion["proveedor"],
            "partes": transcripcion["partes"],
            "duracion": transcripcion["duracion"],
        },
        "proveedores": registro.eventos,
        "frases": [
            {
                "indice": f["indice"],
                "inicio": round(f["inicio"], 3),
                "fin": round(f["fin"], 3),
                "texto": f["texto"],
                **({"visual": f["visual"]} if "visual" in f else {}),
            }
            for f in frases
        ],
    }
    if extra:
        plan.update(extra)
    escribir_json(ruta, plan)
    return ruta
