"""Modo OBS: la grabación de OBS es el material principal.

Pasos:
  1. Detecta las pistas de audio y elige la de voz (plantilla: obs.pista_voz).
  2. Transcribe la voz (Groq -> local).
  3. Jump cuts: quita las pausas de más de 'silencio_max_s' sin cortar palabras.
  4. (Opcional) --max-duracion / --partes: elige los tramos donde más hablas.
  5. Render en una sola pasada: cortes + vertical + subtítulos + audio con ducking.
"""
import bisect
import math
import shutil
import time
from pathlib import Path

from . import audio, red
from .cache import carpeta, escribir_json
from .config import RAIZ, SALIDA
from .cortes import (calcular_tramos, cortar_audio, detectar_eliminables, detectar_silencios, resumen,
                     reubicar_frases)
from .consola import aviso, info, titulo
from .frases import dividir_en_frases
from .mejora_voz import mejorar_voz
from .render import filtro_voz, renderizar
from .subtitulos import generar_ass
from .texto import formato_tiempo
from .transcripcion import transcribir_audio
from .vertical import alto_facecam, filtro_vertical

_SILENCIO_DB = -55.0  # una pista con volumen medio por debajo de esto se considera vacía


# --------------------------------------------------------------------------- pistas
def elegir_pistas(entrada: Path, cfg_obs: dict) -> tuple[int, list[int]]:
    """Devuelve (pista_voz, pistas_juego). Los números empiezan en 1."""
    pistas = audio.pistas_audio(entrada)
    if not pistas:
        raise RuntimeError(f"{entrada.name} no tiene pistas de audio.")
    n = len(pistas)
    info(f"pistas de audio: {n}" + "".join(
        f"\n    {p['indice']}: {p['codec']}, {p['canales']} canales" + (f", '{p['titulo']}'" if p['titulo'] else "")
        for p in pistas))
    if n == 1:
        info("una sola pista (voz y juego mezclados): se transcribe tal cual")
        return 1, []

    voz = int(cfg_obs.get("pista_voz", 2))
    if not 1 <= voz <= n:
        aviso(f"pista_voz={voz} no existe (hay {n}); uso la pista {n}")
        voz = n
    volumenes = {p["indice"]: audio.volumen_medio(entrada, p["indice"]) for p in pistas}
    info("volumen medio: " + ", ".join(f"pista {k}: {v:.0f} dB" for k, v in volumenes.items()))
    if volumenes[voz] < _SILENCIO_DB:
        con_sonido = [k for k, v in volumenes.items() if v >= _SILENCIO_DB]
        if con_sonido:
            aviso(f"la pista {voz} parece vacía; uso la pista {con_sonido[-1]} como voz "
                  f"(revisa 'pista_voz' en la plantilla)")
            voz = con_sonido[-1]
    juego = [k for k in volumenes if k != voz and volumenes[k] >= _SILENCIO_DB]
    info(f"voz: pista {voz}; juego/escritorio: {', '.join(map(str, juego)) or 'ninguna con sonido'}")
    return voz, juego


# --------------------------------------------------------------------------- jump cuts
class Conservado:
    """K(t): segundos conservados entre 0 y t (para medir ventanas rápido)."""

    def __init__(self, tramos: list[list[float]]):
        self.inicios = [a for a, _ in tramos]
        self.tramos = tramos
        self.acumulado = [0.0]
        for a, b in tramos:
            self.acumulado.append(self.acumulado[-1] + (b - a))

    def hasta(self, t: float) -> float:
        i = bisect.bisect_right(self.inicios, t) - 1
        if i < 0:
            return 0.0
        a, b = self.tramos[i]
        return self.acumulado[i] + (min(t, b) - a)

    def entre(self, a: float, b: float) -> float:
        return self.hasta(b) - self.hasta(a)


