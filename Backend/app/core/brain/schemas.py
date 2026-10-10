"""
Pydantic schemas for the Workspace Brain.

These are the typed data shapes that the rest of the application works with.
The ORM model (models.py) talks to the database; these schemas are what
the repository returns to callers — pure Python objects, no database coupling.
"""
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    """
    All possible stages of the FYP journey.
    Release 0.1 uses only the first three.
    The rest are defined now so the state machine can be extended later
    without changing this file.
    """
    INDUSTRY_SELECTION = "INDUSTRY_SELECTION"
    BRANCH_SELECTION = "BRANCH_SELECTION"
    EVIDENCE_RESEARCH = "EVIDENCE_RESEARCH"
    # Future states — not used in Release 0.1
    PROBLEM_OPTIONS = "PROBLEM_OPTIONS"
    PROBLEM_SELECTED = "PROBLEM_SELECTED"
    AREA_CLASSIFICATION = "AREA_CLASSIFICATION"
    FYP_DESIGN = "FYP_DESIGN"
    APPROVED_FYP = "APPROVED_FYP"          # Release 0.5 ends here: the student approved the FYP design
    SCOPE = "SCOPE"                        # Release 0.6: the student reviews the project definition and scope
    SCOPE_APPROVED = "SCOPE_APPROVED"      # Release 0.6 ends here: the student approved the scope
    AI_STRATEGY = "AI_STRATEGY"            # Release 0.7: the student reviews the AI necessity check and strategy
    AI_STRATEGY_APPROVED = "AI_STRATEGY_APPROVED"  # Release 0.7 ends here: the student approved the AI strategy
    DATASET_DISCOVERY = "DATASET_DISCOVERY"        # Release 0.8: the student reviews the recommended datasets
    DATASET_SELECTED = "DATASET_SELECTED"          # Release 0.8 ends here: the student selected a dataset
    TECHNOLOGY_PLAN = "TECHNOLOGY_PLAN"
    ARCHITECTURE = "ARCHITECTURE"
    EVALUATION = "EVALUATION"
    FEASIBILITY = "FEASIBILITY"
    SUPERVISOR_READINESS = "SUPERVISOR_READINESS"
    PROPOSAL_GENERATION = "PROPOSAL_GENERATION"
    COMPLETE = "COMPLETE"


class DecisionStatus(str, Enum):
    """
    Lifecycle of a single decision inside the Project Brain.
    A decision is not authoritative until it reaches APPROVED.
    """
    CANDIDATE = "candidate"
    RECOMMENDED = "recommended"
    SELECTED = "selected"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


# ── Evidence ──────────────────────────────────────────────────────────────────

class EvidenceTier(str, Enum):
    """
    How strong a source is (product blueprint §11 "Evidence Quality").

    A — Primary evidence: official startup/company website, government
        publication or initiative, peer-reviewed research, official dataset,
        official technical documentation.
    B — Strong secondary evidence: reputable news, established technology or
        industry publication, university research announcement.
    C — Discovery evidence: startup directories, accelerator profiles,
        industry blogs, aggregators, community discussions.
        Useful for discovering ideas; final FYP recommendations should be
        backed by A or B evidence.
    """
    A = "A"
    B = "B"
    C = "C"


class SourceType(str, Enum):
    """What kind of source this is (product blueprint §9 "Evidence Research")."""
    STARTUP = "startup"
    COMPANY = "company"
    GOVERNMENT_INITIATIVE = "government_initiative"
    GOVERNMENT_REPORT = "government_report"
    OFFICIAL_PROGRAM = "official_program"
    NEWS = "news"
    RESEARCH_PAPER = "research_paper"
    UNIVERSITY_RESEARCH = "university_research"
    PUBLIC_CHALLENGE = "public_challenge"
    OPEN_SOURCE = "open_source"
    DATASET = "dataset"
    INDUSTRY_REPORT = "industry_report"
    OTHER = "other"


class ResearchCategory(str, Enum):
    """Which part of the research found this source. Matches the progress steps the student sees."""
    ORGANIZATIONS = "organizations"        # startups and companies
    OFFICIAL_SOURCES = "official_sources"  # government initiatives, reports, programs
    RESEARCH = "research"                  # papers and university research
    DATASETS = "datasets"                  # public datasets (found, not recommended)
    NEWS = "news"                          # industry news (Release 0.4)


