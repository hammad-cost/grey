"""
Fake-mode answers for design_architecture (LLM_MODE=fake, the default).
A template pipeline built from the approved stack and AI strategy; the reply
goes through exactly the same checks as a real model's reply.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider


def _stack(llm_input: dict) -> dict[str, str]:
    return {c["area"]: c["choice"] for c in llm_input.get("technology_stack", [])}


def fake_technical_plan(llm_input: dict) -> dict:
    """Build an LLMTechnicalPlanDraft-shaped reply from the request."""
    ai = llm_input.get("ai_strategy", {})
    uses_ai = ai.get("uses_ai", True)
    stack = _stack(llm_input)
    simpler = "redesign" in llm_input
    dataset = llm_input.get("selected_dataset", "")

    parts = [("data_source", "Dataset", "Provides the records the system works on", dataset)]
    if not simpler:
        parts.append(("processing", "Data preparation", "Cleans and prepares the records", stack.get("ai_ml", "")))
    if uses_ai:
        parts.append(("model", "AI model", "Scores each record and finds the ones that matter", stack.get("ai_ml", "")))
    else:
        parts.append(("rules", "Rule checker", "Applies clear rules to flag the records that matter", ""))
    if "backend" in stack:
        parts.append(("backend", "Backend API", "Serves results to the interface", stack["backend"]))
    if "database" in stack and not simpler:
        parts.append(("storage", "Database", "Stores records and results", stack["database"]))
    parts.append(("interface", "Dashboard", "Shows the results to the user", stack.get("frontend", "")))
    parts.append(("user", "User", "Reviews the results and acts on them", ""))

    components = [
        {"id": f"c{n}", "kind": kind, "name": name, "role": role, "technology": technology}
        for n, (kind, name, role, technology) in enumerate(parts, start=1)
    ]
    flows = [
        {"source": f"c{n}", "target": f"c{n + 1}", "data": "results" if n > 2 else "records"}
        for n in range(1, len(components))
    ]
    allowed = ai.get("allowed_metrics", [])
    preferred = [m for m in ("precision", "recall", "f1_score", "mae", "rmse", "accuracy") if m in allowed][:3]
    metrics = [{"metric": m, "why": "It shows how well the AI part works.", "goal": "Better than the baseline"} for m in preferred]
    tests = [
        {"kind": "functional_testing", "how": "Check each core feature with prepared examples."},
        {"kind": "response_time", "how": "Measure how long the system takes to show a result."},
    ]
    baseline = ""
    if uses_ai:
        tests.append({"kind": "baseline_comparison", "how": "Compare the model with a simple rule on the same test data."})
        baseline = "A simple threshold rule"
    else:
        tests.append({"kind": "usability_testing", "how": "Ask a few target users to try the dashboard."})
    return {
        "summary": "Records flow from the dataset through the analysis to a dashboard the user reviews.",
        "components": components,
        "flows": flows,
        "metrics": metrics if uses_ai else [],
        "tests": tests,
        "baseline": baseline,
    }


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer design_architecture."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMTechnicalPlanDraft", fake_technical_plan)
