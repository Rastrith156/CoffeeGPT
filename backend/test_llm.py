# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

# Ensure backend root is in python path
backend_root = Path(__file__).resolve().parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from core.config import settings
from services.lmstudio_client import LMStudioClient


def print_section(title: str) -> None:
    print("\n" + "=" * 56)
    print(title)
    print("=" * 56)


async def test_timeout_handling() -> tuple[str, str]:
    client = LMStudioClient(timeout_seconds=0.001)
    try:
        await client.list_models()
    except httpx.TimeoutException as exc:
        return ("pass", f"Timeout handling is working ({type(exc).__name__})")
    except httpx.ConnectError as exc:
        return ("blocked", f"LM Studio is unreachable, so timeout could not be tested ({exc})")
    except Exception as exc:
        return ("fail", f"Unexpected error while testing timeout handling: {exc}")
    finally:
        await client.aclose()

    return ("fail", "Tiny-timeout probe completed unexpectedly; timeout handling was not exercised.")


async def main() -> None:
    print_section("LM Studio Backend Verification")
    print(f"Base URL: {settings.lmstudio_base_url}")
    print(f"Model:    {settings.llm_model}")

    client = LMStudioClient()
    discovery_ok = False
    generation_ok = False
    try:
        print_section("1. Model Discovery")
        try:
            models = await client.list_models()
            print(f"Model entries returned: {len(models)}")
            for index, item in enumerate(models[:5], start=1):
                name = item.get("id") or item.get("key") or item.get("model") or "unknown"
                print(f"  {index}. {name}")
            status = await client.get_model_status(settings.llm_model)
            print(f"Configured model available: {status.available}")
            print(f"Configured model ready:     {status.loaded}")
            discovery_ok = True
        except Exception as exc:
            print(f"Discovery failed: {exc}")

        print_section("2. Response Generation")
        try:
            prompt = "What are the two primary cultivated coffee species? Answer in one sentence."
            result = await client.chat(
                model=settings.llm_model,
                user_input=prompt,
                system_prompt="You are a concise coffee market analyst.",
                store=False,
            )
            print("Backend-to-model call succeeded.")
            print(f"Response:    {result.text.strip()}")
            print(f"Response ID: {result.response_id}")
            print(f"Model used:  {result.model_instance_id}")
            if result.stats:
                print(f"Usage:       {result.stats}")
            generation_ok = True
        except Exception as exc:
            print(f"Generation failed: {exc}")

        print_section("3. Timeout Handling")
        outcome, detail = await test_timeout_handling()
        print(f"Timeout probe status: {outcome}")
        print(detail)
    finally:
        await client.aclose()

    print_section("Verification Complete")
    if not (discovery_ok and generation_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
