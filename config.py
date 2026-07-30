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

# ── LLM: proveedor + credenciales ───────────────────────────────────────────
# Cada usuario final puede traer su propia key y su propio proveedor (Groq,
# OpenAI, o cualquier otro compatible con la API de OpenAI) — el SDK de Groq
# ya habla ese mismo protocolo, así que alcanza con permitir override de
# base_url y nombres de modelo en vez de una librería distinta por proveedor.
#
# ROUTER_MODEL: elige herramienta en la Fase 1, conviene un modelo chico/barato.
# MAIN_MODEL: redacta la respuesta final, necesita más capacidad.
PROVIDER_PRESETS = {
    "groq": {
        "base_url": "",
        "main_model": "llama-3.3-70b-versatile",
        "router_model": "llama-3.1-8b-instant",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "main_model": "gpt-4o-mini",
        "router_model": "gpt-4o-mini",
    },
    "custom": {"base_url": "", "main_model": "", "router_model": ""},
}

# Electron pasa las env vars vacías ("") cuando todavía no hay settings
# guardados (primer arranque) — os.getenv(X, "groq") no cubre ese caso porque
# la variable SÍ existe, solo que vacía. Por eso el "or" en vez de un default
# posicional, y PROVIDER_PRESETS.get() en vez de indexado directo.
LLM_PROVIDER = os.getenv("LLM_PROVIDER") or "groq"
# LLM_API_KEY con fallback a GROQ_API_KEY: compat con el .env de desarrollo
# que ya existía antes de este cambio.
LLM_API_KEY  = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY", "")
_preset      = PROVIDER_PRESETS.get(LLM_PROVIDER, PROVIDER_PRESETS["custom"])
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or _preset["base_url"]
MAIN_MODEL   = os.getenv("LLM_MAIN_MODEL") or _preset["main_model"]
# Sin router_model propio (típico de "custom"), reusar MAIN_MODEL: sin esto
# la Fase 1 (router) intentaría llamar al modelo con nombre "".
ROUTER_MODEL = os.getenv("LLM_ROUTER_MODEL") or _preset["router_model"] or MAIN_MODEL


def set_llm_settings(provider: str, api_key: str, base_url: str = "",
                      main_model: str = "", router_model: str = "") -> None:
    """
    Actualiza la config del LLM en caliente, sin reiniciar el proceso.

    Llamado por POST /settings/llm cuando el usuario final completa el
    onboarding. Los módulos que necesiten el valor vigente deben leerlo como
    `config.LLM_API_KEY` (atributo del módulo) en el punto de uso, no vía
    `from config import LLM_API_KEY` — ese import copia el string en el
    momento de importar y no ve cambios posteriores.
    """
    global LLM_PROVIDER, LLM_API_KEY, LLM_BASE_URL, MAIN_MODEL, ROUTER_MODEL
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])
    LLM_PROVIDER = provider
    LLM_API_KEY  = api_key.strip()
    LLM_BASE_URL = (base_url or preset["base_url"]).strip()
    MAIN_MODEL   = (main_model or preset["main_model"]).strip()
    ROUTER_MODEL = (router_model or preset["router_model"] or MAIN_MODEL).strip()

# ── Servidor ─────────────────────────────────────────────────────────────────
PORT         = int(os.getenv("PORT", 8732))
ALLOWED_ORIGIN = f"http://localhost:{PORT}"


def load_prompt(name: str) -> str:
    """Carga un prompt desde prompts/<name>.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def static_file(name: str) -> str:
    """Lee un archivo de static/ como texto (usa BASE_DIR, no el cwd)."""
    return (STATIC_DIR / name).read_text(encoding="utf-8")