# --------------------------------------------------------------------------- partes
def elegir_partes(frases: list[dict], tramos: list[list[float]], max_dur: float, n_partes: int,
                  margen: float) -> list[tuple[float, float, float]]:
    """Ventanas (inicio, fin, puntuación) de frases seguidas que, ya cortadas, duran <= max_dur.

    Puntuación = palabras por segundo en la grabación original (lo denso que hablas)
                 x lo llena que queda la ventana respecto a max_dur.
    """
    K = Conservado(tramos)
    candidatos = []
    j = 0
    for i in range(len(frases)):
        a = frases[i]["inicio"] - margen
        j = max(j, i)
        if K.entre(a, frases[i]["fin"] + margen) > max_dur:
            continue  # una sola frase ya es demasiado larga
        while j + 1 < len(frases) and K.entre(a, frases[j + 1]["fin"] + margen) <= max_dur:
            j += 1
        b = frases[j]["fin"] + margen
        dur = K.entre(a, b)
        palabras = sum(len(f["palabras"]) for f in frases[i:j + 1])
        puntuacion = palabras / max(b - a, 0.1) * min(1.0, dur / max_dur)
        candidatos.append((a, b, puntuacion, dur))

    elegidas = []
    for a, b, puntuacion, dur in sorted(candidatos, key=lambda c: -c[2]):
        if dur < max_dur * 0.5 and elegidas:
            continue
        if all(b <= ea or a >= eb for ea, eb, _ in elegidas):
            elegidas.append((a, b, puntuacion))
        if len(elegidas) == n_partes:
            break
    if len(elegidas) < n_partes:
        aviso(f"solo encontré {len(elegidas)} parte(s) de las {n_partes} pedidas")
    return elegidas


def recortar_tramos(tramos: list[list[float]], a: float, b: float, fps: float) -> list[list[float]]:
    a, b = math.floor(a * fps) / fps, math.ceil(b * fps) / fps
    return [[max(x, a), min(y, b)] for x, y in tramos if y > a and x < b and min(y, b) - max(x, a) >= 2 / fps]


# --------------------------------------------------------------------------- render
def _expresion(tramos: list[list[float]], fps: float) -> str:
    """Selección de cuadros. Se compara contra medio cuadro antes de cada borde para que el
    redondeo nunca meta ni quite un cuadro (así video y audio miden exactamente lo mismo)."""
    m = 0.5 / fps
    return "+".join(f"gte(t,{a - m:.5f})*lt(t,{b - m:.5f})" for a, b in tramos)


def _grafo(tramos_rel, n_juego, formato, cfg_obs, cfg_video, ass_nombre):
    """Entradas: 0 = video de OBS, 1 = voz cortada, 2.. = pistas de juego cortadas."""
    ancho, alto, fps = cfg_video["ancho"], cfg_video["alto"], cfg_video["fps"]
    expr = _expresion(tramos_rel, fps)

    vertical, formato_usado = filtro_vertical(formato, cfg_obs, ancho, alto)
    partes = [
        f"[0:v:0]fps={fps},select='{expr}',setpts=N/{fps}/TB[vsel]",
        vertical,
        f"[vvert]ass=filename={ass_nombre}[v]",
        f"[1:a]{filtro_voz(cfg_video)}" + ("[aout]" if not n_juego else ",asplit=2[voz][voz_clave]"),
    ]
    if n_juego:
        entradas_juego = [f"[{2 + k}:a]" for k in range(n_juego)]
        if n_juego > 1:
            partes.append("".join(entradas_juego) + f"amix=inputs={n_juego}:normalize=0[juego]")
        else:
            partes.append(f"{entradas_juego[0]}anull[juego]")
        vol = float(cfg_obs.get("volumen_juego", 0.25))
        partes.append(f"[juego]volume={vol}[juego_vol]")
        if cfg_obs.get("ducking", True):
            partes.append(f"[juego_vol][voz_clave]sidechaincompress=threshold={cfg_obs.get('ducking_umbral', 0.02)}"
                          f":ratio={cfg_obs.get('ducking_ratio', 6)}:attack=20:release=400[juego_d]")
        else:
            partes.append("[voz_clave]anullsink;[juego_vol]anull[juego_d]")
        partes.append("[voz][juego_d]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]")
    return ";\n".join(partes), formato_usado


