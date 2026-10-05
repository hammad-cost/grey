"""
Tests for the Problem Extraction skill (Release 0.3, Step 3).

Covers the three parts separately, then together:
  context.py    — what the language model is (and is not) shown
  validation.py — how invented, ungrounded or unsafe drafts are rejected
  skill.py      — the flow: read evidence → gateway → validate → retry → result

The model is always FakeLLMProvider (scripted per test). No network, no keys.
"""
from collections import Counter
from datetime import date, datetime, timezone

import pytest

from app.core.brain.schemas import (
    EvidenceTier,
    ProblemTaskType,
    ResearchCategory,
    SourceType,
    StoredEvidenceSource,
)
from app.core.config.settings import Settings
from app.core.llm import STRUCTURED_REASONING, LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.problem_extraction import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.problem_extraction import (
    LLMProblemDraft,
    NotEnoughEvidenceError,
    ProblemExtractionInput,
    ProblemExtractionSkill,
    ProblemPhase,
    TooFewProblemsError,
    build_context,
)
from app.domains.fyp.skills.problem_extraction.context import MAX_CONTEXT_TOKENS, MAX_TEXT_CHARS
from app.domains.fyp.skills.problem_extraction.fake import install_fake_answers
from app.domains.fyp.skills.problem_extraction.validation import check_draft, organization_names, select_candidates
from app.domains.fyp.skills.research_evidence import ResearchEvidenceSkill
from app.domains.fyp.skills.research_evidence.schemas import ResearchEvidenceInput

WS = "ws-navy"


# ── Helpers ───────────────────────────────────────────────────────────────────

def source(n: int, tier: EvidenceTier = EvidenceTier.A, org: str | None = None, **overrides) -> StoredEvidenceSource:
    """A stored evidence source with distinctive, checkable wording."""
    fields = dict(
        id=f"ev-{n}",
        workspace_id=WS,
        research_run_id="run-1",
        retrieved_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        title=f"Maritime monitoring report {n}",
        organization=org or f"Harbor Systems {n} (sample company)",
        source_type=SourceType.COMPANY,
        published_date=date(2026, 1, n),
        url=f"https://source-{n}.example/page",
        problem_addressed=f"Operators review vessel tracking data manually, so suspicious movements number{n} are spotted late.",
        relevant_insight=f"Automated anomaly alerts reduced manual review workload in pilot number{n}.",
        why_it_matters="An organization is investing in this problem.",
        evidence_tier=tier,
        research_category=ResearchCategory.ORGANIZATIONS,
        query=f"secret query {n}",
        provider="mock",
    )
    fields.update(overrides)
    return StoredEvidenceSource(**fields)


EVIDENCE = [source(1), source(2), source(3, EvidenceTier.B), source(4, EvidenceTier.C)]
SOURCES_BY_REF = {f"E{i}": s for i, s in enumerate(EVIDENCE, start=1)}


def citation(ref: str, n: int | None = None) -> dict:
    """A grounded citation: reuses the source's own wording."""
    n = n if n is not None else int(ref[1:])
    return {"ref": ref, "supporting_point": f"Operators review vessel tracking data manually; suspicious movements number{n} spotted late."}


def draft(title: str = "Detecting unusual vessel movements", cites=("E1",), **overrides) -> dict:
    fields = dict(
        title=title,
        real_world_problem="Operators cannot review all vessel movements by hand.",
        observed_solutions="Companies sell automated maritime monitoring platforms.",
        technical_problem="Anomaly detection on vessel trajectory time series.",
        task_type="anomaly_detection",
        why_it_matters="Earlier detection improves maritime safety.",
        possible_fyp_direction="Build a model that flags unusual tracks in public AIS data.",
        evidence=[citation(ref) for ref in cites],
    )
    fields.update(overrides)
    return fields


def check(raw: dict, rejections: Counter | None = None):
    rejections = rejections if rejections is not None else Counter()
    return check_draft(LLMProblemDraft(**raw), SOURCES_BY_REF, organization_names(EVIDENCE), rejections)


def select(raws: list[dict]) -> tuple[list, Counter]:
    rejections: Counter = Counter()
    kept = select_candidates([LLMProblemDraft(**r) for r in raws], SOURCES_BY_REF, rejections)
    return kept, rejections


