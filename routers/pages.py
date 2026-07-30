"""Rutas de páginas y estado del servicio."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

import config
from config import STATIC_DIR, static_file

router = APIRouter()


@router.get("/status")
async def status():
    return {"ready": bool(config.LLM_API_KEY)}


@router.post("/settings/llm")
async def set_llm_settings(request: Request):
    """
    Guardado del onboarding: proveedor + key (+ base_url/modelos si es
    'custom'). Aplica en caliente al proceso corriendo — sin esto el usuario
    tendría que reiniciar la app después de cargar su key.
    """
    body = await request.json()
    provider = (body.get("provider") or "groq").strip()
    api_key = (body.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "error": "La API key no puede estar vacía"}
    if provider == "custom" and not (body.get("base_url") and body.get("main_model")):
        return {"ok": False, "error": "Para un proveedor personalizado, completa la URL y el modelo"}

    config.set_llm_settings(
        provider, api_key,
        base_url=body.get("base_url", ""),
        main_model=body.get("main_model", ""),
        router_model=body.get("router_model", ""),
    )
    return {"ok": True}


@router.get("/", response_class=HTMLResponse)
async def root():
    return static_file("index.html")


@router.get("/static/sw.js")
async def service_worker():
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )
