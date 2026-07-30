"""Endpoint /chat — delega toda la lógica en ChatOrchestrator."""
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

import config
from services import sse
from services.orchestrator import ChatOrchestrator

router = APIRouter()


@router.post("/chat")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])

    if not config.LLM_API_KEY:
        async def err():
            yield sse.error("Falta configurar la API key")
        return StreamingResponse(err(), media_type="text/event-stream")

    orchestrator = ChatOrchestrator(messages)
    return StreamingResponse(orchestrator.run(), media_type="text/event-stream")