class EvidenceSource(BaseModel):
    """
    One normalized piece of evidence, ready to be saved to the Project Brain.

    Every field the product blueprint requires for transparency (§10) is here.
    Text fields must not be empty — evidence without them is rejected.
    """
    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)          # company / agency / university behind it
    source_type: SourceType
    published_date: date | None = None               # not every source has a date
    url: str = Field(pattern=r"^https?://\S+$")
    problem_addressed: str = Field(min_length=1)     # the real problem this source is about
    relevant_insight: str = Field(min_length=1)      # what this source tells us
    why_it_matters: str = Field(min_length=1)        # why it is useful for the student's FYP
    evidence_tier: EvidenceTier
    research_category: ResearchCategory
    query: str = Field(min_length=1)                 # the search that found it (transparency)
    provider: str = Field(min_length=1)              # which search provider, e.g. "mock"


class StoredEvidenceSource(EvidenceSource):
    """An EvidenceSource as read back from the Project Brain, with its storage details."""
    id: str
    workspace_id: str
    research_run_id: str
    retrieved_at: datetime

    model_config = {"from_attributes": True}


# ── Research runs ─────────────────────────────────────────────────────────────

class ResearchStatus(str, Enum):
    """Lifecycle of one research attempt."""
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ResearchRun(BaseModel):
    """One attempt at evidence research for a project."""
    id: str
    workspace_id: str
    status: ResearchStatus
    provider: str
    started_at: datetime
    completed_at: datetime | None = None
    sources_found: int = 0
    high_quality_count: int = 0      # number of Tier A sources
    error: str | None = None

    model_config = {"from_attributes": True}


# ── Problem opportunities (Release 0.3) ───────────────────────────────────────

# The blueprint asks for a small number of strong problems (§13): 3–5.
MAX_PROBLEM_OPTIONS = 5


class ProblemTaskType(str, Enum):
    """The kind of technical task behind a problem. A fixed list, so the UI and later skills can rely on it."""
    ANOMALY_DETECTION = "anomaly_detection"
    CLASSIFICATION = "classification"
    FORECASTING = "forecasting"
    OPTIMIZATION = "optimization"
    NLP = "nlp"
    COMPUTER_VISION = "computer_vision"
    RECOMMENDATION = "recommendation"
    DECISION_SUPPORT = "decision_support"
    OTHER = "other"


class ProblemStatus(str, Enum):
    """A problem option is a candidate until the student selects it."""
    CANDIDATE = "candidate"
    SELECTED = "selected"


class EvidenceStrength(BaseModel):
    """How many cited sources of each tier back a problem. Counted by code, never by the LLM."""
    tier_a: int = Field(default=0, ge=0)
    tier_b: int = Field(default=0, ge=0)
    tier_c: int = Field(default=0, ge=0)


class ProblemEvidenceLink(BaseModel):
    """One piece of stored evidence that supports a problem, and the point it supports."""
    evidence_source_id: str = Field(min_length=1)
    supporting_point: str = Field(min_length=1)


class ProblemCandidate(BaseModel):
    """
    One validated problem opportunity, ready to be saved to the Project Brain.

    This is what the Problem Extraction skill returns. Every problem cites
    evidence that is already stored for the project (by its id), so the
    student can always see where the idea came from (blueprint §10, §14).
    """
    title: str = Field(min_length=1, max_length=120)          # e.g. "Abnormal vessel movement detection"
    real_world_problem: str = Field(min_length=1)            # the pain point organizations face
    observed_solutions: str = Field(min_length=1)            # what organizations are building (not the problem itself)
    technical_problem: str = Field(min_length=1)             # the underlying technical challenge
    task_type: ProblemTaskType
    why_it_matters: str = Field(min_length=1)
    possible_fyp_direction: str = Field(min_length=1)        # a student-sized project idea
    evidence: list[ProblemEvidenceLink] = Field(min_length=1)
    evidence_strength: EvidenceStrength


class ProblemSourceDetail(BaseModel):
    """A cited source as shown with a stored problem ("View sources")."""
    evidence_source_id: str
    supporting_point: str
    title: str
    organization: str
    url: str
    source_type: SourceType
    evidence_tier: EvidenceTier
    published_date: date | None = None


