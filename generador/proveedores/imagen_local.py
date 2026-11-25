"""Respaldo local de imágenes: SD-Turbo con diffusers en la GPU (fp32, adecuado para Pascal)."""
import gc
import io

from ..consola import aviso, info

NOMBRE = "sd_turbo"

_pipe = None
_dispositivo = None


def _cargar(cfg: dict, dispositivo: str):
    global _pipe, _dispositivo
    if _pipe is not None and _dispositivo == dispositivo:
        return _pipe
    liberar()
    import torch
    from diffusers import AutoPipelineForText2Image
    s = cfg["sd_turbo"]
    opciones = dict(dtype=torch.float32, variant="fp16")  # se descargan pesos fp16 y se usan en fp32
    try:
        pipe = AutoPipelineForText2Image.from_pretrained(s["modelo"], local_files_only=True, **opciones)
    except Exception:
        info(f"descargando {s['modelo']} (solo la primera vez, ~2.5 GB)...")
        pipe = AutoPipelineForText2Image.from_pretrained(s["modelo"], **opciones)
    pipe.set_progress_bar_config(disable=True)
    pipe.enable_attention_slicing()
    _pipe = pipe.to(dispositivo)
    _dispositivo = dispositivo
    info(f"SD-Turbo cargado en {dispositivo.upper()} (fp32)")
    return _pipe


def _generar_con(pipe, dispositivo, prompt, semilla, s) -> bytes:
    import torch
    generador = torch.Generator(device=dispositivo).manual_seed(semilla)
    imagen = pipe(prompt=prompt, num_inference_steps=s["pasos"], guidance_scale=0.0,
                  width=s["ancho"], height=s["alto"], generator=generador).images[0]
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def generar(prompt: str, semilla: int, cfg: dict) -> bytes:
    import torch
    s = cfg["sd_turbo"]
    if torch.cuda.is_available():
        try:
            return _generar_con(_cargar(cfg, "cuda"), "cuda", prompt, semilla, s)
        except Exception as e:
            aviso(f"SD-Turbo en GPU falló ({type(e).__name__}: {str(e)[:120]}); sigo en CPU (lento)")
    return _generar_con(_cargar(cfg, "cpu"), "cpu", prompt, semilla, s)


def liberar() -> None:
    global _pipe, _dispositivo
    if _pipe is None:
        return
    _pipe, _dispositivo = None, None
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass
