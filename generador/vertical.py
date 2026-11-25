"""Filtros de ffmpeg para pasar video horizontal a vertical: blur, crop y split."""
from .consola import aviso


def _par(n: float) -> int:
    return int(round(n / 2)) * 2


def filtro_vertical(formato: str, cfg_obs: dict, ancho: int, alto: int,
                    entrada: str = "[vsel]", salida: str = "[vvert]") -> tuple[str, str]:
    """Devuelve (fragmento de filtergraph, formato realmente usado)."""
    if formato == "split":
        facecam = cfg_obs.get("facecam")
        if not facecam or len(facecam) != 4:
            aviso("formato 'split' sin 'facecam' [x, y, ancho, alto] en la plantilla: uso 'blur'")
            formato = "blur"

    if formato == "crop":
        cx = float(cfg_obs.get("crop_x", 0.5))  # 0 = izquierda, 0.5 = centro, 1 = derecha
        return (f"{entrada}scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
                f"crop={ancho}:{alto}:(iw-{ancho})*{cx}:(ih-{alto})/2,setsar=1{salida}"), "crop"

    if formato == "split":
        fx, fy, fw, fh = (float(v) for v in cfg_obs["facecam"])
        alto_juego = _par(alto * float(cfg_obs.get("split_alto_juego", 0.6)))
        alto_cam = alto - alto_juego
        return (f"{entrada}split=2[vs_a][vs_b];"
                f"[vs_a]scale={ancho}:{alto_juego}:force_original_aspect_ratio=increase,"
                f"crop={ancho}:{alto_juego}[vs_juego];"
                f"[vs_b]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},"
                f"scale={ancho}:{alto_cam}:force_original_aspect_ratio=increase,crop={ancho}:{alto_cam}[vs_cam];"
                f"[vs_juego][vs_cam]vstack,setsar=1{salida}"), "split"

    # blur (por defecto): video completo al centro sobre una copia desenfocada
    zoom = float(cfg_obs.get("zoom_blur", 1.0))
    ancho_frente = _par(ancho * zoom)
    recorte = f",crop={ancho}:ih" if ancho_frente > ancho else ""
    pa, pb = _par(ancho / 4), _par(alto / 4)  # se desenfoca en pequeño: mucho más rápido
    return (f"{entrada}split=2[vb_a][vb_b];"
            f"[vb_a]scale={pa}:{pb}:force_original_aspect_ratio=increase,crop={pa}:{pb},"
            f"boxblur=20:3,eq=brightness=-0.06,scale={ancho}:{alto},setsar=1[vb_fondo];"
            f"[vb_b]scale={ancho_frente}:-2{recorte}[vb_frente];"
            f"[vb_fondo][vb_frente]overlay=(W-w)/2:(H-h)/2{salida}"), "blur"


def alto_facecam(cfg_obs: dict, alto: int) -> int:
    return alto - _par(alto * float(cfg_obs.get("split_alto_juego", 0.6)))
