"""
OpenAICompatibleProvider — one adapter for every vendor that speaks the
OpenAI "chat completions" format. Release 0.3 uses it for Groq; OpenAI
itself (and others) can use it later with a different base URL and key.

It uses httpx directly (no vendor SDK), so adding a vendor adds no dependency.

Error translation (HTTP → Grey error):
  401, 403                         → LLMAuthError
  429 mentioning a daily/quota cap → LLMQuotaExhausted
  429 otherwise                    → LLMRateLimited (with retry-after, if sent)
  413, or 400 about context length → LLMContextTooLong
  400 about the JSON schema        → LLMInvalidOutput
  other 4xx                        → LLMBadRequest
  498, 5xx, connection problems    → LLMServerError
  no answer in time                → LLMTimeout
  a refusal / content filter       → LLMRefusal
  reply cut off (finish "length")  → LLMInvalidOutput

The API key is only ever placed in the Authorization header — never in an
error message or log.
"""
import httpx

from app.core.llm.errors import (
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
)
from app.core.llm.providers.base import LLMProvider, ProviderCall, ProviderResponse

# Words in a 429 message that mean "you've used up a long-term allowance",
# not "slow down for a moment" (e.g. Groq's tokens-per-day limit).
_QUOTA_WORDS = ("per day", "daily", "quota", "insufficient_quota", "billing")
_CONTEXT_WORDS = ("context length", "context_length", "maximum context", "too many tokens", "reduce the length")
_SCHEMA_WORDS = ("does not match the expected schema", "json_validate_failed", "failed to generate json")


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Args:
            name:        how this provider is referred to in routes, e.g. "groq".
            base_url:    e.g. "https://api.groq.com/openai/v1".
            api_key:     the secret key (from .env).
            http_client: tests pass a client with a fake transport; normally None.
        """
        self.name = name
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._client = http_client

    async def generate_json(self, call: ProviderCall) -> ProviderResponse:
        messages = [
            {"role": "system", "content": call.instructions},
            {"role": "user", "content": call.input_json},
        ]
        if call.repair_feedback:
            messages.append({"role": "user", "content": call.repair_feedback})

        if call.strict_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": call.schema_name, "strict": True, "schema": call.json_schema},
            }
        else:
            # JSON mode: valid JSON, but the schema is only described, not enforced.
            response_format = {"type": "json_object"}

        body = {
            "model": call.model,
            "messages": messages,
            "response_format": response_format,
            "max_completion_tokens": call.max_output_tokens,
        }

        try:
            response = await self._post(body, call.timeout_seconds)
        except httpx.TimeoutException as error:
            raise self._error(LLMTimeout, "The provider did not answer in time.", call) from error
        except httpx.TransportError as error:
            raise self._error(LLMServerError, f"Connection problem: {type(error).__name__}", call) from error

        if response.status_code >= 400:
            raise self._http_error(response, call)

        return self._parse(response, call)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _post(self, body: dict, timeout: float) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._client is not None:
            return await self._client.post(self._url, json=body, headers=headers, timeout=timeout)
        async with httpx.AsyncClient() as client:
            return await client.post(self._url, json=body, headers=headers, timeout=timeout)

    def _error(self, error_class: type[LLMError], message: str, call: ProviderCall, **extra) -> LLMError:
        return error_class(message, provider=self.name, model=call.model, **extra)

    def _http_error(self, response: httpx.Response, call: ProviderCall) -> LLMError:
        status = response.status_code
        message = _error_message(response)
        text = message.lower()

        if status in (401, 403):
            return self._error(LLMAuthError, f"HTTP {status}: {message}", call)
        if status == 429:
            if any(word in text for word in _QUOTA_WORDS):
                return self._error(LLMQuotaExhausted, f"HTTP 429: {message}", call)
            return self._error(
                LLMRateLimited, f"HTTP 429: {message}", call,
                retry_after=_retry_after(response),
            )
        if status == 413 or any(word in text for word in _CONTEXT_WORDS):
            return self._error(LLMContextTooLong, f"HTTP {status}: {message}", call)
        if status == 400 and any(word in text for word in _SCHEMA_WORDS):
            return self._error(LLMInvalidOutput, f"HTTP 400: {message}", call)
        if status == 498 or status >= 500:
            return self._error(LLMServerError, f"HTTP {status}: {message}", call)
        return self._error(LLMBadRequest, f"HTTP {status}: {message}", call)

    def _parse(self, response: httpx.Response, call: ProviderCall) -> ProviderResponse:
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise self._error(LLMServerError, "The provider sent an unreadable response.", call) from error

        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise self._error(LLMRefusal, "The model declined this request.", call)
        if choice.get("finish_reason") == "length":
            raise self._error(LLMInvalidOutput, "The reply was cut off before it finished.", call)

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise self._error(LLMInvalidOutput, "The reply was empty.", call)

        usage = data.get("usage") or {}
        return ProviderResponse(
            text=content,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


def _error_message(response: httpx.Response) -> str:
    """The provider's error message, kept short. OpenAI-style bodies look like {"error": {"message": …}}."""
    try:
        error = response.json().get("error") or {}
        message = error.get("message") or error.get("code") or ""
    except (ValueError, AttributeError):
        message = ""
    return (message or response.reason_phrase or "error")[:300]


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
