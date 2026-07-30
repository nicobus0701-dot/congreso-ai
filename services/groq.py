"""
Capa sobre el SDK de Groq: cliente, clasificación de errores y streaming
con reintento sobre rate limit.

Los límites relevantes son de tokens por minuto (TPM), no de requests:
llama-3.1-8b-instant tiene 6k TPM y llama-3.3-70b-versatile 12k TPM.
Por eso la Fase 3 (la pesada) siempre corre en el 70B.
"""
import asyncio
import re

from groq import Groq

import config
from config import logger

RETRY_FALLBACK_SECONDS = 12.0
MAX_ATTEMPTS = 3


def get_client(api_key: str | None = None, base_url: str | None = None) -> Groq:
    """
    Cliente para el proveedor configurado. Sin argumentos usa lo que haya en
    config (Groq por defecto, u otro proveedor OpenAI-compatible si el
    usuario cargó su propia key en el onboarding).
    """
    return Groq(
        api_key=api_key or config.LLM_API_KEY,
        base_url=base_url or (config.LLM_BASE_URL or None),
    )


# ── Clasificación de errores ─────────────────────────────────────────────────

def parse_retry_seconds(e) -> float:
    """Extrae los segundos de espera del mensaje de rate limit de Groq."""
    s = str(e)
    # "Please try again in 2.5s"
    m = re.search(r"try again in ([0-9.]+)s", s, re.IGNORECASE)
    if m:
        return float(m.group(1)) + 0.5
    # "try again in 750ms"
    m = re.search(r"try again in ([0-9.]+)ms", s, re.IGNORECASE)
    if m:
        return float(m.group(1)) / 1000 + 0.5
    # "try again in 1m30s"
    m = re.search(r"try again in (\d+)m(\d+(?:\.\d+)?)s", s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2)) + 0.5
    return RETRY_FALLBACK_SECONDS


def is_rate_limit(e) -> bool:
    s = str(e).lower()
    return any(x in s for x in ("rate limit", "429", "tokens per", "quota", "per day"))


def is_tool_format_error(e) -> bool:
    """El modelo generó un tool_call malformado — conviene reintentar sin tools."""
    s = str(e)
    return "tool_use_failed" in s or "failed_generation" in s or "400" in s


def friendly_error(e) -> str:
    """Traduce la excepción a un mensaje que se le puede mostrar al usuario."""
    s = str(e).lower()
    if "per day" in s or "tpd" in s:
        m = re.search(r"try again in ([0-9hms.]+)", s)
        cuando = "en un rato"
        if m:
            mins = re.search(r"(\d+)m", m.group(1))
            cuando = f"en ~{mins.group(1)} min" if mins else f"en {m.group(1)}"
        return f"Llegamos al límite de tokens por ahora. Vuelve a intentar {cuando}."
    if is_rate_limit(e):
        return "Muchas consultas muy rápido. Espera unos segundos y vuelve a intentarlo."
    return "Hubo un problema al conectar. Intentá de nuevo."


# ── Streaming ────────────────────────────────────────────────────────────────

async def stream_deltas(client, messages, *, model=None, max_tokens=2048,
                        temperature=0.4):
    """Itera los fragmentos de texto de una respuesta en streaming."""
    stream = client.chat.completions.create(
        model=model or config.MAIN_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def stream_with_retry(client, messages, *, model=None, max_tokens=2048,
                            temperature=0.4, on_retry=None):
    """
    Igual que stream_deltas pero reintenta ante rate limit, esperando el tiempo
    exacto que indica el proveedor en el error.

    Emite tuplas ("text", delta) o ("status", mensaje). Si tras MAX_ATTEMPTS
    sigue fallando, emite ("error", mensaje_amigable).
    """
    last_exc = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            async for delta in stream_deltas(client, messages, model=model,
                                             max_tokens=max_tokens,
                                             temperature=temperature):
                yield ("text", delta)
            return
        except Exception as e:
            last_exc = e
            if is_rate_limit(e) and attempt < MAX_ATTEMPTS - 1:
                wait = parse_retry_seconds(e)
                logger.warning("Rate limit del proveedor (intento %d/%d), esperando %.1fs",
                               attempt + 1, MAX_ATTEMPTS, wait)
                msg = f"Límite de la API, reintentando en {wait:.0f}s..."
                if on_retry:
                    on_retry(wait)
                yield ("status", msg)
                await asyncio.sleep(wait)
            else:
                break

    if last_exc:
        logger.error("Stream del LLM falló definitivamente: %s", last_exc)
        yield ("error", friendly_error(last_exc))
