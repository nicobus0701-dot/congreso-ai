"""Endpoint /chat — delega toda la lógica en ChatOrchestrator."""
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from config import GROQ_API_KEY
from services import sse
from services.orchestrator import ChatOrchestrator

router = APIRouter()


@router.post("/chat")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])

    if not GROQ_API_KEY:
        async def err():
            yield sse.error("Falta la API key de Groq")
        return StreamingResponse(err(), media_type="text/event-stream")

    orchestrator = ChatOrchestrator(messages)
    return StreamingResponse(orchestrator.run(), media_type="text/event-stream")
