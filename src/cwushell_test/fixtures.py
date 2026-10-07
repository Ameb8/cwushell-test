"""Shared initial settings and direct harness snapshots for isolated sessions."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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


# Exact UTF-8 bytes, including the final LF, are part of the fixture contract.
EXTERNAL_FIXTURES = (
    Fixture("source.txt", "file", b"cwushell-test source fixture\n"),
    Fixture("removable.txt", "file", b"cwushell-test removable fixture\n"),
    Fixture("copied.txt", "absent"),
)
CD_FIXTURES = (Fixture("fixture_dir", "directory"),)
EXPORT_ENVIRONMENT: dict[str, str | None] = {"CWUSHELL_TEST_EXPORT": None}
UNSET_ENVIRONMENT: dict[str, str | None] = {"CWUSHELL_TEST_UNSET": "fixture_value"}
TERMINAL_ENVIRONMENT = {"TERM": "dumb", "LC_ALL": "C", "LANG": "C"}
FILE_CAPTURE_BYTES = 1048576


def validate_fixtures(fixtures: tuple[Fixture, ...]) -> None:
    """Reject unsafe or ambiguous fixture plans before creating a session."""
    names: set[str] = set()
    for fixture in fixtures:
        if (
            not fixture.path
            or fixture.path in (".", "..")
            or Path(fixture.path).name != fixture.path
            or fixture.path in names
        ):
            raise ValueError("fixture paths must be unique immediate relative names")
        names.add(fixture.path)
        if fixture.kind not in ("file", "directory", "absent"):
            raise ValueError(f"unknown fixture kind: {fixture.kind}")
        if (fixture.kind == "file") != (fixture.contents is not None):
            raise ValueError("only file fixtures must specify contents")


def prepare(directory: Path, fixtures: tuple[Fixture, ...]) -> None:
    """Populate a fresh directory; errors are retained by the session runner."""
    for fixture in fixtures:
        path = directory / fixture.path
        if fixture.kind == "file":
            assert fixture.contents is not None
            path.write_bytes(fixture.contents)
        elif fixture.kind == "directory":
            path.mkdir()
        # Absent entries require no operation in a fresh temporary directory.


def snapshot(
    directory: Path, path: str, phase: Literal["before", "after"]
) -> FileObservation:
    """Observe existence and regular-file bytes without following target symlinks.

    Nonblocking opens avoid hanging on a target-created FIFO. File capture retains
    at most 1 MiB, with an explicit diagnostic if the file exceeds that limit.
    """
    destination = directory / path
    exists: bool | None = None
    try:
        metadata = destination.lstat()
        exists = True
        if stat.S_ISDIR(metadata.st_mode):
            return FileObservation(path, phase, True)
        if not stat.S_ISREG(metadata.st_mode):
            return FileObservation(
                path, phase, True, error="Not a regular file; contents not collected"
            )
        descriptor = os.open(destination, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError("file changed type during observation")
            contents = stream.read(FILE_CAPTURE_BYTES + 1)
        error = None
        if len(contents) > FILE_CAPTURE_BYTES:
            contents = contents[:FILE_CAPTURE_BYTES]
            error = f"File contents truncated at {FILE_CAPTURE_BYTES} bytes"
        return FileObservation(path, phase, True, contents, error)
    except FileNotFoundError as exc:
        if exists is None:
            return FileObservation(path, phase, False)
        return FileObservation(
            path, phase, exists, error=f"Unable to read {destination}: {exc}"
        )
    except OSError as exc:
        return FileObservation(
            path,
            phase,
            exists,
            error=f"Unable to observe {destination}: {exc}; check file type and permissions",
        )