class StoredProblemCandidate(BaseModel):
    """A problem option as read back from the Project Brain, with its cited sources."""
    id: str
    workspace_id: str
    problem_run_id: str
    rank: int                               # 1 = strongest
    status: ProblemStatus
    title: str
    real_world_problem: str
    observed_solutions: str
    technical_problem: str
    task_type: ProblemTaskType
    why_it_matters: str
    possible_fyp_direction: str
    evidence: list[ProblemSourceDetail]
    evidence_strength: EvidenceStrength


class ProblemRunStatus(str, Enum):
    """Lifecycle of one problem-extraction attempt."""
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ProblemRun(BaseModel):
    """One attempt at turning a project's evidence into problem options."""
    id: str
    workspace_id: str
    research_run_id: str                    # the evidence this attempt used
    status: ProblemRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    # Which LLM produced the options (filled in when the run completes)
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    # Quality counts: drafts the LLM returned, options kept, and why the rest were rejected
    candidates_generated: int = 0
    candidates_kept: int = 0
    rejection_summary: dict[str, int] = {}
    error: str | None = None

    model_config = {"from_attributes": True}


# ── From problem to FYP (Release 0.5) ─────────────────────────────────────────

# The student may ask Grey to redesign the FYP this many times (same problem).
# After that only "Approve" remains, so the journey keeps moving (blueprint §45).
MAX_FYP_ADJUSTMENTS = 3


class FunctionalArea(BaseModel):
    """
    Where the chosen problem sits (blueprint §16), decided by Grey, never asked.
    e.g. Defense → Navy → Maritime Surveillance → Vessel Behavior Monitoring.
    """
    functional_area: str = Field(min_length=1, max_length=80)
    specific_area: str = Field(min_length=1, max_length=80)
    explanation: str = Field(min_length=1)          # one plain sentence for the student


class StoredFunctionalArea(FunctionalArea):
    """The project's functional area as read back from the Project Brain."""
    workspace_id: str
    problem_id: str
    provider: str
    model: str
    prompt_version: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FYPAdjustment(str, Enum):
    """
    The controlled ways a student can ask for a redesign (no open brainstorming).
    Grey keeps the same problem every time.
    """
    MAKE_SIMPLER = "make_simpler"
    CHANGE_TARGET_USER = "change_target_user"
    CHANGE_SYSTEM_FOCUS = "change_system_focus"
    REDUCE_COMPLEXITY = "reduce_complexity"


class FYPDesign(BaseModel):
    """
    A student-sized project built from the chosen problem (blueprint §17).

    It describes WHAT the student builds and for whom — never a specific
    dataset, model, API or technology stack (those are later stages).
    """
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1)               # what the student will build
    target_user: str = Field(min_length=1)           # who uses the system
    system_input: str = Field(min_length=1)          # what goes in
    system_output: str = Field(min_length=1)         # what comes out
    main_contribution: str = Field(min_length=1)     # what is new or useful about it
    scope_reduction: str = Field(min_length=1)       # how the real-world problem was made student-sized


class FYPDesignStatus(str, Enum):
    """Each design is a version: the newest is the draft; older ones are superseded; one may be approved."""
    DRAFT = "draft"
    SUPERSEDED = "superseded"
    APPROVED = "approved"


class StoredFYPDesign(FYPDesign):
    """One version of the FYP design as read back from the Project Brain."""
    id: str
    workspace_id: str
    problem_id: str
    run_id: str
    version: int                                     # 1 = first design, 2–4 = redesigns
    status: FYPDesignStatus
    adjustment: FYPAdjustment | None = None          # what the student asked for (None for version 1)
    note: str | None = None                          # the student's optional short note
    created_at: datetime
    approved_at: datetime | None = None

    model_config = {"from_attributes": True}


class FYPDesignRunKind(str, Enum):
    INITIAL = "initial"          # area (if not known yet) + first design
    ADJUSTMENT = "adjustment"    # a redesign the student asked for


class FYPDesignRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class FYPDesignRun(BaseModel):
    """One attempt at designing (or redesigning) the FYP."""
    id: str
    workspace_id: str
    problem_id: str
    kind: FYPDesignRunKind
    adjustment: FYPAdjustment | None = None
    note: str | None = None
    status: FYPDesignRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


# ── Project definition and scope (Release 0.6) ────────────────────────────────

