"""
LLM provider adapters. Only the gateway and config.py use these — skills never do.
"""
from .base import LLMProvider, ProviderCall, ProviderResponse
from .fake import FakeLLMProvider
from .openai_compatible import OpenAICompatibleProvider

__all__ = [
    "FakeLLMProvider",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ProviderCall",
    "ProviderResponse",
]
