"""
Read-only views of the Project Brain, for skills.

A skill that needs Brain data is given one of these narrow interfaces instead
of the full WorkspaceBrainRepository, so it can read what it needs but has no
way to write.

  EvidenceReader         — the interface skills depend on.
  SessionEvidenceReader  — the version the API uses: each read gets its own
                           short-lived database session, and the read always
                           finishes cleanly even if the request is cancelled
                           (e.g. the student closes the tab mid-stream). A read
                           cut off halfway can leave SQLite locked, which would
                           make the student's next attempt fail.

WorkspaceBrainRepository also provides list_evidence(), so tests can pass the
repository itself as an EvidenceReader.
"""
import asyncio
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.brain.schemas import StoredEvidenceSource


class EvidenceReader(Protocol):
    """Reads the evidence stored for a project."""

    async def list_evidence(self, workspace_id: str) -> list[StoredEvidenceSource]:
        """All stored evidence for the project, strongest first."""
        ...


class SessionEvidenceReader:
    """An EvidenceReader that opens its own short-lived session for every read."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_evidence(self, workspace_id: str) -> list[StoredEvidenceSource]:
        # shield(): if the caller is cancelled, the read still finishes and its
        # session closes; the cancellation is then passed on to the caller.
        return await asyncio.shield(self._read(workspace_id))

    async def _read(self, workspace_id: str) -> list[StoredEvidenceSource]:
        from app.core.brain.repository import WorkspaceBrainRepository   # avoids a circular import

        async with self._session_factory() as session:
            return await WorkspaceBrainRepository(session).list_evidence(workspace_id)
