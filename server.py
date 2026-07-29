"""
Punto de entrada de la API.

La lógica vive en:
  routers/   — endpoints HTTP, uno por área funcional
  services/  — orquestación del chat, Groq, PDFs, Word
  prompts/   — prompts del sistema en Markdown
  config.py  — rutas, credenciales y modelos
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import ALLOWED_ORIGIN, PORT, STATIC_DIR
from routers import chat, export, live, pages, pdfs, sesiones


def create_app() -> FastAPI:
    app = FastAPI(title="Congreso IA")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    for module in (pages, chat, sesiones, live, pdfs, export):
        app.include_router(module.router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
