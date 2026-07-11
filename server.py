from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

SYSTEM_PROMPT = """Eres un asistente especializado en monitoreo del Congreso de la República del Perú.

Ayudas a revisar y organizar información parlamentaria. Cuando el usuario te pida organizar datos,
genera tablas en formato Markdown bien estructuradas.

Tus comandos principales:
- "Revisar proyectos" → tabla con columnas: Número | Fecha | Sumilla | Autor | Grupo Parlamentario | Comisión 1 | Comisión 2
- "Revisar sesiones"  → tabla con columnas: Comisión | Fecha | Hora | Proyecto Sustentado | Dictamen | Votación | Acuerdo
- "Revisar agendas"   → tabla con columnas: Cámara | Sesión | Fecha | Hora | Sala | Enlace | Tipo
- "Revisar destacados"→ lista organizada con descripción y enlace de descarga

Cuando el usuario pegue información del Congreso, organízala en el formato correcto.
Si no tiene información aún, explícale cómo obtenerla de los portales oficiales.
Habla siempre en español formal y sé preciso y conciso."""


@app.get("/", response_class=HTMLResponse)
async def root():
    return (Path("static") / "index.html").read_text()


@app.get("/static/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    api_key  = body.get("api_key", os.getenv("GROQ_API_KEY", ""))

    if not api_key:
        async def err():
            yield f"data: {json.dumps({'error': 'Falta la API key de Groq'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    client = Groq(api_key=api_key)

    async def generate():
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                max_tokens=2048,
                temperature=0.4,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield f"data: {json.dumps({'text': delta})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
