"""
Fake-mode answers for prepare_supervisor_brief (LLM_MODE=fake, the default).
Talking points built from the summary lines; checked like a real model's reply.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider

# Which summary lines each question draws on.
_SOURCES = {
    "why_this_problem": ["Real-world problem", "Industry"],
    "evidence": ["Evidence", "Real-world problem"],
    "users": ["Proposed solution", "Project title"],
    "existing_solutions": ["Evidence", "Contribution"],
    "contribution": ["Contribution", "Proposed solution"],
    "why_ai": ["AI / ML strategy", "Architecture"],
    "dataset_source": ["Dataset", "Main risks"],
    "model_evaluation": ["Evaluation", "AI / ML strategy"],
    "limitations": ["Main risks", "Dataset"],
    "timeline": ["Feasibility", "Main risks"],
}


def fake_talking_points(llm_input: dict) -> dict:
    """Build an LLMTalkingPointsDraft-shaped reply from the request."""
    summary = {item["label"]: item["value"] for item in llm_input.get("summary", [])}
    questions = []
    for q in llm_input.get("questions", []):
        points = [f"{label}: {summary.get(label, 'see the brief')}"[:200] for label in _SOURCES.get(q["id"], ["Project title"])]
        questions.append({"id": q["id"], "talking_points": points})
    return {"questions": questions}


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer prepare_supervisor_brief."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMTalkingPointsDraft", fake_talking_points)
