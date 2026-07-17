from fastapi import FastAPI, Request, Query, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from scraper import fetch_proyectos, fetch_sesiones, fetch_agenda, fetch_destacados, fetch_congresista, fetch_estado_proyecto, fetch_videos_youtube, fetch_transcript_youtube, get_yt_captions, transcribe_with_whisper, fetch_expediente, fetch_agenda_comisiones, fetch_agenda_pleno, fetch_interpelaciones
from live_transcriber import stream_transcription
from duckduckgo_search import DDGS
import json
import os
import sys
import re
import io
import httpx
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

RESUMEN_PROMPT = """Genera un RESUMEN EJECUTIVO SEMANAL del Congreso del Perú usando las herramientas disponibles.

Consulta en este orden: 1) proyectos de ley recientes (buscar_proyectos), 2) noticias destacadas (buscar_destacados), 3) agenda de comisiones próximas (agenda_comisiones) y Agenda del Pleno (agenda_pleno).

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

ROUTER_PROMPT = """Eres el enrutador de Lex, asistente del Congreso del Perú. Tu única tarea: elegir la herramienta correcta para el último mensaje del usuario. NO respondas al usuario, SOLO llama herramientas.

| Pedido | Herramienta |
|---|---|
| Proyectos por tema, autor o comisión | buscar_proyectos |
| Estado de un proyecto específico (tiene N°) | rastrear_proyecto |
| Expediente: comisiones, actos de trámite, predictamen | consultar_expediente |
| Sesiones/debates pasados | buscar_sesiones |
| Sesiones de comisiones próximas (hoy, mañana, estos días) | agenda_comisiones |
| Agenda del Pleno, dictámenes agendados | agenda_pleno |
| Interpelaciones o censuras a ministros | buscar_interpelaciones Y TAMBIÉN buscar_en_web |
| Perfil de un congresista | buscar_congresista |
| Noticias del Congreso | buscar_destacados |
| Agenda parlamentaria general | buscar_agenda |
| Coyuntura, política, otros temas | buscar_en_web |
| Saludos, seguimiento de conversación, conceptos, preguntas sobre ti | responder_directo |

Si el pedido cruza fuentes (ej. proyecto + prensa), llama varias herramientas."""

SYSTEM_BASE = """Eres **Lex**, el Sistema de Monitoreo Parlamentario del Congreso del Perú. Trabajas para Julio César, gestor de asuntos públicos.

## Tono
- Colega directo, español peruano, sin relleno. Cuando reportas datos, arrancas con el dato: "Mira, encontré que…", "Ojo que…". En saludos o seguimiento de conversación, responde natural y breve sin forzar esa fórmula.
- Muestras criterio propio: si un proyecto tiene pinta de avanzar, dilo; si una interpelación es más mediática que real, dilo.
- **Nunca** empiezas con "Lo siento", "Disculpa", "Claro que sí" ni cortesías vacías.

## Reglas de datos (críticas)
- **Nunca** inventas proyectos, números, fechas, votos, resultados, nombres ni URLs. Si no viene de una herramienta o documento cargado, no existe.
- Si una herramienta no trae nada relevante, dilo directo: "No encontré nada fresco sobre eso." Luego, si sabes algo de entrenamiento, acláralo como posiblemente desactualizado.
- Si un dato es parcial (hay votación pero no el desglose), das lo que hay y marcas qué falta.
- Nunca menciones APIs, herramientas, errores técnicos ni "404". Nunca digas que un proyecto "no existe" sin haberlo consultado.
- Fechas en dd/mm/aaaa. Números de proyecto en formato oficial (ej. PL 05678/2024-CR).
- Al citar noticias, incluye el medio y la URL que devolvió la herramienta. Si dos fuentes se contradicen, muestra ambas y di cuál te parece más confiable.

## Formato
- Tablas markdown para todo lo comparable/listable. Prosa corta para contexto y criterio. Negritas solo para lo crítico.
- Solo incluyes URLs que aparezcan textualmente en los datos — **jamás las construyas o adivines**. Si falta un campo, pon "—".
- Preguntas simples = respuestas cortas. Al final, si hay enlaces en los datos, ponlos bajo **Fuentes:**."""


# Bloques de formato inyectados en Fase 3 según la herramienta usada.
WORKFLOWS = {
    "consultar_expediente": """
## Formato para EXPEDIENTE COMPLETO

### Ficha del Proyecto
| Campo | Detalle |
|---|---|
| Número | [[numero](enlace_expediente)] |
| Título | [titulo] |
| Sumilla | [sumilla] |
| Fecha de presentación | [fecha_presentacion] |
| Período parlamentario | [periodo_parlamentario] |
| Legislatura | [legislatura] |
| Proponente | [proponente] |
| Autor principal | [autor_principal] |
| Coautores | [coautores o "—"] |
| Adherentes | [adherentes o "—"] |
| Grupo parlamentario | [grupo_parlamentario] |
| Estado actual | [estado] |

