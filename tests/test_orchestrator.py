"""
Tests del ChatOrchestrator.

Toda la lógica de decisión (qué fase correr, qué historial mandar, qué system
prompt armar) es pura y se testea sin tocar Groq ni la red.
"""
import pytest

from services.orchestrator import ChatOrchestrator
from services.prompt_registry import RESUMEN_PROMPT, SYSTEM_MINI


def make(messages, **kwargs):
    """Orquestador ya analizado, con un cliente falso."""
    orch = ChatOrchestrator(messages, client=object())
    orch._analyze()
    for k, v in kwargs.items():
        setattr(orch, k, v)
    return orch


def user(content):
    return {"role": "user", "content": content}


def assistant(content):
    return {"role": "assistant", "content": content}


# ── _analyze ─────────────────────────────────────────────────────────────────

def test_detecta_resumen_semanal_con_sector():
    orch = make([user("__RESUMEN_SEMANAL__: mineria")])
    assert orch.is_resumen
    assert orch.sector == "mineria"
    # El historial se reemplaza por una instrucción sintética.
    assert len(orch.conversation) == 1
    assert "sector mineria" in orch.conversation[0]["content"]


def test_resumen_general_no_menciona_sector():
    orch = make([user("__RESUMEN_SEMANAL__: general")])
    assert orch.is_resumen
    assert "Enfoca el análisis" not in orch.conversation[0]["content"]


def test_detecta_documento_en_contexto():
    orch = make([
        user("He cargado el documento PL-1234.pdf"),
        user("resume la fórmula legal"),
    ])
    assert orch.doc_en_contexto
    assert orch.analizar_documento
    assert orch._short_circuit


def test_documento_con_pregunta_corta_tambien_analiza():
    """Una pregunta breve tras cargar un doc se asume sobre ese doc."""
    orch = make([user("He cargado el documento X.pdf"), user("¿y esto?")])
    assert orch.analizar_documento


def test_documento_con_pregunta_larga_no_relacionada_no_analiza():
    pregunta = (
        "cuales son los proyectos de ley sobre transporte publico presentados "
        "por la comision de economia en el ultimo periodo parlamentario"
    )
    orch = make([user("He cargado el documento X.pdf"), user(pregunta)])
    assert not orch.analizar_documento


def test_detecta_link_de_sesion():
    orch = make([user("analiza https://youtu.be/abcdefghijk")])
    assert orch.has_sesion
    assert orch._short_circuit


def test_resumen_semanal_no_hace_short_circuit_por_sesion():
    """El resumen semanal manda aunque el texto mencione un transcript."""
    orch = make([user("__RESUMEN_SEMANAL__: general transcript")])
    assert orch.is_resumen
    assert not orch._short_circuit


def test_pregunta_normal_no_hace_short_circuit():
    orch = make([user("qué proyectos de ley hay sobre salud")])
    assert not orch._short_circuit
    assert not orch.doc_en_contexto


def test_detecta_expediente_en_contexto():
    orch = make([
        user("dame el expediente 14864"),
        assistant("## FICHA DEL PROYECTO\n...\n## MI LECTURA"),
        user("qué comisiones lo vieron"),
    ])
    assert orch.has_expediente_en_contexto


# ── Fase 1: recorte del historial al router ──────────────────────────────────

def test_router_recorta_historial_si_hay_documento():
    """Un PDF en contexto son miles de tokens que no ayudan a elegir tool."""
    orch = make([user("He cargado el documento " + "x" * 5000), user("hola")])
    msgs = orch._router_messages()
    assert len(msgs) == 2
    assert msgs[1]["content"] == "hola"


def test_router_resume_expediente_en_vez_de_reenviarlo():
    orch = make([
        user("expediente 14864"),
        assistant("FICHA DEL PROYECTO " + "y" * 9000),
        user("y qué comisiones?"),
    ])
    msgs = orch._router_messages()
    assert len(msgs) == 2
    assert "responder_directo" in msgs[1]["content"]
    assert "y qué comisiones?" in msgs[1]["content"]
    assert "y" * 9000 not in msgs[1]["content"]


def test_router_usa_ultimos_4_mensajes_por_defecto():
    msgs_in = [user(f"m{i}") for i in range(10)]
    orch = make(msgs_in)
    msgs = orch._router_messages()
    assert len(msgs) == 5           # system + 4
    assert msgs[-1]["content"] == "m9"


# ── Fase 2: saneado de argumentos ────────────────────────────────────────────

@pytest.mark.parametrize("raw,esperado", [
    ('{"materia": "salud"}',        {"materia": "salud"}),
    ('{"limit": "20"}',             {"limit": 20}),      # string → int
    ('{"limit": "muchos"}',         {"limit": 20}),      # basura → default
    ('{"materia": ""}',             {}),                 # vacíos se descartan
    ("no es json",                  {}),
    ("",                            {}),
    ("[1,2,3]",                     {}),                 # no es un objeto
])
def test_clean_args(raw, esperado):
    assert ChatOrchestrator._clean_args(raw) == esperado


# ── Fase 3: elección de system prompt ────────────────────────────────────────

def test_phase3_usa_prompt_de_resumen():
    orch = make([user("__RESUMEN_SEMANAL__: general")])
    assert orch._phase3_system() == RESUMEN_PROMPT


def test_phase3_usa_mini_con_tools_sin_workflow():
    """Sin workflow propio se ahorra ~800 tokens usando SYSTEM_MINI."""
    orch = make([user("busca en internet qué es una moción")],
                tools_usados=["buscar_en_web"],
                tool_msgs=[{"role": "tool", "content": "{}"}])
    system = orch._phase3_system()
    assert system == SYSTEM_MINI.format(hoy=orch.hoy)


def test_phase3_inyecta_workflow_de_la_tool_usada():
    orch = make([user("expediente 14864")],
                tools_usados=["fetch_expediente"],
                tool_msgs=[{"role": "tool", "content": "{}"}])
    system = orch._phase3_system()
    assert system.startswith(orch.system_base)
    assert len(system) > len(orch.system_base)


def test_phase3_sin_tools_usa_base():
    orch = make([user("hola")])
    assert orch._phase3_system() == orch.system_base


def test_phase3_responder_directo_usa_base():
    orch = make([user("hola")], solo_responder_directo=True)
    assert orch._phase3_system() == orch.system_base


# ── Fase 3: presupuesto de tokens ────────────────────────────────────────────

@pytest.mark.parametrize("tools,esperado", [
    (["fetch_expediente"],  4000),   # expedientes son largos
    (["buscar_proyectos"],  1800),   # respuestas cortas, menos presión de TPM
    ([],                    2500),   # conversación libre
])
def test_phase3_max_tokens(tools, esperado):
    orch = make([user("x")], tools_usados=tools)
    assert orch._phase3_max_tokens() == esperado
