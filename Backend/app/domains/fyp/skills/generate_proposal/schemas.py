"""
Types for the generate_proposal skill (Release 0.14).

  Grey-facing  — GenerateProposalInput / Output: every approved decision (the same
                 bundle the supervisor brief uses), plus a section to rewrite.
  LLM-facing   — LLMSectionsDraft: only the narrative sections asked for in one call.
  Progress     — ProposalPhase / ProposalProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel

from app.core.brain.schemas import Proposal, ProposalSectionId
from app.domains.fyp.skills.prepare_supervisor_brief import SupervisorBriefInput

# The model writes the narrative in three small calls (blueprint §36: "from the Project
# Brain rather than from one large prompt"); every other section is built in code.
SECTION_GROUPS: list[list[ProposalSectionId]] = [
    [ProposalSectionId.INTRODUCTION, ProposalSectionId.BACKGROUND, ProposalSectionId.PROBLEM_STATEMENT,
     ProposalSectionId.MOTIVATION, ProposalSectionId.REAL_WORLD_EVIDENCE],
    [ProposalSectionId.PROPOSED_SOLUTION, ProposalSectionId.AIM, ProposalSectionId.OBJECTIVES,
     ProposalSectionId.METHODOLOGY],
    [ProposalSectionId.EXPECTED_OUTCOMES, ProposalSectionId.LIMITATIONS],
]

SECTION_TITLES = {
    ProposalSectionId.PROJECT_TITLE: "Project Title",
    ProposalSectionId.INTRODUCTION: "Introduction",
    ProposalSectionId.BACKGROUND: "Background",
    ProposalSectionId.PROBLEM_STATEMENT: "Problem Statement",
    ProposalSectionId.MOTIVATION: "Motivation",
    ProposalSectionId.REAL_WORLD_EVIDENCE: "Real-World Evidence",
    ProposalSectionId.PROPOSED_SOLUTION: "Proposed Solution",
    ProposalSectionId.AIM: "Aim",
    ProposalSectionId.OBJECTIVES: "Objectives",
    ProposalSectionId.SCOPE: "Scope",
    ProposalSectionId.FUNCTIONAL_REQUIREMENTS: "Functional Requirements",
    ProposalSectionId.METHODOLOGY: "Methodology",
    ProposalSectionId.DATASET: "Dataset",
    ProposalSectionId.AI_ML_APPROACH: "AI / ML Approach",
    ProposalSectionId.TECHNOLOGY_STACK: "Technology Stack",
    ProposalSectionId.SYSTEM_ARCHITECTURE: "System Architecture",
    ProposalSectionId.HARDWARE_REQUIREMENTS: "Hardware Requirements",
    ProposalSectionId.EVALUATION_PLAN: "Evaluation Plan",
    ProposalSectionId.EXPECTED_OUTCOMES: "Expected Outcomes",
    ProposalSectionId.RISKS: "Risks",
    ProposalSectionId.LIMITATIONS: "Limitations",
    ProposalSectionId.TIMELINE: "Timeline",
    ProposalSectionId.REFERENCES: "References",
}

# Traceability (blueprint §37): where each model-written section comes from.
MODEL_SECTION_SOURCES = {
    ProposalSectionId.INTRODUCTION: ["Chosen problem", "Approved FYP design"],
    ProposalSectionId.BACKGROUND: ["Chosen problem", "Verified evidence sources"],
    ProposalSectionId.PROBLEM_STATEMENT: ["Approved problem definition", "Verified evidence sources"],
    ProposalSectionId.MOTIVATION: ["Approved problem definition", "Chosen problem"],
    ProposalSectionId.REAL_WORLD_EVIDENCE: ["Verified evidence sources"],
    ProposalSectionId.PROPOSED_SOLUTION: ["Approved FYP design", "Approved scope"],
    ProposalSectionId.AIM: ["Approved FYP design"],
    ProposalSectionId.OBJECTIVES: ["Approved scope"],
    ProposalSectionId.METHODOLOGY: ["Approved AI strategy", "Selected dataset", "Approved technical plan"],
    ProposalSectionId.EXPECTED_OUTCOMES: ["Approved FYP design", "Approved evaluation plan"],
    ProposalSectionId.LIMITATIONS: ["Selected dataset", "Accepted feasibility report", "Approved scope"],
}


class GenerateProposalInput(BaseModel):
    """Every approved decision, plus — for a rewrite — the section and the current proposal."""
    decisions: SupervisorBriefInput
    rewrite_section: ProposalSectionId | None = None
    previous: Proposal | None = None


class GenerateProposalOutput(BaseModel):
    proposal: Proposal
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}


class LLMSectionDraft(BaseModel):
    id: str
    paragraphs: list[str]
    items: list[str]          # only "objectives" uses items; [] elsewhere


class LLMSectionsDraft(BaseModel):
    sections: list[LLMSectionDraft]


class ProposalPhase(str, Enum):
    BUILDING = "building_sections"
    WRITING = "writing_sections"
    CHECKING = "checking_proposal"


class ProposalProgress(BaseModel):
    phase: ProposalPhase
    label: str


ProposalProgressCallback = Callable[[ProposalProgress], Awaitable[None]]
