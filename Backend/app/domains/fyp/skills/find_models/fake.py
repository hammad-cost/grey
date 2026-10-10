"""
Fake-mode answers for find_models (LLM_MODE=fake, the default).

Template-based: the first page is a fine-tuning start, the second a benchmark.
The reply goes through exactly the same checks as a real model's reply.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider


def fake_model_plan(llm_input: dict) -> dict:
    """Build an LLMModelPlanDraft-shaped reply from the request."""
    candidates = llm_input.get("candidates", [])[:2]
    task = llm_input.get("ai_strategy", {}).get("task_type", "the AI task").replace("_", " ")
    uses = [
        ("pretrained_model", "fine_tune", "A related model that can be fine-tuned on your selected dataset."),
        ("code_repository", "benchmark", "Compare your own model against it to show your improvement."),
    ]
    options = [
        {
            "candidate_number": n,
            "kind": kind,
            "name": candidate.get("title", "Related model")[:120],
            "use": use,
            "reason": reason,
            "role": f"The {task} part of the system",
            "limitations": ["Built for a different setting, so results may differ"],
        }
        for n, (candidate, (kind, use, reason)) in enumerate(zip(candidates, uses), start=1)
    ]
    summary = (
        "Start from the first option and compare against the second." if len(options) == 2
        else "Nothing ready-made fits well, so build the AI part as your AI strategy plans."
        if not options else "One related option is worth trying."
    )
    return {"summary": summary, "options": options}


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer find_models."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMModelPlanDraft", fake_model_plan)
