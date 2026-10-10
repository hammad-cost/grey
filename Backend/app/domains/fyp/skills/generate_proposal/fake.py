"""
Fake-mode answers for generate_proposal (LLM_MODE=fake, the default).
Template text built from the approved decisions; checked like a real model's reply.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider


def fake_sections(llm_input: dict) -> dict:
    """Build an LLMSectionsDraft-shaped reply for the sections asked for."""
    summary = {i["label"]: i["value"] for i in llm_input.get("summary", [])}
    design = llm_input.get("design", {})
    cite = " [1]" if llm_input.get("evidence") else ""
    core = llm_input.get("core_features", []) or ["the core feature"]
    rewrite = " (rewritten)" if "rewrite" in llm_input else ""
    text = {
        "introduction": f"This project addresses a problem in {summary.get('Industry', 'the chosen field')}{rewrite}.",
        "background": f"{summary.get('Real-world problem', 'The problem')} is well documented{cite}.",
        "problem_statement": f"{summary.get('Real-world problem', 'The problem')} remains unsolved for small teams.",
        "motivation": f"Solving it helps {design.get('target_user', 'the users')} act sooner.",
        "real_world_evidence": f"The evidence shows the problem exists in practice{cite}.",
        "proposed_solution": design.get("summary", "A focused system."),
        "aim": f"To build and evaluate {design.get('title', 'the system')}.",
        "methodology": f"The work follows the approved plan: {summary.get('Architecture', 'the architecture')}.",
        "expected_outcomes": f"A working prototype and an evaluation using {summary.get('Evaluation', 'the planned tests')}.",
        "limitations": f"The main limitations come from the data and the timeline: {summary.get('Main risks', 'see the risks')}.",
    }
    sections = []
    for section_id in llm_input.get("sections_to_write", []):
        if section_id == "objectives":
            items = [f"Build {feature}." for feature in core[:4]] + ["Evaluate the system against the baseline."]
            sections.append({"id": section_id, "paragraphs": [], "items": items[:6] if len(items) >= 3 else items + ["Write the final report."] * (3 - len(items))})
        else:
            sections.append({"id": section_id, "paragraphs": [text.get(section_id, "Section text.")[:1300]], "items": []})
    return {"sections": sections}


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer generate_proposal."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMSectionsDraft", fake_sections)
