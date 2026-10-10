"""
Checks the model's talking points and builds the full supervisor brief. Plain code — no AI.

  unknown_choice     — a question id that isn't one of the ten
  wrong_questions    — not exactly the ten questions, each once
  wrong_count        — fewer than 2 or more than 4 talking points
  empty / too_long   — a talking point is empty, or far longer than asked for
  contains_url       — a link (http://, https://, www.) appears; site names such as the
                       dataset's source ("kaggle.com") are allowed, since the summary itself uses them
"""
import re

from app.core.brain.schemas import SupervisorBrief, SupervisorQuestion, SupervisorQuestionId
from app.domains.fyp.skills.prepare_supervisor_brief.readiness import readiness_checks, supervisor_summary
from app.domains.fyp.skills.prepare_supervisor_brief.schemas import QUESTIONS, LLMTalkingPointsDraft, SupervisorBriefInput

MAX_POINT_CHARS = 240
POINTS = (2, 4)
_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


def check_talking_points(
    draft: LLMTalkingPointsDraft, input: SupervisorBriefInput
) -> tuple[SupervisorBrief | None, str | None]:
    """Turn the talking points into the full SupervisorBrief, or return (None, the reason it was rejected)."""
    questions: dict[SupervisorQuestionId, list[str]] = {}
    for q in draft.questions:
        try:
            question_id = SupervisorQuestionId(q.id.strip().lower())
        except ValueError:
            return None, "unknown_choice"
        points = [" ".join(p.split()) for p in q.talking_points]
        if not POINTS[0] <= len(points) <= POINTS[1]:
            return None, "wrong_count"
        if any(not p for p in points):
            return None, "empty"
        if any(len(p) > MAX_POINT_CHARS for p in points):
            return None, "too_long"
        if any(_LINK.search(p) for p in points):
            return None, "contains_url"
        if question_id in questions:
            return None, "wrong_questions"
        questions[question_id] = points
    if set(questions) != set(SupervisorQuestionId):
        return None, "wrong_questions"
    return SupervisorBrief(
        checks=readiness_checks(input),
        summary=supervisor_summary(input),
        questions=[
            SupervisorQuestion(id=qid, question=QUESTIONS[qid], talking_points=questions[qid])
            for qid in QUESTIONS
        ],
    ), None
