"""
The LLM layer. Skills use only LLMGateway, LLMRequest, LLMResult, the profile
names and the error classes — never a provider, a model name or a vendor SDK.
"""
from .config import build_llm_gateway
from .errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMContextTooLong,
    LLMError,
    LLMInvalidOutput,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMRefusal,
    LLMServerError,
    LLMTimeout,
    LLMUnavailable,
)
from .gateway import GatewayPolicy, LLMGateway
from .profiles import (
    FAST_CHEAP,
    HIGH_QUALITY_REASONING,
    LONG_CONTEXT,
    PROFILE_NAMES,
    STRUCTURED_REASONING,
    WRITING,
)
from .schemas import LLMRequest, LLMResult, LLMUsage

__all__ = [
    "FAST_CHEAP",
    "HIGH_QUALITY_REASONING",
    "LONG_CONTEXT",
    "PROFILE_NAMES",
    "STRUCTURED_REASONING",
    "WRITING",
    "GatewayPolicy",
    "LLMAuthError",
    "LLMBadRequest",
    "LLMContextTooLong",
    "LLMError",
    "LLMGateway",
    "LLMInvalidOutput",
    "LLMQuotaExhausted",
    "LLMRateLimited",
    "LLMRefusal",
    "LLMRequest",
    "LLMResult",
    "LLMServerError",
    "LLMTimeout",
    "LLMUnavailable",
    "LLMUsage",
    "build_llm_gateway",
]
