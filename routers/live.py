"""Rutas de sesión en vivo: transcripción en tiempo real y análisis incremental."""
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from config import GROQ_API_KEY, MAIN_MODEL, logger, static_file
from live_transcriber import stream_transcription
from services import groq as groq_service
from services import sse
from services.prompt_registry import LIVE_ANALYSIS_PROMPT

router = APIRouter()

# Solo se manda la cola del transcript al modelo: el análisis se repite cada
# ~60s y mandar todo el acumulado dispararía el TPM.
LIVE_EXCERPT_CHARS = 3000

NO_BUFFER = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/live", response_class=HTMLResponse)
async def live_page():
    return static_file("live.html")


@router.get("/live/transcribe")
async def live_transcribe(video_id: str = Query(..., description="ID del video de YouTube")):
    """SSE que emite líneas de transcripción en tiempo real."""
    async def generate():
        if not GROQ_API_KEY:
            yield sse.error("Falta la GROQ_API_KEY")
            return
        if not video_id:
            yield sse.error("Falta el parámetro video_id")
            return
        try:
            async for item in stream_transcription(video_id, GROQ_API_KEY):
                yield sse.event(item)
        except Exception as e:
            logger.error("live_transcribe falló para %s: %s", video_id, e)
            yield sse.error(str(e))
        yield sse.DONE

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers=NO_BUFFER)


@router.post("/live/analyze")
async def live_analyze(request: Request):
    """Analiza el transcript acumulado. El frontend lo llama cada ~60s."""
    body = await request.json()
    transcript = body.get("transcript", "").strip()
    titulo = body.get("titulo", "sesión en vivo")

    async def generate():
        if not transcript:
            yield sse.error("Sin transcripción aún.")
            return

        excerpt = transcript[-LIVE_EXCERPT_CHARS:]
        messages = [
            {"role": "system", "content": LIVE_ANALYSIS_PROMPT},
            {"role": "user", "content": f'Sesión: "{titulo}"\n\nTranscripción reciente:\n{excerpt}'},
        ]
        try:
            async for delta in groq_service.stream_deltas(
                groq_service.get_client(), messages,
                model=MAIN_MODEL, max_tokens=400, temperature=0.3,
            ):
                yield sse.text(delta)
            yield sse.DONE
        except Exception as e:
            logger.error("live_analyze falló: %s", e)
            yield sse.error(groq_service.friendly_error(e))

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
