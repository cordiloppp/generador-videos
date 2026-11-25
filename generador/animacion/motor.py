"""Motor de animación.

skia dibuja cada pieza UNA vez (papel, título, stickers, tarjetas) con buena calidad; en cada cuadro,
OpenCV las mueve, gira, escala y mezcla sobre el escenario (mucho más rápido que mezclar con skia).
Los cuadros se envían por tubería a ffmpeg (NVENC) junto con la voz.
"""
import math
import random
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import skia

from ..consola import aviso, fin_progreso, progreso
from ..entorno import ErrorFFmpeg, argumentos_codec, nvenc_disponible, ruta_ffmpeg
from ..render import filtro_voz
from . import dibujo
from .dibujo import ALTO, ANCHO, CENTRO_ESCENA, Y_MESA
from .mascota import dibujar_mascota
from .recursos import fuente, sticker

# (x, y, ángulo). Abajo a la derecha está la mascota: ahí nunca va una etiqueta.
POS_ETIQUETAS = [(800, 520, 6), (250, 1130, 4)]
POS_ETIQUETA_EXTRA = (260, 500, -5)  # arriba a la izquierda, solo si no hay contador
POS_CONTADOR = (230, 560, -4)
POS_MASCOTA = (905, Y_MESA + 2)
Y_PALABRAS = 1610


