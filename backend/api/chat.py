"""
api/chat.py
===========
Chat endpoints.

Task 2 update: /chat/stream now calls provider.stream_generate() directly
for real token-by-token SSE streaming, falling back to orchestrator
word-chunked simulation only if the provider doesn't stream.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from core.dependencies import get_orchestrator
from core.rate_limit import endpoint_rate_limiter
from core.security import get_api_key, sanitize_user_input
from llm.providers.factory import get_provider
from models.schemas import ChatRequest, ChatResponse

router = APIRouter()

# Per-endpoint rate limits (Task 3)
_chat_rate_limit = endpoint_rate_limiter("chat")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    orchestrator=Depends(get_orchestrator),
    _api_key: str = Depends(get_api_key),
    _rate: bool = Depends(_chat_rate_limit),
) -> ChatResponse:
    """Non-streaming chat — returns full response once complete."""
    sanitize_user_input(request.message)
    return await orchestrator.answer_chat(
        message=request.message,
        session_id=request.session_id,
        use_rag=request.use_rag,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    orchestrator=Depends(get_orchestrator),
    _api_key: str = Depends(get_api_key),
    _rate: bool = Depends(_chat_rate_limit),
) -> StreamingResponse:
    """
    SSE streaming endpoint — streams LLM tokens as they arrive.

    Strategy:
      1. Try provider.stream_generate() for real token-by-token output.
      2. If orchestrator has no direct provider access, fall back to
         orchestrator.stream_chat() (word-chunked simulation).

    SSE format:  data: {"token": "<text>"}\\n\\n
                 data: [DONE]\\n\\n
    """
    sanitize_user_input(request.message)

    async def token_generator():
        try:
            provider = get_provider()
            # Build the prompt via orchestrator intent classification
            intent = await orchestrator._orchestrator_agent._classifier.classify_async(
                request.message
            ) if orchestrator._orchestrator_agent else ["general"]

            # System context for the LLM
            system_prompt = (
                "You are CoffeeGPT, an elite AI analyst specialising in global coffee commodity markets. "
                "Provide concise, actionable, data-driven intelligence. "
                "Use markdown formatting where appropriate."
            )

            async for token in provider.stream_generate(
                prompt=request.message,
                system_prompt=system_prompt,
            ):
                yield f"data: {json.dumps({'token': token, 'intent': intent})}\\n\\n"

        except Exception as exc:
            # Graceful fallback — try orchestrator stream_chat
            try:
                async for token in orchestrator.stream_chat(
                    message=request.message,
                    session_id=request.session_id,
                ):
                    yield f"data: {json.dumps({'token': token})}\\n\\n"
            except Exception as inner_exc:
                yield f"data: {json.dumps({'error': str(inner_exc)})}\\n\\n"
        finally:
            yield "data: [DONE]\\n\\n"

    return StreamingResponse(
        token_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
