"""
Tests del ChatOrchestrator.

Toda la lógica de decisión (qué fase correr, qué historial mandar, qué system
prompt armar) es pura y se testea sin tocar Groq ni la red.
"""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.orchestrator import (
    DEFAULT_DIAS_PROYECTOS,
    RESUMEN_DIAS,
    RESUMEN_TOOLS,
    ChatOrchestrator,
    _detecta_proyectos_por_dias,
)
from services.prompt_registry import SYSTEM_MINI, resumen_con_fechas


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
    assert orch._phase3_system() == resumen_con_fechas(orch.hoy, orch.desde)


def test_prompt_de_resumen_lleva_la_ventana_de_fechas():
    """Sin fechas reales el modelo no puede descartar material viejo."""
    orch = make([user("__RESUMEN_SEMANAL__: general")])
    system = orch._phase3_system()
    assert "[fecha actual]" not in system
    assert orch.hoy in system
    assert orch.desde in system
    assert orch.desde != orch.hoy


def test_ventana_del_resumen_son_siete_dias():
    orch = make([user("__RESUMEN_SEMANAL__: general")])
    fmt = "%d/%m/%Y"
    delta = datetime.strptime(orch.hoy, fmt) - datetime.strptime(orch.desde, fmt)
    assert delta.days == RESUMEN_DIAS


@pytest.mark.asyncio
async def test_resumen_usa_herramientas_fijas_no_el_router():
    """
    El resumen semanal no le deja la elección de herramientas al router (8B):
    dejado a su criterio terminaba llamando 7-8 de golpe y reventaba el TPM
    de Groq. _phase2_tools_fijas corre exactamente RESUMEN_TOOLS, en orden.
    """
    orch = make([user("__RESUMEN_SEMANAL__: general")])
    with patch.object(ChatOrchestrator, "_run_tool", new=AsyncMock(return_value={"ok": True})):
        events = [ev async for ev in orch._phase2_tools_fijas(RESUMEN_TOOLS)]

    assert orch.tools_usados == [name for name, _ in RESUMEN_TOOLS]
    assert len(events) == len(RESUMEN_TOOLS)  # un sse.status por herramienta

    # El mensaje "assistant" con tool_calls trae las 4 llamadas de una, y cada
    # una tiene un tool_call_id único que matchea con su mensaje "tool".
    assistant_msg = orch.tool_msgs[0]
    assert len(assistant_msg["tool_calls"]) == len(RESUMEN_TOOLS)
    tool_msgs = [m for m in orch.tool_msgs if m["role"] == "tool"]
    assert len(tool_msgs) == len(RESUMEN_TOOLS)
    ids_assistant = {tc["id"] for tc in assistant_msg["tool_calls"]}
    ids_tool = {m["tool_call_id"] for m in tool_msgs}
    assert ids_assistant == ids_tool


@pytest.mark.asyncio
async def test_run_no_llama_a_fase1_para_resumen():
    """run() desvía is_resumen a _phase2_tools_fijas directo, sin pasar por Fase 1."""
    orch = make([user("__RESUMEN_SEMANAL__: general")])
    with patch.object(ChatOrchestrator, "_phase1", new=AsyncMock(side_effect=AssertionError("no debería llamarse"))), \
         patch.object(ChatOrchestrator, "_run_tool", new=AsyncMock(return_value={"ok": True})), \
         patch.object(ChatOrchestrator, "_stream_final") as mock_stream:
        async def fake_stream(*a, **k):
            yield "data: [DONE]\n\n"
        mock_stream.side_effect = fake_stream
        events = [ev async for ev in orch.run()]

    assert events  # llegó hasta el final sin explotar en Fase 1


# ── _detecta_proyectos_por_dias ───────────────────────────────────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("Revisa los proyectos de ley de los últimos 15 días calendario, y "
     "entrégame un cuadro resumen dividido por temas", 15),
    ("qué proyectos de ley se presentaron en los últimos 7 días sobre minería", 7),
    # Recaída real en producción: la misma pregunta que ya se había arreglado
    # ("...últimos N días...") volvió a fabricar datos con esta otra frase,
    # sin número de días explícito — "novedades" sola debe alcanzar.
    ("Busca y entrégame sistematizado en versión editable las novedades de "
     "proyectos de ley en DIPUTADOS", DEFAULT_DIAS_PROYECTOS),
    ("cuáles son los proyectos de ley más recientes", DEFAULT_DIAS_PROYECTOS),
    ("dame los proyectos de ley de hoy", None),                    # sin número de días
    ("explícame qué es un proyecto de ley", None),                 # conceptual, sin "días"
    ("qué sesiones hay en los próximos 2 días", None),              # "días" sin "proyecto"+"ley"
    ("busca proyectos de autor Chirinos", None),                    # sin ventana de tiempo
])
def test_detecta_proyectos_por_dias(texto, esperado):
    assert _detecta_proyectos_por_dias(texto) == esperado


def test_analyze_setea_forzar_dias_proyectos():
    orch = make([user("Revisa los proyectos de ley de los últimos 15 días calendario, "
                       "y entrégame un cuadro resumen dividido por temas")])
    assert orch.forzar_dias_proyectos == 15


