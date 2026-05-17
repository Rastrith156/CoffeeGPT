"""
agents/chatbot/__init__.py
===========================
Chatbot sub-package public API.

Decomposed modules (Issue #3 fix):
  PromptBuilder       — document-to-context formatting, user-input assembly
  ResponseSynthesizer — LLM call, quality detection, session memory, post-processing
  CitationFormatter   — source-group finders (futures, weather, news, risk)
  FallbackHandler     — grounded fallback + no-context answers
  ContextAssembler    — Redis hot-layer live prefix builder
"""
from agents.chatbot.prompt_builder import PromptBuilder
from agents.chatbot.response_synthesizer import ResponseSynthesizer
from agents.chatbot.citation_formatter import CitationFormatter
from agents.chatbot.fallback_handler import FallbackHandler
from agents.chatbot.context_assembler import ContextAssembler

__all__ = [
    "PromptBuilder",
    "ResponseSynthesizer",
    "CitationFormatter",
    "FallbackHandler",
    "ContextAssembler",
]
