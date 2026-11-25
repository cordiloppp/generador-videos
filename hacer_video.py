"""Generador automático de videos verticales (TikTok / Shorts / Reels).

Ejemplos:
  python hacer_video.py --plantilla proyecto
  python hacer_video.py --plantilla proyecto --local
  python hacer_video.py --modo obs --entrada entrada/obs/partida1.mkv --plantilla juego
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

from generador import red
from generador.cache import carpeta
from generador.config import ENTRADA, RAIZ, SALIDA, cargar_config, cargar_env, crear_carpetas
from generador.consola import configurar_consola, error, fin_progreso, info, progreso, titulo
from generador.cortes import (calcular_tramos, cortar_audio, detectar_eliminables, detectar_silencios,
                              resumen, reubicar_frases, reubicar_palabras)
from generador.mejora_voz import mejorar_voz
from generador.entorno import ErrorFFmpeg, nvenc_disponible, ruta_ffmpeg, silenciar_librerias
from generador.frases import dividir_en_frases
from generador.limites import Contadores
from generador.obs import procesar_obs
from generador.plan import escribir_plan
from generador.plantillas import cargar_plantilla
from generador.proveedores.base import RegistroProveedores
from generador.prompts import generar_prompts
from generador.relleno import obtener_imagenes
from generador.render import render_fondo_negro, render_fragmentos
from generador.subtitulos import generar_ass
from generador.transcripcion import transcribir_audio
from generador.visual import componer_vertical, render_ken_burns, segmentos_visuales


def leer_argumentos():
    p = argparse.ArgumentParser(description="Genera un video vertical automáticamente.")
    p.add_argument("--modo", choices=["normal", "obs"], default="normal")
    p.add_argument("--plantilla", default="proyecto", help="nombre de plantillas/<nombre>.json")
    p.add_argument("--entrada", help="modo normal: audio de voz (por defecto entrada/voz.mp3); modo obs: grabación")
    p.add_argument("--local", action="store_true", help="todo en local, sin intentar ningún servicio")
    p.add_argument("--forzar", action="store_true", help="ignora la caché de transcripción y de prompts")
    p.add_argument("--sin-imagenes", action="store_true", help="modo normal: solo subtítulos sobre fondo negro")
    p.add_argument("--sin-cortes", action="store_true", help="no quitar silencios, repeticiones ni muletillas")
    p.add_argument("--sin-mejora", action="store_true", help="no procesar la voz (ruido, ecualización, compresor)")
    # Modo OBS
    p.add_argument("--max-duracion", type=float, help="obs: duración máxima del short en segundos (p. ej. 60)")
    p.add_argument("--partes", type=int, help="obs: cuántos shorts sacar de una grabación larga")
    p.add_argument("--separar-voz", action="store_true", help="obs: aislar la voz con Demucs (próximamente)")
    p.add_argument("--insertar-material", action="store_true", help="obs: b-roll de clips/imágenes (próximamente)")
    return p.parse_args()


def modo_animado(voz, transcripcion, frases, plantilla, cfg, registro, contadores, args, salida, extra) -> str:
    """Estilo 'escenario de papel': todo se dibuja por código (sin imágenes de IA)."""
    from generador.animacion.guion_visual import generar_guion
    from generador.animacion.motor import Animacion, renderizar_animacion

    vis, cfg_video = plantilla["visual"], cfg["video"]
    duracion = transcripcion["duracion"]
    segmentos = segmentos_visuales(frases, duracion, float(vis.get("max_fragmento_s", 5)), cfg_video["fps"])
    info(f"{len(segmentos)} escenas (máximo {vis.get('max_fragmento_s', 5)} s cada una)")
    guion = generar_guion(segmentos, plantilla, cfg, registro, contadores, forzar=args.forzar)
    info(f"título: {guion['titulo']['linea1']} / {guion['titulo']['linea2']}  (paleta {guion['paleta']})")
    for s, e in zip(segmentos, guion["escenas"]):
        extras = ([f"contador {e['contador']['valor']:g}"] if e["contador"] else []) + e["etiquetas"]
        info(f"  {s['inicio']:5.1f}s  {e['objeto_elegido'] or '-':<22} {', '.join(extras)}")

    titulo("Render")
    anim = Animacion(guion, segmentos, transcripcion["palabras"], duracion, vis)
    codificador = renderizar_animacion(anim, voz, salida, cfg_video)
    extra["visual"] = "animado"
    extra["guion_visual"] = {
        "proveedor": guion["proveedor"], "titulo": guion["titulo"], "paleta": guion["paleta"],
        "escenas": [{"inicio": round(s["inicio"], 3), "fin": round(s["fin"], 3), "texto": s["texto"],
                     "objeto": e["objeto_elegido"], "contador": e["contador"], "etiquetas": e["etiquetas"],
                     "mascota": e["mascota"]} for s, e in zip(segmentos, guion["escenas"])],
    }
    return codificador


def buscar_grabacion_obs(entrada: str | None) -> Path:
    """--entrada, o si no se indica, la grabación más reciente de entrada/obs/."""
    if entrada:
        ruta = Path(entrada)
        ruta = ruta if ruta.is_absolute() else RAIZ / ruta
        if not ruta.exists():
            raise FileNotFoundError(f"No encuentro la grabación: {ruta}")
        return ruta
    candidatas = [p for p in (ENTRADA / "obs").iterdir() if p.suffix.lower() in (".mkv", ".mp4", ".mov", ".flv")]
    if not candidatas:
        raise FileNotFoundError("No hay grabaciones en entrada/obs/ (usa --entrada ruta/al/archivo.mkv)")
    ruta = max(candidatas, key=lambda p: p.stat().st_mtime)
    info(f"sin --entrada: uso la grabación más reciente, {ruta.name}")
    return ruta


def modo_normal(args, cfg, plantilla, registro, contadores) -> Path:
    voz = Path(args.entrada) if args.entrada else ENTRADA / "voz.mp3"
    if not voz.is_absolute():
        voz = RAIZ / voz
    if not voz.exists():
        raise FileNotFoundError(f"No encuentro el audio de voz: {voz}")

    transcripcion = transcribir_audio(voz, cfg, registro, contadores, forzar=args.forzar)

    marca = time.strftime("%Y-%m-%d_%H%M%S")
    nombre = f"{marca}_{plantilla['nombre']}"
    tmp = carpeta("tmp") / f"render_{nombre}"
    tmp.mkdir(parents=True, exist_ok=True)
    cfg_video = cfg["video"]
    extra = {"modo_local": red.modo_local()}

    # Mejora de voz (reducción de ruido + procesado tipo podcast), todo local
    if cfg["mejora_voz"].get("activar", True) and not args.sin_mejora:
        voz_procesada, extra["mejora_voz"] = mejorar_voz(voz, cfg["mejora_voz"])
    else:
        voz_procesada = voz

    # Jump cuts: silencios reales del audio + repeticiones y muletillas
    cfg_cortes = plantilla["cortes"]
    if cfg_cortes.get("activar", True) and not args.sin_cortes:
        titulo("Cortes")
        palabras = transcripcion["palabras"]
        eliminadas = detectar_eliminables(palabras) if cfg_cortes.get("quitar_repeticiones", True) else {}
        silencio_max = float(cfg_cortes["silencio_max_s"])
        silencios = detectar_silencios(voz_procesada, silencio_max, cfg_cortes.get("umbral_silencio_db", "auto"))
        tramos = calcular_tramos(palabras, transcripcion["duracion"], cfg_video["fps"], silencio_max,
                                 float(cfg_cortes["margen_s"]), eliminadas, silencios)
        extra["cortes"] = resumen(palabras, eliminadas, transcripcion["duracion"], tramos)
        voz_final = cortar_audio(voz_procesada, 1, 0.0, transcripcion["duracion"] + 0.5, tramos,
                                 tmp / "voz_cortada.wav")
        # Las frases se dividen sobre el audio original (sus pausas marcan las ideas) y luego se reubican
        conservadas = [p for i, p in enumerate(palabras) if i not in eliminadas]
        frases = reubicar_frases(dividir_en_frases(conservadas, cfg["frases"]), tramos)
        transcripcion = {**transcripcion, "palabras": reubicar_palabras(palabras, tramos, eliminadas),
                         "duracion": round(sum(b - a for a, b in tramos), 3)}
    else:
        voz_final = voz_procesada
        frases = dividir_en_frases(transcripcion["palabras"], cfg["frases"])
    voz_original, voz = voz, voz_final

    titulo("Frases y subtítulos")
    info(f"{len(frases)} frases")
    for f in frases:
        info(f"  {f['indice']:>3}. [{f['inicio']:6.2f}-{f['fin']:6.2f}] {f['texto']}")

    ass = generar_ass(frases, plantilla["subtitulos"], tmp / "subtitulos.ass", cfg_video["ancho"], cfg_video["alto"])
    duracion = transcripcion["duracion"]
    salida = SALIDA / f"{nombre}.mp4"

    if args.sin_imagenes:
        titulo("Render")
        codificador = render_fondo_negro(voz, ass, salida, duracion, cfg_video)
        extra["visual"] = "fondo negro (--sin-imagenes)"
    elif plantilla["visual"].get("tipo") == "animado":
        codificador = modo_animado(voz, transcripcion, frases, plantilla, cfg, registro, contadores, args,
                                   salida, extra)
    else:
        vis = plantilla["visual"]
        segmentos = segmentos_visuales(frases, duracion, float(vis["max_fragmento_s"]), cfg_video["fps"])
        info(f"{len(segmentos)} fragmentos visuales (máximo {vis['max_fragmento_s']} s cada uno)")
        prompts = generar_prompts(segmentos, plantilla, cfg, registro, contadores, forzar=args.forzar)
        imagenes = obtener_imagenes(prompts, cfg, registro, contadores, tmp)

        titulo("Render")
        lista = []
        for k, (seg, img) in enumerate(zip(segmentos, imagenes)):
            progreso("fragmentos", k / len(segmentos))
            comp = componer_vertical(img["archivo"], tmp / f"comp_{k:03d}.jpg", cfg_video["ancho"], cfg_video["alto"])
            clip = tmp / f"frag_{k:03d}.mp4"
            acercar = not (vis["alternar_zoom"] and k % 2)
            render_ken_burns(comp, clip, seg["cuadros"], float(vis["ken_burns_zoom"]), acercar, cfg_video)
            lista.append(f"file '{clip.name}'")
            seg["visual"] = {"tipo": "imagen_ia", "proveedor": img["proveedor"], "prompt": img["prompt"],
                             "archivo": img["archivo"].name, "desde_cache": img["cache"],
                             "zoom": "acercar" if acercar else "alejar"}
        progreso("fragmentos", 1.0)
        fin_progreso()
        (tmp / "lista.txt").write_text("\n".join(lista), encoding="utf-8")
        codificador = render_fragmentos(tmp / "lista.txt", voz, ass, salida, duracion, cfg_video)
        extra["segmentos_visuales"] = [
            {"indice": s["indice"], "inicio": round(s["inicio"], 3), "fin": round(s["fin"], 3),
             "texto": s["texto"], **s["visual"]} for s in segmentos]
    shutil.copy(ass, SALIDA / f"{nombre}.ass")  # útil para revisar los subtítulos

    ruta_plan = escribir_plan(SALIDA / f"{nombre}.plan.json", modo="normal", plantilla=plantilla["nombre"],
                              entrada=(voz_original.relative_to(RAIZ) if voz_original.is_relative_to(RAIZ)
                                       else voz_original).as_posix(),
                              salida=salida.name, transcripcion=transcripcion, frases=frases,
                              registro=registro, codificador=codificador, extra=extra)
    shutil.rmtree(tmp, ignore_errors=True)
    info(f"plan: {ruta_plan.name}")
    return salida


def main() -> int:
    configurar_consola()
    silenciar_librerias()
    args = leer_argumentos()
    crear_carpetas()
    cargar_env()
    cfg = cargar_config()
    if args.local:
        red.activar_modo_local()

    titulo("Inicio")
    try:
        info(f"ffmpeg: {ruta_ffmpeg()}")
        info(f"codificador: {'h264_nvenc' if nvenc_disponible() else 'libx264 (NVENC no disponible)'}")
        info("modo: " + args.modo + (" (solo local)" if args.local else ""))
        plantilla = cargar_plantilla(args.plantilla)
        registro, contadores = RegistroProveedores(), Contadores()
        inicio = time.time()

        if args.modo == "obs":
            salidas = procesar_obs(buscar_grabacion_obs(args.entrada), args, cfg, plantilla, registro, contadores)
        else:
            salidas = [modo_normal(args, cfg, plantilla, registro, contadores)]

        titulo("Listo")
        for salida in salidas:
            info(f"video: {salida}")
        info(f"tiempo total: {time.time() - inicio:.1f} s")
        return 0
    except (FileNotFoundError, NotImplementedError, ErrorFFmpeg, RuntimeError) as e:
        error(str(e))
        return 1
    except KeyboardInterrupt:
        error("cancelado")
        return 130


if __name__ == "__main__":
    sys.exit(main())
