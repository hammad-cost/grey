"""
Tests for the industry / branch taxonomy.
These are pure data tests — no async, no DB, no LangGraph.
"""
from app.domains.fyp.workflows.discovery.taxonomy import (
    INDUSTRIES,
    get_branches_for_industry,
    is_valid_branch,
    is_valid_industry,
)


def test_industries_list_is_not_empty():
    assert len(INDUSTRIES) > 0


def test_industries_contains_expected_entries():
    for expected in ["Healthcare", "Defense", "Finance", "Education"]:
        assert expected in INDUSTRIES


def test_all_industries_have_branches():
    """Every industry in the list must have at least one branch."""
    for industry in INDUSTRIES:
        branches = get_branches_for_industry(industry)
        assert branches, f"'{industry}' has no branches defined"


def test_defense_branches():
    branches = get_branches_for_industry("Defense")
    assert "Army" in branches
    assert "Navy" in branches
    assert "Air Force" in branches
    assert "Cyber Defense" in branches


def test_unknown_industry_returns_empty_list():
    assert get_branches_for_industry("Underwater Basket Weaving") == []


def test_is_valid_industry_true():
    assert is_valid_industry("Defense") is True
    assert is_valid_industry("Healthcare") is True


def test_is_valid_industry_false():
    assert is_valid_industry("Magic") is False
    assert is_valid_industry("") is False


def test_is_valid_branch_true():
    assert is_valid_branch("Defense", "Navy") is True
    assert is_valid_branch("Healthcare", "Clinical AI") is True


def test_is_valid_branch_false():
    assert is_valid_branch("Defense", "Clinical AI") is False
    assert is_valid_branch("Defense", "") is False


def test_is_valid_branch_unknown_industry():
    assert is_valid_branch("Unknown", "Navy") is False
