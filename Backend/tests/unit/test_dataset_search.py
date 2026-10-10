"""
Tests for the dataset search (Release 0.8, Step 2) — plain code, no AI.

Covers which searches are built (first search, "other options", "own data"),
which pages count as a dataset page (the generic portal pages from the 0.4
live run are dropped), duplicates, the search budget, pages shown before,
and what happens when searches fail.
"""
import pytest

from app.core.brain.schemas import DatasetCandidate, DatasetPreference
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import (
    SearchFocus,
    SearchProvider,
    SearchQuery,
    SearchRateLimited,
    SearchResult,
    SearchUnavailable,
)
from app.domains.fyp.skills.find_datasets.search import (
    MAX_CANDIDATES,
    build_dataset_queries,
    is_dataset_page,
    normalize_url,
    search_datasets,
)


class ScriptedSearch(SearchProvider):
    """Returns the given results for every search, or raises the given error."""

    name = "scripted"

    def __init__(self, results: list[SearchResult] | None = None, error: Exception | None = None):
        self.results = results or []
        self.error = error
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.results


def result(url: str, title: str = "Vessel tracks dataset") -> SearchResult:
    return SearchResult(title=title, url=url, snippet="Labelled vessel positions.", provider="scripted")


def known(url: str) -> DatasetCandidate:
    return DatasetCandidate(title="Known", url=url, snippet="s", query="q", provider="mock")


# ── Queries ───────────────────────────────────────────────────────────────────

def test_the_first_search_has_four_targeted_queries():
    queries = build_dataset_queries("Logistics", "Maritime", "Late detection of unusual vessel movements", "anomaly_detection")
    assert [q.text for q in queries] == [
        "Maritime anomaly detection dataset",
        "Late detection of unusual vessel movements dataset",
        "Maritime Logistics open data",
        "anomaly detection Maritime benchmark dataset",
    ]
    assert all(q.focus == SearchFocus.DATASETS and q.include_domains for q in queries)
    assert queries[0].include_domains == ["kaggle.com", "huggingface.co"]
    assert "data.gov" in queries[2].include_domains
    assert queries[3].include_domains == ["paperswithcode.com", "github.com"]


def test_a_project_without_an_ai_task_still_gets_sensible_queries():
    queries = build_dataset_queries("Logistics", "Maritime", "Berth scheduling", "none")
    assert queries[0].text == "Maritime dataset"
    assert queries[3].text == "Maritime benchmark dataset"


def test_long_problem_titles_are_shortened():
    title = "A very long problem title with many many words that keeps going on and on"
    query = build_dataset_queries("I", "B", title, "nlp")[1]
    assert query.text == "A very long problem title with many many dataset"


def test_other_options_uses_different_wording_and_own_data_makes_no_searches():
    first = {q.text for q in build_dataset_queries("Logistics", "Maritime", "Vessel delays", "forecasting")}
    other = build_dataset_queries("Logistics", "Maritime", "Vessel delays", "forecasting", DatasetPreference.OTHER_OPTIONS)
    assert len(other) == 3 and not first & {q.text for q in other}
    assert build_dataset_queries("L", "M", "V", "forecasting", DatasetPreference.OWN_DATA) == []


# ── Which pages are dataset pages ─────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://www.kaggle.com/datasets/someone/vessel-tracks",
    "https://huggingface.co/datasets/someone/ship-ais",
    "https://archive.ics.uci.edu/dataset/123/ship+tracks",
    "https://zenodo.org/records/1234567",
    "https://paperswithcode.com/dataset/ais-tracks",
    "https://catalog.data.gov/dataset/vessel-traffic-data",
    "https://data.gov.uk/dataset/abc-123/port-traffic",
    "https://data.europa.eu/data/datasets/maritime-traffic?locale=en",
    "https://github.com/someone/ais-anomaly-dataset",
    "https://datasets.ml-hub.example/maritime-benchmark",              # sample (mock) page
    "https://data.open-portal.gov.example/datasets/maritime-records",  # sample (mock) page
])
def test_dataset_pages_are_kept(url):
    assert is_dataset_page(url)


@pytest.mark.parametrize("url", [
    "https://data.gov/",                          # the 0.4 live run returned these
    "https://data.gov/about",
    "https://data.gov/metrics",
    "https://zenodo.org/",
    "https://www.kaggle.com/datasets",
    "https://www.kaggle.com/competitions/some-challenge",
    "https://huggingface.co/models",
    "https://archive.ics.uci.edu/datasets",
    "https://paperswithcode.com/task/anomaly-detection",
    "https://github.com/topics/anomaly-detection",
    "https://github.com/someone",
    "https://some-portal.example/search",
    "https://some-portal.example/",
])
def test_generic_pages_are_dropped(url):
    assert not is_dataset_page(url)


