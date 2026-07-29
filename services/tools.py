"""
Catálogo de herramientas que el modelo puede invocar en la Fase 1 del chat.

TOOLS        — schemas en formato function-calling de OpenAI/Groq.
TOOL_MAP     — nombre de herramienta → coroutine que la ejecuta.
STATUS_LABELS— texto de progreso que ve el usuario mientras corre cada una.
"""
import asyncio

from ddgs import DDGS

from config import logger
from scraper import (
    fetch_agenda,
    fetch_agenda_camaras,
    fetch_agenda_comisiones,
    fetch_agenda_pleno,
    fetch_comisiones,
    fetch_congresista,
    fetch_destacados,
    fetch_estado_proyecto,
    fetch_expediente,
    fetch_interpelaciones,
    fetch_proyectos,
    fetch_sesiones,
)

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
            "name": "fetch_comisiones",
            "description": (
                "Obtiene el CUADRO DE COMISIONES del Congreso del Perú (las 89 comisiones "
                "ordinarias, especiales y de investigación) y los accesos oficiales a la "
                "COMISIÓN PERMANENTE y a las comisiones del Senado y de la Cámara de "
                "Diputados. Devuelve además los enlaces directos verificados a los portales "
                "y visores oficiales. Úsala SIEMPRE que el usuario pida el cuadro de "
                "comisiones, la lista de comisiones, los miembros o integrantes de una "
                "comisión, o los accesos a la Comisión Permanente del Senado o Diputados. "
                "NO respondas que no tienes acceso: llama a esta herramienta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "camara": {
                        "type": "string",
                        "description": "Opcional. 'senado' o 'diputados' para priorizar los enlaces de esa cámara. Omitir para incluir ambas."
                    }
                }
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
    """
    Búsqueda web en un executor — el SDK es síncrono y bloquearía el loop.

    Usa `ddgs`. El paquete anterior (`duckduckgo_search`) quedó deprecado y su
    parser dejó de extraer resultados: devolvía [] para toda consulta sin lanzar
    excepción, así que el modelo concluía "no tengo acceso" en vez de fallar.
    Por eso acá una lista vacía se reporta explícitamente como sin_datos.
    """
    def _search():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=limit))

    try:
        results = await asyncio.get_running_loop().run_in_executor(None, _search)
    except Exception as e:
        logger.warning("buscar_en_web falló para %r: %s", query, e)
        return {"sin_datos": True, "mensaje": f"La búsqueda web falló: {e}"}

    if not results:
        logger.warning("buscar_en_web sin resultados para %r", query)
        return {"sin_datos": True,
                "mensaje": f"La búsqueda web no devolvió resultados para '{query}'."}

    return [{"titulo": r.get("title"), "url": r.get("href"), "resumen": r.get("body")}
            for r in results]


async def _responder_directo():
    return {"nota": "Responde directamente con tu conocimiento, sin datos externos."}


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
    "fetch_comisiones":        lambda args: fetch_comisiones(**{k: v for k, v in args.items() if k in ("camara",)}),
    "fetch_agenda_camaras":    lambda args: fetch_agenda_camaras(**{k: v for k, v in args.items() if k in ("dias", "camara")}),
    "fetch_interpelaciones":   lambda args: fetch_interpelaciones(**{k: v for k, v in args.items() if k in ("ministro",)}),
    "responder_directo":       lambda args: _responder_directo(),
}

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
    "fetch_comisiones":        "Consultando el cuadro de comisiones...",
    "fetch_agenda_camaras":    "Revisando agenda del Congreso bicameral...",
    "fetch_interpelaciones":   "Buscando mociones de interpelación...",
    "responder_directo":       "Pensando...",
}
