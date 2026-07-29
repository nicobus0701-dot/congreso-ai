"""
ChatOrchestrator — las tres fases del endpoint /chat.

  Fase 1 (router, 8B)  elige qué herramienta hace falta, o ninguna.
  Fase 2               ejecuta las herramientas elegidas y recorta sus resultados.
  Fase 3 (main, 70B)   redacta la respuesta final en streaming.

Hay además un atajo: analizar un PDF ya cargado o una sesión de YouTube no
necesita scraping, así que va directo a Fase 3 con el workflow correspondiente.

Todos los métodos públicos son generadores asíncronos que emiten strings SSE
ya formateados (ver services/sse.py).
"""
import json
import re
from datetime import datetime

from config import MAIN_MODEL, ROUTER_MODEL, logger
from scraper import fetch_transcript_youtube
from services import groq as groq_service
from services import sse
from services.prompt_registry import (
    RESUMEN_PROMPT,
    ROUTER_PROMPT,
    SYSTEM_MINI,
    WORKFLOW_PDF_FORMULA,
    WORKFLOW_SESION,
    WORKFLOWS,
    system_con_fecha,
)
from services.tools import STATUS_LABELS, TOOL_MAP, TOOLS

# Un tool result de 7k chars ≈ 2000 tokens. Más que eso dispara el TPM.
MAX_TOOL_RESULT_CHARS = 7000

# Marcadores que indican que ya se mostró un expediente completo en el hilo.
EXPEDIENTE_MARKERS = (
    "FICHA DEL PROYECTO",
    "COMISIONES A LAS QUE FUE DERIVADO",
    "ACTOS DE TRABAJO POR COMISIÓN",
    "MI LECTURA",
)

PALABRAS_ANALISIS = (
    "analiza", "analizar", "resume", "resumir", "resumen", "fórmula legal",
    "formula legal", "qué propone", "que propone", "qué modifica", "que modifica",
    "artículo", "articulo", "deroga", "explica",
)

YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|live/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