def _render_parte(entrada: Path, tramos: list[list[float]], palabras: list[dict], nombre: str,
                  pista_voz, pistas_juego, cfg, plantilla, args_meta: dict, registro, transcripcion,
                  eliminadas: dict, voz: tuple[Path, int]):
    """voz = (archivo, pista) de donde sale la voz: la voz mejorada si existe, si no la pista de OBS."""
    cfg_obs, cfg_video = plantilla["obs"], cfg["video"]
    fps = cfg_video["fps"]
    inicio_lectura = tramos[0][0]
    fin_lectura = tramos[-1][1]
    tramos_rel = [[round(a - inicio_lectura, 4), round(b - inicio_lectura, 4)] for a, b in tramos]
    duracion = sum(b - a for a, b in tramos)

    conservadas = [p for i, p in enumerate(palabras) if i not in eliminadas]
    frases = reubicar_frases(dividir_en_frases(conservadas, cfg["frases"]), tramos)

    tmp = carpeta("tmp") / f"render_{nombre}"
    tmp.mkdir(parents=True, exist_ok=True)
    estilo = dict(plantilla["subtitulos"])
    if cfg_obs.get("formato") == "split" and cfg_obs.get("facecam"):
        # Subtítulos sobre la línea entre juego y facecam
        estilo["margen_inferior"] = alto_facecam(cfg_obs, cfg_video["alto"]) - int(estilo.get("tamano", 92)) // 2
    ass = generar_ass(frases, estilo, tmp / "subtitulos.ass", cfg_video["ancho"], cfg_video["alto"])
    grafo, formato_usado = _grafo(tramos_rel, len(pistas_juego), cfg_obs.get("formato", "blur"),
                                  cfg_obs, cfg_video, ass.name)
    (tmp / "grafo.txt").write_text(grafo, encoding="utf-8")

    salida = SALIDA / f"{nombre}.mp4"
    info(f"{len(tramos)} tramos, {duracion:.1f} s de video ({formato_usado}) -> {salida.name}")

    lectura = fin_lectura - inicio_lectura + 0.5
    info("cortando audio...")
    wavs = [cortar_audio(voz[0], voz[1], inicio_lectura, lectura, tramos_rel, tmp / "voz.wav")]
    wavs += [cortar_audio(entrada, p, inicio_lectura, lectura, tramos_rel, tmp / f"pista{p}.wav")
             for p in pistas_juego]

    def args(codec):
        return ["-ss", f"{inicio_lectura:.4f}", "-t", f"{lectura:.4f}",
                "-i", entrada, *[x for w in wavs for x in ("-i", w.name)], "-/filter_complex", "grafo.txt",
                "-map", "[v]", "-map", "[aout]", *codec,
                "-c:a", "aac", "-b:a", f"{cfg_video['audio_kbps']}k", "-movflags", "+faststart", salida]

    codificador = renderizar(args, duracion, cfg_video, "render", cwd=tmp)
    shutil.copy(ass, SALIDA / f"{nombre}.ass")
    shutil.rmtree(tmp, ignore_errors=True)

    plan = {
        "creado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "modo": "obs",
        "plantilla": plantilla["nombre"],
        "entrada": (entrada.relative_to(RAIZ) if entrada.is_relative_to(RAIZ) else entrada).as_posix(),
        "salida": salida.name,
        "codificador_video": codificador,
        "formato_vertical": formato_usado,
        "pistas": {"voz": pista_voz, "juego": pistas_juego},
        **args_meta,
        "transcripcion": {k: transcripcion[k] for k in ("proveedor", "partes", "duracion")},
        "proveedores": registro.eventos,
        "duracion_salida": round(duracion, 3),
        "tramos_conservados": [[round(a, 3), round(b, 3)] for a, b in tramos],
        "frases": [{"indice": f["indice"], "inicio": round(f["inicio"], 3), "fin": round(f["fin"], 3),
                    "texto": f["texto"]} for f in frases],
    }
    escribir_json(SALIDA / f"{nombre}.plan.json", plan)
    return salida