THREE_GOOD = [
    draft("Detecting unusual vessel movements", ("E1",)),
    draft("Forecasting port congestion", ("E2",), task_type="forecasting"),
    draft("Classifying ships from imagery", ("E3",), task_type="computer_vision"),
]


class RecordingReader:
    """An EvidenceReader stand-in. It has no write methods at all."""
    def __init__(self, evidence: list[StoredEvidenceSource]) -> None:
        self.evidence = evidence
        self.calls: list[str] = []

    async def list_evidence(self, workspace_id: str) -> list[StoredEvidenceSource]:
        self.calls.append(workspace_id)
        return self.evidence


def fake_gateway():
    """A fake-mode gateway and its fake provider, ready to be scripted."""
    gateway = build_llm_gateway(Settings(_env_file=None))
    return gateway, gateway.router.provider("fake")


INPUT = ProblemExtractionInput(workspace_id=WS, industry="Defense", branch="Navy")


# ── Context: what the model sees ──────────────────────────────────────────────

def test_context_lists_sources_strongest_first_with_short_refs():
    context = build_context("Defense", "Navy", list(reversed(EVIDENCE)))
    entries = context.llm_input["evidence"]

    assert [e["ref"] for e in entries] == ["E1", "E2", "E3", "E4"]
    assert [e["tier"] for e in entries] == ["A", "A", "B", "C"]
    assert context.sources_by_ref["E4"].id == "ev-4"
    assert context.llm_input["industry"] == "Defense" and context.llm_input["branch"] == "Navy"


def test_context_never_contains_urls_ids_queries_or_providers():
    text = str(build_context("Defense", "Navy", EVIDENCE).llm_input)
    for secret in ("https://", ".example", "ev-1", "run-1", "secret query", "mock"):
        assert secret not in text


def test_context_shortens_long_texts():
    long = source(1, problem_addressed="word " * 400)
    context = build_context("Defense", "Navy", [long, source(2), source(3)])
    assert len(context.llm_input["evidence"][0]["problem_addressed"]) <= MAX_TEXT_CHARS


def test_context_drops_weakest_sources_to_fit_the_budget():
    many = [source(n, EvidenceTier.A if n < 10 else EvidenceTier.C,
                   relevant_insight="detail " * 40) for n in range(1, 21)]
    context = build_context("Defense", "Navy", many)

    assert len(str(context.llm_input)) // 4 <= MAX_CONTEXT_TOKENS * 1.1
    assert 3 <= len(context.sources_by_ref) < 20
    assert all(s.evidence_tier == EvidenceTier.A for s in list(context.sources_by_ref.values())[:5])


def test_too_few_sources_is_not_enough_evidence():
    with pytest.raises(NotEnoughEvidenceError):
        build_context("Defense", "Navy", [source(1), source(2)])


def test_only_tier_c_sources_is_not_enough_evidence():
    with pytest.raises(NotEnoughEvidenceError):
        build_context("Defense", "Navy", [source(n, EvidenceTier.C) for n in range(1, 5)])


# ── Validation: one draft ─────────────────────────────────────────────────────

def test_valid_draft_becomes_a_candidate_citing_stored_evidence():
    candidate = check(draft(cites=("E1", "E3")))

    assert candidate.title == "Detecting unusual vessel movements"
    assert candidate.task_type == ProblemTaskType.ANOMALY_DETECTION
    assert [l.evidence_source_id for l in candidate.evidence] == ["ev-1", "ev-3"]
    assert (candidate.evidence_strength.tier_a, candidate.evidence_strength.tier_b) == (1, 1)


def test_refs_are_matched_case_insensitively():
    assert check(draft(evidence=[{**citation("E1"), "ref": " e1 "}])) is not None


def test_invented_ref_is_dropped_and_counted():
    rejections = Counter()
    candidate = check(draft(evidence=[citation("E1"), citation("E99", 1)]), rejections)

    assert [l.evidence_source_id for l in candidate.evidence] == ["ev-1"]
    assert rejections["unknown_ref"] == 1


def test_draft_with_only_invented_refs_is_rejected():
    rejections = Counter()
    assert check(draft(evidence=[citation("E77", 1), citation("E88", 2)]), rejections) is None
    assert rejections == Counter({"unknown_ref": 2, "no_valid_evidence": 1})