# --------------------------------------------------------------------------- curvas
def _lim(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def salir_atras(p: float, s: float = 1.9) -> float:
    """Sobrepasa un poco y vuelve: el típico 'pop'."""
    p = _lim(p) - 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def suave(p: float) -> float:
    return 1 - (1 - _lim(p)) ** 3


def entrar(p: float) -> float:
    return _lim(p) ** 3


# --------------------------------------------------------------------------- compositor
def a_capa(img: skia.Image) -> np.ndarray:
    """skia.Image -> array BGRA con alfa premultiplicado (lo que espera mezclar())."""
    return img.toarray(colorType=skia.kBGRA_8888_ColorType, alphaType=skia.kPremul_AlphaType)


def mezclar(destino: np.ndarray, capa: np.ndarray, x: int, y: int) -> None:
    """Mezcla 'capa' (premultiplicada) sobre 'destino' con su esquina en (x, y), recortando bordes."""
    h, w = capa.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(destino.shape[1], x + w), min(destino.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    src = capa[y0 - y:y1 - y, x0 - x:x1 - x]
    roi = destino[y0:y1, x0:x1]
    inv = cv2.bitwise_not(src[..., 3])
    cv2.add(src, cv2.multiply(roi, cv2.merge((inv, inv, inv, inv)), scale=1 / 255), dst=roi)


def poner(destino: np.ndarray, capa: np.ndarray, cx: float, cy: float, escala: float = 1.0,
          angulo: float = 0.0, alfa: float = 1.0) -> None:
    """Coloca una capa centrada en (cx, cy), con escala, giro (grados, horario) y opacidad."""
    if escala <= 0.01 or alfa <= 0.01:
        return
    h, w = capa.shape[:2]
    if abs(escala - 1) < 1e-3 and abs(angulo) < 1e-2:
        img = capa
    else:
        rad = math.radians(angulo)
        bw = int(abs(w * math.cos(rad)) * escala + abs(h * math.sin(rad)) * escala) + 2
        bh = int(abs(w * math.sin(rad)) * escala + abs(h * math.cos(rad)) * escala) + 2
        m = cv2.getRotationMatrix2D((w / 2, h / 2), -angulo, escala)
        m[0, 2] += bw / 2 - w / 2
        m[1, 2] += bh / 2 - h / 2
        img = cv2.warpAffine(capa, m, (bw, bh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                             borderValue=(0, 0, 0, 0))
    if alfa < 1:
        img = (img * alfa).astype(np.uint8)
    mezclar(destino, img, int(round(cx - img.shape[1] / 2)), int(round(cy - img.shape[0] / 2)))


def _formato_numero(valor: float, prefijo: str, sufijo: str) -> str:
    texto = f"{int(round(valor)):,}".replace(",", ".")  # 15.300 (separador de miles en español)
    return f"{prefijo}{texto}{sufijo}"


class Lienzo:
    """Superficie skia pequeña y reutilizable para piezas que cambian en cada cuadro."""

    def __init__(self, ancho: int, alto: int):
        self.superficie = skia.Surface(ancho, alto)
        self.lienzo = self.superficie.getCanvas()

    def capa(self) -> np.ndarray:
        return a_capa(self.superficie.makeImageSnapshot())


# --------------------------------------------------------------------------- animación
class Animacion:
    def __init__(self, guion: dict, segmentos: list[dict], palabras: list[dict], duracion: float,
                 cfg_visual: dict):
        self.duracion = duracion
        self.paleta = dibujo.PALETAS[guion["paleta"]]
        self.fondo = dibujo.fondo_escenario(self.paleta)
        self.titulo = a_capa(dibujo.imagen_titulo(guion["titulo"]["linea1"], guion["titulo"]["linea2"], self.paleta))
        marca = cfg_visual.get("marca") or ""
        if marca:
            # La firma es fija: se pinta una vez sobre el escenario
            mezclar(self.fondo, a_capa(dibujo.imagen_marca(marca)),
                    ANCHO // 2 - dibujo.imagen_marca(marca).width() // 2, Y_MESA + 120)
        self.palabras = palabras

        self.escenas = []
        stickers = {}
        for i, (seg, e) in enumerate(zip(segmentos, guion["escenas"])):
            capa = None
            if e.get("svg"):
                if e["svg"] not in stickers:
                    stickers[e["svg"]] = sticker(e["svg"], 470)
                capa = stickers[e["svg"]]
            contador = None
            if e.get("contador"):
                c = e["contador"]
                contador = {**c, "capa": a_capa(dibujo.imagen_tarjeta_contador(c["etiqueta"] or "TOTAL", semilla=i))}
            etiquetas = [a_capa(dibujo.imagen_etiqueta(t, dibujo.COLORES_ETIQUETA[(i + k) % len(dibujo.COLORES_ETIQUETA)],
                                                       semilla=i * 7 + k))
                         for k, t in enumerate(e.get("etiquetas", []))]
            self.escenas.append({"inicio": seg["inicio"], "fin": seg["fin"], "capa": capa, "svg": e.get("svg"),
                                 "contador": contador, "etiquetas": etiquetas, "mascota": e.get("mascota", "feliz")})

        self.grupos = self._grupos_palabras()
        self.lienzo_mascota = Lienzo(320, 360)
        self.lienzo_numero = Lienzo(360, 130)
        rnd = random.Random(5)
        self.parpadeos, t = [], 1.5
        while t < duracion + 5:
            self.parpadeos.append(t)
            t += rnd.uniform(2.2, 4.2)

    # ---------------------------------------------------------------- subtítulos en tarjetas
    def _grupos_palabras(self) -> list[dict]:
        """Grupos de hasta 3 palabras que caben en una fila; cada palabra con su tarjeta."""
        grupos, actual, ancho = [], [], 0
        for i, p in enumerate(self.palabras):
            texto = p["texto"].strip(" ,.;:\"“”«»()")
            if not texto:
                continue
            capa = a_capa(dibujo.imagen_palabra(texto, semilla=i))
            ancho_capa = capa.shape[1] - 20
            if actual and (len(actual) >= 3 or ancho + ancho_capa > 1000 or p["inicio"] - actual[-1]["fin"] > 0.6):
                grupos.append(actual)
                actual, ancho = [], 0
            actual.append({**p, "capa": capa, "angulo": random.Random(i).uniform(-3, 3)})
            ancho += ancho_capa
            if p["texto"].rstrip().endswith((".", "?", "!")):
                grupos.append(actual)
                actual, ancho = [], 0
        if actual:
            grupos.append(actual)
        resultado = []
        for k, g in enumerate(grupos):
            fin = g[-1]["fin"] + 0.35
            if k + 1 < len(grupos):
                siguiente = grupos[k + 1][0]["inicio"]
                fin = siguiente if siguiente - g[-1]["fin"] <= 0.3 else min(fin, siguiente)
            resultado.append({"inicio": g[0]["inicio"], "fin": fin, "palabras": g})
        return resultado

    def _hablando(self, t: float) -> bool:
        for p in self.palabras:
            if p["inicio"] > t:
                return False
            if p["inicio"] <= t <= p["fin"]:
                return True
        return False

    # ---------------------------------------------------------------- cuadro
    def dibujar(self, cuadro: np.ndarray, t: float) -> None:
        np.copyto(cuadro, self.fondo)
        escena = None
        for k, e in enumerate(self.escenas):
            if e["inicio"] - 0.01 <= t < e["fin"] or (k == len(self.escenas) - 1 and t >= e["inicio"]):
                escena = (k, e)
                break
        if escena:
            self._escena(cuadro, t, *escena)

        # Título: cae desde arriba al empezar y se balancea apenas
        p = t / 0.55
        destino_y = 75 + self.titulo.shape[0] / 2
        y = -250 + (250 + destino_y) * salir_atras(p, 1.4) if p < 1 else destino_y
        poner(cuadro, self.titulo, ANCHO / 2, y, angulo=-1.2 + 0.5 * math.sin(t * 1.3) - (1 - suave(p)) * 6)

        self._mascota(cuadro, t, escena[1] if escena else None)
        self._palabras(cuadro, t)

    def _escena(self, cuadro, t: float, k: int, e: dict) -> None:
        anterior = self.escenas[k - 1] if k > 0 else None
        siguiente = self.escenas[k + 1] if k + 1 < len(self.escenas) else None
        local, resto = t - e["inicio"], e["fin"] - t
        igual_antes = anterior is not None and anterior["svg"] == e["svg"]
        igual_despues = siguiente is not None and siguiente["svg"] == e["svg"]

        if e["capa"] is not None:
            escala = 1.0 if igual_antes else salir_atras(local / 0.45)
            giro = 0 if igual_antes else (1 - suave(local / 0.45)) * -14
            if not igual_despues and siguiente is not None and resto < 0.18:
                escala *= 1 - entrar(1 - resto / 0.18)
            poner(cuadro, e["capa"], CENTRO_ESCENA[0], CENTRO_ESCENA[1] + math.sin(t * 2.1) * 10, escala,
                  giro + math.sin(t * 1.6) * 2)

        salida = 1 - entrar(1 - resto / 0.15) if siguiente is not None and resto < 0.15 else 1.0
        c = e["contador"]
        if c:
            pc = (local - 0.25) / 0.4
            if pc > 0:
                x, y, ang = POS_CONTADOR
                escala = salir_atras(pc) * salida
                # Tarjeta + número dibujados juntos y colocados como una sola pieza
                tarjeta = c["capa"].copy()
                texto = _formato_numero(c["valor"] * suave((local - 0.35) / 1.3), c["prefijo"], c["sufijo"])
                tam = min(84, 300 / max(1, len(texto)) * 1.55)
                ln = self.lienzo_numero.lienzo
                ln.clear(skia.ColorTRANSPARENT)
                f = fuente("numero", tam)
                ln.drawString(texto, 180 - f.measureText(texto) / 2, 95, f, skia.Paint(Color=dibujo.TINTA, AntiAlias=True))
                numero = self.lienzo_numero.capa()
                mezclar(tarjeta, numero, tarjeta.shape[1] // 2 - 180, tarjeta.shape[0] // 2 - 40)
                poner(cuadro, tarjeta, x, y, escala, ang)
        posiciones = POS_ETIQUETAS + ([] if c else [POS_ETIQUETA_EXTRA])
        for i, capa in enumerate(e["etiquetas"][:len(posiciones)]):
            pe = (local - 0.45 - 0.22 * i) / 0.35
            if pe <= 0:
                continue
            x, y, ang = posiciones[i]
            poner(cuadro, capa, x, y + math.sin(t * 2 + i) * 4, salir_atras(pe) * salida, ang + (1 - suave(pe)) * 18)

    def _mascota(self, cuadro, t: float, escena: dict | None) -> None:
        salto, aplastar = 0.0, 0.0
        if escena:
            p = (t - escena["inicio"]) / 0.5
            if 0 <= p <= 1:
                salto = 75 * math.sin(math.pi * p)
                aplastar = 0.6 * (1 - p / 0.15) if p < 0.15 else -0.3 * math.sin(math.pi * p)
            elif 1 < p < 1.3:
                aplastar = 0.5 * math.sin(math.pi * (p - 1) / 0.3)
        parpadeo = 0.0
        for b in self.parpadeos:
            if b <= t < b + 0.14:
                parpadeo = 1.0
                break
            if b > t:
                break
        boca = (0.5 + 0.5 * abs(math.sin(t * 17))) if self._hablando(t) else 0.0
        brazo = max(0.0, math.sin(t * 9)) if 0.6 < t < 2.2 else 0.0
        mirar = (0.0, 0.0) if t < 2.2 else (-1.0, -0.2)
        ln = self.lienzo_mascota.lienzo
        ln.clear(skia.ColorTRANSPARENT)
        # La mascota se dibuja en su lienzo pequeño con los pies en (160, 330) y se coloca encima
        dibujar_mascota(ln, 160, 330, escala=0.95, salto=salto, aplastar=aplastar + 0.04 * math.sin(t * 3),
                        parpadeo=parpadeo, boca=boca, expresion=escena["mascota"] if escena else "feliz",
                        mirar=mirar, brazo=brazo)
        capa = self.lienzo_mascota.capa()
        mezclar(cuadro, capa, POS_MASCOTA[0] - 160, POS_MASCOTA[1] - 330)

    def _palabras(self, cuadro, t: float) -> None:
        grupo = next((g for g in self.grupos if g["inicio"] <= t < g["fin"]), None)
        if not grupo:
            return
        anchos = [p["capa"].shape[1] - 20 for p in grupo["palabras"]]
        total = sum(anchos)
        escala_fila = min(1.0, 1000 / total)
        x = ANCHO / 2 - total * escala_fila / 2
        for p, a in zip(grupo["palabras"], anchos):
            pp = (t - p["inicio"] + 0.04) / 0.2
            if pp > 0:
                poner(cuadro, p["capa"], x + a * escala_fila / 2, Y_PALABRAS, salir_atras(pp, 2.2) * escala_fila,
                      p["angulo"])
            x += a * escala_fila


# --------------------------------------------------------------------------- render
def renderizar_animacion(anim: Animacion, voz: Path, salida: Path, cfg_video: dict) -> str:
    """Genera los cuadros y los envía por tubería a ffmpeg. Devuelve el codificador usado."""
    fps = cfg_video["fps"]
    total = math.ceil(anim.duracion * fps)
    codecs = (["h264_nvenc"] if nvenc_disponible() else []) + ["libx264"]
    for codec in codecs:
        try:
            _render(anim, voz, salida, cfg_video, total, fps, codec == "h264_nvenc")
            return codec
        except ErrorFFmpeg as e:
            if codec == codecs[-1]:
                raise
            aviso(f"{codec} falló, reintento con libx264:\n{e}")
    raise ErrorFFmpeg("no se pudo renderizar")


def _render(anim, voz, salida, cfg_video, total, fps, nvenc):
    comando = [ruta_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{ANCHO}x{ALTO}", "-r", str(fps), "-i", "-",
               "-i", str(voz), "-filter_complex", f"[1:a]{filtro_voz(cfg_video)}[a]",
               "-map", "0:v", "-map", "[a]", *argumentos_codec(cfg_video, nvenc),
               "-c:a", "aac", "-b:a", f"{cfg_video['audio_kbps']}k", "-movflags", "+faststart", "-shortest",
               str(salida)]
    cuadro = np.empty((ALTO, ANCHO, 4), np.uint8)
    etiqueta = f"animación ({'h264_nvenc' if nvenc else 'libx264'})"
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log:
        proceso = subprocess.Popen(comando, stdin=subprocess.PIPE, stderr=log)
        try:
            for n in range(total):
                anim.dibujar(cuadro, n / fps)
                proceso.stdin.write(cuadro.data)
                if n % 15 == 0:
                    progreso(etiqueta, n / total)
            proceso.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        proceso.wait()
        fin_progreso()
        if proceso.returncode != 0:
            log.seek(0)
            raise ErrorFFmpeg(f"ffmpeg falló (código {proceso.returncode}):\n{log.read()[-800:]}")


def cuadro_de_muestra(anim: Animacion, t: float, destino: Path) -> Path:
    """Guarda un cuadro suelto como PNG (para revisar el diseño)."""
    cuadro = np.empty((ALTO, ANCHO, 4), np.uint8)
    anim.dibujar(cuadro, t)
    cv2.imwrite(str(destino), cuadro)
    return destino
