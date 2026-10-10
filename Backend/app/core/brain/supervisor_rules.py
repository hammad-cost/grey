"""
Supervisor brief rules (Release 0.13) — plain code, no AI.

A brief is complete only when every readiness check (blueprint §33) and every
likely supervisor question (blueprint §35) appears exactly once.
"""
from app.core.brain.schemas import ReadinessCheckId, SupervisorBrief, SupervisorQuestionId


class SupervisorBriefRuleError(ValueError):
    """The brief breaks a rule."""


def brief_rule_broken(brief: SupervisorBrief) -> str | None:
    """The first rule the brief breaks (a short code), or None."""
    if sorted(c.check for c in brief.checks) != sorted(ReadinessCheckId):
        return "missing_check"
    if sorted(q.id for q in brief.questions) != sorted(SupervisorQuestionId):
        return "missing_question"
    return None


def check_brief(brief: SupervisorBrief) -> None:
    """Raise SupervisorBriefRuleError if the brief breaks a rule."""
    broken = brief_rule_broken(brief)
    if broken is not None:
        raise SupervisorBriefRuleError(f"The supervisor brief breaks a rule ({broken}).")
