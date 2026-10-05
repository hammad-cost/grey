"""
Tests for the GreyEvent envelope.
"""
import pytest

from app.core.events import (
    AllowedAction,
    EventStatus,
    EventType,
    GreyEvent,
    build_event,
)


def test_build_event_minimal():
    """build_event creates a valid GreyEvent with required fields."""
    event = build_event(
        type=EventType.PROJECT_CREATED,
        workspace_id="ws-001",
        workflow="discovery",
        stage="INDUSTRY_SELECTION",
        status=EventStatus.AWAITING_USER,
    )

    assert event.type == EventType.PROJECT_CREATED
    assert event.workspace_id == "ws-001"
    assert event.domain == "fyp"
    assert event.workflow == "discovery"
    assert event.stage == "INDUSTRY_SELECTION"
    assert event.status == EventStatus.AWAITING_USER
    assert event.data == {}
    assert event.brain_patch == {}
    assert event.allowed_actions == []


def test_build_event_with_payload():
    """build_event stores data, brain_patch and allowed_actions correctly."""
    event = build_event(
        type=EventType.INDUSTRY_SAVED,
        workspace_id="ws-002",
        workflow="discovery",
        stage="BRANCH_SELECTION",
        status=EventStatus.AWAITING_USER,
        data={"industry": "Defense"},
        brain_patch={"industry": "Defense", "industry_status": "approved"},
        allowed_actions=[AllowedAction.SELECT_BRANCH, AllowedAction.ASK_GREY],
    )

    assert event.data["industry"] == "Defense"
    assert event.brain_patch["industry_status"] == "approved"
    assert AllowedAction.SELECT_BRANCH in event.allowed_actions
    assert AllowedAction.ASK_GREY in event.allowed_actions


def test_event_serialises_to_dict():
    """GreyEvent can be serialised to a plain dict (needed for FastAPI responses)."""
    event = build_event(
        type=EventType.BRANCH_SAVED,
        workspace_id="ws-003",
        workflow="discovery",
        stage="EVIDENCE_RESEARCH",
        status=EventStatus.RUNNING,
    )

    as_dict = event.model_dump()
    assert as_dict["type"] == "branch_saved"
    assert as_dict["status"] == "running"
    assert as_dict["domain"] == "fyp"


def test_event_type_values_are_strings():
    """EventType values are plain strings, safe to send over HTTP."""
    assert EventType.PROJECT_CREATED == "project_created"
    assert EventType.INDUSTRY_SAVED == "industry_saved"
    assert EventType.BRANCH_SAVED == "branch_saved"


def test_allowed_action_values_match_frontend_contract():
    """AllowedAction values must match the action names the frontend expects."""
    assert AllowedAction.SELECT_INDUSTRY == "selectIndustry"
    assert AllowedAction.SELECT_BRANCH == "selectBranch"
    assert AllowedAction.START_PROJECT == "startProject"
    assert AllowedAction.ASK_GREY == "askGrey"
