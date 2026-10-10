"""
Fake-mode answers for plan_technology (LLM_MODE=fake, the default).
Template-based on whether the project uses AI and on the re-plan request;
the reply goes through exactly the same checks as a real model's reply.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider

LAPTOP = {
    "kind": "normal_laptop", "name": "A normal laptop", "purpose": "Build, run and demonstrate the system",
    "essential": True, "cost": "none", "alternative": "",
}
COLAB = {
    "kind": "google_colab", "name": "Free Google Colab GPU", "purpose": "Train the model faster than on a laptop",
    "essential": False, "cost": "none", "alternative": "Train a smaller model on the laptop",
}


def _choice(area: str, choice: str, reason: str) -> dict:
    return {"area": area, "choice": choice, "reason": reason}


def fake_technology_plan(llm_input: dict) -> dict:
    """Build an LLMTechnologyPlanDraft-shaped reply from the request."""
    uses_ai = llm_input.get("ai_strategy", {}).get("uses_ai", True)
    simpler = "replan" in llm_input
    if simpler:
        stack = [
            _choice("frontend", "Streamlit", "One Python dashboard is enough to show the results."),
            _choice("database", "SQLite", "A single file database needs no server."),
        ]
    else:
        stack = [
            _choice("frontend", "React", "The main frontend need is one interactive dashboard."),
            _choice("backend", "FastAPI", "A small Python API connects the dashboard to the analysis."),
            _choice("database", "PostgreSQL", "It stores records and results reliably."),
        ]
    if uses_ai:
        stack.append(_choice("ai_ml", "Python with scikit-learn", "Classic models are enough for this task."))
        if not simpler:
            stack.append(_choice("training", "Google Colab", "Free GPUs speed up training experiments."))
    stack.append(_choice("deployment", "Local", "Running it on a laptop is enough for the demo."))
    hardware = [LAPTOP] + ([COLAB] if uses_ai and not simpler else [])
    summary = (
        "A lightweight Python dashboard on a laptop, with as few tools as possible." if simpler
        else "A small web app with a Python backend, running on a normal laptop."
    )
    return {"summary": summary, "stack": stack, "hardware": hardware}


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer plan_technology."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMTechnologyPlanDraft", fake_technology_plan)
