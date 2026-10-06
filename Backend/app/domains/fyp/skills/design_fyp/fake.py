"""
Fake-mode answers for design_fyp (LLM_MODE=fake, the default).

FakeLLMProvider calls fake_design() to build a reply from the request, and the
reply goes through exactly the same checks as a real model's reply. Simple
and template-based: good enough to exercise the app, not real reasoning.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider

# requested change (the start of its text) → (title ending, target user, summary sentence)
_REDESIGNS = [
    ("Make the project simpler", "a simpler version",
     None, "It focuses on one clear goal with fewer features."),
    ("Design the project for a different target user", "for a new user group",
     "Team leads who review the results each week", "It is now designed for team leads who review results."),
    ("Keep the problem but focus the system", "with a new system focus",
     None, "It now focuses on explaining each result rather than producing many results."),
    ("Reduce the implementation effort", "a lighter build",
     None, "It uses fewer components and a small sample of data."),
]


def fake_design(llm_input: dict) -> dict:
    """Build an LLMFYPDesignDraft-shaped reply from the problem (and redesign request) in the request."""
    problem = llm_input.get("problem", {})
    branch = llm_input.get("branch", "this branch")
    area = llm_input.get("specific_area", "this area")
    title = f"{problem.get('title', 'A focused project')}: a student prototype"
    design = {
        "title": title,
        "summary": f"A prototype tool that helps {branch} teams with {area.lower()} using public or simulated data.",
        "target_user": f"Analysts working in {branch}",
        "system_input": "Records describing the situation over time",
        "system_output": "A short list of findings, each with a plain-language reason",
        "main_contribution": "Clear, checkable results that a non-expert can understand.",
        "scope_reduction": (
            f"Instead of solving the whole problem, the project covers one part of it: {area.lower()}."
        ),
    }

    redesign = llm_input.get("redesign")
    if redesign:
        request = redesign.get("requested_change", "")
        previous = redesign.get("previous_design", {})
        for start, ending, user, sentence in _REDESIGNS:
            if request.startswith(start):
                design["title"] = f"{problem.get('title', 'A focused project')}: {ending}"
                design["summary"] = f"{previous.get('summary', design['summary'])} {sentence}"
                if user:
                    design["target_user"] = user
                break
        if redesign.get("student_note"):
            design["summary"] += " It follows the student's note."
    return design


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer design_fyp."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMFYPDesignDraft", fake_design)
