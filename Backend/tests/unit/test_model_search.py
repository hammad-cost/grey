"""
Tests for the model search (Release 0.9, Step 2) — plain code, no AI.

Covers which searches are built, which pages count as one model / API / code
base, and that the shared search runner keeps only those pages.
"""
import pytest

from app.core.brain.schemas import ModelPreference
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import SearchFocus
from app.domains.fyp.skills.find_datasets.search import search_datasets
from app.domains.fyp.skills.find_models.search import CLOUD_AI_SITES, build_model_queries, is_model_page
from tests.unit.test_dataset_search import ScriptedSearch, result


def test_the_first_search_has_four_targeted_queries():
    queries = build_model_queries("Defense", "Navy", "Abnormal vessel movement detection", "anomaly_detection")
    assert [q.text for q in queries] == [
        "Navy anomaly detection pretrained model",
        "Abnormal vessel movement detection model code",
        "anomaly detection pretrained model pytorch",
        "anomaly detection API service",
    ]
    assert all(q.focus == SearchFocus.GENERAL and q.include_domains for q in queries)
    assert queries[3].include_domains == CLOUD_AI_SITES


def test_other_models_uses_different_wording():
    first = {q.text for q in build_model_queries("Defense", "Navy", "Vessels", "nlp")}
    other = build_model_queries("Defense", "Navy", "Vessels", "nlp", ModelPreference.OTHER_OPTIONS)
    assert len(other) == 3 and not first & {q.text for q in other}


@pytest.mark.parametrize("url", [
    "https://huggingface.co/someone/vessel-anomaly-detector",
    "https://www.kaggle.com/models/someone/track-model",
    "https://pytorch.org/hub/pytorch_vision_resnet",
    "https://paperswithcode.com/paper/deep-anomaly-detection",
    "https://github.com/someone/ais-anomaly",
    "https://cloud.google.com/vertex-ai/docs/anomaly-detection",
    "https://research.example-university.example/research/navy-models",     # sample (mock) page
])
def test_model_pages_are_kept(url):
    assert is_model_page(url)


@pytest.mark.parametrize("url", [
    "https://huggingface.co/models",
    "https://huggingface.co/datasets/someone/tracks",
    "https://huggingface.co/spaces/someone/demo",
    "https://huggingface.co/someone",
    "https://www.kaggle.com/datasets/someone/tracks",
    "https://pytorch.org/",
    "https://paperswithcode.com/task/anomaly-detection",
    "https://github.com/topics/anomaly-detection",
    "https://cloud.google.com/products",
    "https://cloud.google.com/",
    "https://some-site.example/search",
])
def test_generic_pages_are_dropped(url):
    assert not is_model_page(url)


async def test_the_shared_runner_keeps_only_model_pages():
    search = ScriptedSearch([
        result("https://huggingface.co/someone/model-a"),
        result("https://huggingface.co/datasets/someone/data"),
        result("https://www.kaggle.com/models/a/b"),
    ])
    found = await search_datasets(search, build_model_queries("D", "N", "V", "nlp"), max_searches=6,
                                  is_wanted=is_model_page)
    assert [c.url for c in found.candidates] == ["https://huggingface.co/someone/model-a",
                                                 "https://www.kaggle.com/models/a/b"]


async def test_the_sample_search_gives_model_pages():
    found = await search_datasets(MockSearchProvider(), build_model_queries("Defense", "Navy", "Vessels", "nlp"),
                                  max_searches=6, is_wanted=is_model_page)
    assert len(found.candidates) >= 4
