"""
Tests for the prepare_supervisor_brief skill (Release 0.13, Step 2): readiness
checks and summary (plain code), the talking points (fake LLM).
"""
import copy

import pytest

from app.core.brain.schemas import (
    FunctionalArea,
    FYPDesign,
    ReadinessCheckId,
    ReadinessStatus,
    SupervisorQuestionId,
)
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.prepare_supervisor_brief import PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.assess_feasibility import LLMFeasibilityDraft, check_feasibility_draft
from app.domains.fyp.skills.assess_feasibility.fake import fake_feasibility
from app.domains.fyp.skills.prepare_supervisor_brief import (
    QUESTIONS,
    BriefPhase,
    LLMTalkingPointsDraft,
    PrepareSupervisorBriefSkill,
    SupervisorBriefInput,
    SupervisorBriefRejectedError,
    build_llm_input,
    check_talking_points,
)
from app.domains.fyp.skills.prepare_supervisor_brief.fake import fake_talking_points
from app.domains.fyp.skills.prepare_supervisor_brief.readiness import readiness_checks, supervisor_summary
from tests.unit.test_assess_feasibility_skill import feasibility_input, technical_plan
from tests.unit.test_brain_ai_strategy import ml_strategy
from tests.unit.test_brain_datasets import public
from tests.unit.test_brain_project_definition import make_definition
from tests.unit.test_design_architecture_skill import technology
from tests.unit.test_fyp_design_skills import AREA, BRIEF, GOOD_DESIGN, WS, collect, gateway_and_fake, stored_problem
from tests.unit.test_plan_technology_skill import MODELS


def feasibility_report(**levels):
    input = feasibility_input()
    reply = fake_feasibility({})
    for judgement in reply["judgements"]:
        if judgement["dimension"] in levels:
            judgement["level"] = levels[judgement["dimension"]]
    return check_feasibility_draft(LLMFeasibilityDraft(**reply), input)[0]


def brief_input(evidence=None, **levels) -> SupervisorBriefInput:
    return SupervisorBriefInput(
        workspace_id=WS, industry="Defense", branch="Navy", area=FunctionalArea.model_validate(AREA.model_dump()),
        problem=BRIEF, evidence=stored_problem().evidence if evidence is None else evidence,
        design=FYPDesign(**GOOD_DESIGN), definition=make_definition(), strategy=ml_strategy(), dataset=public(1),
        models=MODELS, technology=technology(), technical=technical_plan(), feasibility=feasibility_report(**levels),
    )


GOOD = fake_talking_points(build_llm_input(brief_input()))


def bad(change) -> dict:
    reply = copy.deepcopy(GOOD)
    change(reply)
    return reply


# ── Checks and summary (plain code) ───────────────────────────────────────────

def test_all_checks_pass_for_a_sound_project():
    checks = readiness_checks(brief_input())
    assert [c.check for c in checks] == list(ReadinessCheckId)
    assert all(c.status == ReadinessStatus.PASS for c in checks)
    assert checks[1].detail == "1 strong source (Tier A or B) support the problem."


def test_weaknesses_need_attention():
    checks = {c.check: c for c in readiness_checks(brief_input(evidence=[], time="concern", novelty="concern"))}
    assert checks[ReadinessCheckId.EVIDENCE_SUPPORTED].status == ReadinessStatus.ATTENTION
    assert checks[ReadinessCheckId.SCOPE_REALISTIC].status == ReadinessStatus.ATTENTION
    assert checks[ReadinessCheckId.CONTRIBUTION_CLEAR].status == ReadinessStatus.ATTENTION
    assert "cut" in checks[ReadinessCheckId.SCOPE_REALISTIC].detail


def test_the_summary_has_the_blueprint_lines_from_approved_decisions():
    summary = supervisor_summary(brief_input())
    assert [i.label for i in summary] == [
        "Project title", "Industry", "Functional area", "Real-world problem", "Evidence", "Proposed solution",
        "Contribution", "Dataset", "AI / ML strategy", "Technology stack", "Architecture", "Evaluation",
        "Feasibility", "Main risks",
    ]
    values = {i.label: i.value for i in summary}
    assert values["Project title"] == GOOD_DESIGN["title"]
    assert values["Dataset"].startswith("Vessel tracks dataset 1 (public dataset")
    assert values["Feasibility"].startswith("High")
    assert " → " in values["Architecture"]


# ── Talking points (LLM) ──────────────────────────────────────────────────────

def test_the_model_sees_the_summary_and_the_ten_questions():
    shown = build_llm_input(brief_input())
    assert [q["id"] for q in shown["questions"]] == [q.value for q in SupervisorQuestionId]
    assert shown["checks_needing_attention"] == []
    assert len(QUESTIONS) == 10


def test_a_good_reply_becomes_the_full_brief():
    brief, reason = check_talking_points(LLMTalkingPointsDraft(**GOOD), brief_input())
    assert reason is None and brief.ready
    assert [q.id for q in brief.questions] == list(SupervisorQuestionId)
    assert brief.questions[0].question == "Why did you choose this problem?"


def test_site_names_are_allowed_but_links_are_not():
    allowed = bad(lambda r: r["questions"][0]["talking_points"].__setitem__(0, "The data comes from kaggle.com."))
    assert check_talking_points(LLMTalkingPointsDraft(**allowed), brief_input())[1] is None
    linked = bad(lambda r: r["questions"][0]["talking_points"].__setitem__(0, "See https://kaggle.com/x"))
    assert check_talking_points(LLMTalkingPointsDraft(**linked), brief_input())[1] == "contains_url"


@pytest.mark.parametrize("change, reason", [
    (lambda r: r["questions"][0].update(id="favourite_colour"), "unknown_choice"),
    (lambda r: r["questions"].pop(), "wrong_questions"),
    (lambda r: r["questions"].append(copy.deepcopy(r["questions"][0])), "wrong_questions"),
    (lambda r: r["questions"][0].update(talking_points=["only one"]), "wrong_count"),
    (lambda r: r["questions"][0]["talking_points"].__setitem__(0, " "), "empty"),
    (lambda r: r["questions"][0]["talking_points"].__setitem__(0, "x" * 300), "too_long"),
])
def test_bad_replies_are_rejected(change, reason):
    brief, rejected = check_talking_points(LLMTalkingPointsDraft(**bad(change)), brief_input())
    assert brief is None and rejected == reason


async def test_the_skill_prepares_checks_and_retries_once():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad(lambda r: r["questions"].pop()), GOOD])
    output, progress = await collect(PrepareSupervisorBriefSkill(gateway), brief_input())
    assert output.rejection_summary == {"wrong_questions": 1} and output.prompt_version == PROMPT_VERSION
    assert progress[0].phase == BriefPhase.CHECKING
    fake.script("fake-model", [bad(lambda r: r["questions"].pop())] * 2)
    with pytest.raises(SupervisorBriefRejectedError):
        await PrepareSupervisorBriefSkill(gateway).execute(brief_input())
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await PrepareSupervisorBriefSkill(gateway).execute(brief_input())


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))
    output = await registry.get("prepare_supervisor_brief").execute(brief_input())
    assert len(output.brief.questions) == 10 and output.brief.ready