# Scope sizes Grey asks for, and the limits the student's own changes must keep.
MIN_CORE_FEATURES = 2           # a project needs at least two must-have features
MAX_CORE_FEATURES = 8           # more than this is no longer one student's project


class ProblemDefinition(BaseModel):
    """A precise definition of the approved FYP's problem (blueprint §19)."""
    problem_statement: str = Field(min_length=1)     # what problem exists
    affected_users: str = Field(min_length=1)        # who experiences it
    why_it_matters: str = Field(min_length=1)
    current_solutions: str = Field(min_length=1)     # what currently exists
    gap: str = Field(min_length=1)                   # what gap remains
    what_will_be_built: str = Field(min_length=1)    # what exactly the student will build


class SolutionModule(BaseModel):
    """One main part of the proposed system, e.g. "Data upload — lets the analyst add records"."""
    name: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1)


class ProposedSolution(BaseModel):
    """
    What the final system will look like (blueprint §21). The target user,
    input and output come from the approved FYP design, so they are not
    repeated here. Whether and how AI is used is decided in a later stage
    (the AI necessity check) — never here.
    """
    system_purpose: str = Field(min_length=1)
    modules: list[SolutionModule] = Field(min_length=2, max_length=6)
    workflow_steps: list[str] = Field(min_length=3, max_length=8)   # the expected workflow, in order


class ScopeKind(str, Enum):
    """Where a feature sits in the project scope (blueprint §20)."""
    CORE = "core"                    # must be implemented
    OPTIONAL = "optional"            # may be added if time remains
    OUT_OF_SCOPE = "out_of_scope"    # intentionally excluded


class ScopeItem(BaseModel):
    """One feature in the scope."""
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1)
    kind: ScopeKind


class ProjectDefinition(BaseModel):
    """
    The problem definition, scope and proposed solution for the approved FYP
    (blueprint §19–21), as checked by Grey and ready to be saved.
    """
    problem_definition: ProblemDefinition
    proposed_solution: ProposedSolution
    scope: list[ScopeItem] = Field(min_length=1)


class ProjectDefinitionStatus(str, Enum):
    DRAFT = "draft"          # the student is reviewing it (and may move scope items)
    APPROVED = "approved"    # the student approved the scope


class StoredScopeItem(ScopeItem):
    """A scope item as read back from the Project Brain."""
    id: str
    position: int            # order inside its list (core / optional / out of scope)

    model_config = {"from_attributes": True}


class StoredProjectDefinition(BaseModel):
    """The project definition as read back from the Project Brain, with its scope items."""
    id: str
    workspace_id: str
    design_id: str                       # the approved FYP design it was written for
    run_id: str
    status: ProjectDefinitionStatus
    problem_definition: ProblemDefinition
    proposed_solution: ProposedSolution
    scope: list[StoredScopeItem]         # core first, then optional, then out of scope
    scope_changes: int = 0               # how many times the student moved an item
    created_at: datetime
    approved_at: datetime | None = None


class ProjectDefinitionRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ProjectDefinitionRun(BaseModel):
    """One attempt at writing the project definition."""
    id: str
    workspace_id: str
    design_id: str
    status: ProjectDefinitionRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


# ── AI necessity check and AI / ML strategy (Release 0.7) ─────────────────────

# How many times the student can ask Grey to check again with a preference.
MAX_AI_STRATEGY_RECHECKS = 2


class AINecessity(str, Enum):
    """Does this project actually need AI? (blueprint §22). Grey never forces AI in."""
    AI_NECESSARY = "ai_necessary"          # AI is necessary
    AI_OPTIONAL = "ai_optional"            # AI is useful but optional
    TRADITIONAL_ML = "traditional_ml"      # traditional machine learning is sufficient
    RULE_BASED = "rule_based"              # a rule-based approach is better
    OPTIMIZATION = "optimization"          # optimization is more appropriate
    EXISTING_MODEL = "existing_model"      # an existing model or API is sufficient
    NOT_REQUIRED = "not_required"          # AI is not required


class AITaskType(str, Enum):
    """The technical AI task, when AI is used (blueprint §23)."""
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    FORECASTING = "forecasting"
    ANOMALY_DETECTION = "anomaly_detection"
    COMPUTER_VISION = "computer_vision"
    OBJECT_DETECTION = "object_detection"
    NLP = "nlp"
    RECOMMENDATION = "recommendation"
    CLUSTERING = "clustering"
    TIME_SERIES_ANALYSIS = "time_series_analysis"
    RETRIEVAL = "retrieval"
    GENERATIVE_AI = "generative_ai"


