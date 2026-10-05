"""
The interface every LLM provider adapter implements.

An adapter's whole job:
  1. turn a ProviderCall into the vendor's request format,
  2. send it,
  3. return the raw JSON text + token counts,
  4. translate EVERY vendor failure into a Grey LLMError subclass.

Adapters never retry, never fall back and never validate the reply against
the schema — the gateway does all of that, the same way for every vendor.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderCall:
    """One request to one model."""

    model: str
    instructions: str                   # system prompt
    input_json: str                     # the facts, as JSON text
    schema_name: str                    # e.g. "LLMProblemDrafts"
    json_schema: dict[str, Any]         # provider-facing schema (see schema_tools.py)
    strict_schema: bool                 # ask the provider to enforce the schema exactly
    max_output_tokens: int
    timeout_seconds: float
    repair_feedback: str | None = None  # set when asking the model to fix its previous reply


@dataclass
class ProviderResponse:
    """What came back: the JSON text (not yet validated) and token usage."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(ABC):
    """Base class for provider adapters (fake, Groq, later Anthropic, OpenAI, LiteLLM, …)."""

    name: str

    @abstractmethod
    async def generate_json(self, call: ProviderCall) -> ProviderResponse:
        """Send one call. Raise only LLMError subclasses."""
        ...
