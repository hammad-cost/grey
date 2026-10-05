"""
ResearchEvidenceSkill — Grey's first real skill.

Given an industry and branch, it searches for real-world evidence, turns each
result into a normalized Project Brain EvidenceSource, and returns them
strongest first.

What the skill does:
  - runs the research plan (queries.py) through a SearchProvider
  - classifies each result's source type and evidence tier (classification.py)
  - fills every evidence field the product blueprint requires
  - removes duplicate URLs and keeps the best sources per category
  - reports safe progress (what it is doing, how many sources) as it goes

What the skill does NOT do (by design):
  - save anything — the workflow/repository saves the result
  - decide the next workflow stage
  - know which screen the student is looking at
  - call a specific search vendor — it only knows the SearchProvider interface
  - call an LLM (not needed in Release 0.2)
"""
from collections import Counter
from datetime import date
from typing import Awaitable, Callable

from app.core.brain.schemas import EvidenceSource, EvidenceTier, ResearchCategory
from app.core.skills.base import Skill, SkillMetadata
from app.core.tools.search import SearchProvider, SearchResult
from app.domains.fyp.skills.research_evidence.classification import (
    classify,
    organization_name,
    split_snippet,
    why_it_matters,
)
from app.domains.fyp.skills.research_evidence.queries import EVALUATING_LABEL, build_research_plan
from app.domains.fyp.skills.research_evidence.schemas import (
    ResearchEvidenceInput,
    ResearchEvidenceOutput,
    ResearchPhase,
    ResearchProgress,
    ResearchSummary,
)

# The function the caller passes in to receive progress updates.
ProgressCallback = Callable[[ResearchProgress], Awaitable[None]]


def _strongest_first(source: EvidenceSource) -> tuple:
    """Sort key: Tier A → B → C, then newest first (undated last), then title."""
    newest_first = -(source.published_date or date.min).toordinal()
    return (source.evidence_tier.value, newest_first, source.title)


class ResearchEvidenceSkill(Skill):
    metadata = SkillMetadata(
        name="research_evidence",
        description=(
            "Research real-world evidence (organizations, official sources, research, "
            "datasets) for an industry and branch, and return normalized, tiered evidence."
        ),
        version="0.2.0",
    )

    def __init__(self, search: SearchProvider) -> None:
        self._search = search

    async def execute(
        self,
        input: ResearchEvidenceInput,
        on_progress: ProgressCallback | None = None,
    ) -> ResearchEvidenceOutput:
        """
        Run the research and return the evidence.

        Raises:
            SearchProviderError: if the search provider fails. Nothing is
                returned in that case; the caller decides how to handle it.
        """
        kept: list[EvidenceSource] = []
        seen_urls: set[str] = set()
        queries_run: list[str] = []

        async def report(phase: ResearchPhase, label: str, category: ResearchCategory | None):
            if on_progress is not None:
                await on_progress(ResearchProgress(
                    phase=phase,
                    category=category,
                    label=label,
                    sources_found=len(kept),
                    high_quality_sources=sum(1 for s in kept if s.evidence_tier == EvidenceTier.A),
                ))

        plan = build_research_plan(input.industry, input.branch, input.max_sources_per_category)

        for step in plan:
            await report(ResearchPhase.SEARCHING_SOURCES, step.label, step.category)

            found: list[EvidenceSource] = []
            for query in step.queries:
                queries_run.append(query.text)
                for result in await self._search.search(query):
                    if result.url in seen_urls:
                        continue          # already found by an earlier search
                    seen_urls.add(result.url)
                    found.append(self._to_evidence(result, step.category, query.text, input))

            # Keep only the strongest few per category, so no category floods the evidence.
            found.sort(key=_strongest_first)
            kept.extend(found[: input.max_sources_per_category])

            await report(ResearchPhase.SOURCES_FOUND, step.label, step.category)

        await report(ResearchPhase.EVALUATING_EVIDENCE, EVALUATING_LABEL, None)
        kept.sort(key=_strongest_first)

        return ResearchEvidenceOutput(
            industry=input.industry,
            branch=input.branch,
            sources=kept,
            queries_run=queries_run,
            summary=self._summarize(kept),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _to_evidence(
        self,
        result: SearchResult,
        category: ResearchCategory,
        query: str,
        input: ResearchEvidenceInput,
    ) -> EvidenceSource:
        """Normalize one raw search result into a complete EvidenceSource."""
        source_type, tier = classify(result, category)
        problem, insight = split_snippet(result.snippet)
        return EvidenceSource(
            title=result.title,
            organization=organization_name(result),
            source_type=source_type,
            published_date=result.published_date,
            url=result.url,
            problem_addressed=problem,
            relevant_insight=insight,
            why_it_matters=why_it_matters(tier, source_type, input.industry, input.branch),
            evidence_tier=tier,
            research_category=category,
            query=query,
            provider=self._search.name,
        )

    def _summarize(self, sources: list[EvidenceSource]) -> ResearchSummary:
        tiers = Counter(s.evidence_tier for s in sources)
        categories = Counter(s.research_category for s in sources)
        return ResearchSummary(
            total_sources=len(sources),
            high_quality_count=tiers[EvidenceTier.A],
            by_tier={tier: tiers[tier] for tier in EvidenceTier},
            by_category={category: categories[category] for category in ResearchCategory},
            provider=self._search.name,
        )
