"""Cortes automáticos (jump cuts): silencios, repeticiones y muletillas.

- Los silencios se miden en el AUDIO (silencedetect): los timestamps de Whisper/Groq a veces
  estiran una palabra para tapar una pausa ("para" de 4 s con 2 s de silencio dentro).
- Las repeticiones ("está hecho está hecho", "que que") y muletillas ("eh", "mmm") se detectan
  en la transcripción; se conserva la ÚLTIMA versión (suele ser la buena).
- Todos los bordes se alinean a cuadros (1/fps) para que audio y video sigan sincronizados.
"""
import bisect
import math
import re
import subprocess
import wave
from pathlib import Path

from .consola import info
from .entorno import ejecutar_ffmpeg, ruta_ffmpeg
from .texto import normalizar

MULETILLAS = {"eh", "ehh", "eeh", "em", "emm", "mm", "mmm", "hmm", "um", "uh", "ah", "ahh", "este eh"}
# Repeticiones de una palabra que suelen ser intencionales
DOBLES_PERMITIDAS = {"muy", "no", "si", "ya", "bien", "mas", "poco", "jaja", "ja", "rapido", "ahora"}


# --------------------------------------------------------------------------- detección
def detectar_eliminables(palabras: list[dict], muletillas=MULETILLAS, max_n: int = 4) -> dict[int, str]:
    """Índices de palabras a quitar -> motivo."""
    norm = [normalizar(p["texto"]) for p in palabras]
    eliminar: dict[int, str] = {}
    i = 0
    while i < len(norm):
        if norm[i] in muletillas:
            eliminar[i] = "muletilla"
            i += 1
            continue
        # Arranque en falso: "pa-" seguido de "para"
        if (i + 1 < len(norm) and len(norm[i]) >= 2 and norm[i + 1].startswith(norm[i]) and norm[i] != norm[i + 1]
                and palabras[i]["texto"].rstrip().endswith(("-", "…", "..."))):
            eliminar[i] = "arranque en falso"
            i += 1
            continue
        hecho = False
        for n in range(max_n, 0, -1):
            if i + 2 * n > len(norm):
                continue
            a, b = norm[i:i + n], norm[i + n:i + 2 * n]
            if a == b and all(a) and not (n == 1 and a[0] in DOBLES_PERMITIDAS):
                if palabras[i + n]["inicio"] - palabras[i + n - 1]["fin"] < 2.0:
                    for k in range(i, i + n):
                        eliminar[k] = "repetición"
                    i += n
                    hecho = True
                    break
        if not hecho:
            i += 1
    return eliminar


def detectar_silencios(wav: Path, minimo_s: float, umbral_db: float | str = "auto",
                       pista: int = 1) -> list[tuple[float, float]]:
    """Tramos de silencio de al menos 'minimo_s' (ffmpeg silencedetect) en la pista indicada."""
    if umbral_db == "auto":
        umbral_db = _umbral_auto(wav, pista)
    comando = [ruta_ffmpeg(), "-hide_banner", "-nostats", "-i", str(wav), "-map", f"0:a:{pista - 1}",
               "-af", f"silencedetect=noise={umbral_db}dB:d={minimo_s}", "-f", "null", "-"]
    r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    silencios, inicio = [], None
    for linea in r.stderr.splitlines():
        if m := re.search(r"silence_start: ([\d.]+)", linea):
            inicio = float(m.group(1))
        elif (m := re.search(r"silence_end: ([\d.]+)", linea)) and inicio is not None:
            silencios.append((inicio, float(m.group(1))))
            inicio = None
    if inicio is not None:
        silencios.append((inicio, math.inf))
    return silencios


def _umbral_auto(wav: Path, pista: int = 1) -> float:
    """Umbral de silencio relativo al volumen medio de la voz (entre -50 y -30 dB)."""
    comando = [ruta_ffmpeg(), "-hide_banner", "-nostats", "-i", str(wav), "-map", f"0:a:{pista - 1}",
               "-af", "volumedetect", "-f", "null", "-"]
    r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"mean_volume: (-?[\d.]+)", r.stderr)
    medio = float(m.group(1)) if m else -25.0
    return max(-50.0, min(-30.0, medio - 14))


# --------------------------------------------------------------------------- tramos
def _restar(tramos: list[list[float]], quitar: list[tuple[float, float]]) -> list[list[float]]:
    resultado = []
    for a, b in tramos:
        partes = [[a, b]]
        for qa, qb in quitar:
            nuevas = []
            for x, y in partes:
                if qb <= x or qa >= y:
                    nuevas.append([x, y])
                    continue
                if qa > x:
                    nuevas.append([x, qa])
                if qb < y:
                    nuevas.append([qb, y])
            partes = nuevas
        resultado.extend(partes)
    return resultado


