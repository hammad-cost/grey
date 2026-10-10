"""
Fake-mode answers for find_datasets (LLM_MODE=fake, the default).

FakeLLMProvider calls fake_dataset_plan() to build a reply from the request,
and the reply goes through exactly the same checks as a real model's reply.
Template-based: it takes the first numbered pages, and falls back to data
the student creates or collects. Good enough to exercise the app, not real reasoning.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider

NOT_STATED = "Not stated — check the dataset page"


def _public(number: int, candidate: dict, branch: str) -> dict:
    return {
        "kind": "public",
        "candidate_number": number,
        "name": candidate.get("title", "Public dataset")[:120],
        "size": NOT_STATED,
        "main_features": ["Record date", "Measured values", "Outcome"],
        "labels": NOT_STATED,
        "license": NOT_STATED,
        "relevance": f"Its records match the {branch} problem your core features work on.",
        "preprocessing": ["Remove duplicate and empty records", "Split into training and test parts"],
        "limitations": ["May not cover every case your users meet"],
        "fit": "good" if number == 1 else "partial",
        "how_to_get": "",
    }


def _own(kind: str, branch: str) -> dict:
    simulated = kind == "synthetic"
    return {
        "kind": kind,
        "candidate_number": 0,
        "name": f"Simulated {branch} records" if simulated else f"Collected {branch} records",
        "size": "Aim for a few thousand records" if simulated else "Aim for a few hundred records",
        "main_features": ["Record date", "Measured values", "Outcome"],
        "labels": "You set the outcome for each record you create" if simulated else "You record the outcome for each case",
        "license": "Your own data",
        "relevance": "You control exactly which cases appear, so every core feature can be tested.",
        "preprocessing": ["Check the records look realistic"],
        "limitations": ["May miss patterns that only real data shows"],
        "fit": "partial",
        "how_to_get": (
            "Write a small script that generates realistic records, including the unusual cases."
            if simulated else
            "Collect records with a short form shared with a few target users, with their consent."
        ),
    }


def fake_dataset_plan(llm_input: dict) -> dict:
    """Build an LLMDatasetPlanDraft-shaped reply from the request."""
    branch = llm_input.get("branch", "project")
    candidates = llm_input.get("candidates", [])
    uses_ai = llm_input.get("ai_strategy", {}).get("uses_ai", True)
    purpose = (
        "Train and test the AI part of the system." if uses_ai
        else "Build, test and demonstrate the system (the project doesn't use AI)."
    )
    publics = [_public(n, c, branch) for n, c in enumerate(candidates[:2], start=1)]

    request = llm_input.get("research", {}).get("student_request", "")
    if "own data" in request:
        return {
            "purpose": purpose,
            "primary": _own("synthetic", branch),
            "alternative": publics[0] if publics else _own("student_collected", branch),
        }
    if len(publics) == 2:
        return {"purpose": purpose, "primary": publics[0], "alternative": publics[1]}
    if len(publics) == 1:
        return {"purpose": purpose, "primary": publics[0], "alternative": _own("synthetic", branch)}
    return {"purpose": purpose, "primary": _own("synthetic", branch), "alternative": _own("student_collected", branch)}


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer find_datasets."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMDatasetPlanDraft", fake_dataset_plan)
