"""Transcripción con caché, división en partes y respaldo por parte.

Formato del resultado:
{
  "duracion": 61.2,
  "partes": [{"indice": 1, "inicio": 0.0, "fin": 61.2, "proveedor": "groq"}],
  "proveedor": "groq" | "local" | "mixto",
  "palabras": [{"texto": "Hola,", "inicio": 0.12, "fin": 0.45}, ...]
}
"""
import math
import os
import shutil
from difflib import SequenceMatcher
from pathlib import Path

from . import audio, cache, red
from .consola import info, titulo
from .limites import Contadores
from .proveedores import transcripcion_groq as groq
from .proveedores import transcripcion_local as local
from .proveedores.base import ProveedorNoDisponible, RegistroProveedores, ejecutar_con_respaldo
from .texto import normalizar

_VERSION = 2  # súbelo si cambia el formato para invalidar la caché vieja
PASO = "transcripción"


def _planear_partes(duracion: float, cfg: dict) -> list[tuple[float, float]]:
    """Divide en tramos que quepan en el límite de MB de Groq, con traslape."""
    g = cfg["groq"]
    max_mb = float(os.environ.get("GROQ_MAX_MB_PRUEBA", g["max_mb_por_parte"]))  # solo para pruebas
    bytes_por_s = g["kbps"] * 1000 / 8
    max_s = max_mb * 1e6 / bytes_por_s
    if duracion <= max_s:
        return [(0.0, duracion)]
    traslape = g["traslape_s"]
    n = math.ceil((duracion - traslape) / (max_s - traslape))
    paso = (duracion - traslape) / n
    return [(i * paso, min(duracion, i * paso + paso + traslape)) for i in range(n)]


def _centro(p: dict) -> float:
    return (p["inicio"] + p["fin"]) / 2


def _unir_partes(resultados: list[tuple[tuple[float, float], dict]]) -> list[dict]:
    """Une las palabras de partes traslapadas sin duplicar lo que se oye en ambas.

    En la zona de traslape se buscan las mismas palabras (por texto) en las dos partes:
    se conserva la parte anterior hasta la coincidencia y la nueva desde ahí. Si no hay
    coincidencia fiable, se corta a la mitad del traslape por tiempo.
    """
    total: list[dict] = []
    for i, ((inicio, _fin), res) in enumerate(resultados):
        nuevas = [{"texto": p["texto"], "inicio": round(p["inicio"] + inicio, 3),
                   "fin": round(p["fin"] + inicio, 3)} for p in res["palabras"]]
        if i == 0:
            total = nuevas
            continue
        fin_anterior = resultados[i - 1][0][1]
        zona_a = [k for k, p in enumerate(total) if p["fin"] > inicio - 0.5]
        zona_b = [k for k, p in enumerate(nuevas) if p["inicio"] < fin_anterior + 0.5]
        if zona_a and zona_b:
            ta = [normalizar(total[k]["texto"]) for k in zona_a]
            tb = [normalizar(nuevas[k]["texto"]) for k in zona_b]
            m = SequenceMatcher(None, ta, tb, autojunk=False).find_longest_match(0, len(ta), 0, len(tb))
            if m.size >= 2 or (m.size == 1 and abs(total[zona_a[m.a]]["inicio"]
                                                   - nuevas[zona_b[m.b]]["inicio"]) < 0.6):
                total = total[:zona_a[m.a]] + nuevas[zona_b[m.b]:]
                continue
        corte = (inicio + fin_anterior) / 2
        total = [p for p in total if _centro(p) < corte] + [p for p in nuevas if _centro(p) >= corte]
    # No se ordena por tiempo: el orden del texto es el correcto aunque algún timestamp venga mal
    return _sanear_tiempos(total)


def _sanear_tiempos(palabras: list[dict]) -> list[dict]:
    """Evita solapes: si una palabra empieza antes de que termine la anterior, se ajusta.

    Groq a veces da a una palabra un inicio anterior al de la palabra previa.
    """
    fin_anterior = 0.0
    for p in palabras:
        if p["inicio"] < fin_anterior:
            p["inicio"] = fin_anterior
        if p["fin"] < p["inicio"] + 0.02:
            p["fin"] = round(p["inicio"] + 0.02, 3)
        fin_anterior = p["fin"]
    return palabras