def procesar_obs(entrada: Path, args, cfg: dict, plantilla: dict, registro, contadores) -> list[Path]:
    cfg_obs = plantilla["obs"]
    titulo("Grabación de OBS")
    v = audio.info_video(entrada)
    info(f"{entrada.name}: {v['ancho']}x{v['alto']} @ {v['fps']} fps, {v['duracion'] / 60:.1f} min")
    pista_voz, pistas_juego = elegir_pistas(entrada, cfg_obs)
    if args.separar_voz:
        aviso("--separar-voz (Demucs) todavía no está disponible; transcribo la pista tal cual")
    if args.insertar_material:
        aviso("--insertar-material todavía no está disponible; uso solo la grabación")

    transcripcion = transcribir_audio(entrada, cfg, registro, contadores, pista=pista_voz, forzar=args.forzar)
    palabras = transcripcion["palabras"]

    # Mejora de voz y silencios reales: solo si el micrófono está en su propia pista
    # (con todo mezclado, la reducción de ruido se comería el audio del juego)
    voz, silencios, info_mejora = (entrada, pista_voz), None, None
    silencio_max = float(cfg_obs.get("silencio_max_s", 0.7))
    if pistas_juego:
        if cfg["mejora_voz"].get("activar", True) and not args.sin_mejora:
            voz_mejorada, info_mejora = mejorar_voz(entrada, cfg["mejora_voz"], pista=pista_voz)
            voz = (voz_mejorada, 1)
        silencios = detectar_silencios(voz[0], silencio_max, pista=voz[1])
    elif not args.sin_mejora:
        aviso("una sola pista mezclada: no aplico la mejora de voz (afectaría al audio del juego)")

    titulo("Jump cuts")
    fps = cfg["video"]["fps"]
    margen = float(cfg_obs.get("margen_s", 0.15))
    eliminadas = {} if args.sin_cortes or not cfg_obs.get("quitar_repeticiones", True) else detectar_eliminables(palabras)
    if args.sin_cortes:
        tramos = [[0.0, math.floor(v["duracion"] * fps) / fps]]
    else:
        tramos = calcular_tramos(palabras, v["duracion"], fps, silencio_max, margen, eliminadas, silencios)
    info_cortes = resumen(palabras, eliminadas, v["duracion"], tramos)
    conservado = info_cortes["duracion_final"]

    marca = time.strftime("%Y-%m-%d_%H%M%S")
    base = f"{marca}_{plantilla['nombre']}_obs"
    max_dur = args.max_duracion or (60 if args.partes else None)
    if args.partes and not args.max_duracion:
        aviso("--partes sin --max-duracion: uso 60 s por parte")

    if max_dur and conservado > max_dur:
        frases = dividir_en_frases(palabras, cfg["frases"])
        ventanas = elegir_partes(frases, tramos, max_dur, args.partes or 1, margen)
        trabajos = []
        for k, (a, b, puntuacion) in enumerate(ventanas, start=1):
            nombre = base if len(ventanas) == 1 else f"{base}_parte{k}"
            trabajos.append((nombre, recortar_tramos(tramos, a, b, fps),
                             {"parte": k, "ventana_original": [round(a, 2), round(b, 2)],
                              "puntuacion": round(puntuacion, 3)}))
            info(f"parte {k}: {formato_tiempo(a)} - {formato_tiempo(b)} de la grabación "
                 f"(puntuación {puntuacion:.2f})")
    else:
        if max_dur:
            info(f"ya dura {conservado:.1f} s (<= {max_dur} s): un solo video")
        trabajos = [(base, tramos, {})]

    salidas = []
    for nombre, tramos_parte, meta in trabajos:
        titulo(f"Render {nombre}")
        meta = {**meta, "modo_local": red.modo_local(), "mejora_voz": info_mejora,
                "palabras_quitadas": info_cortes["palabras_quitadas"]}
        salidas.append(_render_parte(entrada, tramos_parte, palabras, nombre, pista_voz, pistas_juego,
                                     cfg, plantilla, meta, registro, transcripcion, eliminadas, voz))
    return salidas