def test_urls_are_normalized():
    assert normalize_url("https://zenodo.org/records/1/#files") == "https://zenodo.org/records/1"


# ── Running the searches ──────────────────────────────────────────────────────

async def test_only_dataset_pages_are_kept_once_each():
    search = ScriptedSearch([
        result("https://www.kaggle.com/datasets/a/tracks/"),
        result("https://www.kaggle.com/datasets/a/tracks#about"),
        result("https://data.gov/about"),
    ])
    queries = build_dataset_queries("Logistics", "Maritime", "Vessel delays", "forecasting")
    found = await search_datasets(search, queries, max_searches=6)
    assert found.searches_used == 4
    assert [c.url for c in found.candidates] == ["https://www.kaggle.com/datasets/a/tracks"]
    candidate = found.candidates[0]
    assert candidate.query == queries[0].text
    assert candidate.provider == "scripted"
    assert candidate.publisher == "kaggle.com"          # no publisher → the site


async def test_the_search_budget_is_respected():
    search = ScriptedSearch([])
    queries = build_dataset_queries("Logistics", "Maritime", "Vessel delays", "forecasting")
    found = await search_datasets(search, queries, max_searches=2)
    assert found.searches_used == 2 and len(search.queries) == 2


async def test_pages_shown_before_are_skipped_and_known_pages_are_reused():
    search = ScriptedSearch([result("https://zenodo.org/records/1"), result("https://zenodo.org/records/2")])
    found = await search_datasets(
        search,
        build_dataset_queries("L", "M", "V", "forecasting", DatasetPreference.OTHER_OPTIONS),
        max_searches=6,
        known=[known("https://zenodo.org/records/1"), known("https://zenodo.org/records/9")],
        exclude_urls={"https://zenodo.org/records/1/"},
    )
    assert [c.url for c in found.candidates] == ["https://zenodo.org/records/2", "https://zenodo.org/records/9"]


async def test_own_data_reuses_known_pages_without_searching():
    search = ScriptedSearch([])
    found = await search_datasets(search, [], max_searches=6, known=[known("https://zenodo.org/records/9")])
    assert found.searches_used == 0 and search.queries == []
    assert [c.url for c in found.candidates] == ["https://zenodo.org/records/9"]


async def test_candidates_are_capped():
    search = ScriptedSearch([result(f"https://zenodo.org/records/{n}") for n in range(20)])
    found = await search_datasets(search, build_dataset_queries("L", "M", "V", "nlp"), max_searches=6)
    assert len(found.candidates) == MAX_CANDIDATES


async def test_one_failed_search_is_skipped():
    class FailsOnce(ScriptedSearch):
        async def search(self, query):
            if not self.queries:
                self.queries.append(query)
                raise SearchRateLimited("slow down")
            return await super().search(query)

    found = await search_datasets(
        FailsOnce([result("https://zenodo.org/records/1")]),
        build_dataset_queries("L", "M", "V", "nlp"),
        max_searches=6,
    )
    assert found.searches_failed == 1
    assert len(found.candidates) == 1


async def test_when_every_search_fails_the_error_is_raised():
    with pytest.raises(SearchUnavailable):
        await search_datasets(
            ScriptedSearch(error=SearchUnavailable("all down")),
            build_dataset_queries("L", "M", "V", "nlp"),
            max_searches=6,
        )


async def test_when_every_search_fails_known_pages_still_count():
    found = await search_datasets(
        ScriptedSearch(error=SearchUnavailable("all down")),
        build_dataset_queries("L", "M", "V", "nlp", DatasetPreference.OTHER_OPTIONS),
        max_searches=6,
        known=[known("https://zenodo.org/records/9")],
    )
    assert len(found.candidates) == 1


async def test_progress_is_reported_before_each_search():
    calls = []

    async def on_search(index, total):
        calls.append((index, total))

    await search_datasets(ScriptedSearch([]), build_dataset_queries("L", "M", "V", "nlp"), max_searches=3, on_search=on_search)
    assert calls == [(0, 3), (1, 3), (2, 3)]


async def test_the_sample_search_gives_distinct_dataset_pages():
    queries = build_dataset_queries("Logistics", "Maritime", "Vessel delays", "forecasting")
    found = await search_datasets(MockSearchProvider(), queries, max_searches=6)
    assert len(found.candidates) == MAX_CANDIDATES          # 4 searches × 2 sample pages
    assert all(c.provider == "mock" for c in found.candidates)
