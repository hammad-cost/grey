"""
Fake-mode answers for classify_area (LLM_MODE=fake, the default).

FakeLLMProvider calls fake_area() to build a reply from the request, and the
reply goes through exactly the same checks as a real model's reply. Simple
and pattern-based: good enough to exercise the app, not real reasoning.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider

# task type → (functional area, what the problem is about)
_AREAS = {
    "anomaly_detection": ("Operations Monitoring", "spotting unusual activity early"),
    "classification": ("Data Quality and Triage", "sorting cases into the right category"),
    "forecasting": ("Planning and Forecasting", "predicting what will happen next"),
    "optimization": ("Resource Planning", "using limited resources better"),
    "nlp": ("Document and Text Processing", "understanding written information"),
    "computer_vision": ("Visual Inspection", "understanding images"),
    "recommendation": ("Decision Guidance", "suggesting the right option"),
    "decision_support": ("Decision Support", "helping people decide with complete information"),
    "other": ("Operations Improvement", "improving how work gets done"),
}


def fake_area(llm_input: dict) -> dict:
    """Build an LLMAreaDraft-shaped reply from the problem in the request."""
    problem = llm_input.get("problem", {})
    functional, about = _AREAS.get(problem.get("task_type"), _AREAS["other"])
    specific = " ".join(problem.get("title", "Problem Focus").split())[:80].strip()
    if specific.lower() == functional.lower():
        specific = f"{specific} Focus"
    return {
        "functional_area": functional,
        "specific_area": specific,
        "explanation": f"This problem is about {about} in {llm_input.get('branch', 'this branch')}.",
    }


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer classify_area."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMAreaDraft", fake_area)
