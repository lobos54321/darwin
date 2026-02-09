"""
Unified LLM Client with retry + fallback for Project Darwin

Supports both OpenAI and Anthropic API formats.
Auto-detects format based on provider URL or explicit configuration.
Includes rate limiting to prevent quota exhaustion.
"""

import os
import asyncio
import httpx
import time
from typing import Optional, List, Dict, Any


# Rate limiting: Track call timestamps per provider
_call_timestamps: Dict[str, List[float]] = {}
_RATE_LIMIT_CALLS = int(os.getenv("LLM_RATE_LIMIT_CALLS", "10"))  # Max calls per window
_RATE_LIMIT_WINDOW = int(os.getenv("LLM_RATE_LIMIT_WINDOW", "60"))  # Window in seconds


def _check_rate_limit(provider_name: str) -> bool:
    """Check if we're within rate limits. Returns True if allowed."""
    now = time.time()
    
    if provider_name not in _call_timestamps:
        _call_timestamps[provider_name] = []
    
    # Clean old timestamps
    _call_timestamps[provider_name] = [
        ts for ts in _call_timestamps[provider_name] 
        if now - ts < _RATE_LIMIT_WINDOW
    ]
    
    if len(_call_timestamps[provider_name]) >= _RATE_LIMIT_CALLS:
        return False
    
    _call_timestamps[provider_name].append(now)
    return True


class LLMProvider:
    """Single LLM provider configuration"""
    def __init__(self, name: str, base_url: str, model: str, api_key: str, api_format: str = "auto"):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.api_format = api_format  # "openai", "anthropic", or "auto"
        self.consecutive_failures = 0
        self.max_failures = 5  # circuit breaker threshold
        self.accounts_json = os.getenv("ACCOUNTS_JSON", "{}")

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < self.max_failures

    def record_success(self):
        self.consecutive_failures = 0

    def record_failure(self):
        self.consecutive_failures += 1
    
    def detect_format(self) -> str:
        """Auto-detect API format based on URL"""
        if self.api_format != "auto":
            return self.api_format
        
        url_lower = self.base_url.lower()
        if "anthropic" in url_lower or "claude" in url_lower:
            return "anthropic"
        # Default to OpenAI format
        return "openai"


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
            api_format=os.getenv("LLM_API_FORMAT", "auto"),
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
                api_format=os.getenv(f"LLM_FALLBACK_{i}_FORMAT", "auto"),
            ))

    return providers


# Module-level providers list (initialized once)
_providers: List[LLMProvider] = _build_providers()


def get_providers() -> List[LLMProvider]:
    return _providers


async def _call_openai_format(
    client: httpx.AsyncClient,
    provider: LLMProvider,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> Optional[str]:
    """Call LLM using OpenAI API format"""
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
        return data["choices"][0]["message"]["content"]
    
    return None


async def _call_anthropic_format(
    client: httpx.AsyncClient,
    provider: LLMProvider,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> Optional[str]:
    """Call LLM using Anthropic API format"""
    headers = {
        "x-api-key": provider.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    
    # Add accounts pool if available (for Antigravity Proxy)
    if provider.accounts_json and provider.accounts_json != "{}":
        headers["x-accounts"] = provider.accounts_json
    
    response = await client.post(
        f"{provider.base_url}/v1/messages",
        headers=headers,
        json={
            "model": provider.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )

    if response.status_code == 200:
        data = response.json()
        content_blocks = data.get("content", [])
        result = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                result += block.get("text", "")
        return result.strip() if result else None
    
    return None


async def call_llm(
    messages: List[Dict[str, str]],
    max_tokens: int = 500,
    temperature: float = 0.7,
    timeout: float = 60.0,
    max_retries: int = 2,
) -> Optional[str]:
    """
    Call LLM with retry + provider fallback + rate limiting.
    Supports both OpenAI and Anthropic API formats.
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
        
        # Rate limit check
        if not _check_rate_limit(provider.name):
            print(f"⏳ Rate limit hit for {provider.name} ({_RATE_LIMIT_CALLS} calls/{_RATE_LIMIT_WINDOW}s). Trying next...")
            continue

        api_format = provider.detect_format()
        
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if api_format == "anthropic":
                        text = await _call_anthropic_format(
                            client, provider, messages, max_tokens, temperature
                        )
                    else:
                        text = await _call_openai_format(
                            client, provider, messages, max_tokens, temperature
                        )
                    
                    if text:
                        provider.record_success()
                        return text
                    
                    print(f"⚠️ [{provider.name}] Empty response")

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


async def call_llm_with_fallback(
    prompt: str,
    max_tokens: int = 500,
    temperature: float = 0.7,
    system_prompt: str = None,
) -> str:
    """
    Convenience wrapper that always returns a string.
    Returns safe fallback message on failure.
    """
    SAFE_FALLBACK = "I'm currently unable to process this request."
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    result = await call_llm(messages, max_tokens=max_tokens, temperature=temperature)
    return result if result else SAFE_FALLBACK
