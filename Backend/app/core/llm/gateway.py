"""
LLM Gateway

The single point through which every skill calls a language model.
Skills never import a provider SDK — they build an LLMRequest naming a
profile (e.g. "structured_reasoning") and call generate_structured().

What the gateway does for every request:
  1. picks the profile's usable routes (provider + model), in order,
  2. calls a route, retrying short-lived failures with a growing pause,
  3. falls back to the next route when a route can't answer,
  4. checks the reply against the Pydantic schema, asking once for a repair,
  5. logs every attempt (skill, profile, provider, model, outcome, tokens,
     latency — never the prompt, the input or any key),
  6. returns the validated output and where it came from.

Failure rules (see errors.py):
  rate limit / timeout / server error → retry, then fall back
  quota used up                       → fall back (route cools down for a long time)
  invalid API key                     → provider marked unavailable, fall back
  reply doesn't match the schema      → one repair attempt, then fall back
  request too long for the model      → fall back only to a model with a bigger context
  safety refusal / bad request        → stop. Never sent to another model.

Every limit (timeouts, retries, cooldowns) comes from settings via config.py.
"""
import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.core.llm.errors import (
    LLMAuthError,
    LLMContextTooLong,
    LLMError,
    LLMInvalidOutput,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMServerError,
    LLMTimeout,
    LLMUnavailable,
)
from app.core.llm.providers.base import ProviderCall
from app.core.llm.router import LLMRouter
from app.core.llm.schema_tools import strict_json_schema
from app.core.llm.schemas import LLMAttempt, LLMRequest, LLMResult, LLMUsage, ModelRoute, T

logger = logging.getLogger("grey.llm")

# Longest pause between retries, whatever the provider asks for.
MAX_RETRY_PAUSE_SECONDS = 30.0


@dataclass(frozen=True)
class GatewayPolicy:
    """Limits for one gateway call. Built from settings in config.py."""

    attempt_timeout_seconds: float = 60.0      # one call to one model
    total_deadline_seconds: float = 150.0      # everything, all retries and fallbacks
    max_retries: int = 2                       # extra tries per route for short-lived failures
    retry_base_seconds: float = 1.0            # first pause; doubles each retry
    cooldown_seconds: float = 60.0             # after rate limits / repeated server errors
    quota_cooldown_seconds: float = 3600.0     # after a quota / daily limit


def estimate_tokens(text: str) -> int:
    """A rough token count (about 4 characters per token) used only to rule out routes that are clearly too small."""
    return len(text) // 4 + 1