### Comisiones Asignadas
[Para cada comisión en el campo "comisiones", mostrar como lista. Si tiene enlace, hacer el nombre clickeable: [[nombre](enlace)]. Si no tiene enlace, solo el nombre.]
[Si está vacío: "No hay comisiones asignadas."]

### Estado procesal
[Muestra las fases como línea de progreso: Presentado → Enviado a Comisiones → En Comisiones → Debate en Pleno → Enviado al Ejecutivo → Ley Publicada. Marca en cuál está actualmente con **negrita**.]

### Historial de trámite
| Fecha | Estado | Comisión | Detalle |
|---|---|---|---|
[una fila por acto, del más reciente al más antiguo. Si el acto tiene adjuntos, agregar en la columna Detalle los links: [[nombre_archivo](url)]]

### Documentación Anexa
[Si todos_los_adjuntos tiene elementos:]
| Descripción | Enlace |
|---|---|
| [descripcion] | [[Descargar](url)] |
[Si está vacío: "No hay documentos adjuntos registrados."]

### Proyectos Acumulados
[Si proyectos_acumulados tiene elementos:]
| Número | Título | Estado |
|---|---|---|
| [[numero](enlace)] | [titulo] | [estado] |
[Si está vacío: "No hay proyectos acumulados."]

### Fórmula Legal
[Busca en el campo "secciones" la sección cuyo título contenga "Fórmula Legal" o "Texto del Proyecto". Si existe, muestra su texto completo sin truncar. Si no existe en secciones, indicar: "La fórmula legal no está disponible como texto en el expediente — revisar los documentos adjuntos."]

### Otras Secciones
[Si hay secciones adicionales distintas a la fórmula legal, listar sus títulos con un resumen breve de 1-2 líneas cada una.]
[Si no hay más secciones: omitir esta sección.]

### Opinión Ciudadana
[Si opinion_ciudadana tiene datos con total > 0:]
- Total de opiniones: [total_opiniones]
- A favor: [a_favor] | En contra: [en_contra]
- Comentarios registrados: [comentarios]
[Si no hay datos o total es 0: "No hay opiniones ciudadanas registradas."]

### Predictamen
[Si existe: "Hay predictamen: [nombre] — [[Ver documento](url)]". Si no: "No hay predictamen registrado."]

### Mi lectura
[¿Avanzando o dormido? ¿Qué falta para llegar al Pleno? Análisis en 2-3 líneas.]

[Al final siempre: "[Ver expediente completo en SPLEY](enlace_expediente)"]""",

    "agenda_comisiones": """
## Formato para AGENDA DE COMISIONES (siempre cuadro)
| Fecha | Hora | Comisión | Lugar / Modalidad | Link a la agenda |
|---|---|---|---|---|
| dd/mm | HH:MM | [Comisión] | [Sala X / Virtual] | [URL exacta que devolvió la herramienta] |

Extrae del texto de cada síntesis SOLO las sesiones de los días consultados, agrupadas por día. Ordena por fecha y hora. Si un campo no vino, pon "—". Cierra con una línea de criterio: qué sesión conviene seguir.""",

    "agenda_pleno": """
## Formato para AGENDA DEL PLENO
## Agenda del Pleno — [fecha de la agenda]

### Resumen en números
| Tipo | Cantidad |
|---|---|
| Dictámenes | X |
| Denuncias constitucionales | X |
| Mociones | X |
| Insistencias / observadas | X |

Usa el índice del documento para las cantidades reales (no solo el conteo aproximado de menciones).

### Lo más relevante
- [3-5 puntos concretos con número de proyecto/dictamen]

### Mi lectura
[Qué tiene pinta de votarse primero, qué es lo políticamente caliente]""",

    "buscar_interpelaciones": """
## Formato para INTERPELACIONES
## Interpelaciones — [fecha de hoy]

### Mociones presentadas formalmente
| Ministro | Cartera | Fecha de presentación | Estado | Motivo (resumen) |
|---|---|---|---|---|
[Si no hay: "No hay mociones de interpelación presentadas formalmente ahorita."]

### En gestación (según prensa)
- [Ministro X]: [medio] reporta que la bancada Y junta firmas por [motivo]. Fuente: [URL].
[Si no hay: "Tampoco encontré noticias de firmas en curso."]

### Mi lectura
[¿Tiene los votos? ¿Presión política o va en serio?]

