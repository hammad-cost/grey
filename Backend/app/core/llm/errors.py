"""
LLM errors — one class per kind of failure.

Provider adapters translate every vendor error (HTTP status, SDK exception)
into one of these, so the gateway can decide what to do without knowing
anything about Groq, Anthropic, OpenAI, …

Each class says two things:
  retryable        — is it worth trying the SAME provider/model again?
  fallback_allowed — may the gateway move on to the NEXT provider/model?

Safety refusals are deliberately NOT fallback-allowed: Grey never tries
another model just to get around a refusal.
"""


class LLMError(Exception):
    """Base class for every LLM failure."""

    kind = "llm_error"
    retryable = False
    fallback_allowed = False

    def __init__(self, message: str, *, provider: str | None = None, model: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model


class LLMRateLimited(LLMError):
    """Too many requests (HTTP 429). Retry after a pause, then fall back."""

    kind = "rate_limited"
    retryable = True
    fallback_allowed = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after          # seconds the provider asked us to wait, if it said


class LLMTimeout(LLMError):
    """The provider did not answer in time. Retry, then fall back."""

    kind = "timeout"
    retryable = True
    fallback_allowed = True


class LLMServerError(LLMError):
    """The provider failed on its side (5xx, overloaded, connection dropped). Retry, then fall back."""

    kind = "server_error"
    retryable = True
    fallback_allowed = True


class LLMQuotaExhausted(LLMError):
    """The account's quota or daily limit is used up. Retrying won't help; fall back."""

    kind = "quota_exhausted"
    fallback_allowed = True


class LLMAuthError(LLMError):
    """The API key is missing, wrong, or not allowed. The provider is unusable; fall back."""

    kind = "auth_error"
    fallback_allowed = True


class LLMContextTooLong(LLMError):
    """The request is too big for this model. Fall back only to a model with a bigger context."""

    kind = "context_too_long"
    fallback_allowed = True


class LLMInvalidOutput(LLMError):
    """The reply was not valid JSON for the requested schema (or was cut off). Repair once, then fall back."""

    kind = "invalid_output"
    fallback_allowed = True


class LLMRefusal(LLMError):
    """The model declined for safety reasons. Never retried, never sent to another model."""

    kind = "refusal"


class LLMBadRequest(LLMError):
    """Grey sent something invalid (a bug on our side). Another model would fail the same way."""

    kind = "bad_request"


class LLMUnavailable(LLMError):
    """No provider/model could produce a valid answer (all failed, cooling down, or not configured)."""

    kind = "unavailable"

    def __init__(self, message: str, *, causes: list[str] | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.causes = causes or []              # error kinds seen along the way, e.g. ["rate_limited", "timeout"]