def transcribir_audio(fuente: Path, cfg: dict, registro: RegistroProveedores, contadores: Contadores,
                      pista: int | None = None, forzar: bool = False) -> dict:
    titulo("Transcripción")
    clave = cache.clave(cache.huella_archivo(fuente), pista, _VERSION)
    ruta_cache = cache.carpeta("transcripciones") / f"{clave}.json"
    guardada = None if forzar else cache.leer_json(ruta_cache)
    if guardada:
        registro.anotar(PASO, "caché", "usado", detalle=f"transcrita antes con {guardada['proveedor']}")
        if guardada["proveedor"] != "groq" and not red.modo_local():
            info("(usa --forzar para volver a transcribir, p. ej. con Groq)")
        return guardada

    tmp = cache.carpeta("tmp") / f"transcripcion_{clave}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        wav = audio.extraer_wav16k(fuente, tmp / "voz_16k.wav", pista)
        duracion = audio.duracion(wav)
        info(f"audio: {fuente.name} ({duracion:.1f} s)" + (f", pista {pista}" if pista else ""))

        # Chequeo rápido de Groq antes de preparar nada para subir
        usar_groq = False
        if "groq" in cfg["proveedores"]["transcripcion"]:
            try:
                groq.comprobar(cfg)
                usar_groq = True
            except ProveedorNoDisponible as e:
                estado = "omitido" if red.modo_local() else "fallo"
                registro.anotar(PASO, "groq", estado, e.motivo)
                registro.marcar_caido("groq", e.motivo)

        partes = _planear_partes(duracion, cfg) if usar_groq else [(0.0, duracion)]
        if len(partes) > 1:
            info(f"el audio supera el límite de subida: lo divido en {len(partes)} partes")

        resultados, detalle_partes = [], []
        for i, (inicio, fin) in enumerate(partes, start=1):
            nombre_paso = PASO if len(partes) == 1 else f"{PASO} parte {i}/{len(partes)}"
            candidatos = []
            if usar_groq:
                candidatos.append(("groq", _tarea_groq(i, wav, inicio, fin, tmp, cfg, contadores)))
            candidatos.append(("local", _tarea_local(i, wav, inicio, fin, len(partes), tmp, cfg)))
            res, proveedor = ejecutar_con_respaldo(registro, nombre_paso, candidatos)
            resultados.append(((inicio, fin), res))
            detalle_partes.append({"indice": i, "inicio": round(inicio, 3), "fin": round(fin, 3),
                                   "proveedor": proveedor})
    finally:
        local.liberar()
        shutil.rmtree(tmp, ignore_errors=True)

    proveedores = {p["proveedor"] for p in detalle_partes}
    resultado = {
        "fuente": fuente.name,
        "pista": pista,
        "duracion": round(duracion, 3),
        "proveedor": proveedores.pop() if len(proveedores) == 1 else "mixto",
        "partes": detalle_partes,
        "palabras": _unir_partes(resultados),
    }
    if not resultado["palabras"]:
        raise RuntimeError("La transcripción salió vacía: ¿el audio tiene voz?")
    cache.escribir_json(ruta_cache, resultado)
    info(f"{len(resultado['palabras'])} palabras transcritas")
    return resultado


def _tarea_groq(i, wav, inicio, fin, tmp, cfg, contadores):
    def tarea():
        # Prueba de respaldo por parte: SIMULAR_FALLO_GROQ_PARTE=2 hace fallar la parte 2
        if os.environ.get("SIMULAR_FALLO_GROQ_PARTE", "").strip() == str(i):
            raise ProveedorNoDisponible("groq", "fallo simulado (SIMULAR_FALLO_GROQ_PARTE)")
        mp3 = audio.extraer_mp3(wav, tmp / f"parte_{i}.mp3", inicio, fin - inicio, cfg["groq"]["kbps"])
        return groq.transcribir_parte(mp3, fin - inicio, cfg, contadores)
    return tarea


def _tarea_local(i, wav, inicio, fin, total, tmp, cfg):
    def tarea():
        ruta = wav if total == 1 else audio.recortar(wav, tmp / f"parte_{i}.wav", inicio, fin - inicio)
        return local.transcribir(ruta, cfg)
    return tarea
