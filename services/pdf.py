"""
Extracción de texto y miniaturas de PDFs.

PyMuPDF (fitz) se importa dentro de cada función: es pesado y solo hace falta
cuando el usuario abre o sube un documento.
"""
import httpx

from config import logger

MAX_TEXT_CHARS = 40000
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"


async def download(url: str, timeout: int = 30) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        return await c.get(url, headers={"User-Agent": UA})


def extract_text(data: bytes) -> tuple[str, int]:
    """Devuelve (texto, número de páginas), recortado a MAX_TEXT_CHARS."""
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    pages = len(doc)
    text = "\n\n".join(page.get_text() for page in doc).strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f"\n\n[Texto recortado — documento original: {pages} páginas]"
    return text, pages


def render_thumbnail(data: bytes, zoom: float = 1.8) -> bytes:
    """PNG de la primera página."""
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png")


def looks_like_pdf(resp: httpx.Response) -> bool:
    """Heurística: algunos servidores del Congreso no mandan el content-type."""
    if resp.status_code != 200:
        return False
    ct = resp.headers.get("content-type", "application/pdf").lower()
    return "html" not in ct


def safe_extract_text(data: bytes) -> str:
    """extract_text tolerante a fallos — devuelve '' si el PDF no se puede leer."""
    try:
        text, _ = extract_text(data)
        return text
    except Exception as e:
        logger.debug("extract_text falló: %s", e)
        return ""
