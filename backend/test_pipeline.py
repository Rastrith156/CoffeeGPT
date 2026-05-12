from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure backend root is in python path
backend_root = Path(__file__).resolve().parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from agents.chatbot_agent import CoffeeChatbotAgent
from ingestion.pipeline import IngestionPipeline
from rag.pipeline import RAGPipeline
from rag.retriever import CoffeeRetriever


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


async def main() -> None:
    print_section("CoffeeGPT Pipeline Verification")

    retriever = CoffeeRetriever()
    rag_pipeline = RAGPipeline(retriever=retriever)
    ingestion = IngestionPipeline(rag_pipeline=rag_pipeline)
    chatbot = CoffeeChatbotAgent(retriever=retriever)
    question = "What happened in coffee market today?"
    indexed_ok = False
    retrieval_ok = False
    rag_ok = False

    try:
        print_section("1. News Ingestion")
        jobs = await ingestion.run(source="news")
        for job in jobs:
            print(f"Source:   {job.source}")
            print(f"Status:   {job.status}")
            print(f"Ingested: {job.records_ingested}")
            print(f"Indexed:  {job.documents_indexed}")
            print(f"Detail:   {job.detail}")
        indexed_ok = any(job.documents_indexed > 0 for job in jobs)

        print_section("2. Retriever Search")
        docs = await asyncio.to_thread(retriever.search, question, 3)
        print(f"Question: {question}")
        print(f"Chunks returned: {len(docs)}")
        for index, doc in enumerate(docs, start=1):
            print(f"  {index}. {doc.metadata.get('title', 'Untitled')} [{doc.metadata.get('source', 'unknown')}]")
        retrieval_ok = len(docs) > 0

        print_section("3. Chatbot RAG Answer")
        response = await chatbot.answer(question=question, session_id="test_e2e_flow")
        print(f"Retrieval mode: {response.retrieval_mode}")
        print(f"Model:          {response.model}")
        print(f"Sources cited:  {len(response.sources)}")
        print("Answer:")
        print(response.answer.strip())
        for citation in response.sources:
            print(f"  - {citation.source}: {citation.title}")
        rag_ok = response.retrieval_mode == "rag"
    finally:
        await chatbot.lmstudio_client.aclose()

    print_section("Verification Complete")
    if not (indexed_ok and retrieval_ok and rag_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