class ChatOrchestrator:
    """Ejecuta una vuelta completa de conversación sobre el historial dado."""

    def __init__(self, messages: list, client=None):
        self.messages = messages or []
        self.client = client or groq_service.get_client()
        self.hoy = datetime.now().strftime("%d/%m/%Y")
        self.system_base = system_con_fecha(self.hoy)

        # Estado que rellena _analyze()
        self.last_msg = ""
        self.is_resumen = False
        self.sector = None
        self.analizar_documento = False
        self.has_sesion = False
        self.has_expediente_en_contexto = False
        self.doc_en_contexto = False
        self.conversation: list = []

        # Estado que rellenan las fases 2 y 3
        self.tool_msgs: list = []
        self.tools_usados: list = []
        self.solo_responder_directo = False

    # ── Análisis del pedido ──────────────────────────────────────────────────

    def _analyze(self):
        """Clasifica el pedido para decidir el camino y armar el historial."""
        msgs = self.messages
        self.last_msg = msgs[-1].get("content", "") if msgs else ""
        low_last = self.last_msg.lower()

        # Resumen semanal: el frontend lo marca con un centinela.
        self.is_resumen = self.last_msg.strip().startswith("__RESUMEN_SEMANAL__")
        if self.is_resumen and ":" in self.last_msg:
            self.sector = self.last_msg.strip().split(":", 1)[1].strip()

        # ¿Hay un PDF cargado? El frontend lo inyecta como mensaje de usuario.
        recientes = msgs[-6:]
        self.doc_en_contexto = any(
            "He cargado el documento" in (m.get("content", "") or "")
            for m in recientes if m.get("role") == "user"
        )
        pide_analisis = any(w in low_last for w in PALABRAS_ANALISIS)
        # Analizar un doc ya cargado se resuelve con el texto en contexto:
        # no hace falta ninguna herramienta de scraping.
        self.analizar_documento = self.doc_en_contexto and (
            pide_analisis or len(self.last_msg) < 60
        )

        self.has_sesion = (
            "youtube.com" in low_last or "youtu.be" in low_last
            or "transcript" in low_last or "[sesión" in low_last
        )

        recent_assistant = " ".join(
            m.get("content", "") for m in msgs[-6:] if m.get("role") == "assistant"
        )
        self.has_expediente_en_contexto = any(
            marker in recent_assistant for marker in EXPEDIENTE_MARKERS
        )

        if self.is_resumen:
            base = "Genera el resumen ejecutivo semanal completo del Congreso del Perú."
            if self.sector and self.sector != "general":
                base += (
                    f" Enfoca el análisis especialmente en el sector {self.sector} y los "
                    "proyectos de ley, noticias y agenda que impacten a ese sector."
                )
            self.conversation = [{"role": "user", "content": base}]
        else:
            self.conversation = msgs[-20:]

    @property
    def _short_circuit(self) -> bool:
        """Analizar doc o sesión no requiere Fase 1 ni 2."""
        return self.analizar_documento or (self.has_sesion and not self.is_resumen)

    # ── Atajo: documento o sesión en contexto ────────────────────────────────

    async def _run_short_circuit(self):
        system_p3 = self.system_base
        if self.analizar_documento:
            system_p3 += "\n" + WORKFLOW_PDF_FORMULA
        if self.has_sesion:
            system_p3 += "\n" + WORKFLOW_SESION
            ok = True
            async for ev in self._inject_transcript():
                if ev is None:          # centinela: sin transcript, ya se avisó
                    ok = False
                    break
                yield ev
            if not ok:
                return

        msgs = [{"role": "system", "content": system_p3}] + self.conversation
        async for ev in self._stream_final(msgs, max_tokens=2048):
            yield ev

    async def _inject_transcript(self):
        """
        Busca el transcript del video de YouTube del último mensaje y lo mete
        en la conversación. Emite None si no hay transcript disponible.
        """
        m = YT_ID_RE.search(self.last_msg)
        if not m:
            return

        yield sse.status("Obteniendo transcript de la sesión...")
        try:
            data = await fetch_transcript_youtube(m.group(1))
        except Exception as e:
            logger.warning("fetch_transcript_youtube falló: %s", e)
            data = None

        if data and data.get("ok") and data.get("text"):
            transcript_msg = {
                "role": "user",
                "content": (
                    f"[TRANSCRIPT DE LA SESIÓN — fuente: {data.get('source', 'youtube')}]\n"
                    f"{data['text']}\n"
                    "[FIN DEL TRANSCRIPT]"
                ),
            }
            self.conversation = (
                self.conversation[:-1] + [transcript_msg, self.conversation[-1]]
            )
            return

        # Sin subtítulos: responder sin gastar una llamada al modelo.
        yield sse.text(
            "No pude obtener el transcript de ese video (sin subtítulos disponibles "
            "o video privado). Para analizar la sesión podés: (1) cargar el PDF del "
            "acta con el botón de adjunto, o (2) pegar el texto del transcript "
            "directamente en el chat."
        )
        yield sse.DONE
        yield None

    # ── Fase 1: elección de herramienta ──────────────────────────────────────

    def _router_messages(self) -> list:
        """
        Historial que se manda al router. Se recorta agresivamente: un PDF o un
        expediente en contexto son miles de tokens que no aportan nada a la
        elección de herramienta y revientan el TPM ya en la Fase 1.
        """
        if self.doc_en_contexto:
            return [{"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": self.last_msg}]

        if self.has_expediente_en_contexto:
            ctx = (
                "[CONTEXTO: El asistente ya mostró el expediente completo de un proyecto "
                "en esta conversación (FICHA DEL PROYECTO, SEGUIMIENTO, COMISIONES, etc.). "
                "Si el usuario pregunta sobre ese expediente — comisiones, actos, predictamen, "
                "adjuntos, estado, autores — usa responder_directo. "
                "Solo llama fetch_expediente si pide OTRO proyecto diferente.]\n\n"
                f"Pregunta: {self.last_msg}"
            )
            return [{"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": ctx}]

        return [{"role": "system", "content": ROUTER_PROMPT}] + self.messages[-4:]

    async def _phase1(self):
        """Devuelve el choice del router, o None si ya se emitió una respuesta."""
        try:
            resp = self.client.chat.completions.create(
                model=ROUTER_MODEL,
                messages=self._router_messages(),
                tools=TOOLS,
                tool_choice="required",
                max_tokens=512,
                temperature=0.2,
                stream=False,
            )
            return resp.choices[0]
        except Exception as e:
            logger.warning("Fase 1 (router) falló: %s", e)
            raise

    async def _phase1_fallback(self, exc):
        """
        El router falló. Si fue por un tool_call malformado, respondemos igual
        con el modelo grande y sin herramientas; si no, mostramos el error.
        """
        if not groq_service.is_tool_format_error(exc):
            yield sse.error(groq_service.friendly_error(exc))
            return

        msgs = [{"role": "system", "content": self.system_base}] + self.conversation
        try:
            async for delta in groq_service.stream_deltas(
                self.client, msgs, model=MAIN_MODEL, max_tokens=2048
            ):
                yield sse.text(delta)
            yield sse.DONE
        except Exception as e2:
            logger.error("Fallback de Fase 1 falló: %s", e2)
            yield sse.error(groq_service.friendly_error(e2))

    # ── Fase 2: ejecución de herramientas ────────────────────────────────────

    @staticmethod
    def _clean_args(raw: str) -> dict:
        try:
            args = json.loads(raw or "{}")
        except (ValueError, TypeError):
            return {}
        if not isinstance(args, dict):
            return {}
        if "limit" in args:
            try:
                args["limit"] = int(args["limit"])
            except (ValueError, TypeError):
                args["limit"] = 20
        return {k: v for k, v in args.items() if v != ""}

    async def _phase2(self, choice):
        """Ejecuta las tool calls del router, emitiendo el estado de cada una."""
        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            return

        # responder_directo no es una herramienta real: es la señal de
        # "contestá con tu conocimiento, sin datos externos".
        real_calls = [tc for tc in choice.message.tool_calls
                      if tc.function.name != "responder_directo"]
        if not real_calls:
            self.solo_responder_directo = True
            return

        self.tool_msgs.append({
            "role": "assistant",
            "content": choice.message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in real_calls
            ],
        })

        for tc in real_calls:
            name = tc.function.name
            self.tools_usados.append(name)
            args = self._clean_args(tc.function.arguments)

            yield sse.status(STATUS_LABELS.get(name, "Consultando el Congreso..."))

            result = await self._run_tool(name, args)

            result_str = json.dumps(result, ensure_ascii=False)
            if len(result_str) > MAX_TOOL_RESULT_CHARS:
                result_str = result_str[:MAX_TOOL_RESULT_CHARS] + '... [recortado]"}'

            self.tool_msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

    @staticmethod
    async def _run_tool(name: str, args: dict) -> dict:
        """Ejecuta una herramienta y normaliza cualquier fallo a 'sin_datos'."""
        if name not in TOOL_MAP:
            logger.warning("El modelo pidió una herramienta inexistente: %s", name)
            return {"sin_datos": True, "mensaje": f"Herramienta '{name}' no disponible."}
        try:
            result = await TOOL_MAP[name](args)
        except Exception as e:
            logger.error("Herramienta %s falló con args=%s: %s", name, args, e)
            return {"sin_datos": True,
                    "mensaje": f"Error al consultar {name}: {str(e)[:100]}"}

        if isinstance(result, dict) and "error" in result:
            return {"sin_datos": True,
                    "mensaje": result.get("error", "No hay información disponible.")}
        return result

    # ── Fase 3: respuesta final ──────────────────────────────────────────────

    def _phase3_system(self) -> str:
        """Arma el system prompt: base compacta + solo los flujos que aplican."""
        if self.is_resumen:
            return RESUMEN_PROMPT
        if self.solo_responder_directo or not self.tool_msgs:
            return self.system_base

        # Con tool results conviene SYSTEM_MINI (~800 tokens menos), salvo que
        # la herramienta tenga un workflow de formato propio que sí hace falta.
        needs_workflow = any(t in WORKFLOWS for t in self.tools_usados)
        if not needs_workflow:
            return SYSTEM_MINI.format(hoy=self.hoy)

        system_p3 = self.system_base
        for t in self.tools_usados:
            if t in WORKFLOWS:
                system_p3 += "\n" + WORKFLOWS[t]
        return system_p3

    def _phase3_max_tokens(self) -> int:
        if "fetch_expediente" in self.tools_usados:
            return 4000
        if self.tools_usados:
            # Proyectos/agenda: respuesta más corta, menos presión sobre el TPM.
            return 1800
        return 2500

    async def _stream_final(self, msgs, max_tokens):
        """Streaming de Fase 3 con reintento sobre rate limit."""
        async for kind, payload in groq_service.stream_with_retry(
            self.client, msgs, model=MAIN_MODEL, max_tokens=max_tokens
        ):
            if kind == "text":
                yield sse.text(payload)
            elif kind == "status":
                yield sse.status(payload)
            elif kind == "error":
                yield sse.error(payload)
                return
        yield sse.DONE

    # ── Punto de entrada ─────────────────────────────────────────────────────

    async def run(self):
        """Generador de eventos SSE para una vuelta completa de conversación."""
        self._analyze()

        if self._short_circuit:
            async for ev in self._run_short_circuit():
                yield ev
            return

        try:
            choice = await self._phase1()
        except Exception as e:
            async for ev in self._phase1_fallback(e):
                yield ev
            return

        async for ev in self._phase2(choice):
            yield ev

        # Con tool results el contexto ya viene del resultado; mandar 20 mensajes
        # extra dispara el TPM. Con herramientas: solo los últimos 4.
        conv_p3 = self.messages[-4:] if self.tool_msgs else self.conversation
        msgs = (
            [{"role": "system", "content": self._phase3_system()}]
            + conv_p3
            + self.tool_msgs
        )

        async for ev in self._stream_final(msgs, self._phase3_max_tokens()):
            yield ev
