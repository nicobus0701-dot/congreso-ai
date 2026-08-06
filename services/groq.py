"""
Capa sobre el cliente LLM: cliente, clasificación de errores y streaming con
reintento sobre rate limit.

Habla siempre por el SDK de `openai` — mismo cliente sin importar si el
proveedor activo (config.LLM_PROVIDER) es Groq, Gemini o el propio OpenAI:
los tres exponen un endpoint compatible con el formato de chat completions de
OpenAI, así que solo cambia la URL base y la key. Ver config.py.

Los límites de cada proveedor son distintos (Groq: tokens por minuto; Gemini:
requests por día en el tier gratis) — parse_retry_seconds/is_rate_limit
reconocen los formatos de error de ambos.
"""
import asyncio
import re

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_PROVIDER, MAIN_MODEL, logger

_PROVIDER_LABEL = LLM_PROVIDER.capitalize()

RETRY_FALLBACK_SECONDS = 12.0
MAX_ATTEMPTS = 3

# Los modelos "flash" de Gemini piensan por default y, a través del shim de
# OpenAI, ese razonamiento se cuela como texto normal en la respuesta (se ve
# como el modelo "pensando en voz alta" antes de la respuesta real). Groq/
# OpenAI no tienen este comportamiento con sus modelos actuales, así que el
# parámetro solo se manda cuando el proveedor activo es Gemini.
_EXTRA_PARAMS = {"reasoning_effort": "low"} if LLM_PROVIDER == "gemini" else {}


def get_client(api_key: str | None = None) -> OpenAI:
    """Cliente del proveedor LLM activo. Sin argumento usa la key del entorno."""
    return OpenAI(api_key=api_key or LLM_API_KEY, base_url=LLM_BASE_URL)


# ── Clasificación de errores ─────────────────────────────────────────────────

def parse_retry_seconds(e) -> float:
    """Extrae los segundos de espera del mensaje de rate limit (Groq o Gemini)."""
    s = str(e)
    # Groq: "Please try again in 2.5s" / Gemini: "Please retry in 2.5s"
    m = re.search(r"(?:try again|retry) in ([0-9.]+)s", s, re.IGNORECASE)
    if m:
        return float(m.group(1)) + 0.5
    # "try again in 750ms"
    m = re.search(r"(?:try again|retry) in ([0-9.]+)ms", s, re.IGNORECASE)
    if m:
        return float(m.group(1)) / 1000 + 0.5
    # "try again in 1m30s"
    m = re.search(r"(?:try again|retry) in (\d+)m(\d+(?:\.\d+)?)s", s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2)) + 0.5
    # Gemini: retryDelay estilo protobuf, ej. "retryDelay': '17s'"
    m = re.search(r"retryDelay[\"']?\s*[:=]\s*[\"']?([0-9.]+)s", s, re.IGNORECASE)
    if m:
        return float(m.group(1)) + 0.5
    return RETRY_FALLBACK_SECONDS


def is_rate_limit(e) -> bool:
    s = str(e).lower()
    return any(x in s for x in ("rate limit", "429", "tokens per", "quota", "per day",
                                 "resource_exhausted", "resource exhausted"))


def is_tool_format_error(e) -> bool:
    """El modelo generó un tool_call malformado — conviene reintentar sin tools."""
    s = str(e)
    return "tool_use_failed" in s or "failed_generation" in s or "400" in s


def friendly_error(e) -> str:
    """Traduce la excepción a un mensaje que se le puede mostrar al usuario."""
    s = str(e).lower()
    if "per day" in s or "tpd" in s or "perday" in s:
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

async def stream_deltas(client, messages, *, model=MAIN_MODEL, max_tokens=2048,
                        temperature=0.4):
    """Itera los fragmentos de texto de una respuesta en streaming."""
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
        **_EXTRA_PARAMS,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def stream_with_retry(client, messages, *, model=MAIN_MODEL, max_tokens=2048,
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
                logger.warning("%s rate limit (intento %d/%d), esperando %.1fs",
                               _PROVIDER_LABEL, attempt + 1, MAX_ATTEMPTS, wait)
                msg = f"Límite de {_PROVIDER_LABEL}, reintentando en {wait:.0f}s..."
                if on_retry:
                    on_retry(wait)
                yield ("status", msg)
                await asyncio.sleep(wait)
            else:
                break

    if last_exc:
        logger.error("%s stream falló definitivamente: %s", _PROVIDER_LABEL, last_exc)
        yield ("error", friendly_error(last_exc))
