"""
Types used by the LLM layer.

  LLMRequest  — what a skill asks for (a profile, instructions, input, output schema)
  LLMResult   — what it gets back (validated output + which model answered + usage)
  ModelRoute  — one provider + model the gateway may try
  ModelProfile — an ordered list of routes for one kind of work

Skills only ever build an LLMRequest and read an LLMResult.
They never see routes, providers or model names.
"""
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMRequest(Generic[T]):
    """A structured task for a language model."""

    skill: str                      # who is asking, e.g. "problem_extraction" (for logs and cost)
    profile: str                    # what kind of model is needed, e.g. "structured_reasoning"
    instructions: str               # the task (system prompt) — from a prompts file, never inline in a node
    input: dict[str, Any]           # the facts the model reasons over
    output_schema: type[T]          # the Pydantic model the reply must match
    max_output_tokens: int | None = None   # None = the route's own limit


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMAttempt:
    """One try at one route. Kept for logging and for the run record."""

    provider: str
    model: str
    outcome: str                    # "ok" or an error kind, e.g. "rate_limited"
    latency_ms: int


@dataclass
class LLMResult(Generic[T]):
    """A validated answer and where it came from."""

    output: T
    provider: str
    model: str
    usage: LLMUsage
    attempts: list[LLMAttempt] = field(default_factory=list)

    @property
    def fallback_used(self) -> bool:
        """True if the answer did not come from the first route that was tried."""
        tried = [(a.provider, a.model) for a in self.attempts]
        return bool(tried) and tried[0] != (self.provider, self.model)


@dataclass(frozen=True)
class ModelRoute:
    """One provider + model, with the limits the router needs."""

    provider: str                   # e.g. "groq", "fake"
    model: str                      # e.g. "openai/gpt-oss-120b"
    context_window: int             # total tokens (input + output) the model accepts
    max_output_tokens: int          # most tokens we ask it to generate
    strict_schema: bool = False     # True if the provider can enforce our JSON schema exactly

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class ModelProfile:
    """A kind of work and the routes to try for it, in order (first = preferred)."""

    name: str
    routes: tuple[ModelRoute, ...]
