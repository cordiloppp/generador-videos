"""Mensajes de consola sencillos y legibles."""
import sys


def configurar_consola() -> None:
    """Fuerza UTF-8 en la consola para que los acentos no rompan nada en Windows."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def titulo(texto: str) -> None:
    print(f"\n=== {texto} ===", flush=True)


def info(texto: str) -> None:
    print(f"  {texto}", flush=True)


def aviso(texto: str) -> None:
    print(f"  [aviso] {texto}", flush=True)


def error(texto: str) -> None:
    print(f"  [error] {texto}", file=sys.stderr, flush=True)


def progreso(etiqueta: str, fraccion: float) -> None:
    """Barra de progreso en una sola línea (se sobrescribe con \\r)."""
    fraccion = max(0.0, min(1.0, fraccion))
    llenos = int(fraccion * 30)
    barra = "#" * llenos + "-" * (30 - llenos)
    print(f"\r  {etiqueta} [{barra}] {fraccion * 100:5.1f}%", end="", flush=True)


def fin_progreso() -> None:
    print(flush=True)
