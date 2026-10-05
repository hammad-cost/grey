"""
LLM Gateway

The single point through which every skill calls a language model.
Skills never import an LLM provider SDK directly — they always go through here.

Why a gateway?
  - Provider independence: swap OpenAI for Anthropic (or any other) by
    changing this file only. Skills stay unchanged.
  - Cost control: every call is logged with skill name, model, tokens, and latency.
  - Prompt versioning: prompts live in domains/fyp/prompts/, not scattered in skills.
  - Structured output: the gateway validates the response against the expected schema.

Release 0.1 status:
  No real LLM calls are needed yet. The gateway exists as a placeholder so
  skills can be written against its interface now and filled in later.
  Calling generate_structured() in Release 0.1 raises NotImplementedError.
"""
from typing import Any, Type

from pydantic import BaseModel


class ModelPolicy(BaseModel):
    """
    Controls which model a skill is allowed to use and what it costs.
    Cheap extraction tasks use a smaller model; complex reasoning uses a larger one.
    """
    model: str = "claude-sonnet-4-6"    # default model
    max_tokens: int = 2048
    temperature: float = 0.2            # low temperature = more predictable output


class LLMGateway:
    """
    The only place in Grey that is allowed to call a language model.

    Usage (once implemented):
        gateway = LLMGateway()
        result = await gateway.generate_structured(
            task="Extract real-world problems from the following evidence.",
            input={"evidence": [...]},
            output_schema=ExtractedProblemsSchema,
            policy=ModelPolicy(model="claude-haiku-4-5-20251001"),
        )
    """

    async def generate_structured(
        self,
        *,
        task: str,
        input: dict[str, Any],
        output_schema: Type[BaseModel],
        policy: ModelPolicy | None = None,
    ) -> BaseModel:
        """
        Send a structured task to a language model and return a validated result.

        Args:
            task:          The instruction for the model (what to do).
            input:         The data the model needs to do the task.
            output_schema: A Pydantic model class. The response will be validated
                           against this schema before being returned.
            policy:        Which model to use and token/temperature settings.
                           Defaults to ModelPolicy() if not provided.

        Returns:
            A validated instance of output_schema.

        Raises:
            NotImplementedError: In Release 0.1 — no LLM provider is configured yet.
        """
        raise NotImplementedError(
            "The LLM Gateway is not yet connected to a provider. "
            "Real LLM calls are introduced in a future release. "
            "Release 0.1 uses deterministic logic only."
        )
