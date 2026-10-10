"""
Fake-mode answers for plan_ai_strategy (LLM_MODE=fake, the default).

FakeLLMProvider calls fake_strategy() to build a reply from the request, and
the reply goes through exactly the same checks as a real model's reply.
Template-based: the verdict follows the problem's task type and the
student's re-check preference. Good enough to exercise the app, not real reasoning.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider

# Problem task type (from problem extraction) → (verdict, AI task, primary approach, fallback approach).
_BY_PROBLEM_TASK = {
    "anomaly_detection": ("traditional_ml", "anomaly_detection", "train_model", "hybrid"),
    "classification": ("traditional_ml", "classification", "train_model", "hybrid"),
    "forecasting": ("traditional_ml", "forecasting", "train_model", "hybrid"),
    "recommendation": ("traditional_ml", "recommendation", "train_model", "hybrid"),
    "nlp": ("ai_necessary", "nlp", "pretrained_model", "use_api"),
    "computer_vision": ("ai_necessary", "computer_vision", "fine_tune", "pretrained_model"),
    "decision_support": ("ai_optional", "classification", "train_model", "none"),
    "optimization": ("optimization", "none", "none", "none"),
    "other": ("ai_optional", "classification", "train_model", "none"),
}

_NO_CHOICE = {"approach": "none", "reason": ""}


def _components(llm_input: dict) -> list[str]:
    core = llm_input.get("project_definition", {}).get("core_features", [])
    names = [feature.get("title", "") for feature in core if feature.get("title")]
    return names[:3] or ["Data input", "Results view"]


def _without_ai_reply(components: list[str]) -> dict:
    return {
        "necessity": "rule_based",
        "necessity_reason": "Clear rules and thresholds set with the target users can cover the core scope.",
        "without_ai": "Rules flag the cases that matter; they are easy to explain but miss new patterns.",
        "ai_component": "",
        "non_ai_components": [*components, "Rule checker"][:6],
        "task_type": "none",
        "primary_strategy": _NO_CHOICE,
        "fallback_strategy": _NO_CHOICE,
    }


def _existing_model_reply(components: list[str], task: str) -> dict:
    return {
        "necessity": "existing_model",
        "necessity_reason": "A ready-made model can do the AI part well enough for a student prototype.",
        "without_ai": "Fixed rules could flag some cases, but would miss many of them.",
        "ai_component": "The analysis step, which sends each record to a ready-made model.",
        "non_ai_components": components,
        "task_type": task,
        "primary_strategy": {"approach": "pretrained_model", "reason": "No training is needed, so it is quick to build."},
        "fallback_strategy": {"approach": "use_api", "reason": "A hosted service can be used if running the model locally is too slow."},
    }


def fake_strategy(llm_input: dict) -> dict:
    """Build an LLMAIStrategyDraft-shaped reply from the request."""
    components = _components(llm_input)
    problem_task = llm_input.get("problem", {}).get("task_type", "other")
    verdict, task, primary, fallback = _BY_PROBLEM_TASK.get(problem_task, _BY_PROBLEM_TASK["other"])

    request = llm_input.get("recheck", {}).get("student_request", "")
    if "without AI" in request:
        return _without_ai_reply(components)
    if "ready-made model" in request:
        return _existing_model_reply(components, task if task != "none" else "classification")
    if verdict == "optimization":
        reply = _without_ai_reply(components)
        reply["necessity"] = "optimization"
        reply["necessity_reason"] = "The problem is about finding the best plan, which is an optimization task."
        return reply

    return {
        "necessity": verdict,
        "necessity_reason": "The patterns that matter are hard to capture with fixed rules alone.",
        "without_ai": "Fixed rules could flag the obvious cases, but would miss new or subtle ones.",
        "ai_component": "The analysis step, which scores each record and finds the ones that matter.",
        "non_ai_components": components,
        "task_type": task,
        "primary_strategy": {"approach": primary, "reason": "Public or simulated data is enough for a student project."},
        "fallback_strategy": (
            {"approach": fallback, "reason": "A simpler option if the main approach doesn't work well enough."}
            if fallback != "none" else _NO_CHOICE
        ),
    }


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer plan_ai_strategy."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMAIStrategyDraft", fake_strategy)
