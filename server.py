import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("congreso-ai")

import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq

from live_transcriber import stream_transcription
from scraper import (
    fetch_agenda,
    fetch_agenda_camaras,
    fetch_agenda_comisiones,
    fetch_agenda_pleno,
    fetch_congresista,
    fetch_destacados,
    fetch_estado_proyecto,
    fetch_expediente,
    fetch_interpelaciones,
    fetch_proyectos,
    fetch_sesiones,
    fetch_transcript_youtube,
    fetch_videos_youtube,
    get_yt_captions,
    transcribe_with_whisper,
)

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
BASE_DIR = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = Path(BASE_DIR) / "prompts"

def _p(name: str) -> str:
    """Carga un prompt desde prompts/<name>.md al arranque."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8732"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

RESUMEN_PROMPT = _p("resumen")

ROUTER_PROMPT = _p("router")

SYSTEM_BASE = _p("system_base")


# System prompt compacto para Phase 3 con tool results — ahorra ~800 tokens vs SYSTEM_BASE
SYSTEM_MINI = _p("system_mini")

# Bloques de formato inyectados en Fase 3 según la herramienta usada.
WORKFLOWS = {
    "fetch_expediente": _p("workflow_expediente"),

    "fetch_agenda_comisiones": _p("workflow_agenda_comisiones"),

    "fetch_agenda_pleno": _p("workflow_agenda_pleno"),

    "fetch_interpelaciones": _p("workflow_interpelaciones"),

    "fetch_agenda_camaras": _p("workflow_agenda_camaras"),

    "buscar_proyectos": _p("workflow_proyectos"),
}

# Flujos que dependen de PDF/transcript cargado (no de una herramienta).
WORKFLOW_PDF_FORMULA = _p("workflow_pdf")

WORKFLOW_SESION = _p("workflow_sesion")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_proyectos",
            "description": (
                "Obtiene proyectos de ley del Congreso del Perú desde el sistema SPLEY. "
                "Úsala cuando el usuario pida proyectos, leyes, expedientes o quiera buscar "
                "por tema/materia, autor/congresista, comisión, número de proyecto o rango de fechas. "
                "Para búsquedas por TEMA usa el parámetro 'materia'. "
                "Para los ÚLTIMOS N DÍAS usa el parámetro 'dias' (ej: dias=15 para últimos 15 días). "
                "Para un número específico usa 'numero'. Para un autor usa 'autor'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "materia": {
                        "type": "string",
                        "description": "Tema o materia a buscar (ej: 'educacion', 'salud', 'transporte', 'mineria')"
                    },
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
                        "description": "Número del proyecto de ley (ej: '14860/2025-CR' o solo '14860')"
                    },
                    "legislatura": {
                        "type": "string",
                        "description": "Período legislativo (default: '2021-2026')"
                    },
                    "dias": {
                        "type": "integer",
                        "description": "Filtrar proyectos presentados en los últimos N días calendario (ej: 15 para los últimos 15 días)"
                    },
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
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_congresista",
            "description": (
                "Obtiene el perfil completo de un congresista: todos sus proyectos de ley "
                "presentados, resumen por estado (aprobado, en comisión, archivado, etc.) "
                "y noticias recientes sobre esa persona. "
                "Úsala cuando el usuario pregunte por un congresista específico, "
                "quiera saber qué ha legislado alguien, o necesite el historial de un parlamentario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {
                        "type": "string",
                        "description": "Nombre o apellido del congresista (ej: 'Montoya', 'Patricia Chirinos')"
                    }
                },
                "required": ["nombre"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_web",
            "description": (
                "Busca cualquier tema general en internet usando DuckDuckGo. "
                "Úsala para preguntas que NO son sobre proyectos de ley, sesiones, agenda o congresistas específicos: "
                "historia, definiciones, noticias generales, conceptos legales, datos del mundo, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Términos de búsqueda"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Número de resultados (default: 5)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rastrear_proyecto",
            "description": (
                "Obtiene el estado detallado y actual de un proyecto de ley específico "
                "por su número. Úsala cuando el usuario quiera saber en qué estado está "
                "un proyecto puntual, si fue aprobado, archivado, o está en comisión."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "numero": {
                        "type": "string",
                        "description": "Número del proyecto (ej: '1234/2024-CR' o simplemente '1234')"
                    }
                },
                "required": ["numero"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_expediente",
            "description": (
                "Obtiene el expediente COMPLETO de un proyecto de ley desde el portal SPLEY del "
                "Congreso, con sus 5 pestañas: (1) Seguimiento — todos los movimientos con fecha, "
                "estado procesal, comisión, detalle y adjuntos; (2) Proyectos Acumulados; "
                "(3) Documentación Anexa — oficios, opiniones de ministerios, informes; "
                "(4) Secciones — texto del proyecto, fórmula legal, dictámenes, autógrafas; "
                "(5) Opinión Ciudadana. Usar cuando el usuario pida el expediente, el seguimiento, "
                "el trámite en comisiones, los actos de trabajo, los adjuntos o el predictamen de "
                "un proyecto específico. Si el usuario solo dio el tema, primero identificar el "
                "número con buscar_proyectos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "numero_proyecto": {
                        "type": "string",
                        "description": "Número del proyecto de ley. Acepta formato oficial completo ('14864/2025-CR') o solo el correlativo ('14864')."
                    },
                    "periodo": {
                        "type": "string",
                        "description": "Periodo parlamentario, ej. '2021' para el periodo 2021-2026. Por defecto usa el periodo vigente."
                    }
                },
                "required": ["numero_proyecto"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_agenda_comisiones",
            "description": (
                "Obtiene las sesiones de comisiones programadas para los próximos días desde "
                "la web del Congreso. Devuelve por cada sesión: fecha, hora, comisión, lugar o "
                "modalidad, y link a la agenda. Usar cuando el usuario pregunte qué sesiones de "
                "comisiones hay hoy, mañana o en los próximos días."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dias": {
                        "type": "integer",
                        "description": "Cantidad de días hacia adelante a consultar. Por defecto 2."
                    },
                    "comision": {
                        "type": "string",
                        "description": "Opcional. Filtrar por nombre (o parte del nombre) de una comisión específica, ej. 'Energía y Minas'."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_agenda_pleno",
            "description": (
                "Obtiene la estructura de la Agenda del Pleno vigente desde la web del Congreso: "
                "cuántos dictámenes, denuncias constitucionales, mociones e insistencias hay "
                "agendados, con el detalle de cada ítem. Usar cuando el usuario pregunte por la "
                "Agenda del Pleno, qué se va a debatir en el Pleno, o cuántos dictámenes/denuncias hay."
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
            "name": "responder_directo",
            "description": (
                "Usar cuando la pregunta NO requiere datos actualizados del Congreso ni "
                "búsqueda web: saludos ('hola', 'buenos días'), preguntas sobre ti mismo, "
                "seguimiento de una respuesta anterior ('¿y eso qué implica?', 'explícame eso'), "
                "conceptos, definiciones o historia que puedes responder con tu conocimiento."
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
            "name": "fetch_agenda_camaras",
            "description": (
                "Obtiene las sesiones programadas del Senado, Cámara de Diputados y Pleno del "
                "Congreso bicameral desde comunicaciones.congreso.gob.pe/agenda. "
                "Usar cuando el usuario pregunte por sesiones del Senado, Diputados, Pleno "
                "bicameral, o la agenda general del nuevo Congreso."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dias": {
                        "type": "integer",
                        "description": "Días hacia adelante a consultar (default: 2)."
                    },
                    "camara": {
                        "type": "string",
                        "description": "Filtrar por cámara: 'senado', 'diputados', 'pleno', 'comision'. Omitir para ver todas."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_interpelaciones",
            "description": (
                "Obtiene las mociones de interpelación a ministros presentadas formalmente ante "
                "el Congreso y noticias sobre mociones en gestación (recolección de firmas). "
                "Devuelve por cada moción: ministro, cartera, fecha, estado y motivo. "
                "Usar cuando el usuario pregunte por interpelaciones o mociones contra ministros. "
                "IMPORTANTE: complementar siempre con buscar_en_web para detectar mociones en "
                "recolección de firmas que aún no aparecen en el sistema."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ministro": {
                        "type": "string",
                        "description": "Opcional. Filtrar por nombre del ministro o de la cartera, ej. 'Interior' o 'Ministro de Salud'."
                    }
                }
            }
        }
    }
]

async def buscar_en_web(query: str, limit: int = 5):
    try:
        loop = __import__('asyncio').get_event_loop()
        def _search():
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=limit))
            return results
        results = await loop.run_in_executor(None, _search)
        return [{"titulo": r.get("title"), "url": r.get("href"), "resumen": r.get("body")} for r in results]
    except Exception as e:
        return {"sin_datos": True, "mensaje": str(e)}

TOOL_MAP = {
    "buscar_proyectos":        lambda args: fetch_proyectos(**args),
    "buscar_sesiones":         lambda args: fetch_sesiones(**args),
    "buscar_agenda":           lambda args: fetch_agenda(),
    "buscar_destacados":       lambda args: fetch_destacados(),
    "buscar_congresista":      lambda args: fetch_congresista(**args),
    "rastrear_proyecto":       lambda args: fetch_estado_proyecto(**args),
    "buscar_en_web":           lambda args: buscar_en_web(**args),
    "fetch_expediente":        lambda args: fetch_expediente(
                                   numero=args.get("numero_proyecto") or args.get("numero", "")
                               ),
    "fetch_agenda_comisiones": lambda args: fetch_agenda_comisiones(**{k: v for k, v in args.items() if k in ("dias", "comision")}),
    "fetch_agenda_pleno":      lambda args: fetch_agenda_pleno(),
    "fetch_agenda_camaras":    lambda args: fetch_agenda_camaras(**{k: v for k, v in args.items() if k in ("dias", "camara")}),
    "fetch_interpelaciones":   lambda args: fetch_interpelaciones(**{k: v for k, v in args.items() if k in ("ministro",)}),
    "responder_directo":       lambda args: _responder_directo(),
}

async def _responder_directo():
    return {"nota": "Responde directamente con tu conocimiento, sin datos externos."}

STATUS_LABELS = {
    "buscar_proyectos":        "Buscando proyectos de ley en SPLEY...",
    "buscar_sesiones":         "Consultando sesiones del Congreso...",
    "buscar_agenda":           "Obteniendo agenda parlamentaria...",
    "buscar_destacados":       "Cargando noticias del Congreso...",
    "buscar_congresista":      "Consultando perfil del congresista...",
    "rastrear_proyecto":       "Rastreando estado del proyecto...",
    "buscar_en_web":           "Buscando en internet...",
    "fetch_expediente":        "Consultando el expediente completo en SPLEY (5 pestañas)...",
    "fetch_agenda_comisiones": "Revisando agenda de comisiones...",
    "fetch_agenda_pleno":      "Cargando la Agenda del Pleno...",
    "fetch_agenda_camaras":    "Revisando agenda del Congreso bicameral...",
    "fetch_interpelaciones":   "Buscando mociones de interpelación...",
    "responder_directo":       "Pensando...",
}


@app.get("/status")
async def status():
    ready = bool(os.getenv("GROQ_API_KEY", ""))
    return {"ready": ready}


@app.get("/", response_class=HTMLResponse)
async def root():
    return (Path("static") / "index.html").read_text()


@app.get("/static/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})


@app.get("/sessions", response_class=HTMLResponse)
async def sessions_page():
    return (Path("static") / "sessions.html").read_text()


@app.get("/pdfs", response_class=HTMLResponse)
async def pdfs_page():
    return (Path("static") / "pdfs.html").read_text()


REFERENCIAS_PDF = [
    {
        "titulo": "Reglamento del Congreso de la República (setiembre 2025)",
        "enlace": "https://www3.congreso.gob.pe/Docs/constitucion/reglamento/reglamento%20setiembre-2025.pdf",
        "tipo": "Referencia",
    },
    {
        "titulo": "Constitución Política del Perú (dic. 2024)",
        "enlace": "https://www3.congreso.gob.pe/Docs/files/constitucion/constitucion-12-2024.pdf",
        "tipo": "Referencia",
    },
    {
        "titulo": "Manual de Técnica Legislativa — 3ra edición",
        "enlace": "https://www3.congreso.gob.pe/Docs/dgp/files/manual-tecnica-legislativa-3raedicion.pdf",
        "tipo": "Referencia",
    },
]

@app.get("/congreso-pdfs")
async def congreso_pdfs():
    """PDFs rápidos: destacados del homepage + referencias fijas."""
    pdfs = []
    try:
        data = await fetch_destacados()
        for item in data.get("destacados", []):
            url = item.get("enlace", "")
            if url.lower().endswith(".pdf"):
                pdfs.append({"titulo": item["titulo"], "enlace": url, "tipo": "Destacado"})
        for item in data.get("citaciones", []):
            url = item.get("enlace", "")
            if url.lower().endswith(".pdf"):
                pdfs.append({"titulo": item["titulo"], "enlace": url, "tipo": "Citación"})
    except Exception:
        pass
    seen = {p["enlace"] for p in pdfs}
    for ref in REFERENCIAS_PDF:
        if ref["enlace"] not in seen:
            seen.add(ref["enlace"])
            pdfs.append(ref)
    return {"pdfs": pdfs}

@app.get("/congreso-proyectos")
async def congreso_proyectos():
    """Proyectos SPLEY recientes — se carga en segundo plano."""
    try:
        data = await fetch_proyectos(limit=15)
        proyectos = []
        for item in data.get("items", []):
            numero = item.get("numero", "")
            titulo = item.get("sumilla", numero)
            enlace = item.get("enlace", "")
            if enlace:
                proyectos.append({
                    "titulo": f"[{numero}] {titulo[:100]}" if numero else titulo[:110],
                    "enlace": enlace,
                    "tipo": "Proyecto de Ley",
                })
        return {"pdfs": proyectos}
    except Exception:
        return {"pdfs": []}


@app.get("/pdf-thumbnail")
async def pdf_thumbnail(url: str = Query(...)):
    import fitz
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"})
        if r.status_code != 200 or "pdf" not in r.headers.get("content-type", "application/pdf").lower():
            ct = r.headers.get("content-type", "")
            if "html" in ct or r.status_code != 200:
                return Response(status_code=404, content=b"not a pdf")
        doc = fitz.open(stream=r.content, filetype="pdf")
        page = doc[0]
        mat = fitz.Matrix(1.8, 1.8)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        return Response(status_code=400, content=str(e).encode())


@app.post("/load-pdf-url")
async def load_pdf_url(request: Request):
    import fitz
    body = await request.json()
    url  = body.get("url", "")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"})
        doc  = fitz.open(stream=r.content, filetype="pdf")
        pages = len(doc)
        text  = "\n\n".join(page.get_text() for page in doc).strip()
        if len(text) > 40000:
            text = text[:40000] + f"\n\n[Texto recortado — documento original: {pages} páginas]"
        name = url.split("/")[-1]
        return {"ok": True, "pages": pages, "text": text, "filename": name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    import fitz
    try:
        data = await file.read()
        doc  = fitz.open(stream=data, filetype="pdf")
        pages = len(doc)
        text  = "\n\n".join(page.get_text() for page in doc).strip()
        # Cap en 40000 chars para no reventar el contexto
        if len(text) > 40000:
            text = text[:40000] + f"\n\n[Texto recortado — documento original: {pages} páginas]"
        return {"ok": True, "pages": pages, "text": text, "filename": file.filename}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/chat")
async def chat(request: Request):
    body     = await request.json()
    messages = body.get("messages", [])
    api_key  = GROQ_API_KEY

    if not api_key:
        async def err():
            yield f"data: {json.dumps({'error': 'Falta la API key de Groq'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    client = Groq(api_key=api_key)

    async def generate():
        # Inyectar fecha actual en el system prompt para evitar alucinaciones temporales
        hoy = datetime.now().strftime("%d/%m/%Y")
        system_con_fecha = SYSTEM_BASE + f"\n\n**Fecha actual: {hoy}** — Solo muestra sesiones o eventos a partir de hoy. Si una herramienta no devuelve sesiones reales, NO digas simplemente 'no hay sesiones'. En cambio: (1) explica brevemente el posible motivo (feriado, receso parlamentario, fin de semana, etc. según la fecha), (2) sugiere alternativas concretas como revisar la agenda de la semana siguiente, consultar proyectos de ley en trámite, o revisar los destacados y citaciones. Sé directo y útil, no te limites a dar una negativa seca."

        def _parse_retry_seconds(e) -> float:
            """Extrae los segundos de espera del error de rate limit de Groq."""
            s = str(e)
            # "Please try again in 2.5s" o "try again in 750ms"
            m = re.search(r"try again in ([0-9.]+)s", s, re.IGNORECASE)
            if m:
                return float(m.group(1)) + 0.5
            m = re.search(r"try again in ([0-9.]+)ms", s, re.IGNORECASE)
            if m:
                return float(m.group(1)) / 1000 + 0.5
            m = re.search(r"try again in (\d+)m(\d+(?:\.\d+)?)s", s, re.IGNORECASE)
            if m:
                return int(m.group(1)) * 60 + float(m.group(2)) + 0.5
            return 12.0  # fallback conservador

        def _friendly_error(e):
            s = str(e).lower()
            if "per day" in s or "tpd" in s:
                m = re.search(r"try again in ([0-9hms.]+)", s)
                cuando = "en un rato"
                if m:
                    mins = re.search(r"(\d+)m", m.group(1))
                    cuando = f"en ~{mins.group(1)} min" if mins else f"en {m.group(1)}"
                return (f"Llegamos al límite de tokens por ahora. Vuelve a intentar {cuando}.")
            if "rate limit" in s or "429" in s or "tokens per" in s or "quota" in s:
                return "Muchas consultas muy rápido. Espera unos segundos y vuelve a intentarlo."
            return "Hubo un problema al conectar. Intentá de nuevo."

        # Detectar si es solicitud de resumen semanal
        last_msg = messages[-1].get("content", "") if messages else ""
        is_resumen = last_msg.strip().startswith("__RESUMEN_SEMANAL__")
        sector = None
        if is_resumen and ":" in last_msg:
            sector = last_msg.strip().split(":", 1)[1].strip()

        # ¿Hay un PDF/documento cargado en el historial reciente? El frontend lo
        # inyecta como un mensaje que empieza con "He cargado el documento".
        recientes = messages[-6:]
        doc_en_contexto = any(
            "He cargado el documento" in (m.get("content", "") or "")
            for m in recientes if m.get("role") == "user"
        )
        low_last = last_msg.lower()
        pide_analisis = any(w in low_last for w in (
            "analiza", "analizar", "resume", "resumir", "resumen", "fórmula legal",
            "formula legal", "qué propone", "que propone", "qué modifica", "que modifica",
            "artículo", "articulo", "deroga", "explica",
        ))
        # Análisis de un documento ya cargado: se trabaja sobre el texto en
        # contexto, NO se necesita ninguna herramienta de scraping.
        analizar_documento = doc_en_contexto and (pide_analisis or len(last_msg) < 60)

        # Detectar link de sesión / transcript para el flujo de análisis de sesión.
        has_sesion = ("youtube.com" in low_last or "youtu.be" in low_last
                      or "transcript" in low_last or "[sesión" in low_last)
        has_pdf    = analizar_documento

        # conversation: historial para la Fase 3. El system se arma dinámicamente
        # (base compacta + solo los flujos relevantes) para no reventar tokens.
        if is_resumen:
            base_msg = "Genera el resumen ejecutivo semanal completo del Congreso del Perú."
            if sector and sector != "general":
                base_msg += f" Enfoca el análisis especialmente en el sector {sector} y los proyectos de ley, noticias y agenda que impacten a ese sector."
            conversation = [{"role": "user", "content": base_msg}]
        else:
            # Mantener historial amplio para conversación fluida
            conversation = messages[-20:]

        # Short-circuit: analizar un documento cargado o una sesión no requiere
        # scraping. Vamos directo a la Fase 3 con el flujo correspondiente.
        if analizar_documento or (has_sesion and not is_resumen):
            system_p3 = system_con_fecha
            if analizar_documento:
                system_p3 += "\n" + WORKFLOW_PDF_FORMULA
            if has_sesion:
                system_p3 += "\n" + WORKFLOW_SESION
                # Intentar obtener el transcript del video de YouTube antes de Fase 3
                yt_match = re.search(
                    r"(?:youtube\.com/(?:watch\?v=|live/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})",
                    last_msg
                )
                if yt_match:
                    video_id = yt_match.group(1)
                    yield f"data: {json.dumps({'status': 'Obteniendo transcript de la sesión...'})}\n\n"
                    try:
                        transcript_data = await fetch_transcript_youtube(video_id)
                    except Exception:
                        transcript_data = None

                    if transcript_data and transcript_data.get("ok") and transcript_data.get("text"):
                        # Insertar el transcript como contexto justo antes del último mensaje del usuario
                        transcript_msg = {
                            "role": "user",
                            "content": (
                                f"[TRANSCRIPT DE LA SESIÓN — fuente: {transcript_data.get('source', 'youtube')}]\n"
                                f"{transcript_data['text']}\n"
                                "[FIN DEL TRANSCRIPT]"
                            )
                        }
                        conversation = conversation[:-1] + [transcript_msg, conversation[-1]]
                    else:
                        # Sin subtítulos disponibles — informar directamente sin pasar por el modelo
                        yield f"data: {json.dumps({'text': 'No pude obtener el transcript de ese video (sin subtítulos disponibles o video privado). Para analizar la sesión podés: (1) cargar el PDF del acta con el botón de adjunto, o (2) pegar el texto del transcript directamente en el chat.'})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

            msgs_directo = [{"role": "system", "content": system_p3}] + conversation
            try:
                stream = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=msgs_directo,
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
                yield f"data: {json.dumps({'error': _friendly_error(e)})}\n\n"
            return

        # router_msgs: prompt compacto solo para elegir tools en la Fase 1.
        # Si hay un doc gigante en contexto, no lo mandamos al router (gasta tokens
        # y no aporta a la elección de herramienta): usamos solo el texto del pedido.
        # Detectar si hay un expediente completo en el historial reciente
        recent_assistant = " ".join(
            m.get("content", "") for m in messages[-6:]
            if m.get("role") == "assistant"
        )
        has_expediente_en_contexto = any(
            marker in recent_assistant
            for marker in ("FICHA DEL PROYECTO", "COMISIONES A LAS QUE FUE DERIVADO",
                           "ACTOS DE TRABAJO POR COMISIÓN", "MI LECTURA")
        )

        if doc_en_contexto:
            router_msgs = [{"role": "system", "content": ROUTER_PROMPT},
                           {"role": "user", "content": last_msg}]
        elif has_expediente_en_contexto:
            # El expediente ya está en contexto: enviar solo la pregunta + nota breve.
            # NO mandar el historial completo al router — el expediente puede ser miles
            # de tokens y revienta el rate limit solo en Phase 1.
            router_context = (
                "[CONTEXTO: El asistente ya mostró el expediente completo de un proyecto "
                "en esta conversación (FICHA DEL PROYECTO, SEGUIMIENTO, COMISIONES, etc.). "
                "Si el usuario pregunta sobre ese expediente — comisiones, actos, predictamen, "
                "adjuntos, estado, autores — usa responder_directo. "
                "Solo llama fetch_expediente si pide OTRO proyecto diferente.]\n\n"
                f"Pregunta: {last_msg}"
            )
            router_msgs = [{"role": "system", "content": ROUTER_PROMPT},
                           {"role": "user", "content": router_context}]
        else:
            router_msgs = [{"role": "system", "content": ROUTER_PROMPT}] + messages[-4:]

        # ── Phase 1: let model decide if it needs tools ────────
        # Usar modelo pequeño (8B) para el router: solo elige una función,
        # no necesita 70B. El 8B tiene 20k TPM vs 6k del 70B — evita rate limits.
        ROUTER_MODEL = "llama-3.1-8b-instant"
        MAIN_MODEL   = "llama-3.3-70b-versatile"

        def _is_tool_format_error(e):
            s = str(e)
            return "tool_use_failed" in s or "failed_generation" in s or "400" in s

        try:
            resp = client.chat.completions.create(
                model=ROUTER_MODEL,
                messages=router_msgs,
                tools=TOOLS,
                tool_choice="required",
                max_tokens=512,
                temperature=0.2,
                stream=False,
            )
        except Exception as e:
            if _is_tool_format_error(e):
                # Model generated malformed tool call — retry without tools
                try:
                    resp2 = client.chat.completions.create(
                        model=MAIN_MODEL,
                        messages=[{"role": "system", "content": system_con_fecha}] + conversation,
                        max_tokens=2048,
                        temperature=0.4,
                        stream=True,
                    )
                    for chunk in resp2:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield f"data: {json.dumps({'text': delta})}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e2:
                    yield f"data: {json.dumps({'error': _friendly_error(e2)})}\n\n"
            else:
                yield f"data: {json.dumps({'error': _friendly_error(e)})}\n\n"
            return

        choice  = resp.choices[0]
        finish  = choice.finish_reason

        # ── Phase 2: execute tools if requested ────────────────
        tool_msgs   = []   # assistant tool_call + tool result messages
        tools_usados = []  # nombres de tools ejecutadas (para armar el flujo de Fase 3)
        solo_responder_directo = False  # señal para Phase 3 minimalista

        if finish == "tool_calls" and choice.message.tool_calls:
            # Ignorar responder_directo: es solo señal de "responde sin datos"
            real_calls = [tc for tc in choice.message.tool_calls
                          if tc.function.name != "responder_directo"]
            if not real_calls:
                solo_responder_directo = True

            if real_calls:
                tool_msgs.append({
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
                        for tc in real_calls
                    ]
                })

                for tc in real_calls:
                    name = tc.function.name
                    tools_usados.append(name)
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except (ValueError, TypeError):
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    if "limit" in args:
                        try:
                            args["limit"] = int(args["limit"])
                        except (ValueError, TypeError):
                            args["limit"] = 20
                    args = {k: v for k, v in args.items() if v != ""}

                    status = STATUS_LABELS.get(name, "Consultando el Congreso...")
                    yield f"data: {json.dumps({'status': status})}\n\n"

                    try:
                        if name not in TOOL_MAP:
                            result = {"sin_datos": True, "mensaje": f"Herramienta '{name}' no disponible."}
                        else:
                            result = await TOOL_MAP[name](args)
                            if isinstance(result, dict) and "error" in result:
                                result = {"sin_datos": True, "mensaje": result.get("error", "No hay información disponible.")}
                    except Exception as tool_err:
                        result = {"sin_datos": True, "mensaje": f"Error al consultar {name}: {str(tool_err)[:100]}"}

                    # Cap tool result: 7k chars ≈ ~2000 tokens — protege TPM del 8B
                    result_str = json.dumps(result, ensure_ascii=False)
                    if len(result_str) > 7000:
                        result_str = result_str[:7000] + '... [recortado]"}'
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })

        # ── Build Phase 3 system prompt: base + solo los flujos relevantes ──
        if is_resumen:
            system_p3 = RESUMEN_PROMPT
        elif solo_responder_directo:
            system_p3 = system_con_fecha
        elif tool_msgs:
            # Con tool results: usar SYSTEM_MINI para ahorrar tokens (~800 menos)
            # fetch_expediente y PDF necesitan sus workflows completos igual
            mini = SYSTEM_MINI.format(hoy=hoy)
            has_heavy_workflow = any(t in WORKFLOWS for t in tools_usados) or has_pdf or has_sesion
            if has_heavy_workflow:
                system_p3 = system_con_fecha
                for t in tools_usados:
                    if t in WORKFLOWS:
                        system_p3 += "\n" + WORKFLOWS[t]
                if has_pdf:
                    system_p3 += "\n" + WORKFLOW_PDF_FORMULA
                if has_sesion:
                    system_p3 += "\n" + WORKFLOW_SESION
            else:
                system_p3 = mini
        else:
            system_p3 = system_con_fecha

        # Cuando hay tool results, recortar el historial enviado a Phase 3.
        # El tool result ya aporta el contexto; mandar 20 mensajes adicionales
        # dispara el TPM fácilmente. Con tools: solo los últimos 4 mensajes.
        conv_p3 = messages[-4:] if tool_msgs else conversation

        msgs = [{"role": "system", "content": system_p3}] + conv_p3 + tool_msgs

        # ── Phase 3: stream final answer ───────────────────────
        # Con tool results el request es pesado (>6k tokens) — usar 8B (20k TPM).
        # Sin tools (solo conversación) el request es ligero — usar 70B.
        _p3_model   = MAIN_MODEL  # 70B: 12k TPM vs 6k del 8B — siempre usar el de mayor límite
        if "fetch_expediente" in tools_usados:
            _max_tokens = 4000
        elif tools_usados:
            _max_tokens = 1800  # queries de proyectos/agenda: respuesta más corta, menos TPM
        else:
            _max_tokens = 2500

        import asyncio as _asyncio

        async def _stream_p3(msgs_in, max_tok):
            stream = client.chat.completions.create(
                model=_p3_model,
                messages=msgs_in,
                max_tokens=max_tok,
                temperature=0.4,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        _is_rate = lambda e: any(x in str(e).lower() for x in ("rate limit","429","tokens per","quota","per day"))

        last_exc = None
        for attempt in range(3):
            try:
                async for delta in _stream_p3(msgs, _max_tokens):
                    yield f"data: {json.dumps({'text': delta})}\n\n"
                yield "data: [DONE]\n\n"
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                if _is_rate(e) and attempt < 2:
                    wait = _parse_retry_seconds(e)
                    yield f"data: {json.dumps({'status': f'Límite de Groq, reintentando en {wait:.0f}s...'})}\n\n"
                    await _asyncio.sleep(wait)
                else:
                    break
        if last_exc:
            yield f"data: {json.dumps({'error': _friendly_error(last_exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/export/docx")
async def export_docx(request: Request):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    body = await request.json()
    md   = body.get("content", "")

    doc = Document()

    # Page margins
    for section in doc.sections:
        section.left_margin   = Inches(1.2)
        section.right_margin  = Inches(1.2)
        section.top_margin    = Inches(1.0)
        section.bottom_margin = Inches(1.0)

    # Header line
    hdr_para = doc.add_paragraph()
    hdr_run  = hdr_para.add_run("DOCUMENTO CONFIDENCIAL — GESTIÓN DE ASUNTOS PÚBLICOS")
    hdr_run.font.size  = Pt(8)
    hdr_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    hdr_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()  # spacer

    def strip_inline(text):
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*',     r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        return text

    def _add_hyperlink(paragraph, text, url):
        """Add a clickable hyperlink run to a paragraph."""
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        part = paragraph.part
        r_id = part.relate_to(url, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink', is_external=True)
        hyperlink = OxmlElement('w:hyperlink')
        hyperlink.set(qn('r:id'), r_id)
        r = OxmlElement('w:r')
        rPr = OxmlElement('w:rPr')
        rStyle = OxmlElement('w:rStyle')
        rStyle.set(qn('w:val'), 'Hyperlink')
        rPr.append(rStyle)
        r.append(rPr)
        t = OxmlElement('w:t')
        t.text = text
        r.append(t)
        hyperlink.append(r)
        paragraph._p.append(hyperlink)

    def add_md_para(para_text):
        """Add a paragraph with bold, italic and hyperlink support."""
        p = doc.add_paragraph()
        # Split on links first, then bold/italic
        tokens = re.split(r'(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*)', para_text)
        for tok in tokens:
            link_m = re.match(r'\[([^\]]+)\]\(([^)]+)\)', tok)
            if link_m:
                _add_hyperlink(p, link_m.group(1), link_m.group(2))
            elif tok.startswith('**') and tok.endswith('**'):
                run = p.add_run(tok[2:-2])
                run.bold = True
            elif tok.startswith('*') and tok.endswith('*'):
                run = p.add_run(tok[1:-1])
                run.italic = True
            else:
                p.add_run(tok)
        return p

    def is_table_row(s):
        return s.startswith('|') and s.endswith('|')

    def is_separator_row(s):
        return is_table_row(s) and re.match(r'^\|[\s\-|:]+\|$', s)

    def add_word_table(rows):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        cols = len(rows[0])
        tbl  = doc.add_table(rows=len(rows), cols=cols)
        tbl.style = 'Table Grid'
        for r_idx, row in enumerate(rows):
            for c_idx, cell_text in enumerate(row):
                cell = tbl.cell(r_idx, c_idx)
                cell.text = strip_inline(cell_text.strip())
                if r_idx == 0:  # header row bold + dark bg
                    run = cell.paragraphs[0].runs[0] if cell.paragraphs[0].runs else cell.paragraphs[0].add_run(cell.text)
                    cell.paragraphs[0].clear()
                    run = cell.paragraphs[0].add_run(cell_text.strip())
                    run.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    tc_pr = cell._tc.get_or_add_tcPr()
                    shd   = OxmlElement('w:shd')
                    shd.set(qn('w:val'),   'clear')
                    shd.set(qn('w:color'), 'auto')
                    shd.set(qn('w:fill'),  '1a1a1a')
                    tc_pr.append(shd)
        doc.add_paragraph()

    # Collect table rows before processing
    lines = md.split('\n')
    i = 0
    while i < len(lines):
        stripped = lines[i].rstrip()

        # Detect markdown table block
        if is_table_row(stripped) and i + 1 < len(lines) and is_separator_row(lines[i+1].rstrip()):
            parse_row = lambda s: [c for c in s.strip('|').split('|')]
            header = parse_row(stripped)
            i += 2  # skip header + separator
            data_rows = [header]
            while i < len(lines) and is_table_row(lines[i].rstrip()):
                data_rows.append(parse_row(lines[i].rstrip()))
                i += 1
            add_word_table(data_rows)
            continue

        if stripped.startswith('### '):
            doc.add_heading(strip_inline(stripped[4:]), level=3)
        elif stripped.startswith('## '):
            doc.add_heading(strip_inline(stripped[3:]), level=2)
        elif stripped.startswith('# '):
            doc.add_heading(strip_inline(stripped[2:]), level=1)
        elif stripped.startswith('---'):
            doc.add_paragraph('─' * 60)
        elif re.match(r'^[-*]\s+', stripped):
            text   = re.sub(r'^[-*]\s+', '', stripped)
            p      = doc.add_paragraph(style='List Bullet')
            tokens = re.split(r'(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*)', text)
            for tok in tokens:
                link_m = re.match(r'\[([^\]]+)\]\(([^)]+)\)', tok)
                if link_m:
                    _add_hyperlink(p, link_m.group(1), link_m.group(2))
                elif tok.startswith('**') and tok.endswith('**'):
                    run = p.add_run(tok[2:-2]); run.bold = True
                elif tok.startswith('*') and tok.endswith('*'):
                    run = p.add_run(tok[1:-1]); run.italic = True
                else:
                    p.add_run(tok)
        elif re.match(r'^\d+\.\s+', stripped):
            doc.add_paragraph(re.sub(r'^\d+\.\s+', '', stripped), style='List Number')
        elif stripped == '':
            doc.add_paragraph()
        else:
            add_md_para(stripped)
        i += 1

    # Footer
    doc.add_paragraph()
    ftr_para = doc.add_paragraph()
    date_str = datetime.now().strftime('%d/%m/%Y')
    ftr_run  = ftr_para.add_run(f"Generado por Lex — Sistema de Monitoreo Parlamentario · {date_str}")
    ftr_run.font.size  = Pt(8)
    ftr_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    ftr_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    filename = f"Resumen-Congreso-{datetime.now().strftime('%Y-%m-%d')}.docx"
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/sesiones/cookies-status")
async def sesiones_cookies_status():
    from scraper import COOKIE_PATHS, _get_cookie_path
    path = _get_cookie_path()
    return {"ok": bool(path), "path": path, "search_paths": COOKIE_PATHS}


@app.get("/sesiones/videos")
async def sesiones_videos():
    result = await fetch_videos_youtube(limit=15)
    return result


def _build_sesion_prompt(titulo: str, texto: str) -> str:
    return f"""Analiza este transcript de la sesión del Congreso del Perú titulada: "{titulo}".