def test_ungrounded_supporting_point_is_dropped():
    made_up = {"ref": "E1", "supporting_point": "Satellite budgets doubled after a congressional hearing last year."}
    rejections = Counter()
    assert check(draft(evidence=[made_up]), rejections) is None
    assert rejections["ungrounded"] == 1


def test_same_source_cited_twice_is_kept_once():
    candidate = check(draft(cites=("E1", "E1", "E2")))
    assert [l.evidence_source_id for l in candidate.evidence] == ["ev-1", "ev-2"]


def test_tier_c_only_problem_is_rejected():
    rejections = Counter()
    assert check(draft(cites=("E4",)), rejections) is None
    assert rejections["only_tier_c"] == 1


@pytest.mark.parametrize("field", ["title", "possible_fyp_direction"])
def test_naming_an_organization_is_rejected(field):
    rejections = Counter()
    assert check(draft(**{field: "Rebuild the Harbor Systems 2 platform"}), rejections) is None
    assert rejections["names_organization"] == 1


def test_organization_may_be_mentioned_when_describing_solutions():
    assert check(draft(observed_solutions="Harbor Systems 1 sells a monitoring platform.")) is not None


@pytest.mark.parametrize("text", ["See https://navy.mil/report", "Details at www.example.org", "From data.gov"])
def test_urls_are_rejected(text):
    rejections = Counter()
    assert check(draft(why_it_matters=text), rejections) is None
    assert rejections["contains_url"] == 1


def test_overly_long_fields_are_rejected():
    rejections = Counter()
    assert check(draft(technical_problem="x " * 400), rejections) is None
    assert rejections["too_long"] == 1


# ── Validation: across drafts ─────────────────────────────────────────────────

def test_duplicate_titles_are_merged_with_their_sources():
    kept, rejections = select([
        draft("Detecting unusual vessel movements", ("E1",)),
        draft("Detecting unusual vessel movement patterns", ("E2",)),
        *THREE_GOOD[1:],
    ])
    titles = [c.title for c in kept]
    assert len(kept) == 3
    assert titles.count("Detecting unusual vessel movements") + titles.count("Detecting unusual vessel movement patterns") == 1
    merged = next(c for c in kept if "unusual" in c.title)
    assert {l.evidence_source_id for l in merged.evidence} == {"ev-1", "ev-2"}
    assert rejections["duplicate"] == 1


def test_drafts_citing_the_same_sources_are_merged():
    kept, rejections = select([
        draft("Spotting suspicious ships", ("E1", "E2")),
        draft("Tracking risky vessels early", ("E1", "E2")),
    ])
    assert len(kept) == 1
    assert rejections["duplicate"] == 1


def test_strongest_evidence_ranks_first():
    kept, _ = select([
        draft("Weak but valid problem", ("E3",)),
        draft("Strong problem with two primaries", ("E1", "E2"), task_type="forecasting"),
    ])
    assert [c.title for c in kept] == ["Strong problem with two primaries", "Weak but valid problem"]


def test_problems_sharing_one_source_are_not_merged():
    """Different problems often cite the same strong source; that alone isn't a duplicate."""
    kept, rejections = select([
        draft("Spotting suspicious ships", ("E1", "E2")),
        draft("Forecasting port congestion", ("E2",), task_type="forecasting"),
    ])
    assert len(kept) == 2
    assert rejections["duplicate"] == 0


def test_at_most_five_problems_are_kept():
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]
    kept, rejections = select([draft(f"Distinct {word} problem", (f"E{1 + i % 3}",)) for i, word in enumerate(words)])
    assert len(kept) == 5
    assert rejections["duplicate"] == 0


# ── The skill ─────────────────────────────────────────────────────────────────

async def test_skill_returns_validated_candidates_and_llm_details():
    gateway, fake = fake_gateway()
    fake.script("fake-model", [{"problems": THREE_GOOD}])
    reader = RecordingReader(EVIDENCE)

    output = await ProblemExtractionSkill(gateway).execute(INPUT, reader)

    assert len(output.candidates) == 3
    assert all(l.evidence_source_id.startswith("ev-") for c in output.candidates for l in c.evidence)
    assert (output.provider, output.model, output.prompt_version) == ("fake", "fake-model", PROMPT_VERSION)
    assert output.candidates_generated == 3
    assert reader.calls == [WS]