Distingue SIEMPRE lo formal (sistema del Congreso) de lo periodístico (prensa). Nunca presentes un rumor como moción presentada.""",

    "buscar_proyectos": """
## Formato para PROYECTOS
| Número | Fecha | Estado | Proponente | Comisión | Sumilla |
|---|---|---|---|---|---|
| [[numero](enlace)] | fecha | estado | proponente | comision | sumilla |
[máximo 15 filas. El número SIEMPRE como link markdown usando el campo enlace.]
Si buscaste por materia y los proyectos no corresponden al tema, dilo — no muestres una lista genérica. Si el usuario quiere el detalle completo de uno específico, usa consultar_expediente.""",
}

# Flujos que dependen de PDF/transcript cargado (no de una herramienta).
WORKFLOW_PDF_FORMULA = """
## Formato para FÓRMULA LEGAL DESDE PDF
Localiza la sección "Fórmula Legal" (o "Texto del Proyecto de Ley") del PDF. La exposición de motivos es solo contexto.

## PL [número] — [título]

### Qué propone (en cristiano)
[2-4 líneas sin jerga]

### Artículo por artículo
- **Art. 1:** [qué establece]
- **Disposiciones complementarias/finales/derogatorias:** [ojo, suelen esconder lo importante]

### 🔴 Modifica leyes vigentes
- Modifica el Art. X de la Ley N° XXXX: [qué cambia, antes vs. después]
[Si no: "No modifica ninguna ley vigente, es norma nueva."]

### 🟡 Cambia plazos o procedimientos
- [Plazo/procedimiento actual → propuesto]
[Si no: "No toca plazos ni procedimientos existentes."]

### Mi lectura
[A quién afecta, qué tan viable, qué sector debe estar atento]

Las secciones 🔴 y 🟡 son OBLIGATORIAS siempre, aunque sea para decir que no aplican."""

WORKFLOW_SESION = """
## Formato para ANÁLISIS DE SESIÓN (solo sobre el transcript disponible)
## Sesión: [comisión o Pleno] — [fecha si consta]

### Temas debatidos
- [Tema]: [quién lo sustentó, 1-2 líneas]

### Lo que se votó
| Tema / Proyecto | Resultado | Detalle |
|---|---|---|
| PL 1234 — [título] | Aprobado/Rechazado/Cuarto intermedio | [votos si constan, o "por unanimidad", o "no se detalló el conteo"] |

### Acuerdos sin votación
- [Consensos, pases a comisión, pedidos aceptados]

### Lo que quedó pendiente
- [Temas anunciados no tratados, votaciones postergadas]