def calcular_tramos(palabras: list[dict], duracion: float, fps: float, silencio_max: float, margen: float,
                    eliminadas: dict[int, str] | None = None,
                    silencios: list[tuple[float, float]] | None = None) -> list[list[float]]:
    """Tramos de la grabación que se conservan."""
    eliminadas = eliminadas or {}
    # 1) Por palabras: se corta en pausas largas y alrededor de las palabras eliminadas
    tramos: list[list[float]] = []
    anterior = None  # índice de la última palabra conservada
    for i, p in enumerate(palabras):
        if i in eliminadas:
            continue
        ini, fin = max(0.0, p["inicio"] - margen), min(duracion, p["fin"] + margen)
        if i - 1 in eliminadas:
            ini = max(ini, palabras[i - 1]["fin"])
        if i + 1 in eliminadas:
            fin = min(fin, palabras[i + 1]["inicio"])
        corte = anterior is None or (i - 1 != anterior) or (p["inicio"] - palabras[anterior]["fin"] > silencio_max)
        if tramos and not corte:
            tramos[-1][1] = max(tramos[-1][1], fin)
        else:
            tramos.append([ini, fin])
        anterior = i

    # 2) Por audio: se quitan los silencios reales (dejando 'margen' a cada lado)
    if silencios:
        quitar = [(a + margen, b - margen) for a, b in silencios if b - a >= silencio_max and b - a > 2 * margen]
        tramos = _restar(tramos, quitar)

    # 3) Alineación a cuadros y limpieza
    alineados: list[list[float]] = []
    tope = math.floor(duracion * fps) / fps
    for a, b in sorted(tramos):
        a, b = math.floor(a * fps) / fps, min(math.ceil(b * fps) / fps, tope)
        if b - a < 3 / fps:
            continue
        if alineados and a <= alineados[-1][1]:
            alineados[-1][1] = max(alineados[-1][1], b)
        else:
            alineados.append([a, b])
    return alineados


def mapear_tiempo(tramos: list[list[float]], acumulado: list[float], inicios: list[float], t: float) -> float:
    """Tiempo de la grabación original -> tiempo en el video cortado (lo cortado se pega al siguiente tramo)."""
    i = bisect.bisect_right(inicios, t) - 1
    if i < 0:
        return 0.0
    a, b = tramos[i]
    return acumulado[i] + (min(t, b) - a)


def reubicar_palabras(palabras: list[dict], tramos: list[list[float]],
                      eliminadas: dict[int, str] | None = None) -> list[dict]:
    """Palabras con sus tiempos en el video cortado (sin las eliminadas)."""
    eliminadas = eliminadas or {}
    inicios = [a for a, _ in tramos]
    acumulado = [0.0]
    for a, b in tramos:
        acumulado.append(acumulado[-1] + b - a)
    total = acumulado[-1]
    nuevas = []
    for i, p in enumerate(palabras):
        if i in eliminadas:
            continue
        if p["fin"] <= tramos[0][0] - 0.05 or p["inicio"] >= tramos[-1][1] + 0.05:
            continue  # fuera de la parte elegida
        ini = mapear_tiempo(tramos, acumulado, inicios, p["inicio"])
        fin = mapear_tiempo(tramos, acumulado, inicios, p["fin"])
        if fin - ini < 0.06:  # palabra casi entera dentro de un corte: se le deja un instante
            fin = min(total, ini + 0.12)
        nuevas.append({"texto": p["texto"], "inicio": round(ini, 3), "fin": round(fin, 3)})
    return nuevas


def reubicar_frases(frases: list[dict], tramos: list[list[float]]) -> list[dict]:
    """Frases divididas sobre la grabación ORIGINAL (donde las pausas indican dónde acaba una idea),
    con sus tiempos pasados al video cortado."""
    salida = []
    for f in frases:
        palabras = reubicar_palabras(f["palabras"], tramos)
        if not palabras:
            continue
        salida.append({**f, "indice": len(salida) + 1, "inicio": palabras[0]["inicio"], "fin": palabras[-1]["fin"],
                       "texto": " ".join(p["texto"] for p in palabras), "palabras": palabras})
    return salida


# --------------------------------------------------------------------------- audio
def _offset_datos_wav(ruta: Path) -> int:
    with open(ruta, "rb") as f:
        cabecera = f.read(8192)
    pos = cabecera.find(b"data")
    if pos < 0:
        raise RuntimeError(f"WAV sin bloque 'data': {ruta}")
    return pos + 8


def cortar_audio(entrada: Path, pista: int, inicio: float, dur: float, tramos_rel: list[list[float]],
                 destino: Path, sr: int = 48000) -> Path:
    """Extrae una pista y concatena solo los tramos conservados, exacto a la muestra (estéreo 48 kHz)."""
    completo = destino.with_name(destino.stem + "_completo.wav")
    ejecutar_ffmpeg(["-ss", f"{inicio:.4f}", "-t", f"{dur:.4f}", "-i", entrada, "-map", f"0:a:{pista - 1}",
                     "-vn", "-ac", "2", "-ar", str(sr), "-c:a", "pcm_s16le", completo])
    bytes_muestra = 4
    offset = _offset_datos_wav(completo)
    with open(completo, "rb") as origen, wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        for a, b in tramos_rel:
            ia, ib = round(a * sr), round(b * sr)
            origen.seek(offset + ia * bytes_muestra)
            trozo = origen.read((ib - ia) * bytes_muestra)
            w.writeframes(trozo + b"\x00" * ((ib - ia) * bytes_muestra - len(trozo)))
    completo.unlink(missing_ok=True)
    return destino


def resumen(palabras: list[dict], eliminadas: dict[int, str], duracion: float, tramos: list[list[float]]) -> dict:
    conservado = sum(b - a for a, b in tramos)
    quitadas = [{"texto": palabras[i]["texto"], "inicio": palabras[i]["inicio"], "motivo": m}
                for i, m in sorted(eliminadas.items())]
    info(f"de {duracion:.1f} s quedan {conservado:.1f} s ({len(tramos)} tramos, "
         f"{duracion - conservado:.1f} s quitados)")
    if quitadas:
        info("palabras quitadas: " + ", ".join(f"'{q['texto']}' ({q['motivo']}, {q['inicio']:.1f}s)"
                                               for q in quitadas[:12]))
    return {"duracion_original": round(duracion, 3), "duracion_final": round(conservado, 3),
            "tramos_conservados": [[round(a, 3), round(b, 3)] for a, b in tramos], "palabras_quitadas": quitadas}
