"""
Fake-mode answers for define_project (LLM_MODE=fake, the default).

FakeLLMProvider calls fake_definition() to build a reply from the request, and
the reply goes through exactly the same checks as a real model's reply.
Simple and template-based: good enough to exercise the app, not real reasoning.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider


def fake_definition(llm_input: dict) -> dict:
    """Build an LLMProjectDefinitionDraft-shaped reply from the approved design in the request."""
    design = llm_input.get("approved_design", {})
    problem = llm_input.get("problem", {})
    user = design.get("target_user", "The target user")
    output = design.get("system_output", "useful results")
    return {
        "problem_definition": {
            "problem_statement": problem.get("real_world_problem", "A real-world problem exists."),
            "affected_users": user,
            "why_it_matters": problem.get("why_it_matters", "It slows down important work."),
            "current_solutions": "Large tools exist, but they are complex and not built for this specific need.",
            "gap": "There is no simple tool that explains its results to a non-expert user.",
            "what_will_be_built": design.get("summary", "A focused prototype tool."),
        },
        "system_purpose": f"Help {user.lower()} get {output.lower()}.",
        "modules": [
            {"name": "Data input", "purpose": f"Lets the user add {design.get('system_input', 'records').lower()}."},
            {"name": "Analysis", "purpose": "Checks the records and finds the results that matter."},
            {"name": "Results view", "purpose": "Shows each result with a plain-language reason."},
        ],
        "workflow_steps": [
            "The user adds the records they want to check",
            "The system analyses the records",
            "The user reviews the results and their reasons",
        ],
        "core_features": [
            {"title": "Record upload", "description": "The user can add records from a file."},
            {"title": "Result list", "description": "The system lists the results in order of importance."},
            {"title": "Plain-language reasons", "description": "Each result comes with a short reason."},
        ],
        "optional_features": [
            {"title": "Export report", "description": "The user can save the results as a short report."},
            {"title": "Result filters", "description": "The user can filter results by type or date."},
        ],
        "out_of_scope": [
            {"title": "Live data feeds", "description": "The project uses saved public or simulated data only."},
            {"title": "Mobile app", "description": "The project is a single web prototype."},
        ],
    }


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer define_project."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMProjectDefinitionDraft", fake_definition)
