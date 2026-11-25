"""Respaldo local para los prompts: traducción es->en con Helsinki-NLP/opus-mt-es-en (~300 MB, CPU)."""
from ..consola import info

NOMBRE = "traductor_local"
MODELO = "Helsinki-NLP/opus-mt-es-en"

_tokenizador = None
_modelo = None


def _cargar():
    global _tokenizador, _modelo
    if _modelo is not None:
        return
    from transformers import MarianMTModel, MarianTokenizer
    try:
        # Primero del disco (funciona sin internet)
        _tokenizador = MarianTokenizer.from_pretrained(MODELO, local_files_only=True)
        _modelo = MarianMTModel.from_pretrained(MODELO, local_files_only=True)
    except Exception:
        info(f"descargando el traductor local {MODELO} (solo la primera vez, ~300 MB)...")
        _tokenizador = MarianTokenizer.from_pretrained(MODELO)
        _modelo = MarianMTModel.from_pretrained(MODELO)
    _modelo.eval()


def traducir(textos: list[str]) -> list[str]:
    import torch
    _cargar()
    salida = []
    for i in range(0, len(textos), 16):
        lote = _tokenizador(textos[i:i + 16], return_tensors="pt", padding=True, truncation=True, max_length=256)
        with torch.no_grad():
            generado = _modelo.generate(**lote, max_new_tokens=200, num_beams=4)
        salida.extend(_tokenizador.batch_decode(generado, skip_special_tokens=True))
    return [s.strip() for s in salida]


def generar_prompts(textos: list[str], estilo: str) -> list[str]:
    return [f"{t.rstrip('.')}, {estilo}" for t in traducir(textos)]


def liberar() -> None:
    global _tokenizador, _modelo
    _tokenizador, _modelo = None, None
