"""
Fake-mode answers for assess_feasibility (LLM_MODE=fake, the default).
Template judgements; the reply goes through exactly the same checks as a real model's reply.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider


def fake_feasibility(llm_input: dict) -> dict:
    """Build an LLMFeasibilityDraft-shaped reply from the request."""
    uses_api = any(o.get("kind") == "api_service" for o in llm_input.get("model_plan", []))
    collected = llm_input.get("dataset", {}).get("kind") == "student_collected"
    judgements = [
        ("problem_relevance", "favourable", "Real and current", "The problem comes from current evidence in the branch."),
        ("technical_complexity", "moderate", "Moderate", "The core features are reachable but need steady work."),
        ("time", "favourable", "Fits the timeline", "The core scope can be built and evaluated in a few months."),
        ("external_dependencies", "moderate" if uses_api else "favourable",
         "Relies on a service" if uses_api else "Few dependencies",
         "An outside service may change or cost money." if uses_api else "The student controls the main parts."),
        ("ethical_legal", "moderate" if collected else "favourable",
         "Consent needed" if collected else "Low concern",
         "Collected data needs consent and careful storage." if collected else "No personal data is needed."),
        ("risk", "moderate", "Manageable", "Most risks can be reduced by starting the data work early."),
        ("novelty", "moderate", "Clear but modest", "The contribution is useful, though related tools exist."),
    ]
    return {
        "summary": "The project is realistic for one student if the data preparation starts early.",
        "judgements": [
            {"dimension": d, "level": level, "finding": finding, "reason": reason}
            for d, level, finding, reason in judgements
        ],
        "main_risks": [
            {"risk": "Data preparation takes longer than planned", "mitigation": "Start with a small sample in the first month."},
            {"risk": "The model performs worse than hoped", "mitigation": "Keep the simple baseline and report both honestly."},
        ],
    }


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer assess_feasibility."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMFeasibilityDraft", fake_feasibility)
