"""
Unified LLM Client with retry + fallback for Project Darwin
"""

import os
import asyncio
import httpx
from typing import Optional, List, Dict, Any


class LLMProvider:
    """Single LLM provider configuration"""
    def __init__(self, name: str, base_url: str, model: str, api_key: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.consecutive_failures = 0
        self.max_failures = 5  # circuit breaker threshold

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < self.max_failures

    def record_success(self):
        self.consecutive_failures = 0

    def record_failure(self):
        self.consecutive_failures += 1


def _build_providers() -> List[LLMProvider]:
    """Build provider list from environment variables"""
    providers = []

    # Primary provider
    primary_url = os.getenv("LLM_BASE_URL", "")
    if primary_url:
        providers.append(LLMProvider(
            name="primary",
            base_url=primary_url,
            model=os.getenv("LLM_MODEL", "gemini-3-pro-high"),
            api_key=os.getenv("LLM_API_KEY", ""),
        ))

    # Fallback providers (LLM_FALLBACK_1_URL, LLM_FALLBACK_2_URL, etc.)
    for i in range(1, 4):
        url = os.getenv(f"LLM_FALLBACK_{i}_URL", "")
        if url:
            providers.append(LLMProvider(
                name=f"fallback_{i}",
                base_url=url,
                model=os.getenv(f"LLM_FALLBACK_{i}_MODEL", "gpt-4"),
                api_key=os.getenv(f"LLM_FALLBACK_{i}_KEY", ""),
            ))

    return providers


# Module-level providers list (initialized once)
_providers: List[LLMProvider] = _build_providers()


def get_providers() -> List[LLMProvider]:
    return _providers


async def call_llm(
    messages: List[Dict[str, str]],
    max_tokens: int = 500,
    temperature: float = 0.7,
    timeout: float = 60.0,
    max_retries: int = 2,
) -> Optional[str]:
    """
    Call LLM with retry + provider fallback.
    Returns response text or None on total failure.
    """
    providers = get_providers()
    if not providers:
        print("⚠️ No LLM providers configured")
        return None

    for provider in providers:
        if not provider.is_healthy:
            print(f"⏭️ Skipping unhealthy provider: {provider.name}")
            continue

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{provider.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {provider.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": provider.model,
                            "messages": messages,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                        },
                    )

                    if response.status_code == 200:
                        data = response.json()
                        text = data["choices"][0]["message"]["content"]
                        provider.record_success()
                        return text

                    print(f"⚠️ [{provider.name}] HTTP {response.status_code}: {response.text[:200]}")

            except httpx.TimeoutException:
                print(f"⏰ [{provider.name}] Timeout (attempt {attempt + 1}/{max_retries + 1})")
            except Exception as e:
                print(f"❌ [{provider.name}] Error (attempt {attempt + 1}/{max_retries + 1}): {e}")

            # Exponential backoff between retries
            if attempt < max_retries:
                delay = 2 ** attempt
                await asyncio.sleep(delay)

        # All retries exhausted for this provider
        provider.record_failure()
        print(f"🔴 [{provider.name}] All retries exhausted, trying next provider...")

    print("🔴 All LLM providers failed")
    return None