class AIApproach(str, Enum):
    """How the AI part is built (blueprint §23): one primary approach, maybe one fallback."""
    TRAIN_MODEL = "train_model"
    FINE_TUNE = "fine_tune"                # fine-tune an existing model
    PRETRAINED_MODEL = "pretrained_model"  # use a pretrained model as it is
    USE_API = "use_api"
    HYBRID = "hybrid"


class AIStrategyPreference(str, Enum):
    """
    The controlled ways a student can ask Grey to check again. There is
    deliberately no "use more AI" option: Grey never forces AI into a project.
    """
    WITHOUT_AI = "without_ai"              # "Can I do this without AI?"
    EXISTING_MODEL = "existing_model"      # use a ready-made model or service instead of building one


class StrategyChoice(BaseModel):
    """One implementation approach and why it fits."""
    approach: AIApproach
    reason: str = Field(min_length=1)


class AIStrategy(BaseModel):
    """
    The AI necessity check and, when AI is used, the AI / ML strategy.
    The consistency rules (e.g. no task type when AI isn't used) live in
    ai_strategy_rules.py. Never names a specific dataset, model or API —
    those are chosen in later stages.
    """
    necessity: AINecessity
    necessity_reason: str = Field(min_length=1)       # why this verdict, for this project
    without_ai: str = Field(min_length=1)             # how the project could work without AI
    ai_component: str | None = None                   # which part uses AI (None when AI isn't used)
    non_ai_components: list[str] = Field(min_length=1, max_length=6)
    task_type: AITaskType | None = None
    primary_strategy: StrategyChoice | None = None
    fallback_strategy: StrategyChoice | None = None


class AIStrategyStatus(str, Enum):
    DRAFT = "draft"          # the student is reviewing it (and may ask Grey to check again)
    APPROVED = "approved"


class StoredAIStrategy(BaseModel):
    """The AI strategy as read back from the Project Brain."""
    id: str
    workspace_id: str
    definition_id: str                       # the approved project definition it was checked against
    run_id: str
    status: AIStrategyStatus
    strategy: AIStrategy
    rechecks_used: int = 0
    preference: AIStrategyPreference | None = None   # what the student asked for in the latest re-check
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None


class AIStrategyRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class AIStrategyRun(BaseModel):
    """One attempt at the AI necessity check (the first one, or a re-check)."""
    id: str
    workspace_id: str
    definition_id: str
    preference: AIStrategyPreference | None = None   # None for the first check
    status: AIStrategyRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


# ── Dataset discovery (Release 0.8) ───────────────────────────────────────────

# How many times the student can ask Grey to search again with a preference.
MAX_DATASET_RESEARCHES = 2

# What Grey writes when a search snippet doesn't say (size, labels, license…).
NOT_STATED = "Not stated — check the dataset page"


class DatasetKind(str, Enum):
    """Where the data comes from (blueprint §24)."""
    PUBLIC = "public"                          # a public dataset Grey found online
    SYNTHETIC = "synthetic"                    # data the student generates
    STUDENT_COLLECTED = "student_collected"    # data the student collects (surveys, sensors, logs…)


class DatasetFit(str, Enum):
    """Does the dataset actually fit the chosen problem? (blueprint §25)"""
    GOOD = "good"          # fits the problem as it is
    PARTIAL = "partial"    # fits only after extra preparation, or with clear limits


class DatasetChoice(str, Enum):
    """Which of the two recommended datasets the student selects."""
    PRIMARY = "primary"
    ALTERNATIVE = "alternative"


class DatasetPreference(str, Enum):
    """The controlled ways a student can ask Grey to search again (no free text)."""
    OTHER_OPTIONS = "other_options"    # "Find other options"
    OWN_DATA = "own_data"              # "I'd rather create or collect my own data"


class DatasetCandidate(BaseModel):
    """
    One dataset page the search found. Kept with the run, so Grey can only
    recommend public datasets it really found (never invented ones).
    """
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://\S+$")
    snippet: str = Field(min_length=1)
    publisher: str | None = None
    query: str = Field(min_length=1)     # the search that found it (transparency)
    provider: str = Field(min_length=1)  # which search provider, e.g. "mock"


