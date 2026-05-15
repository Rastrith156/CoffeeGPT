"""
api/chat.py
===========
Chat endpoints.

Fix #1: SSE yield strings now use real \\n\\n newlines (not double-escaped \\\\n\\\\n).
Fix #2: `intent` is sent once in a dedicated meta frame, not embedded in every token.
Fix #3: Intent classification is delegated via orchestrator.classify_intent() —
         no more drilling into ._orchestrator_agent._classifier private chain.
Fix #14: The outer except block now logs the error before falling through to fallback.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from core.dependencies import get_orchestrator
from core.logger import logger
from core.rate_limit import endpoint_rate_limiter
from core.security import get_api_key, sanitize_user_input
from llm.providers.factory import get_provider
from models.schemas import ChatRequest, ChatResponse

router = APIRouter()

# Per-endpoint rate limits
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

    Fix #1: All yield statements produce real newlines (\\n\\n), not escaped strings.
    Fix #2: intent is sent once as a dedicated 'event: meta' frame before token stream.
    Fix #3: intent classification goes through orchestrator.classify_intent() —
            no private-attribute chain drilling.

    SSE format:
        event: meta\\n
        data: {"intent": [...]}\\n\\n
        data: {"token": "<text>"}\\n\\n
        data: [DONE]\\n\\n
    """
    sanitize_user_input(request.message)

    async def token_generator():
        # Fix #3: classify intent via the public orchestrator method, not private attrs
        intent = await orchestrator.classify_intent(request.message)

        # Fix #2: send intent exactly ONCE as a dedicated meta event before tokens
        yield f"event: meta\ndata: {json.dumps({'intent': intent})}\n\n"

        try:
            provider = get_provider()

            system_prompt = (
                "You are CoffeeGPT, an elite AI analyst specialising in global coffee commodity markets. "
                "Provide concise, actionable, data-driven intelligence. "
                "Use markdown formatting where appropriate."
            )

            # Fix #1: real \n\n newlines — SSE spec requires two newlines to terminate each frame
            async for token in provider.stream_generate(
                prompt=request.message,
                system_prompt=system_prompt,
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"

        except Exception as primary_exc:
            # Fix #14: always log the error before falling through — never swallow silently
            logger.warning(
                "chat_stream primary provider path failed, falling back to orchestrator: {}",
                primary_exc,
            )
            try:
                async for token in orchestrator.stream_chat(
                    message=request.message,
                    session_id=request.session_id,
                ):
                    yield f"data: {json.dumps({'token': token})}\n\n"
            except Exception as fallback_exc:
                logger.error("chat_stream fallback also failed: {}", fallback_exc)
                yield f"data: {json.dumps({'error': str(fallback_exc)})}\n\n"

        finally:
            # Fix #1: real newline terminator
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        token_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
