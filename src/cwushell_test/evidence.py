"""Case and report contracts, constructible without launching a target.

Execution evidence remains the PTY helper's Evidence object. Fixture collectors
and scenario runners attach context here without comparing output to expectations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Mapping

from cwushell_test.pty_session import Command, Evidence, Interaction


@dataclass(frozen=True)
class Fixture:
    """Initial fixture description; contents are bytes, directories use None."""

    path: str
    kind: Literal["file", "directory", "absent"]
    contents: bytes | None = None


@dataclass(frozen=True)
class FileObservation:
    """Harness snapshot, including unavailable observations and diagnostics.

    None for exists means existence could not be observed; None for contents
    means contents were not collected. An empty byte string is an observed empty
    file. After snapshots are taken after process/PTY cleanup, before removal.
    """

    path: str
    phase: Literal["before", "after"]
    exists: bool | None
    contents: bytes | None = None
    error: str | None = None


@dataclass(frozen=True)
class CaseSummary:
    """Shared terminal/report summary; labels are simultaneous observations."""

    case_id: str
    suite_id: str
    title: str
    outcomes: tuple[str, ...]
    events: tuple[Interaction, ...]
    exit_status: int | None
    signal_status: int | None
    dispatched_count: int
    undispatched_count: int


@dataclass(frozen=True)
class CaseEvidence:
    """One independent session and its exact planned input and context.

    Pass the original Command sequence and returned Evidence, without rewriting
    tabs. A dispatch timeout may send a partial line; only fully dispatched lines
    appear in session.dispatched, as defined by the PTY helper.
    """

    case_id: str
    suite_id: str
    title: str
    commands: tuple[Command, ...]
    session: Evidence
    fixtures: tuple[Fixture, ...] = ()
    controlled_environment: Mapping[str, str | None] = field(default_factory=dict)
    file_observations: tuple[FileObservation, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def summary(self) -> CaseSummary:
        session = self.session
        # EOF alone does not prove a process exited (it may close its terminal).
        outcomes = [session.reason]
        outcomes.extend(event.reason for event in session.interactions)
        if session.exit_status is not None:
            outcomes.append("PROCESS_EXIT")
        if session.signal_status is not None:
            outcomes.append("SIGNAL")
        if session.undispatched:
            outcomes.append("INCOMPLETE_DISPATCH")
        if session.cleanup_error is not None:
            outcomes.append("CLEANUP_ERROR")
        return CaseSummary(
            self.case_id,
            self.suite_id,
            self.title,
            tuple(dict.fromkeys(outcomes)),
            tuple(session.interactions),
            session.exit_status,
            session.signal_status,
            len(session.dispatched),
            len(session.undispatched),
        )


@dataclass(frozen=True)
class ExecutionMetadata:
    """Values collected by the workflow, not inferred by the renderer."""

    timestamp: datetime
    target: Path
    target_architecture: str
    kernel_version: str
    timeout: float
    max_output_bytes: int


@dataclass(frozen=True)
class Report:
    metadata: ExecutionMetadata
    cases: tuple[CaseEvidence, ...]
