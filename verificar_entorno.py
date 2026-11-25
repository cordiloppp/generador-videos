"""Comprueba que el equipo tiene todo lo necesario y dice cómo instalar lo que falte.

  python verificar_entorno.py
"""
import importlib.util
import platform
import subprocess
import sys

from generador import red
from generador.config import cargar_env, clave
from generador.consola import configurar_consola, info, titulo
from generador.entorno import ErrorFFmpeg, nvenc_disponible, preparar_dlls_cuda, ruta_ffmpeg

OK, MAL, OPC = "[OK] ", "[FALTA]", "[--] "


def main() -> int:
    configurar_consola()
    cargar_env()
    problemas = 0

    titulo("Sistema")
    info(f"{platform.system()} {platform.release()} ({platform.version()})")
    v = sys.version_info
    if v[:2] >= (3, 10):
        info(f"{OK} Python {platform.python_version()} ({sys.executable})")
    else:
        problemas += 1
        info(f"{MAL} Python {platform.python_version()}: hace falta 3.10+ -> winget install Python.Python.3.11")

    titulo("ffmpeg")
    try:
        ruta = ruta_ffmpeg()
        version = subprocess.run([ruta, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        info(f"{OK} {version}")
        info(f"      {ruta}")
        if nvenc_disponible():
            info(f"{OK} h264_nvenc funciona (prueba de codificación real)")
        else:
            info(f"{MAL} h264_nvenc no funciona: se usará libx264 (más lento).")
            info("      Con driver 58x y GPU Pascal usa ffmpeg 8.0.x (gyan.dev, build full) en herramientas/ffmpeg/")
    except ErrorFFmpeg:
        problemas += 1
        info(f"{MAL} ffmpeg no encontrado: descarga el build 'full' de https://www.gyan.dev/ffmpeg/builds/")
        info("      y descomprímelo en herramientas/ffmpeg/ (debe existir herramientas/ffmpeg/bin/ffmpeg.exe)")

    titulo("GPU / CUDA")
    if importlib.util.find_spec("torch"):
        import torch
        if torch.cuda.is_available():
            arqs = torch.cuda.get_arch_list()
            info(f"{OK} torch {torch.__version__} con CUDA {torch.version.cuda}: {torch.cuda.get_device_name(0)}")
            if "sm_61" not in arqs:
                info(f"{MAL} esta build de torch no incluye Pascal (sm_61). Reinstala con cu126:")
                info("      pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126")
        else:
            info(f"{MAL} torch {torch.__version__} no ve la GPU. Reinstala con cu126 (ver README).")
    else:
        info(f"{OPC} torch no instalado (necesario a partir de la fase 3)")
    if importlib.util.find_spec("ctranslate2"):
        preparar_dlls_cuda()
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        tipos = sorted(ctranslate2.get_supported_compute_types("cuda")) if n else []
        info(f"{OK if n else MAL} faster-whisper / CTranslate2 {ctranslate2.__version__}: "
             f"{n} GPU, tipos {', '.join(tipos) or 'ninguno (usará CPU)'}")
    else:
        problemas += 1
        info(f"{MAL} faster-whisper no instalado -> pip install -r requirements.txt")

    titulo("Servicios gratuitos (claves en .env)")
    for nombre, var, url in [
        ("Groq (transcripción)", "GROQ_API_KEY", "https://api.groq.com/openai/v1/models"),
    ]:
        k = clave(var)
        if not k:
            info(f"{OPC} {nombre}: sin {var} -> se usará el respaldo local")
            continue
        try:
            red.verificar_servicio(var, url, timeout=5, headers={"Authorization": f"Bearer {k}"})
            info(f"{OK} {nombre}: clave válida y servicio accesible")
        except Exception as e:
            info(f"{OPC} {nombre}: no disponible ({getattr(e, 'motivo', e)}) -> respaldo local")

    titulo("Resultado")
    info("Todo listo." if problemas == 0 else f"Hay {problemas} problema(s) que resolver (arriba).")
    return 0 if problemas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