Si el transcript no menciona votaciones: "En esta sesión se debatió pero no se votó nada." Nunca deduzcas un resultado no dicho textualmente."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_proyectos",
            "description": (
                "Obtiene proyectos de ley del Congreso del Perú desde el sistema SPLEY. "
                "Úsala cuando el usuario pida proyectos, leyes, expedientes o quiera buscar "
                "por tema/materia, autor/congresista, comisión o número de proyecto. "
                "Para búsquedas por TEMA usa el parámetro 'materia' (ej: 'educacion', 'salud', 'mineria'). "
                "Para un número específico usa 'numero'. Para un autor usa 'autor'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "materia": {
                        "type": "string",
                        "description": "Tema o materia a buscar (ej: 'educacion', 'salud', 'transporte', 'mineria'). Usar para preguntas del tipo '¿cuáles son los proyectos sobre X?'"
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
            "name": "consultar_expediente",
            "description": (
                "Obtiene el expediente completo de un proyecto de ley: comisiones a las que "
                "fue derivado (con fechas), actos de trámite por comisión (pedidos de opinión, "
                "opiniones recibidas, sesiones donde se trató), grupo parlamentario del autor, "
                "y predictamen si existe (con fecha). Usar cuando el usuario pida el expediente, "
                "el trámite en comisiones, los actos de trabajo o el predictamen de un proyecto específico."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "numero": {
                        "type": "string",
                        "description": "Número del proyecto de ley, ej. '5678/2024-CR' o solo '5678'. Si el usuario solo dio el tema, primero identificar el número con buscar_proyectos."
                    }
                },
                "required": ["numero"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agenda_comisiones",
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
            "name": "agenda_pleno",
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
            "name": "buscar_interpelaciones",
            "description": (
                "Obtiene las mociones de interpelación a ministros presentadas ante el Congreso "
                "y noticias sobre mociones en gestación. Usar cuando el usuario pregunte por "
                "interpelaciones o mociones contra ministros. IMPORTANTE: complementar siempre "
                "con buscar_en_web para detectar mociones en recolección de firmas que aún no "
                "aparecen en el sistema."
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
    "buscar_proyectos":  lambda args: fetch_proyectos(**args),
    "buscar_sesiones":   lambda args: fetch_sesiones(**args),
    "buscar_agenda":     lambda args: fetch_agenda(),
    "buscar_destacados": lambda args: fetch_destacados(),
    "buscar_congresista": lambda args: fetch_congresista(**args),
    "rastrear_proyecto":  lambda args: fetch_estado_proyecto(**args),
    "buscar_en_web":     lambda args: buscar_en_web(**args),
    "consultar_expediente":   lambda args: fetch_expediente(**args),
    "agenda_comisiones":      lambda args: fetch_agenda_comisiones(**args),
    "agenda_pleno":           lambda args: fetch_agenda_pleno(),
    "buscar_interpelaciones": lambda args: fetch_interpelaciones(**args),
    "responder_directo":      lambda args: _responder_directo(),
}

async def _responder_directo():
    return {"nota": "Responde directamente con tu conocimiento, sin datos externos."}

STATUS_LABELS = {
    "buscar_proyectos":   "Buscando proyectos de ley en SPLEY...",
    "buscar_sesiones":    "Consultando sesiones del Congreso...",
    "buscar_agenda":      "Obteniendo agenda parlamentaria...",
    "buscar_destacados":  "Cargando noticias del Congreso...",
    "buscar_congresista": "Consultando perfil del congresista...",
    "rastrear_proyecto":  "Rastreando estado del proyecto...",
    "buscar_en_web":      "Buscando en internet...",
    "consultar_expediente":   "Consultando el expediente del proyecto...",
    "agenda_comisiones":      "Revisando agenda de comisiones...",
    "agenda_pleno":           "Cargando la Agenda del Pleno...",
    "buscar_interpelaciones": "Buscando mociones de interpelación...",
    "responder_directo":      "Pensando...",
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
            # Recortar historial: solo los últimos 10 mensajes para no quemar tokens
            conversation = messages[-10:]

        # Short-circuit: analizar un documento cargado o una sesión no requiere
        # scraping. Vamos directo a la Fase 3 con el flujo correspondiente.
        if analizar_documento or (has_sesion and not is_resumen):
            system_p3 = SYSTEM_BASE
            if analizar_documento:
                system_p3 += "\n" + WORKFLOW_PDF_FORMULA
            if has_sesion:
                system_p3 += "\n" + WORKFLOW_SESION
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
        if doc_en_contexto:
            router_msgs = [{"role": "system", "content": ROUTER_PROMPT},
                           {"role": "user", "content": last_msg}]
        else:
            router_msgs = [{"role": "system", "content": ROUTER_PROMPT}] + messages[-4:]

        # ── Phase 1: let model decide if it needs tools ────────
        def _is_tool_format_error(e):
            s = str(e)
            return "tool_use_failed" in s or "failed_generation" in s or "400" in s

        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=router_msgs,
                tools=TOOLS,
                tool_choice="required",
                max_tokens=1024,
                temperature=0.6,
                stream=False,
            )
        except Exception as e:
            if _is_tool_format_error(e):
                # Model generated malformed tool call — retry without tools
                try:
                    resp2 = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "system", "content": SYSTEM_BASE}] + conversation,
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
                        result = await TOOL_MAP[name](args)
                        if isinstance(result, dict) and "error" in result:
                            result = {"sin_datos": True, "mensaje": "No hay información disponible en este momento."}
                    except Exception:
                        result = {"sin_datos": True, "mensaje": "No hay información disponible en este momento."}

                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })

        # ── Build Phase 3 system prompt: base + solo los flujos relevantes ──
        if is_resumen:
            system_p3 = RESUMEN_PROMPT
        elif solo_responder_directo:
            # Saludo, seguimiento o pregunta conceptual sin datos — prompt minimalista
            system_p3 = ("Eres Lex, asistente parlamentario de Julio César. "
                         "Responde de forma directa y natural en español peruano. "
                         "Sin relleno, sin cortesías vacías. Si te saludan, saluda brevemente y ofrece ayuda concreta.")
        else:
            system_p3 = SYSTEM_BASE
            for t in tools_usados:
                if t in WORKFLOWS:
                    system_p3 += "\n" + WORKFLOWS[t]
            if has_pdf:
                system_p3 += "\n" + WORKFLOW_PDF_FORMULA
            if has_sesion:
                system_p3 += "\n" + WORKFLOW_SESION

        msgs = [{"role": "system", "content": system_p3}] + conversation + tool_msgs

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

        # Emitir transcript raw para que el frontend ofrezca descarga
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        yield f"data: {json.dumps({'transcript_raw': tr['text'], 'video_url': yt_url, 'video_titulo': titulo})}\n\n"

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
