from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from core.dependencies import get_orchestrator
from core.security import sanitize_user_input
from models.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, orchestrator=Depends(get_orchestrator)) -> ChatResponse:
    sanitize_user_input(request.message)
    return await orchestrator.answer_chat(
        message=request.message,
        session_id=request.session_id,
        use_rag=request.use_rag,
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, orchestrator=Depends(get_orchestrator)) -> StreamingResponse:
    """SSE streaming endpoint — streams LLM tokens as they arrive."""
    sanitize_user_input(request.message)

    async def token_generator():
        try:
            async for token in orchestrator.stream_chat(
                message=request.message,
                session_id=request.session_id,
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        token_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
