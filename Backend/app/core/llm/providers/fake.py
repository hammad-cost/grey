"""
FakeLLMProvider — a provider that never touches the network.

Used by every automated test and by the app when LLM_MODE=fake (the default),
so Grey runs without an API key and without cost.

Two ways to tell it what to answer:

  script     — a queue of replies per model, used by tests:
                 fake.script("fake-a", [LLMRateLimited("busy"), {"answer": 42}])
               Each item is either an exception to raise, a dict (sent back as
               JSON), or a string (sent back as-is, e.g. broken JSON).

  responders — a function per output schema that builds a reply from the
               input, used when the app runs in fake mode:
                 fake.add_responder("LLMProblemDrafts", build_fake_drafts)

Every call is recorded in `calls`, so tests can check what was sent.
"""
import json
from collections.abc import Callable
from typing import Any

from app.core.llm.errors import LLMBadRequest
from app.core.llm.providers.base import LLMProvider, ProviderCall, ProviderResponse

Responder = Callable[[dict[str, Any]], dict[str, Any]]


class FakeLLMProvider(LLMProvider):
    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.calls: list[ProviderCall] = []
        self._scripts: dict[str, list[Any]] = {}
        self._responders: dict[str, Responder] = {}

    def script(self, model: str, replies: list[Any]) -> None:
        """Queue replies for `model`, used in order."""
        self._scripts.setdefault(model, []).extend(replies)

    def add_responder(self, schema_name: str, responder: Responder) -> None:
        """Answer every call for `schema_name` by calling `responder(input)`."""
        self._responders[schema_name] = responder

    async def generate_json(self, call: ProviderCall) -> ProviderResponse:
        self.calls.append(call)

        queue = self._scripts.get(call.model)
        if queue:
            reply = queue.pop(0)
            if isinstance(reply, Exception):
                raise reply
        elif call.schema_name in self._responders:
            reply = self._responders[call.schema_name](json.loads(call.input_json))
        else:
            raise LLMBadRequest(
                f"FakeLLMProvider has no reply for model '{call.model}' / schema '{call.schema_name}'.",
                provider=self.name,
                model=call.model,
            )

        text = reply if isinstance(reply, str) else json.dumps(reply)
        # Rough token counts so usage logging has something realistic to show.
        return ProviderResponse(
            text=text,
            input_tokens=(len(call.instructions) + len(call.input_json)) // 4,
            output_tokens=len(text) // 4,
        )
