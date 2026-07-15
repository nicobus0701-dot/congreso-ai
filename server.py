from fastapi import FastAPI, Request, Query, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from scraper import fetch_proyectos, fetch_sesiones, fetch_agenda, fetch_destacados, fetch_congresista, fetch_estado_proyecto, fetch_videos_youtube, fetch_transcript_youtube, get_yt_captions, transcribe_with_whisper
from live_transcriber import stream_transcription
from duckduckgo_search import DDGS
import json
import os
import re
import io
import httpx
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

RESUMEN_PROMPT = """Genera un RESUMEN EJECUTIVO SEMANAL del Congreso del Perú usando las herramientas disponibles.

Consulta en este orden: 1) proyectos de ley recientes, 2) noticias destacadas, 3) agenda parlamentaria.

Estructura el resumen EXACTAMENTE así (usa estos encabezados):

# RESUMEN EJECUTIVO — CONGRESO DEL PERÚ
**Semana del [fecha actual]**
Preparado por: Lex — Sistema de Monitoreo Parlamentario

---

## 1. PANORAMA DE LA SEMANA
[2-3 párrafos describiendo el contexto político general y los temas que dominaron la agenda]

## 2. PROYECTOS DE LEY DESTACADOS
[Tabla con los proyectos más relevantes: Número | Fecha | Estado | Materia | Autores]
[Breve análisis de los 2-3 más importantes]

## 3. AGENDA Y SESIONES
[Lista de sesiones y convocatorias relevantes con fechas]

## 4. NOTICIAS Y COYUNTURA
[Las 3-5 noticias más importantes con su impacto]

## 5. PUNTOS DE ATENCIÓN
[Lista de temas que requieren seguimiento la próxima semana]

---
**Fuentes verificadas:**
[Lista de links a las fuentes consultadas]

Sé analítico, no solo descriptivo. Incluye tu criterio sobre qué es relevante y por qué."""

SYSTEM_PROMPT = """Eres Lex, un asistente especializado en el Congreso del Perú. Trabajas con Julio Cesar, gestor de asuntos públicos.

CUÁNDO USAR LAS HERRAMIENTAS:
Úsalas siempre que el tema pueda tener información reciente o actualizada, incluso si el usuario no dice "busca" explícitamente. Ejemplos:
- Cualquier pregunta sobre proyectos de ley, sesiones, agenda, noticias o actividad del Congreso → usa las tools del Congreso
- Preguntas sobre temas de coyuntura, política, economía, noticias del día → usa buscar_en_web
- Perfil o actividad de un congresista → buscar_congresista
- Estado de un proyecto específico → rastrear_proyecto
Tu objetivo es siempre dar LA INFORMACIÓN MÁS RECIENTE disponible. Si hay tools relevantes, úsalas antes de responder.

CUÁNDO NO USAR HERRAMIENTAS — responde directo con tu conocimiento:
- Saludos o apertura de conversación ("hola", "buenos días")
- Preguntas sobre ti mismo o cómo funcionas
- Seguimiento de respuesta anterior: "¿y eso qué implica?", "explicame eso", "¿qué opinas?"
- Conceptos, definiciones, historia o conocimiento general que no requiere datos del momento
- Conversación casual o estrategia sin necesidad de datos frescos

CÓMO HABLAR:
- Natural y directo, como colega. Sin intro larga. Nunca empieces con "A continuación", "Aquí te presento", "Por supuesto", "Claro que sí" ni frases de relleno.
- Español peruano, sin ser formal.
- Arranca directo con el dato: "Mira, encontré que...", "Ojo que...", "Lo interesante acá es..."
- Muestra criterio propio: si algo en los datos te parece importante, dilo.
- Para conocimiento general (historia, definiciones, conceptos) puedes responder con lo que ya sabes, sin necesitar datos externos.

CUANDO NO HAY DATOS FRESCOS:
Si la consulta devuelve vacío, error o sin_datos=True, di lo que sabes de tu entrenamiento y aclara que no encontraste información actualizada al momento. Nunca digas: "error", "404", "herramienta", "API".

NUNCA:
- Menciones APIs, herramientas, errores técnicos ni limitaciones del sistema.
- Inventes proyectos, números de expediente, votos, fechas de sesión ni datos del Congreso que no estén textualmente en los resultados de las tools.
- Construyas ni adivines URLs. Solo usa enlaces que aparezcan explícitamente en los datos devueltos.
- Empieces respuestas con "Lo siento" ni con disculpas de ningún tipo.

FORMATO (solo cuando traigas datos):
- Varios proyectos: tabla Número | Fecha | Estado | Sumilla | Autores
- Noticias/sesiones: lista corta con contexto
- Una cosa específica: prosa conversacional

AL FINAL de respuestas con datos de tools, agrega SOLO los enlaces que aparezcan textualmente en los datos. NUNCA construyas URLs. Si no hay enlaces en los datos, no pongas sección de fuentes.
---
**Fuentes:**
- [descripción](enlace exacto del dato)"""

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
    "buscar_proyectos":  lambda args: fetch_proyectos(**args),
    "buscar_sesiones":   lambda args: fetch_sesiones(**args),
    "buscar_agenda":     lambda args: fetch_agenda(),
    "buscar_destacados": lambda args: fetch_destacados(),
    "buscar_congresista": lambda args: fetch_congresista(**args),
    "rastrear_proyecto":  lambda args: fetch_estado_proyecto(**args),
    "buscar_en_web":     lambda args: buscar_en_web(**args),
}

