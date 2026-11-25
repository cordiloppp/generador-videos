"""Detección de herramientas: ffmpeg, NVENC y librerías CUDA."""
import os
import platform
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import HERRAMIENTAS


class ErrorFFmpeg(RuntimeError):
    pass


def _buscar_binario(nombre: str) -> str | None:
    ext = ".exe" if platform.system() == "Windows" else ""
    local = HERRAMIENTAS / "ffmpeg" / "bin" / f"{nombre}{ext}"
    if local.exists():
        return str(local)
    return shutil.which(nombre)


@lru_cache(maxsize=None)
def ruta_ffmpeg() -> str:
    ruta = _buscar_binario("ffmpeg")
    if not ruta:
        raise ErrorFFmpeg("No se encontró ffmpeg. Ejecuta: python verificar_entorno.py")
    return ruta


@lru_cache(maxsize=None)
def ruta_ffprobe() -> str:
    ruta = _buscar_binario("ffprobe")
    if not ruta:
        raise ErrorFFmpeg("No se encontró ffprobe. Ejecuta: python verificar_entorno.py")
    return ruta


def ejecutar_ffmpeg(argumentos: list, cwd: Path | str | None = None) -> None:
    """Ejecuta ffmpeg sin mostrar nada; si falla, lanza ErrorFFmpeg con el final del log."""
    comando = [ruta_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *map(str, argumentos)]
    r = subprocess.run(comando, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        cola = "\n".join(r.stderr.strip().splitlines()[-8:])
        raise ErrorFFmpeg(f"ffmpeg falló (código {r.returncode}):\n{cola}")


@lru_cache(maxsize=None)
def nvenc_disponible() -> bool:
    """Prueba real: codifica 1 segundo con h264_nvenc (que aparezca en la lista no basta)."""
    try:
        ejecutar_ffmpeg(["-f", "lavfi", "-i", "color=black:s=1080x1920:r=30", "-t", "1",
                         "-c:v", "h264_nvenc", "-f", "null", "-"])
        return True
    except ErrorFFmpeg:
        return False


def argumentos_codec(config_video: dict, usar_nvenc: bool) -> list[str]:
    """Argumentos de ffmpeg para el codificador de video elegido."""
    comunes = ["-pix_fmt", "yuv420p", "-r", str(config_video["fps"])]
    if usar_nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr",
                "-cq", str(config_video["nvenc_cq"]), "-b:v", "10M", "-maxrate", "16M",
                "-bufsize", "20M", "-profile:v", "high", *comunes]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(config_video["x264_crf"]),
            "-profile:v", "high", *comunes]


def silenciar_librerias() -> None:
    """Oculta los avisos y barras de progreso de transformers/diffusers/huggingface_hub."""
    import warnings
    for var, valor in {"TRANSFORMERS_VERBOSITY": "error", "DIFFUSERS_VERBOSITY": "error",
                       "HF_HUB_VERBOSITY": "error", "HF_HUB_DISABLE_PROGRESS_BARS": "1",
                       "HF_HUB_DISABLE_TELEMETRY": "1", "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1"}.items():
        os.environ.setdefault(var, valor)
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning, module=r"(huggingface_hub|transformers|diffusers|torch)")


_dlls_preparadas = False


def preparar_dlls_cuda() -> None:
    """En Windows, hace visibles las DLL de CUDA/cuDNN que trae PyTorch para CTranslate2."""
    global _dlls_preparadas
    if _dlls_preparadas or platform.system() != "Windows":
        return
    _dlls_preparadas = True
    import importlib.util
    carpetas = []
    spec = importlib.util.find_spec("torch")
    if spec and spec.origin:
        carpetas.append(Path(spec.origin).parent / "lib")
    spec_nv = importlib.util.find_spec("nvidia")
    if spec_nv and spec_nv.submodule_search_locations:
        for base in spec_nv.submodule_search_locations:
            carpetas.extend(Path(base).glob("*/bin"))
    for carpeta in carpetas:
        if carpeta.is_dir():
            try:
                os.add_dll_directory(str(carpeta))
            except OSError:
                pass
            os.environ["PATH"] = str(carpeta) + os.pathsep + os.environ.get("PATH", "")
