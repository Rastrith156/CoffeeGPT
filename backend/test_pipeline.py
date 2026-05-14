# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent


def ensure_local_site_packages() -> None:
    # Let the script work from an IDE even when the selected interpreter is not the project venv.
    for candidate in (
        backend_root / "venv" / "Lib" / "site-packages",
        backend_root / ".venv" / "Lib" / "site-packages",
    ):
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            return


ensure_local_site_packages()

# Ensure backend root is in python path
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


def print_items(title: str, items: list[str]) -> None:
    if not items:
        return
    print(title)
    for item in items:
        print(f"  - {item}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local smoke test for the CoffeeGPT pipeline.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when optional local services such as Qdrant or LM Studio are offline.",
    )
    return parser.parse_args()


async def main(strict: bool = False) -> None:
    print_section("CoffeeGPT Pipeline Verification")

    retriever = CoffeeRetriever()
    rag_pipeline = RAGPipeline(retriever=retriever)
    ingestion = IngestionPipeline(rag_pipeline=rag_pipeline)
    chatbot = CoffeeChatbotAgent(retriever=retriever)
    retrieval_question = "Will coffee prices rise this week after heavy rainfall in Brazil?"
    weather_question = "Will rain affect coffee crops this week in Kodagu?"
    futures_question = "Why are coffee futures moving today?"
    decision_question = "Is market risk increasing this week?"
    chat_question = "Should I sell coffee now?"
    errors: list[str] = []
    warnings: list[str] = []

    try:
        print_section("1. News Ingestion")
        bootstrap_count = await asyncio.to_thread(
            rag_pipeline.index_records,
            [
                {
                    "title": "Brazil coffee production may decline due to heavy rainfall",
                    "content": (
                        "Brazil coffee production may decline due to heavy rainfall in key growing regions. "
                        "Flooded fields and delayed harvest activity could tighten near-term supply and put "
                        "upward pressure on coffee prices."
                    ),
                    "record_type": "bootstrap_news_article",
                    "raw": {
                        "summary": "Bootstrap coffee market article used to validate the first end-to-end RAG flow.",
                    },
                    "metadata": {
                        "source": "bootstrap_news",
                        "title": "Brazil coffee production may decline due to heavy rainfall",
                        "published_at": "2026-05-12",
                        "url": "https://example.com/bootstrap/brazil-rainfall",
                        "channel": "Bootstrap Seed",
                    },
                }
            ],
        )
        print(f"Bootstrap indexed: {bootstrap_count}")
        jobs = await ingestion.run(source="news")
        for job in jobs:
            print(f"Source:   {job.source}")
            print(f"Status:   {job.status}")
            print(f"Ingested: {job.records_ingested}")
            print(f"Indexed:  {job.documents_indexed}")
            print(f"Detail:   {job.detail}")
        if not any(job.status == "completed" for job in jobs):
            errors.append("News ingestion did not complete successfully.")

        qdrant_available = await asyncio.to_thread(retriever.available)
        if qdrant_available and not any(job.documents_indexed > 0 for job in jobs):
            errors.append("Qdrant is online, but the ingestion run did not index any documents.")
        if not qdrant_available:
            warnings.append("Qdrant is offline, so indexing and retriever checks are informational only.")

        print_section("2. Weather Ingestion")
        weather_jobs = await ingestion.run(source="weather")
        for job in weather_jobs:
            print(f"Source:   {job.source}")
            print(f"Status:   {job.status}")
            print(f"Ingested: {job.records_ingested}")
            print(f"Indexed:  {job.documents_indexed}")
            print(f"Detail:   {job.detail}")
        if not any(job.status == "completed" for job in weather_jobs):
            errors.append("Weather ingestion did not complete successfully.")
        if qdrant_available and not any(job.documents_indexed > 0 for job in weather_jobs):
            errors.append("Qdrant is online, but the weather ingestion run did not index any documents.")

        print_section("3. Futures Ingestion")
        futures_jobs = await ingestion.run(source="futures")
        for job in futures_jobs:
            print(f"Source:   {job.source}")
            print(f"Status:   {job.status}")
            print(f"Ingested: {job.records_ingested}")
            print(f"Indexed:  {job.documents_indexed}")
            print(f"Detail:   {job.detail}")
        if not any(job.status == "completed" for job in futures_jobs):
            errors.append("Futures ingestion did not complete successfully.")
        if qdrant_available and not any(job.documents_indexed > 0 for job in futures_jobs):
            errors.append("Qdrant is online, but the futures ingestion run did not index any documents.")

        print_section("4. Unified Retriever Search")
        docs = []
        print(f"Question: {retrieval_question}")
        if qdrant_available:
            docs = await asyncio.to_thread(retriever.search, retrieval_question, 10)
            print(f"Chunks returned: {len(docs)}")
            for index, doc in enumerate(docs[:5], start=1):
                print(f"  {index}. {doc.metadata.get('title', 'Untitled')} [{doc.metadata.get('source', 'unknown')}]")
            if not docs:
                errors.append("Retriever returned no chunks even though Qdrant is online.")
            else:
                retrieved_sources = {str(doc.metadata.get("source") or "") for doc in docs}
                if "futures" not in retrieved_sources:
                    errors.append("Unified retrieval did not return futures context for the market question.")
                if "weather" not in retrieved_sources:
                    errors.append("Unified retrieval did not return weather context for the market question.")
                if not any(source.startswith("news") or source == "bootstrap_news" for source in retrieved_sources):
                    errors.append("Unified retrieval did not return any news context for the market question.")
        else:
            print("Skipped: Qdrant is offline.")

        print_section("5. Weather Retriever Search")
        weather_docs = []
        print(f"Question: {weather_question}")
        if qdrant_available:
            weather_docs = await asyncio.to_thread(retriever.search, weather_question, 8)
            weather_docs = [doc for doc in weather_docs if doc.metadata.get("source") == "weather"]
            print(f"Weather chunks returned: {len(weather_docs)}")
            for index, doc in enumerate(weather_docs[:3], start=1):
                print(f"  {index}. {doc.metadata.get('title', 'Untitled')} [{doc.metadata.get('region', 'unknown')}]")
            if not weather_docs:
                errors.append("Weather retrieval returned no weather chunks even though weather ingestion completed.")
        else:
            print("Skipped: Qdrant is offline.")

        print_section("6. Futures Retriever Search")
        print(f"Question: {futures_question}")
        if qdrant_available:
            futures_docs = await asyncio.to_thread(retriever.search, futures_question, 8)
            futures_docs = [doc for doc in futures_docs if doc.metadata.get("source") == "futures"]
            print(f"Futures chunks returned: {len(futures_docs)}")
            for index, doc in enumerate(futures_docs[:3], start=1):
                print(f"  {index}. {doc.metadata.get('title', 'Untitled')} [{doc.metadata.get('market', 'unknown')}]")
            if not futures_docs:
                errors.append("Futures retrieval returned no futures chunks even though futures ingestion completed.")
        else:
            print("Skipped: Qdrant is offline.")

        print_section("7. Decision-Support Retriever Search")
        print(f"Question: {decision_question}")
        if qdrant_available:
            decision_docs = await asyncio.to_thread(retriever.search, decision_question, 8)
            print(f"Decision-support chunks returned: {len(decision_docs)}")
            for index, doc in enumerate(decision_docs[:5], start=1):
                print(
                    f"  {index}. {doc.metadata.get('title', 'Untitled')} "
                    f"[{doc.metadata.get('source', 'unknown')}]"
                )
            decision_sources = {str(doc.metadata.get('source') or '') for doc in decision_docs}
            if "forecasting" not in decision_sources:
                errors.append(
                    "Decision-support retrieval did not return forecasting artifacts for the market-risk question."
                )
        else:
            print("Skipped: Qdrant is offline.")

        print_section("8. Chatbot RAG Answer")
        print(f"Question: {chat_question}")
        response = await chatbot.answer(question=chat_question, session_id="test_e2e_flow")
        print(f"Retrieval mode: {response.retrieval_mode}")
        print(f"Model:          {response.model}")
        print(f"Sources cited:  {len(response.sources)}")
        print("Answer:")
        print(response.answer.strip())
        for citation in response.sources:
            print(f"  - {citation.source}: {citation.title}")
        if response.retrieval_mode == "rag":
            pass
        elif response.retrieval_mode == "retrieval_fallback":
            warnings.append("LM Studio is offline, so the chatbot returned retrieval fallback text.")
        elif response.retrieval_mode == "unavailable":
            warnings.append("LM Studio is offline and no retrievable context was available.")
        else:
            warnings.append(f"Chatbot returned `{response.retrieval_mode}` mode instead of full RAG.")
    finally:
        await chatbot.lmstudio_client.aclose()

    print_section("Verification Complete")
    print_items("Warnings:", warnings)
    print_items("Errors:", errors)

    if errors or (strict and warnings):
        raise SystemExit(1)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(strict=args.strict))
