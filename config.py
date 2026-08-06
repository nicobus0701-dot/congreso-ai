"""
Configuración central: rutas, credenciales, modelos y carga de prompts.

Todo lo que antes vivía disperso en la cabecera de server.py se centraliza aquí
para que routers/ y services/ no dependan del módulo de arranque.
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("congreso-ai")

# ── Rutas ────────────────────────────────────────────────────────────────────
# Con PyInstaller los datos van a sys._MEIPASS; en dev, al directorio del repo.
BASE_DIR    = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
STATIC_DIR  = BASE_DIR / "static"
PROMPTS_DIR = BASE_DIR / "prompts"

# GROQ_API_KEY es independiente del selector de proveedor de abajo: la
# transcripción de audio en vivo (Whisper, en live_transcriber.py y
# scraper.py) SIEMPRE habla con Groq directo, sin importar qué proveedor de
# chat esté activo — Gemini/OpenAI no exponen ese mismo endpoint de Whisper.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ── Proveedor de LLM para chat ────────────────────────────────────────────────
# El producto final habla con la API de OpenAI. Mientras tanto, para probar sin
# quemar cuota/plata, se puede apuntar a cualquier endpoint compatible con el
# formato OpenAI (Gemini y Groq lo son) con solo cambiar LLM_PROVIDER en .env —
# el resto del código (services/groq.py, orchestrator, etc.) no cambia, porque
# todos hablan a través del mismo cliente `openai.OpenAI(base_url=...)`.
#
# Para pasar a producción con OpenAI real: LLM_PROVIDER=openai + OPENAI_API_KEY
# en .env. No hace falta tocar nada más.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

_PROVIDERS = {
    "groq": {
        "base_url":     "https://api.groq.com/openai/v1",
        "api_key":      GROQ_API_KEY,
        "router_model": "llama-3.1-8b-instant",
        "main_model":   "llama-3.3-70b-versatile",
    },
    "gemini": {
        "base_url":     "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key":      os.getenv("GEMINI_API_KEY", ""),
        # "gemini-flash-latest" resuelve a un modelo distinto según el momento
        # (visto: cambió a "gemini-3.6-flash", con cuota gratis de solo 20
        # pedidos/día) — "-lite-latest" es más estable y con más cuota libre
        # en esta cuenta, verificado.
        "router_model": "gemini-flash-lite-latest",
        "main_model":   "gemini-flash-lite-latest",
    },
    "cerebras": {
        "base_url":     "https://api.cerebras.ai/v1",
        "api_key":      os.getenv("CEREBRAS_API_KEY", ""),
        "router_model": "llama3.1-8b",
        "main_model":   "llama-3.3-70b",
    },
    "openai": {
        "base_url":     None,  # SDK usa el endpoint oficial por default
        "api_key":      os.getenv("OPENAI_API_KEY", ""),
        "router_model": os.getenv("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
        "main_model":   os.getenv("OPENAI_MAIN_MODEL", "gpt-4o"),
    },
}

_provider_cfg = _PROVIDERS.get(LLM_PROVIDER, _PROVIDERS["groq"])
LLM_BASE_URL  = _provider_cfg["base_url"]
LLM_API_KEY   = _provider_cfg["api_key"]
ROUTER_MODEL  = _provider_cfg["router_model"]
MAIN_MODEL    = _provider_cfg["main_model"]

# ── Servidor ─────────────────────────────────────────────────────────────────
PORT         = int(os.getenv("PORT", 8732))
ALLOWED_ORIGIN = f"http://localhost:{PORT}"


def load_prompt(name: str) -> str:
    """Carga un prompt desde prompts/<name>.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def static_file(name: str) -> str:
    """Lee un archivo de static/ como texto (usa BASE_DIR, no el cwd)."""
    return (STATIC_DIR / name).read_text(encoding="utf-8")