def repair_message(error: ValidationError | LLMInvalidOutput) -> str:
    """Tell the model what was wrong with its reply — field paths and messages only, never input values."""
    if isinstance(error, ValidationError):
        problems = "; ".join(
            f"{'.'.join(str(p) for p in item['loc']) or 'reply'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
    else:
        problems = str(error)
    return (
        "Your previous reply did not match the required JSON schema. "
        f"Problems: {problems[:1500]}. "
        "Reply again with only the corrected JSON object."
    )


class LLMGateway:
    """The only place in Grey that is allowed to call a language model."""

    def __init__(
        self,
        router: LLMRouter,
        policy: GatewayPolicy | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = lambda: random.uniform(0.0, 0.5),
    ) -> None:
        self.router = router
        self.policy = policy or GatewayPolicy()
        self._sleep = sleep            # tests pass fakes for sleep, clock and jitter
        self._clock = clock
        self._jitter = jitter

    async def generate_structured(self, request: LLMRequest[T]) -> LLMResult[T]:
        """
        Run a structured task and return a validated result.

        Raises:
            LLMRefusal:     the model declined (no fallback, by design).
            LLMBadRequest:  Grey sent an invalid request (a bug).
            LLMUnavailable: no route could produce a valid answer.
            ValueError:     the profile name is unknown (a bug in the skill).
        """
        input_json = json.dumps(request.input, ensure_ascii=False, sort_keys=True, default=str)
        schema = strict_json_schema(request.output_schema)
        schema_name = request.output_schema.__name__
        input_tokens = estimate_tokens(request.instructions + input_json)

        profile = self.router.profile(request.profile)
        start = self._clock()
        attempts: list[LLMAttempt] = []
        causes: list[str] = []
        needs_bigger_context_than = 0

        for route in profile.routes:
            output_tokens = request.max_output_tokens or route.max_output_tokens
            # Re-checked for every route: an earlier failure may have just ruled this one out.
            if route not in self.router.usable_routes(request.profile, input_tokens + output_tokens):
                continue
            if route.context_window <= needs_bigger_context_than:
                continue

            result = await self._try_route(
                request, route, input_json, schema_name, schema, output_tokens, start, attempts, causes,
            )
            if isinstance(result, LLMResult):
                return result
            if isinstance(result, LLMContextTooLong):
                needs_bigger_context_than = route.context_window

        raise LLMUnavailable(
            f"No model could answer for profile '{request.profile}'"
            + (f" (tried: {', '.join(causes)})." if causes else " (no usable model configured)."),
            causes=causes,
        )

    # ── One route ─────────────────────────────────────────────────────────────

    async def _try_route(
        self,
        request: LLMRequest[T],
        route: ModelRoute,
        input_json: str,
        schema_name: str,
        schema: dict,
        output_tokens: int,
        start: float,
        attempts: list[LLMAttempt],
        causes: list[str],
    ) -> LLMResult[T] | LLMError | None:
        """
        Try one route: retries for short-lived failures, one repair for a bad reply.
        Returns the result, or the error that made us give up on this route
        (None when the deadline ran out). Refusals and bad requests are raised.
        """
        provider = self.router.provider(route.provider)
        health = self.router.health
        policy = self.policy
        retries = 0
        repair_feedback: str | None = None

        while True:
            remaining = policy.total_deadline_seconds - (self._clock() - start)
            if remaining <= 0:
                causes.append("deadline")
                return None

            call = ProviderCall(
                model=route.model,
                instructions=request.instructions,
                input_json=input_json,
                schema_name=schema_name,
                json_schema=schema,
                strict_schema=route.strict_schema,
                max_output_tokens=output_tokens,
                timeout_seconds=min(policy.attempt_timeout_seconds, remaining),
                repair_feedback=repair_feedback,
            )

            began = self._clock()
            try:
                response = await provider.generate_json(call)
                output = request.output_schema.model_validate_json(response.text)
            except ValidationError as error:
                outcome: LLMError | ValidationError = error
            except LLMError as error:
                outcome = error
            else:
                attempts.append(self._attempt(request, route, "ok", began, response.input_tokens, response.output_tokens))
                health.record_success(route)
                return LLMResult(
                    output=output,
                    provider=route.provider,
                    model=route.model,
                    usage=LLMUsage(response.input_tokens, response.output_tokens),
                    attempts=attempts,
                )

            # ── Something went wrong: decide what to do ───────────────────────
            kind = "invalid_output" if isinstance(outcome, ValidationError) else outcome.kind
            attempts.append(self._attempt(request, route, kind, began))
            causes.append(kind)

            if isinstance(outcome, (ValidationError, LLMInvalidOutput)):
                if repair_feedback is None:                 # one repair attempt per route
                    repair_feedback = repair_message(outcome)
                    continue
                return outcome if isinstance(outcome, LLMError) else LLMInvalidOutput(str(outcome))

            if not outcome.fallback_allowed:                # refusal, bad request
                raise outcome

            if isinstance(outcome, LLMAuthError):
                health.mark_unavailable(route.provider, outcome.kind)
                return outcome
            if isinstance(outcome, LLMQuotaExhausted):
                health.cool_down(route, policy.quota_cooldown_seconds)
                return outcome
            if isinstance(outcome, LLMContextTooLong):
                return outcome

            # Short-lived failure: rate limit, timeout, server error.
            pause = self._pause(retries, getattr(outcome, "retry_after", None))
            time_left = policy.total_deadline_seconds - (self._clock() - start)
            if outcome.retryable and retries < policy.max_retries and pause < time_left:
                retries += 1
                await self._sleep(pause)
                continue

            if isinstance(outcome, LLMRateLimited):
                health.cool_down(route, max(policy.cooldown_seconds, outcome.retry_after or 0.0))
            elif isinstance(outcome, (LLMServerError, LLMTimeout)):
                health.record_failure(route, policy.cooldown_seconds)
            return outcome

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pause(self, retries: int, retry_after: float | None) -> float:
        """How long to wait before the next retry: what the provider asked for, or 1s, 2s, 4s… plus a little randomness."""
        if retry_after is not None:
            return min(retry_after, MAX_RETRY_PAUSE_SECONDS)
        return min(self.policy.retry_base_seconds * (2 ** retries) + self._jitter(), MAX_RETRY_PAUSE_SECONDS)

    def _attempt(
        self,
        request: LLMRequest,
        route: ModelRoute,
        outcome: str,
        began: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> LLMAttempt:
        """Record and log one attempt. Never logs the prompt, the input, or a key."""
        latency_ms = int((self._clock() - began) * 1000)
        logger.info(
            "llm_call skill=%s profile=%s provider=%s model=%s outcome=%s "
            "input_tokens=%d output_tokens=%d latency_ms=%d",
            request.skill, request.profile, route.provider, route.model, outcome,
            input_tokens, output_tokens, latency_ms,
        )
        return LLMAttempt(provider=route.provider, model=route.model, outcome=outcome, latency_ms=latency_ms)