Genera un resumen estructurado con este formato EXACTO:

## Resumen — {titulo}

### Temas tratados
[Tabla: Tema | Descripción | Resultado/Estado]

### Proyectos o normas mencionados
[Tabla: Número/Nombre | Tema | Posición mayoritaria]

### Votaciones o acuerdos
[Tabla: Asunto | A favor | En contra | Resultado]

### Puntos destacados
[Lista de los 3-5 momentos más relevantes de la sesión]

---
Transcript de la sesión:
{texto[:40000]}"""


@app.post("/sesiones/resumir")
async def sesiones_resumir(request: Request):
    body     = await request.json()
    video_id = body.get("video_id", "")
    titulo   = body.get("titulo", "este video")
    en_vivo  = body.get("en_vivo", False)
    api_key  = GROQ_API_KEY

    async def generate():
        if not video_id:
            yield f"data: {json.dumps({'error': 'Falta el ID del video'})}\n\n"
            return

        # ── Fase 1: subtítulos de YouTube ─────────────────────
        yield f"data: {json.dumps({'status': 'Buscando subtítulos en YouTube...'})}\n\n"
        loop = __import__('asyncio').get_event_loop()
        captions = await loop.run_in_executor(None, get_yt_captions, video_id)

        tr = captions  # can be None

        # ── Fase 2: Whisper si no hay subtítulos ──────────────
        if not tr:
            if not api_key:
                yield f"data: {json.dumps({'error': 'No hay subtítulos disponibles para este video.'})}\n\n"
                return

            minutes = 5 if en_vivo else 10
            label   = f"los últimos {minutes} min del stream en vivo" if en_vivo else f"los primeros {minutes} min"
            yield f"data: {json.dumps({'status': f'No hay subtítulos. Descargando audio ({label})... esto toma ~2 minutos.'})}\n\n"

            tr = await loop.run_in_executor(None, transcribe_with_whisper, video_id, api_key, minutes)
            if not tr.get("ok"):
                yield f"data: {json.dumps({'error': tr.get('error', 'No se pudo transcribir el audio.')})}\n\n"
                return

            nota = tr.get("nota", "")
            yield f"data: {json.dumps({'status': f'Audio transcrito. Analizando ({nota})...'})}\n\n"
        else:
            yield f"data: {json.dumps({'status': 'Subtítulos obtenidos. Analizando sesión...'})}\n\n"

        # Emitir transcript raw para que el frontend ofrezca descarga
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        yield f"data: {json.dumps({'transcript_raw': tr['text'], 'video_url': yt_url, 'video_titulo': titulo})}\n\n"

        prompt = _build_sesion_prompt(titulo, tr['text'])
        client = Groq(api_key=api_key)
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Eres Lex, experto en análisis parlamentario del Congreso del Perú. Analiza transcripts de sesiones y los conviertes en resúmenes ejecutivos con tablas."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,
                temperature=0.3,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield f"data: {json.dumps({'text': delta})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("sesiones_resumir LLM error: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/sesiones/resumir-texto")
async def sesiones_resumir_texto(request: Request):
    """Resume un transcript que el usuario pegó manualmente."""
    body    = await request.json()
    texto   = body.get("texto", "").strip()
    titulo  = body.get("titulo", "esta sesión")
    api_key = GROQ_API_KEY

    async def generate():
        if not texto:
            yield f"data: {json.dumps({'error': 'No hay texto para resumir.'})}\n\n"
            return
        if not api_key:
            yield f"data: {json.dumps({'error': 'Falta la API key de Groq.'})}\n\n"
            return

        yield f"data: {json.dumps({'status': 'Analizando transcripción...'})}\n\n"

        prompt = _build_sesion_prompt(titulo, texto)
        client = Groq(api_key=api_key)
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Eres Lex, experto en análisis parlamentario del Congreso del Perú."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,
                temperature=0.3,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield f"data: {json.dumps({'text': delta})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("sesiones_resumir_texto LLM error: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


LIVE_ANALYSIS_PROMPT = _p("live_analysis")


@app.get("/live/transcribe")
async def live_transcribe(video_id: str = Query(..., description="ID del video de YouTube")):
    """SSE stream que emite líneas de transcripción en tiempo real."""
    api_key = GROQ_API_KEY

    async def generate():
        if not api_key:
            yield f"data: {json.dumps({'error': 'Falta la GROQ_API_KEY'})}\n\n"
            return
        if not video_id:
            yield f"data: {json.dumps({'error': 'Falta el parámetro video_id'})}\n\n"
            return
        try:
            async for item in stream_transcription(video_id, api_key):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/live/analyze")
async def live_analyze(request: Request):
    """Analiza el transcript acumulado con Lex. Llamar cada ~60s desde el frontend."""
    body       = await request.json()
    transcript = body.get("transcript", "").strip()
    titulo     = body.get("titulo", "sesión en vivo")
    api_key    = os.getenv("GROQ_API_KEY", "")

    async def generate():
        if not transcript:
            yield f"data: {json.dumps({'error': 'Sin transcripción aún.'})}\n\n"
            return
        # Send only the last 3000 chars to keep tokens low
        excerpt = transcript[-3000:]
        prompt  = f'Sesión: "{titulo}"\n\nTranscripción reciente:\n{excerpt}'
        client  = Groq(api_key=api_key)
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": LIVE_ANALYSIS_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=400,
                temperature=0.3,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield f"data: {json.dumps({'text': delta})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/live", response_class=HTMLResponse)
async def live_page():
    return (Path("static") / "live.html").read_text()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8732))
    uvicorn.run(app, host="127.0.0.1", port=port)