def test_resumen_no_activa_forzar_dias_proyectos():
    """is_resumen tiene su propio set de herramientas — no debe pisarse con esto."""
    orch = make([user("__RESUMEN_SEMANAL__: general, con proyectos de ley de 15 días")])
    assert orch.forzar_dias_proyectos is None


@pytest.mark.asyncio
async def test_run_fuerza_buscar_proyectos_sin_pasar_por_router():
    """
    Bug real encontrado en producción: para esta frase el router (8B) elegía
    responder_directo con demasiada frecuencia (~4 de 7 intentos en pruebas
    en vivo) y el modelo grande terminaba inventando una tabla de proyectos
    falsos. forzar_dias_proyectos bypasea el router por completo acá.
    """
    orch = make([user("Revisa los proyectos de ley de los últimos 15 días calendario, "
                       "y entrégame un cuadro resumen dividido por temas")])
    assert orch.forzar_dias_proyectos == 15

    with patch.object(ChatOrchestrator, "_phase1", new=AsyncMock(side_effect=AssertionError("no debería llamarse"))), \
         patch.object(ChatOrchestrator, "_run_tool", new=AsyncMock(return_value={"ok": True})) as mock_run_tool, \
         patch.object(ChatOrchestrator, "_stream_final") as mock_stream:
        async def fake_stream(*a, **k):
            yield "data: [DONE]\n\n"
        mock_stream.side_effect = fake_stream
        events = [ev async for ev in orch.run()]

    assert events
    assert orch.tools_usados == ["buscar_proyectos"]
    mock_run_tool.assert_awaited_once_with("buscar_proyectos", {"dias": 15})


# ── _deduplicar_tool_calls ─────────────────────────────────────────────────────

def tool_call(id_, name, args=None):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=name, arguments=json.dumps(args or {})))


def test_deduplica_fetch_comisiones_repetido():
    """
    Bug real: el router llamaba fetch_comisiones dos veces en el mismo turno
    cuando el usuario nombraba Senado y Diputados — confirmado en vivo dos
    veces, incluso después de aclarar la descripción de la herramienta (el
    fix de prompt solo no fue suficiente).
    """
    calls = [
        tool_call("1", "fetch_comisiones", {"camara": "senado"}),
        tool_call("2", "fetch_comisiones", {"camara": "diputados"}),
    ]
    result = ChatOrchestrator._deduplicar_tool_calls(calls)
    assert len(result) == 1
    assert result[0].function.name == "fetch_comisiones"
    # Sin camara: con una cámara puntual se pierden los enlaces de la otra
    # (ver fetch_comisiones en scraper.py) — la que sobrevive va sin filtro.
    assert json.loads(result[0].function.arguments) == {}


def test_no_deduplica_herramientas_distintas():
    calls = [
        tool_call("1", "fetch_comisiones", {}),
        tool_call("2", "buscar_proyectos", {"materia": "salud"}),
    ]
    result = ChatOrchestrator._deduplicar_tool_calls(calls)
    assert len(result) == 2


def test_no_deduplica_herramientas_fuera_de_la_lista():
    """buscar_proyectos con distintos filtros SÍ puede repetirse con sentido."""
    calls = [
        tool_call("1", "buscar_proyectos", {"materia": "salud"}),
        tool_call("2", "buscar_proyectos", {"materia": "educacion"}),
    ]
    result = ChatOrchestrator._deduplicar_tool_calls(calls)
    assert len(result) == 2


# ── _run_tool: reintento ante falla transitoria ───────────────────────────────

@pytest.mark.asyncio
async def test_run_tool_reintenta_una_vez_y_se_recupera():
    """
    Bug real: SPLEY tuvo un hipo puntual, buscar_proyectos falló, y Solón
    respondió "no puedo buscar ahora" en vez de reintentar — pese a que la
    misma consulta funcionaba perfecto al segundo intento.
    """
    fake_tool = AsyncMock(side_effect=[TimeoutError("boom"), {"items": [1, 2, 3]}])
    with patch("services.orchestrator.TOOL_MAP", {"buscar_proyectos": fake_tool}), \
         patch("services.orchestrator.asyncio.sleep", new=AsyncMock()):
        result = await ChatOrchestrator._run_tool("buscar_proyectos", {"dias": 15})

    assert result == {"items": [1, 2, 3]}
    assert fake_tool.await_count == 2


@pytest.mark.asyncio
async def test_run_tool_solo_reintenta_una_vez():
    """Si falla dos veces seguidas, se rinde — no reintenta indefinidamente."""
    fake_tool = AsyncMock(side_effect=TimeoutError("boom"))
    with patch("services.orchestrator.TOOL_MAP", {"buscar_proyectos": fake_tool}), \
         patch("services.orchestrator.asyncio.sleep", new=AsyncMock()):
        result = await ChatOrchestrator._run_tool("buscar_proyectos", {"dias": 15})

    assert result["sin_datos"] is True
    assert fake_tool.await_count == 2


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


def test_phase3_max_tokens_resumen_tiene_prioridad():
    """is_resumen manda su propio presupuesto aunque tools_usados matchee otro caso."""
    orch = make([user("__RESUMEN_SEMANAL__: general")],
                tools_usados=["fetch_expediente"])
    assert orch._phase3_max_tokens() == 3000
