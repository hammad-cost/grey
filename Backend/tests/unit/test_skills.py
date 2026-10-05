"""
Tests for the Skill base protocol and SkillRegistry.
(The LLM Gateway has its own tests in test_llm_gateway.py.)
"""
import pytest
from pydantic import BaseModel

from app.core.skills.base import Skill, SkillMetadata
from app.core.skills.registry import SkillRegistry


# ── Minimal concrete skill used only in tests ─────────────────────────────────

class _EchoInput(BaseModel):
    message: str

class _EchoOutput(BaseModel):
    echo: str

class _EchoSkill(Skill):
    """A trivial skill that echoes its input. Used only in tests."""
    metadata = SkillMetadata(
        name="echo",
        description="Echoes the input message back.",
    )

    async def execute(self, input: _EchoInput) -> _EchoOutput:
        return _EchoOutput(echo=input.message)


# ── SkillMetadata ─────────────────────────────────────────────────────────────

def test_skill_metadata_defaults():
    """SkillMetadata has sensible defaults for optional fields."""
    meta = SkillMetadata(name="test_skill", description="A test.")
    assert meta.version == "0.1.0"
    assert meta.requires_human_approval is False


# ── Skill base ────────────────────────────────────────────────────────────────

async def test_skill_execute():
    """A concrete skill can be instantiated and called."""
    skill = _EchoSkill()
    result = await skill.execute(_EchoInput(message="hello"))
    assert result.echo == "hello"


def test_skill_repr():
    """Skill __repr__ includes name and version for readable logs."""
    skill = _EchoSkill()
    assert "echo" in repr(skill)
    assert "0.1.0" in repr(skill)


# ── SkillRegistry ─────────────────────────────────────────────────────────────

def test_registry_register_and_get():
    """A registered skill can be retrieved by name."""
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    skill = registry.get("echo")
    assert skill.metadata.name == "echo"


def test_registry_list_skills():
    """list_skills returns all registered skill names."""
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    assert "echo" in registry.list_skills()


def test_registry_contains():
    """'in' operator works on registry."""
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    assert "echo" in registry
    assert "nonexistent" not in registry


def test_registry_len():
    """len() returns the number of registered skills."""
    registry = SkillRegistry()
    assert len(registry) == 0
    registry.register(_EchoSkill())
    assert len(registry) == 1


def test_registry_get_unknown_raises_key_error():
    """get() raises KeyError when skill is not registered."""
    registry = SkillRegistry()
    with pytest.raises(KeyError, match="not registered"):
        registry.get("does_not_exist")


def test_registry_duplicate_raises_value_error():
    """Registering the same name twice raises ValueError."""
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_EchoSkill())
