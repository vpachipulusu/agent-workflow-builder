"""LLM client wrapper using Azure OpenAI."""

from __future__ import annotations

import json
import logging

from openai import AsyncAzureOpenAI

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
)

logger = logging.getLogger(__name__)


def _build_client() -> AsyncAzureOpenAI:
    """Construct the Azure OpenAI async client."""
    kwargs: dict = {
        "azure_endpoint": AZURE_OPENAI_ENDPOINT,
        "api_version": AZURE_OPENAI_API_VERSION,
    }
    if AZURE_OPENAI_API_KEY:
        logger.info("Using API Key authentication for Azure OpenAI")
        kwargs["api_key"] = AZURE_OPENAI_API_KEY
    else:
        # Try credential chain: AzureCli → AzureDeveloperCli → DefaultAzureCredential
        logger.info("Using token-based authentication for Azure OpenAI")
        from azure.identity.aio import (
            AzureCliCredential,
            AzureDeveloperCliCredential,
            ChainedTokenCredential,
        )
        from azure.identity.aio import get_bearer_token_provider

        credential = ChainedTokenCredential(
            AzureCliCredential(),
            AzureDeveloperCliCredential(),
        )
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        kwargs["azure_ad_token_provider"] = token_provider

    return AsyncAzureOpenAI(**kwargs)


_client: AsyncAzureOpenAI | None = None


def get_client() -> AsyncAzureOpenAI:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def reset_client() -> None:
    """Reset the client (e.g., after credential refresh)."""
    global _client
    _client = None


async def chat_completion(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.3,
    response_format: dict | None = None,
) -> str:
    """Send a chat completion request and return the assistant message text."""
    client = get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    kwargs: dict = {
        "model": AZURE_OPENAI_DEPLOYMENT,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        kwargs["response_format"] = response_format

    resp = await client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    logger.debug("LLM response: %s", content[:500])
    return content


async def chat_completion_json(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.2,
) -> dict:
    """Chat completion that returns parsed JSON."""
    raw = await chat_completion(
        system_prompt,
        user_message,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    return json.loads(raw)