async def test_skill_calls_the_gateway_with_the_structured_reasoning_profile():
    gateway, fake = fake_gateway()
    fake.script("fake-model", [{"problems": THREE_GOOD}])
    await ProblemExtractionSkill(gateway).execute(INPUT, RecordingReader(EVIDENCE))

    [call] = fake.calls
    assert call.instructions == INSTRUCTIONS
    assert call.schema_name == "LLMProblemDrafts"
    assert "https://" not in call.input_json
    assert gateway.router.profile(STRUCTURED_REASONING)          # the profile the skill names exists


async def test_skill_reports_safe_progress():
    gateway, fake = fake_gateway()
    fake.script("fake-model", [{"problems": THREE_GOOD}])
    seen = []

    async def on_progress(progress):
        seen.append(progress.phase)

    await ProblemExtractionSkill(gateway).execute(INPUT, RecordingReader(EVIDENCE), on_progress)
    assert seen == [ProblemPhase.REVIEWING_EVIDENCE, ProblemPhase.IDENTIFYING_PROBLEMS, ProblemPhase.CHECKING_PROBLEMS]


async def test_not_enough_evidence_never_calls_the_model():
    gateway, fake = fake_gateway()
    with pytest.raises(NotEnoughEvidenceError):
        await ProblemExtractionSkill(gateway).execute(INPUT, RecordingReader(EVIDENCE[:2]))
    assert fake.calls == []


async def test_too_few_valid_problems_triggers_one_retry_with_feedback():
    gateway, fake = fake_gateway()
    invented = draft("Invented problem", evidence=[citation("E42", 1)])
    fake.script("fake-model", [{"problems": [THREE_GOOD[0], invented]}, {"problems": THREE_GOOD}])

    output = await ProblemExtractionSkill(gateway).execute(INPUT, RecordingReader(EVIDENCE))

    assert len(output.candidates) == 3
    assert len(fake.calls) == 2
    assert "feedback_from_previous_attempt" not in fake.calls[0].input_json
    assert "unknown_ref" in fake.calls[1].input_json
    assert output.candidates_generated == 5
    assert output.rejection_summary["unknown_ref"] == 1


async def test_still_too_few_after_retry_fails_without_padding():
    gateway, fake = fake_gateway()
    hallucinated = {"problems": [draft(f"Problem {i}", evidence=[citation(f"E{50 + i}", 1)]) for i in range(5)]}
    fake.script("fake-model", [hallucinated, hallucinated])

    with pytest.raises(TooFewProblemsError) as caught:
        await ProblemExtractionSkill(gateway).execute(INPUT, RecordingReader(EVIDENCE))
    assert len(fake.calls) == 2
    assert caught.value.rejection_summary["no_valid_evidence"] == 10


async def test_gateway_failures_are_passed_up_to_the_workflow():
    gateway, fake = fake_gateway()
    fake.script("fake-model", [LLMUnavailable("all models down")])
    with pytest.raises(LLMUnavailable):
        await ProblemExtractionSkill(gateway).execute(INPUT, RecordingReader(EVIDENCE))


# ── Registration and fake mode ────────────────────────────────────────────────

def test_skill_is_registered_only_when_a_gateway_is_given():
    without, with_llm = SkillRegistry(), SkillRegistry()
    register_fyp_skills(without, MockSearchProvider())
    register_fyp_skills(with_llm, MockSearchProvider(), fake_gateway()[0])

    assert "problem_extraction" not in without
    assert "problem_extraction" in with_llm


async def test_fake_mode_produces_valid_problems_from_real_sample_evidence():
    """End to end in fake mode: mock research evidence → skill → 3–5 validated problems."""
    research = await ResearchEvidenceSkill(MockSearchProvider()).execute(
        ResearchEvidenceInput(workspace_id=WS, industry="Defense", branch="Navy")
    )
    stored = [
        StoredEvidenceSource(id=f"ev-{i}", workspace_id=WS, research_run_id="run-1",
                             retrieved_at=datetime.now(timezone.utc), **s.model_dump())
        for i, s in enumerate(research.sources)
    ]
    gateway, _ = fake_gateway()
    install_fake_answers(gateway)

    output = await ProblemExtractionSkill(gateway).execute(INPUT, RecordingReader(stored))

    assert 3 <= len(output.candidates) <= 5
    assert output.rejection_summary == {}
