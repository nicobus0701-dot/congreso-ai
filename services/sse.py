"""Helpers para formatear eventos Server-Sent Events."""
import json


def event(payload: dict) -> str:
    """Serializa un dict como evento SSE."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def text(delta: str) -> str:
    """Fragmento de texto del modelo."""
    return event({"text": delta})


def status(msg: str) -> str:
    """Mensaje de progreso mostrado en la UI."""
    return event({"status": msg})


def error(msg: str) -> str:
    """Error mostrado en la UI."""
    return event({"error": msg})


DONE = "data: [DONE]\n\n"
