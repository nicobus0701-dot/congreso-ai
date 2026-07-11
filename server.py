from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from scraper import fetch_proyectos, fetch_sesiones, fetch_agenda, fetch_destacados
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

SYSTEM_PROMPT = """Eres un asistente especializado en monitoreo del Congreso de la República del Perú.

Tienes acceso a herramientas que obtienen información en tiempo real del portal del Congreso.
Úsalas siempre que el usuario pida datos sobre proyectos, sesiones, agendas o noticias.

Cuando presentes datos obtenidos de las herramientas:
- Proyectos de ley → tabla: Número | Fecha | Sumilla | Autor | Grupo Parlamentario | Comisión 1 | Comisión 2
- Sesiones         → tabla: Comisión | Fecha | Hora | Proyecto Sustentado | Dictamen | Votación | Acuerdo
- Agenda           → tabla: Cámara | Sesión | Fecha | Hora | Sala | Enlace | Tipo
- Destacados       → lista con título, fecha y enlace

Si la herramienta devuelve un error, explica el problema claramente y da el enlace directo al portal.
Habla siempre en español formal. Sé preciso y conciso."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_proyectos",
            "description": (
                "Obtiene proyectos de ley del Congreso del Perú desde el sistema SPLEY. "
                "Usa esta herramienta cuando el usuario pida proyectos, leyes, expedientes, "
                "o quiera buscar por autor/congresista, comisión o número de proyecto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "autor": {
                        "type": "string",
                        "description": "Apellido o nombre del congresista autor del proyecto"
                    },
                    "comision": {
                        "type": "string",
                        "description": "Nombre de la comisión parlamentaria"
                    },
                    "numero": {
                        "type": "string",
                        "description": "Número del proyecto de ley (ej: '1234/2023-CR')"
                    },
                    "legislatura": {
                        "type": "string",
                        "description": "Período legislativo (default: '2021-2026')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Cantidad de resultados a devolver (default: 20)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_sesiones",
            "description": (
                "Obtiene sesiones del Congreso del Perú desde el visor oficial. "
                "Usa esta herramienta cuando el usuario pregunte por sesiones, debates, "
                "votaciones o reuniones de comisiones."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "comision": {
                        "type": "string",
                        "description": "Nombre de la comisión"
                    },
                    "fecha": {
                        "type": "string",
                        "description": "Fecha en formato YYYY-MM-DD"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Cantidad de resultados (default: 20)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_agenda",
            "description": (
                "Obtiene la agenda parlamentaria actual del Congreso del Perú: "
                "convocatorias, fechas y horarios de próximas sesiones."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_destacados",
            "description": (
                "Obtiene las noticias y citaciones destacadas del Congreso del Perú."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

TOOL_MAP = {
    "buscar_proyectos":  lambda args: fetch_proyectos(**args),
    "buscar_sesiones":   lambda args: fetch_sesiones(**args),
    "buscar_agenda":     lambda args: fetch_agenda(),
    "buscar_destacados": lambda args: fetch_destacados(),
}

STATUS_LABELS = {
    "buscar_proyectos":  "Buscando proyectos de ley en SPLEY...",
    "buscar_sesiones":   "Consultando sesiones del Congreso...",
    "buscar_agenda":     "Obteniendo agenda parlamentaria...",
    "buscar_destacados": "Cargando noticias del Congreso...",
}


@app.get("/", response_class=HTMLResponse)
async def root():
    return (Path("static") / "index.html").read_text()


@app.get("/static/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})


@app.post("/chat")
async def chat(request: Request):
    body     = await request.json()
    messages = body.get("messages", [])
    api_key  = body.get("api_key", os.getenv("GROQ_API_KEY", ""))

    if not api_key:
        async def err():
            yield f"data: {json.dumps({'error': 'Falta la API key de Groq'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    client = Groq(api_key=api_key)

    async def generate():
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        # ── Phase 1: let model decide if it needs tools ────────
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=msgs,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=512,
                temperature=0.3,
                stream=False,
            )
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        choice  = resp.choices[0]
        finish  = choice.finish_reason

        # ── Phase 2: execute tools if requested ────────────────
        if finish == "tool_calls" and choice.message.tool_calls:
            # Add assistant's tool_call message
            msgs.append({
                "role": "assistant",
                "content": choice.message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in choice.message.tool_calls
                ]
            })

            for tc in choice.message.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")

                # Send status to frontend
                status = STATUS_LABELS.get(name, "Consultando el Congreso...")
                yield f"data: {json.dumps({'status': status})}\n\n"

                # Execute scraper
                try:
                    result = await TOOL_MAP[name](args)
                except Exception as e:
                    result = {"error": str(e)}

                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        # ── Phase 3: stream final answer ───────────────────────
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=msgs,
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
