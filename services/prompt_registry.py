"""
Prompts cargados desde prompts/*.md al arranque.

Un solo punto de import para todo el prompt del sistema: los routers y el
orquestador piden constantes de aquí en vez de leer archivos por su cuenta.
"""
from config import load_prompt

RESUMEN_PROMPT = load_prompt("resumen")
ROUTER_PROMPT  = load_prompt("router")
SYSTEM_BASE    = load_prompt("system_base")

# System prompt compacto para Fase 3 con tool results — ahorra ~800 tokens
# vs SYSTEM_BASE. Lleva un placeholder {hoy}.
SYSTEM_MINI = load_prompt("system_mini")

LIVE_ANALYSIS_PROMPT = load_prompt("live_analysis")

# Bloques de formato inyectados en Fase 3 según la herramienta usada.
WORKFLOWS = {
    "fetch_expediente":        load_prompt("workflow_expediente"),
    "fetch_agenda_comisiones": load_prompt("workflow_agenda_comisiones"),
    "fetch_agenda_pleno":      load_prompt("workflow_agenda_pleno"),
    "fetch_interpelaciones":   load_prompt("workflow_interpelaciones"),
    "fetch_agenda_camaras":    load_prompt("workflow_agenda_camaras"),
    "buscar_proyectos":        load_prompt("workflow_proyectos"),
}

# Flujos que dependen de un PDF/transcript cargado, no de una herramienta.
WORKFLOW_PDF_FORMULA = load_prompt("workflow_pdf")
WORKFLOW_SESION      = load_prompt("workflow_sesion")

# Nota de fecha que se añade a SYSTEM_BASE en cada request para evitar
# alucinaciones temporales y respuestas secas cuando no hay sesiones.
FECHA_NOTA = (
    "\n\n**Fecha actual: {hoy}** — Solo muestra sesiones o eventos a partir de hoy. "
    "Si una herramienta no devuelve sesiones reales, NO digas simplemente 'no hay sesiones'. "
    "En cambio: (1) explica brevemente el posible motivo (feriado, receso parlamentario, "
    "fin de semana, etc. según la fecha), (2) sugiere alternativas concretas como revisar "
    "la agenda de la semana siguiente, consultar proyectos de ley en trámite, o revisar "
    "los destacados y citaciones. Sé directo y útil, no te limites a dar una negativa seca."
)


def system_con_fecha(hoy: str) -> str:
    """SYSTEM_BASE + la nota de fecha del día."""
    return SYSTEM_BASE + FECHA_NOTA.format(hoy=hoy)


def build_sesion_prompt(titulo: str, texto: str) -> str:
    """Prompt de resumen de sesión — compartido por /sesiones/resumir y resumir-texto."""
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
