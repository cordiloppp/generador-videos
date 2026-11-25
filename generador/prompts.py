"""Prompts de imagen para cada fragmento visual: Groq LLM -> traductor local -> texto tal cual."""
from . import cache
from .consola import titulo
from .proveedores import llm_groq, traductor_local
from .proveedores.base import RegistroProveedores, ejecutar_con_respaldo

_VERSION = 1
_LOTE = 25  # fragmentos por petición al LLM


def generar_prompts(segmentos: list[dict], plantilla: dict, cfg: dict, registro: RegistroProveedores,
                    contadores, forzar: bool = False) -> list[str]:
    titulo("Prompts de imagen")
    estilo = plantilla["visual"]["estilo_imagen"]
    textos = [s["texto"] for s in segmentos]
    contexto = " ".join(textos)
    clave = cache.clave(textos, estilo, cfg["groq"]["modelos_llm"], _VERSION)
    ruta = cache.carpeta("prompts") / f"{clave}.json"
    guardado = None if forzar else cache.leer_json(ruta)
    if guardado:
        registro.anotar("prompts", "caché", "usado", detalle=f"generados antes con {guardado['proveedor']}")
        return guardado["prompts"]

    def con_groq():
        prompts = []
        for i in range(0, len(textos), _LOTE):
            lote = llm_groq.generar_prompts(textos[i:i + _LOTE], contexto[:6000], estilo, cfg, contadores)
            prompts.extend(f"{p.rstrip('.')}, {estilo}" for p in lote)
        return prompts

    candidatos = {
        "groq": con_groq,
        "traductor_local": lambda: traductor_local.generar_prompts(textos, estilo),
        "texto": lambda: [f"{t}, {estilo}" for t in textos],  # último recurso: nunca falla
    }
    orden = [n for n in cfg["proveedores"]["prompt"] if n in candidatos] + ["texto"]
    prompts, proveedor = ejecutar_con_respaldo(registro, "prompts", [(n, candidatos[n]) for n in dict.fromkeys(orden)])
    traductor_local.liberar()
    cache.escribir_json(ruta, {"proveedor": proveedor, "prompts": prompts})
    return prompts
