"""Render con ffmpeg: NVENC con respaldo a libx264 y barra de progreso."""
import subprocess
import tempfile
from pathlib import Path

from .consola import aviso, fin_progreso, info, progreso
from .entorno import ErrorFFmpeg, argumentos_codec, nvenc_disponible, ruta_ffmpeg


def _ejecutar_con_progreso(argumentos: list, duracion: float, etiqueta: str, cwd: Path | None) -> None:
    comando = [ruta_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
               "-progress", "pipe:1", "-nostats", *map(str, argumentos)]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log:
        proceso = subprocess.Popen(comando, cwd=cwd, stdout=subprocess.PIPE, stderr=log,
                                   text=True, encoding="utf-8", errors="replace")
        for linea in proceso.stdout:
            if linea.startswith("out_time_us=") and duracion > 0:
                try:
                    progreso(etiqueta, int(linea.split("=")[1]) / 1e6 / duracion)
                except ValueError:
                    pass
        proceso.wait()
        fin_progreso()
        if proceso.returncode != 0:
            log.seek(0)
            cola = "\n".join(log.read().strip().splitlines()[-8:])
            raise ErrorFFmpeg(f"ffmpeg falló (código {proceso.returncode}):\n{cola}")


def renderizar(construir_args, duracion: float, cfg_video: dict, etiqueta: str = "render",
               cwd: Path | None = None) -> str:
    """construir_args(codec_args) -> lista de argumentos. Devuelve el codificador usado."""
    intentos = (["h264_nvenc"] if nvenc_disponible() else []) + ["libx264"]
    if "h264_nvenc" not in intentos:
        aviso("NVENC no disponible: uso libx264 (más lento)")
    for codec in intentos:
        try:
            _ejecutar_con_progreso(construir_args(argumentos_codec(cfg_video, codec == "h264_nvenc")),
                                   duracion, f"{etiqueta} ({codec})", cwd)
            return codec
        except ErrorFFmpeg as e:
            if codec == intentos[-1]:
                raise
            aviso(f"{codec} falló, reintento con libx264:\n{e}")
    raise ErrorFFmpeg("no se pudo renderizar")


def filtro_voz(cfg_video: dict) -> str:
    """Filtro de audio de la voz: mono -> estéreo y volumen normalizado para redes."""
    filtros = ["aresample=48000", "aformat=channel_layouts=stereo"]
    if cfg_video.get("normalizar_volumen", True):
        filtros.insert(0, f"loudnorm=I={cfg_video['lufs']}:TP=-1.5:LRA=11")
    return ",".join(filtros)


def render_fragmentos(lista: Path, voz: Path, ass: Path, salida: Path, duracion: float, cfg_video: dict) -> str:
    """Une los fragmentos ya renderizados (lista para el demuxer concat) + subtítulos + voz."""
    info(f"render final -> {salida.name}")

    def args(codec):
        return [
            "-f", "concat", "-safe", "0", "-i", lista.name, "-i", voz,
            "-filter_complex", f"[0:v]ass=filename={ass.name}[v];[1:a]{filtro_voz(cfg_video)}[a]",
            "-map", "[v]", "-map", "[a]", *codec,
            "-c:a", "aac", "-b:a", f"{cfg_video['audio_kbps']}k", "-movflags", "+faststart", "-shortest", salida,
        ]

    return renderizar(args, duracion, cfg_video, "render", cwd=lista.parent)


def render_fondo_negro(voz: Path, ass: Path, salida: Path, duracion: float, cfg_video: dict) -> str:
    """Fase 1: fondo negro + subtítulos quemados + voz."""
    ancho, alto, fps = cfg_video["ancho"], cfg_video["alto"], cfg_video["fps"]
    info(f"render: {ancho}x{alto} @ {fps} fps -> {salida.name}")

    def args(codec):
        return [
            "-f", "lavfi", "-i", f"color=c=black:s={ancho}x{alto}:r={fps}:d={duracion:.3f}",
            "-i", voz,
            # La ruta del .ass es relativa a cwd para evitar el escape de "C:\" en el filtro
            "-filter_complex", f"[0:v]ass=filename={ass.name}[v];[1:a]{filtro_voz(cfg_video)}[a]",
            "-map", "[v]", "-map", "[a]", *codec,
            "-c:a", "aac", "-b:a", f"{cfg_video['audio_kbps']}k",
            "-movflags", "+faststart", "-shortest", salida,
        ]

    return renderizar(args, duracion, cfg_video, "render", cwd=ass.parent)