STATUS_LABELS = {
    "buscar_proyectos":   "Buscando proyectos de ley en SPLEY...",
    "buscar_sesiones":    "Consultando sesiones del Congreso...",
    "buscar_agenda":      "Obteniendo agenda parlamentaria...",
    "buscar_destacados":  "Cargando noticias del Congreso...",
    "buscar_congresista": "Consultando perfil del congresista...",
    "rastrear_proyecto":  "Rastreando estado del proyecto...",
    "buscar_en_web":      "Buscando en internet...",
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
    api_key  = os.getenv("GROQ_API_KEY", "")

    if not api_key:
        async def err():
            yield f"data: {json.dumps({'error': 'Falta la API key de Groq'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    client = Groq(api_key=api_key)

    async def generate():
        # Detectar si es solicitud de resumen semanal
        last_msg = messages[-1].get("content", "") if messages else ""
        is_resumen = last_msg.strip().startswith("__RESUMEN_SEMANAL__")
        sector = None
        if is_resumen and ":" in last_msg:
            sector = last_msg.strip().split(":", 1)[1].strip()

        system = RESUMEN_PROMPT if is_resumen else SYSTEM_PROMPT

        msgs = [{"role": "system", "content": system}]
        if is_resumen:
            base = "Genera el resumen ejecutivo semanal completo del Congreso del Perú."
            if sector and sector != "general":
                base += f" Enfoca el análisis especialmente en el sector {sector} y los proyectos de ley, noticias y agenda que impacten a ese sector."
            msgs.append({"role": "user", "content": base})
        else:
            # Recortar historial: solo los últimos 10 mensajes para no quemar tokens
            msgs += messages[-10:]

        def _friendly_error(e):
            s = str(e).lower()
            if "rate limit" in s or "429" in s or "tokens per" in s or "quota" in s:
                return "Llegamos al límite de tokens de Groq por ahora. Espera unos segundos y vuelve a intentarlo."
            return "Hubo un problema al conectar. Intentá de nuevo."

        # ── Phase 1: let model decide if it needs tools ────────
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=msgs,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=512,
                temperature=0.6,
                stream=False,
            )
        except Exception as e:
            yield f"data: {json.dumps({'error': _friendly_error(e)})}\n\n"
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
                # Coerce limit to int (model sometimes sends it as string)
                if "limit" in args:
                    try:
                        args["limit"] = int(args["limit"])
                    except (ValueError, TypeError):
                        args["limit"] = 20
                # Strip empty-string optional params so scrapers use their defaults
                args = {k: v for k, v in args.items() if v != ""}

                # Send status to frontend
                status = STATUS_LABELS.get(name, "Consultando el Congreso...")
                yield f"data: {json.dumps({'status': status})}\n\n"

                # Execute scraper
                try:
                    result = await TOOL_MAP[name](args)
                    # If scraper returned an error dict, neutralize it
                    if isinstance(result, dict) and "error" in result:
                        result = {"sin_datos": True, "mensaje": "No hay información disponible en este momento."}
                except Exception:
                    result = {"sin_datos": True, "mensaje": "No hay información disponible en este momento."}

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
            yield f"data: {json.dumps({'error': _friendly_error(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/export/docx")
async def export_docx(request: Request):
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

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
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
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
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
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
    from scraper import _get_cookie_path, COOKIE_PATHS
    path = _get_cookie_path()
    return {"ok": bool(path), "path": path, "search_paths": COOKIE_PATHS}


@app.get("/sesiones/videos")
async def sesiones_videos():
    result = await fetch_videos_youtube(limit=15)
    return result


@app.post("/sesiones/resumir")
async def sesiones_resumir(request: Request):
    body     = await request.json()
    video_id = body.get("video_id", "")
    titulo   = body.get("titulo", "este video")
    en_vivo  = body.get("en_vivo", False)
    api_key  = os.getenv("GROQ_API_KEY", "")

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

        prompt = f"""Analiza este transcript de la sesión del Congreso del Perú titulada: "{titulo}".

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
{tr['text']}"""

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
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/sesiones/resumir-texto")
async def sesiones_resumir_texto(request: Request):
    """Resume un transcript que el usuario pegó manualmente."""
    body    = await request.json()
    texto   = body.get("texto", "").strip()
    titulo  = body.get("titulo", "esta sesión")
    api_key = os.getenv("GROQ_API_KEY", "")

    async def generate():
        if not texto:
            yield f"data: {json.dumps({'error': 'No hay texto para resumir.'})}\n\n"
            return
        if not api_key:
            yield f"data: {json.dumps({'error': 'Falta la API key de Groq.'})}\n\n"
            return

        yield f"data: {json.dumps({'status': 'Analizando transcripción...'})}\n\n"

        prompt = f"""Analiza este transcript de la sesión del Congreso del Perú titulada: "{titulo}".

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
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


LIVE_ANALYSIS_PROMPT = """Estás monitoreando un debate parlamentario en el Congreso del Perú EN VIVO.
Recibirás fragmentos de la transcripción en tiempo real.

Basándote en la transcripción acumulada hasta ahora, genera un análisis breve y actualizado:

**Estado del debate:** [1 línea sobre qué se está debatiendo]
**Posiciones clave:** [qué están diciendo los congresistas, si hay tensiones]
**Puntos de atención:** [algo relevante para un consultor de asuntos públicos]

Sé conciso (máximo 150 palabras). Tono analítico, no descriptivo."""


@app.get("/live/transcribe")
async def live_transcribe(video_id: str = Query(..., description="ID del video de YouTube")):
    """SSE stream que emite líneas de transcripción en tiempo real."""
    api_key = os.getenv("GROQ_API_KEY", "")

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
    uvicorn.run(app, host="0.0.0.0", port=port)
