from __future__ import annotations

from fastapi import APIRouter, Depends

from core.dependencies import get_orchestrator
from models.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, orchestrator=Depends(get_orchestrator)) -> ChatResponse:
    return await orchestrator.answer_chat(
        message=request.message,
        session_id=request.session_id,
        use_rag=request.use_rag,
    )
