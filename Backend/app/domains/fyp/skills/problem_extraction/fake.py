"""
Fake-mode answers for problem extraction (LLM_MODE=fake, the default).

When no real model is configured, FakeLLMProvider calls fake_problem_drafts()
to build a reply from the evidence it was sent. The reply goes through exactly
the same validation as a real model's reply, so the whole flow — context,
gateway, checks, saving, UI — works end to end without a key or any cost.

The problems are simple and pattern-based: good enough to exercise the app,
not a substitute for real reasoning.
"""
from app.core.llm import LLMGateway
from app.core.llm.providers.fake import FakeLLMProvider

# (words to look for in a source's problem text, title, task type, FYP direction)
_PATTERNS = [
    (("by hand", "warning", "manual", "noticed too late"),
     "Early warning for unusual activity in {branch}", "anomaly_detection",
     "Train a model that flags unusual patterns in public or simulated {branch} data and explains each alert."),
    (("predict", "failure", "downtime", "demand"),
     "Predicting failures and demand peaks in {branch}", "forecasting",
     "Build a forecasting model on public time-series data that predicts problems days in advance."),
    (("disconnected", "spread across", "complete", "picture"),
     "A unified decision view for {branch} teams", "decision_support",
     "Build a dashboard that merges several public data sources and highlights inconsistencies automatically."),
    (("reproduce", "private dataset", "benchmark", "small"),
     "Reproducible benchmarks for {branch} machine learning", "classification",
     "Create an open benchmark from public data and compare several baseline models on it."),
    (("report", "error", "quality", "inconsistent"),
     "Automated data-quality checks for {branch} reporting", "classification",
     "Build a tool that detects errors and missing values in {branch} reports before they are used."),
]


def fake_problem_drafts(llm_input: dict) -> dict:
    """Build an LLMProblemDrafts-shaped reply from the evidence in the request."""
    branch = llm_input.get("branch", "this branch")
    problems = []
    used_titles: set[str] = set()

    for source in llm_input.get("evidence", []):
        if source.get("tier") == "C":
            continue
        text = f"{source.get('problem_addressed', '')} {source.get('title', '')}".lower()
        for words, title, task_type, direction in _PATTERNS:
            title = title.format(branch=branch)
            if title in used_titles or not any(word in text for word in words):
                continue
            used_titles.add(title)
            problems.append({
                "title": title,
                "real_world_problem": source["problem_addressed"],
                "observed_solutions": source["relevant_insight"],
                "technical_problem": f"Turning {branch} data into timely, reliable {task_type.replace('_', ' ')}.",
                "task_type": task_type,
                "why_it_matters": "Organizations in this branch are actively investing in it, as the cited sources show.",
                "possible_fyp_direction": direction.format(branch=branch),
                # Quoting the source's own sentence keeps the citation grounded.
                "evidence": [{"ref": source["ref"], "supporting_point": source["problem_addressed"]}],
            })
            break

    return {"problems": problems}


def install_fake_answers(llm: LLMGateway) -> None:
    """If the gateway runs in fake mode, teach the fake provider to answer problem extraction."""
    if llm.router.has_provider("fake"):
        fake = llm.router.provider("fake")
        if isinstance(fake, FakeLLMProvider):
            fake.add_responder("LLMProblemDrafts", fake_problem_drafts)
