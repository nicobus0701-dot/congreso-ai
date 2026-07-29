"""Rutas de páginas y estado del servicio."""
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from config import GROQ_API_KEY, STATIC_DIR, static_file

router = APIRouter()


@router.get("/status")
async def status():
    return {"ready": bool(GROQ_API_KEY)}


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