class DatasetOption(BaseModel):
    """
    One recommended dataset with the information blueprint §25 asks for.
    Facts a search snippet doesn't give (size, license…) say NOT_STATED
    instead of guessing. The rules about links live in dataset_rules.py.
    """
    kind: DatasetKind
    name: str = Field(min_length=1)
    source: str = Field(min_length=1)               # site or organization; "You" for own data
    url: str | None = Field(default=None, pattern=r"^https?://\S+$")   # only for public datasets
    size: str = Field(min_length=1)
    main_features: list[str] = Field(min_length=1, max_length=8)
    labels: str = Field(min_length=1)
    license: str = Field(min_length=1)
    relevance: str = Field(min_length=1)            # why it fits THIS problem
    preprocessing: list[str] = Field(min_length=1, max_length=6)
    limitations: list[str] = Field(min_length=1, max_length=5)
    fit: DatasetFit
    how_to_get: str | None = None                   # how the student creates or collects own data


class DatasetPlan(BaseModel):
    """Grey's recommendation: one primary dataset and one alternative (blueprint §24)."""
    purpose: str = Field(min_length=1)    # what the data is for in this project (train, test, demo…)
    primary: DatasetOption
    alternative: DatasetOption


class DatasetPlanStatus(str, Enum):
    DRAFT = "draft"          # the student is reviewing it (and may ask Grey to search again)
    SELECTED = "selected"    # the student selected one of the two datasets


class StoredDatasetPlan(BaseModel):
    """The dataset recommendation as read back from the Project Brain."""
    id: str
    workspace_id: str
    strategy_id: str                          # the approved AI strategy it was made for
    run_id: str
    status: DatasetPlanStatus
    plan: DatasetPlan
    researches_used: int = 0
    preference: DatasetPreference | None = None   # what the student asked for in the latest re-search
    selected: DatasetChoice | None = None         # set when the student selects a dataset
    created_at: datetime
    updated_at: datetime
    selected_at: datetime | None = None

    @property
    def selected_option(self) -> DatasetOption | None:
        if self.selected is None:
            return None
        return self.plan.primary if self.selected == DatasetChoice.PRIMARY else self.plan.alternative


class DatasetRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class DatasetRun(BaseModel):
    """One dataset search (the first one, or a re-search). The pages it found are read separately."""
    id: str
    workspace_id: str
    strategy_id: str
    preference: DatasetPreference | None = None   # None for the first search
    status: DatasetRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    searches_used: int = 0
    candidates_found: int = 0
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


# ── Snapshot ──────────────────────────────────────────────────────────────────

class WorkspaceBrainSnapshot(BaseModel):
    """
    A read-only view of the current Project Brain state.
    This is what callers receive from WorkspaceBrainRepository.get_snapshot().
    """
    workspace_id: str
    workflow_state: WorkflowState

    industry: str | None = None
    industry_status: DecisionStatus | None = None

    branch: str | None = None
    branch_status: DecisionStatus | None = None

    # The latest research attempt (None until research has started).
    # The evidence itself is read separately with list_evidence().
    research: ResearchRun | None = None

    # The latest problem-extraction attempt and the student's chosen problem
    # (Release 0.3). The options are read separately with list_problem_candidates().
    problem_run: ProblemRun | None = None
    selected_problem: StoredProblemCandidate | None = None

    # From problem to FYP (Release 0.5): where the problem sits, the current
    # design (the draft, or the approved one), how many redesigns were used,
    # and the latest design attempt.
    functional_area: StoredFunctionalArea | None = None
    fyp_design: StoredFYPDesign | None = None
    fyp_adjustments_used: int = 0
    fyp_design_run: FYPDesignRun | None = None

    # Project definition and scope (Release 0.6): the draft or approved
    # definition, and the latest attempt at writing it.
    project_definition: StoredProjectDefinition | None = None
    project_definition_run: ProjectDefinitionRun | None = None

    # AI necessity check and strategy (Release 0.7): the draft or approved
    # strategy, and the latest attempt.
    ai_strategy: StoredAIStrategy | None = None
    ai_strategy_run: AIStrategyRun | None = None

    # Dataset discovery (Release 0.8): the draft or selected recommendation,
    # and the latest search.
    dataset_plan: StoredDatasetPlan | None = None
    dataset_run: DatasetRun | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
