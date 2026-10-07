"""
Scope rules (Release 0.6) — plain code, no AI.

The student can move a feature between Core, Optional and Out of scope. One
function decides whether a move is allowed and what the scope looks like
afterwards, so the workflow and the Project Brain always apply the same rule:

  - the item must exist and must actually change list
  - Core keeps between MIN_CORE_FEATURES and MAX_CORE_FEATURES items
  - a moved item goes to the end of its new list
"""
from typing import TypeVar

from app.core.brain.schemas import MAX_CORE_FEATURES, MIN_CORE_FEATURES, ScopeKind, StoredScopeItem

Item = TypeVar("Item", bound=StoredScopeItem)

# The order the lists are shown in.
KIND_ORDER = [ScopeKind.CORE, ScopeKind.OPTIONAL, ScopeKind.OUT_OF_SCOPE]


class ScopeChangeError(ValueError):
    """The requested scope change is not allowed."""


def sort_scope(items: list[Item]) -> list[Item]:
    """Core first, then optional, then out of scope; each list in its own order."""
    return sorted(items, key=lambda item: (KIND_ORDER.index(item.kind), item.position))


def move_scope_item(items: list[Item], item_id: str, to: ScopeKind) -> list[Item]:
    """
    Return the scope after moving one item to another list (the input is not changed).

    Raises:
        ScopeChangeError: unknown item, already in that list, or Core would
                          become too small or too large.
    """
    item = next((i for i in items if i.id == item_id), None)
    if item is None:
        raise ScopeChangeError(f"'{item_id}' is not part of this project's scope.")
    if item.kind == to:
        raise ScopeChangeError(f"'{item.title}' is already in that list.")

    core = sum(1 for i in items if i.kind == ScopeKind.CORE)
    if item.kind == ScopeKind.CORE and core - 1 < MIN_CORE_FEATURES:
        raise ScopeChangeError(f"Core scope needs at least {MIN_CORE_FEATURES} features.")
    if to == ScopeKind.CORE and core + 1 > MAX_CORE_FEATURES:
        raise ScopeChangeError(
            f"Core scope can have at most {MAX_CORE_FEATURES} features — move one out first."
        )

    last = max((i.position for i in items if i.kind == to), default=-1)
    moved = item.model_copy(update={"kind": to, "position": last + 1})
    return sort_scope([moved if i.id == item_id else i for i in items])
