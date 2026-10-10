"""Bounded PTY execution and evidence collection for one independent scenario."""

import errno
import math
import os
import re
import select
import shlex
import signal
import tempfile
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping, Sequence

import pexpect

from cwushell_test import fixtures as session_fixtures
from cwushell_test.fixtures import FileObservation, Fixture

READ_BYTES = 4096
CLEANUP_GRACE = 0.2  # TERM and KILL each get this bounded grace period.
POLL_INTERVAL = 0.01
EOF_STATUS_GRACE = 0.05
PROMPT_SETTLE_SECONDS = 0.05
# Complete ECMA-48 CSI, control strings, and ordinary ESC sequences. Streaming
# state below also removes an incomplete escape at the retained prefix boundary.
ANSI = re.compile(
    rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|"
    rb"[\]PX^_](?:[^\x1b\x07]|\x1b(?!\\))*(?:\x07|\x1b\\)|"
    rb"(?![\[\]PX^_])[ -/]*[0-~])"
)


@dataclass(frozen=True)
class Action:
    """Exact input bytes; Enter is one explicit LF, with no implicit suffix."""

    kind: Literal["type", "key", "enter"]
    data: bytes


@dataclass
class ActionDispatch:
    """Byte accounting independent of terminal capture, including partial writes."""

    command_index: int
    action_index: int
    action: Action
    sent_bytes: int = 0


@dataclass(frozen=True)
class TerminalObservation:
    """Read-only termios snapshot from the owned PTY, or an explicit diagnostic."""

    phase: str
    flags: tuple[int, ...] = ()
    modes: tuple[tuple[str, bool], ...] = ()
    verase: bytes | None = None
    error: str | None = None


@dataclass(frozen=True)
class Command:
    """One paced interaction: a line or exact actions ending in explicit Enter.

    With actions, text is a plan label. None means wait for terminal EOF.
    """

    text: str
    prompt: str | None = "cwushell>"
    actions: tuple[Action, ...] = ()

    @property
    def input_actions(self) -> tuple[Action, ...]:
        return self.actions or (
            Action("type", self.text.encode("utf-8")),
            Action("enter", b"\n"),
        )


@dataclass(frozen=True)
class Interaction:
    """Observed synchronization event, never a correctness judgment."""

    command: str | None
    reason: str
    waiting_for: str


@dataclass
class Evidence:
    """Retained after cleanup, including incomplete dispatch and capture metadata."""

    max_output_bytes: int
    raw_output: bytes = b""
    truncated: bool = False
    dispatched: list[str] = field(default_factory=list)
    undispatched: list[str] = field(default_factory=list)
    interactions: list[Interaction] = field(default_factory=list)
    reason: str = "ERROR"
    error: str | None = None
    exit_status: int | None = None
    signal_status: int | None = None
    cleanup_actions: list[str] = field(default_factory=list)
    pid: int | None = None
    pgid: int | None = None
    cleanup_exit_status: int | None = None
    cleanup_signal_status: int | None = None
    direct_child_reaped: bool = False
    cleanup_error: str | None = None
    working_directory: str = ""
    launch_seconds: float = 0.0
    interaction_seconds: float = 0.0
    cleanup_seconds: float = 0.0
    fixtures: tuple[Fixture, ...] = ()
    controlled_environment: dict[str, str | None] = field(default_factory=dict)
    file_observations: tuple[FileObservation, ...] = ()
    notes: tuple[str, ...] = ()
    action_dispatch: list[ActionDispatch] = field(default_factory=list)
    terminal_observations: list[TerminalObservation] = field(default_factory=list)
    terminal_profile: str = "dumb; 24x80; launch echo disabled; inherited termios"

    @property
    def output(self) -> str:
        return clean_output(self.raw_output)


class _TerminalCleaner:
    """Streaming escape removal, with constant state even for unterminated OSC."""

    def __init__(self) -> None:
        self.state = "text"

    def feed(self, data: bytes) -> bytes:
        output = bytearray()
        for value in data:
            if self.state == "text":
                if value == 27:
                    self.state = "escape"
                else:
                    output.append(value)
            elif self.state == "escape":
                if value == ord("["):
                    self.state = "csi"
                elif value in b"]PX^_":
                    self.state = "string"
                elif 0x20 <= value <= 0x2F:
                    self.state = "intermediate"
                else:
                    self.state = "text"
            elif self.state in ("csi", "intermediate"):
                if 0x40 <= value <= 0x7E or (
                    self.state == "intermediate" and 0x30 <= value <= 0x7E
                ):
                    self.state = "text"
            elif self.state == "string":
                if value == 7:
                    self.state = "text"
                elif value == 27:
                    self.state = "string_escape"
            elif self.state == "string_escape":
                if value == ord("\\"):
                    self.state = "text"
                elif value != 27:
                    self.state = "string"
        return bytes(output)


def clean_output(raw: bytes) -> str:
    """Strip terminal sequences, decode UTF-8 with replacement, normalize CR/LF."""
    text = _TerminalCleaner().feed(ANSI.sub(b"", raw)).decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


class _Reader:
    def __init__(self, child: pexpect.spawn, evidence: Evidence) -> None:
        self.child = child
        self.evidence = evidence
        self.cleaner = _TerminalCleaner()

    def _retain(self, data: bytes) -> bytes:
        capacity = self.evidence.max_output_bytes - len(self.evidence.raw_output)
        self.evidence.raw_output += data[:capacity]
        if len(data) > capacity:
            self.evidence.truncated = True
        return self.cleaner.feed(data)

    def collect_available(self) -> None:
        """One bounded nonblocking read after stopped dispatch; never wait anew."""
        try:
            data = os.read(self.child.child_fd, READ_BYTES)
        except BlockingIOError:
            return
        except OSError as exc:
            if exc.errno == errno.EIO:
                return
            raise
        self._retain(data)

    def wait(self, prompt: str | None, deadline: float) -> str:
        needle = prompt.encode("utf-8") if prompt is not None else None
        # Track only the matching prefix of the current line, never whole lines.
        # Each interaction starts at a virtual line boundary: the previously
        # consumed prompt usually had no newline, and echo is disabled.
        matched: int | None = 0
        candidate_since: float | None = None
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                return "TIMEOUT"
            if candidate_since is not None:
                remaining = min(
                    remaining,
                    max(0.0, candidate_since + PROMPT_SETTLE_SECONDS - now),
                )
            # Read the pexpect-owned descriptor directly. pexpect's read path
            # sets ptyprocess.flag_eof, which turns subsequent isalive() calls
            # into blocking waitpid even if a live process merely closed its TTY.
            readable, _, _ = select.select([self.child.child_fd], [], [], remaining)
            if not readable:
                now = time.monotonic()
                if (
                    now < deadline
                    and candidate_since is not None
                    and now >= candidate_since + PROMPT_SETTLE_SECONDS
                ):
                    return "PROMPT"
                return "TIMEOUT"
            try:
                data = os.read(self.child.child_fd, READ_BYTES)
            except BlockingIOError:
                continue
            except OSError as exc:
                if exc.errno == errno.EIO:  # Linux PTY slave closed
                    return "EOF"
                raise
            if not data:
                return "EOF"
            cleaned = self._retain(data)
            if needle is not None:
                for value in cleaned:
                    if value in b"\r\n":
                        matched = 0
                    elif matched is not None:
                        if matched < len(needle) and value == needle[matched]:
                            matched += 1
                        elif matched != len(needle) or value not in b" \t":
                            matched = None
                # Wait for a quiet, unterminated line containing only the prompt
                # and optional horizontal padding. ANSI fragments are not yet
                # a complete candidate. Further bytes restart the settling wait.
                candidate_since = (
                    time.monotonic()
                    if matched == len(needle) and self.cleaner.state == "text"
                    else None
                )


def _observe_terminal(child: pexpect.spawn, evidence: Evidence, phase: str) -> None:
    """Never change editing settings or reopen a slave potentially owned by a target."""
    try:
        attrs = termios.tcgetattr(child.child_fd)
        erase = attrs[6][termios.VERASE]
        verase = bytes([erase]) if isinstance(erase, int) else erase
        modes = tuple(
            (name, bool(attrs[index] & getattr(termios, name)))
            for index, names in (
                (0, ("ICRNL", "IXON")),
                (1, ("OPOST", "ONLCR")),
                (3, ("ICANON", "ECHO", "ECHOE", "ECHOK", "ISIG", "IEXTEN")),
            )
            for name in names
        )
        observation = TerminalObservation(phase, tuple(attrs[:4]), modes, verase)
    except (OSError, termios.error) as exc:
        observation = TerminalObservation(phase, error=f"{type(exc).__name__}: {exc}")
    evidence.terminal_observations.append(observation)


def _dispatch(
    child: pexpect.spawn, record: ActionDispatch, deadline: float
) -> Literal["SENT", "TIMEOUT", "EOF"]:
    """Bound each write by the interaction's original deadline; retain its offset."""
    data = record.action.data
    while record.sent_bytes < len(data):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "TIMEOUT"
        _, writable, _ = select.select([], [child.child_fd], [], remaining)
        if writable:
            try:
                count = os.write(
                    child.child_fd,
                    data[record.sent_bytes : record.sent_bytes + READ_BYTES],
                )
                record.sent_bytes += count
            except BlockingIOError:
                continue
            except OSError as exc:
                if exc.errno == errno.EIO:
                    return "EOF"
                raise
    return "SENT" if time.monotonic() < deadline else "TIMEOUT"


def _cleanup(child: pexpect.spawn, evidence: Evidence) -> None:
    """Terminate only the verified group, reap the direct child, close the PTY.

    Group existence includes zombies; only their parents can reap them. Never
    infer group disappearance from the leader's status or add launch hooks.
    """
    if child.closed:
        return
    started = time.monotonic()
    try:
        # Snapshot even after exceptions, before any harness termination action.
        if not child.isalive():
            evidence.exit_status = child.exitstatus
            evidence.signal_status = child.signalstatus
        pgid = evidence.pgid
        if pgid is not None and pgid == child.pid and pgid != os.getpgrp():
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(pgid, sig)
                    evidence.cleanup_actions.append(sig.name)
                except ProcessLookupError:
                    break
                deadline = time.monotonic() + CLEANUP_GRACE
                while time.monotonic() < deadline:
                    child.isalive()  # WNOHANG reaps only our direct child.
                    try:
                        os.killpg(pgid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(
                        min(POLL_INTERVAL, max(0.0, deadline - time.monotonic()))
                    )
        else:
            # Ownership failure must never target the unverified group. The
            # still-waitable direct child is safe to signal by PID instead.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if not child.isalive():
                    break
                child.kill(sig)
                evidence.cleanup_actions.append(f"DIRECT_CHILD_{sig.name}")
                deadline = time.monotonic() + CLEANUP_GRACE
                while child.isalive() and time.monotonic() < deadline:
                    time.sleep(
                        min(POLL_INTERVAL, max(0.0, deadline - time.monotonic()))
                    )
        evidence.direct_child_reaped = not child.isalive()
        if evidence.exit_status is None and evidence.signal_status is None:
            evidence.cleanup_exit_status = child.exitstatus
            evidence.cleanup_signal_status = child.signalstatus
        if not evidence.direct_child_reaped:
            evidence.cleanup_error = "Direct child still live after cleanup deadline"
    except Exception as exc:
        evidence.cleanup_error = f"{type(exc).__name__}: {exc}"
    finally:
        # pexpect.close() may inject unrecorded HUP/CONT/INT and implicit sleeps.
        # Close its owned file object directly; group escalation owns termination.
        # types-pexpect omits the runtime ptyproc attribute.
        process = child.ptyproc  # type: ignore[attr-defined]
        try:
            process.fileobj.close()
        finally:
            process.fd = -1
            process.closed = True
            child.child_fd = -1
            child.closed = True
            evidence.cleanup_seconds = time.monotonic() - started


def run_session(
    target: Path,
    commands: Sequence[Command] = (),
    *,
    initial_prompt: str = "cwushell>",
    timeout: float = 10.0,
    session_timeout: float | None = None,
    max_output_bytes: int = 1048576,
    environment: Mapping[str, str] | None = None,
    fixtures: Sequence[Fixture] = (),
    controlled_environment: Mapping[str, str | None] | None = None,
    terminal_type: Literal["dumb", "xterm"] = "dumb",
) -> Evidence:
    """Execute a finite plan in a fresh temporary directory and return evidence.

    Startup timeout permits the spec's first-command fallback. All later timeouts
    stop dispatch. EOF is recorded even when unexpected; it is never a timeout.
    An optional smaller total budget can stop a stateful sequence early.
    Fixtures are prepared and observed before launch, then observed again after
    process/PTY cleanup. Controlled environment None values remove inherited keys.
    Terminal/locale settings always take precedence over caller environment values.
    """
    plan = tuple(commands)
    total = (1 + len(plan)) * timeout
    if session_timeout is not None:
        if not math.isfinite(session_timeout) or session_timeout <= 0:
            raise ValueError("session timeout must be positive and finite")
        total = min(total, session_timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not math.isfinite(total) or total <= 0:
        raise ValueError("session timeout must be positive and finite")
    if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise ValueError("capture limit must be a positive integer")
    if not initial_prompt or any(command.prompt == "" for command in plan):
        raise ValueError("expected prompts must be nonempty literals")
    if any("\n" in command.text or "\r" in command.text for command in plan):
        raise ValueError("commands must contain exactly one input line")
    if terminal_type not in ("dumb", "xterm"):
        raise ValueError("terminal type must be dumb or xterm")
    for command in plan:
        if command.actions:
            if command.actions[-1] != Action("enter", b"\n"):
                raise ValueError("action plans must end with one explicit Enter LF")
            for action_index, action in enumerate(command.actions):
                if action.kind not in ("type", "key", "enter") or not action.data:
                    raise ValueError("actions require a known kind and nonempty bytes")
                if action.kind == "enter" and action_index != len(command.actions) - 1:
                    raise ValueError("Enter must terminate the interaction")
                if action.kind != "enter" and any(
                    b in action.data for b in (b"\n", b"\r")
                ):
                    raise ValueError("only Enter may submit an action plan")
    fixture_plan = tuple(fixtures)
    session_fixtures.validate_fixtures(fixture_plan)
    executable = target.resolve()
    evidence = Evidence(max_output_bytes, undispatched=[c.text for c in plan])
    evidence.action_dispatch = [
        ActionDispatch(command_index, action_index, action)
        for command_index, command in enumerate(plan, 1)
        for action_index, action in enumerate(command.input_actions, 1)
    ]
    evidence.terminal_profile = (
        f"{terminal_type}; 24x80; launch echo disabled; inherited termios; "
        "literal key bytes (no remapping)"
    )
    env = dict(os.environ if environment is None else environment)
    evidence.fixtures = fixture_plan
    evidence.controlled_environment = dict(controlled_environment or {})
    evidence.controlled_environment.update(session_fixtures.TERMINAL_ENVIRONMENT)
    evidence.controlled_environment["TERM"] = terminal_type
    for name, value in evidence.controlled_environment.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    child: pexpect.spawn | None = None
    started = time.monotonic()
    interaction_started = started
    with tempfile.TemporaryDirectory(prefix="cwushell-test-") as directory:
        evidence.working_directory = directory
        try:
            session_fixtures.prepare(Path(directory), fixture_plan)
            evidence.file_observations = tuple(
                session_fixtures.snapshot(Path(directory), fixture.path, "before")
                for fixture in fixture_plan
            )
            child = pexpect.spawn(
                # pexpect splits its command even with args=[]. Quote the sole
                # executable for that parser; no shell or extra argument is used.
                shlex.quote(str(executable)),
                cwd=directory,
                env=env,
                encoding=None,
                echo=False,
                dimensions=(24, 80),
                maxread=READ_BYTES,
            )
            interaction_started = time.monotonic()
            evidence.launch_seconds = interaction_started - started
            session_deadline = interaction_started + total
            evidence.pid = child.pid
            assert child.pid is not None
            if (
                os.getpgid(child.pid) != child.pid
                or os.getsid(child.pid) != child.pid
                or child.pid == os.getpgrp()
            ):
                raise RuntimeError("PTY launcher did not create an owned process group")
            evidence.pgid = child.pid
            child.setecho(False)
            os.set_blocking(child.child_fd, False)
            _observe_terminal(child, evidence, "Initial after launch echo suppression")
            reader = _Reader(child, evidence)
            deadline = min(session_deadline, interaction_started + timeout)
            event = reader.wait(initial_prompt, deadline)
            if event == "TIMEOUT" and not child.isalive():
                event = "EOF"
            evidence.interactions.append(Interaction(None, event, initial_prompt))
            evidence.reason = event
            _observe_terminal(child, evidence, "After startup wait")
            if event != "EOF":
                for command_index, command in enumerate(plan, 1):
                    now = time.monotonic()
                    if now >= session_deadline:
                        evidence.interactions.append(
                            Interaction(command.text, "TIMEOUT", "command dispatch")
                        )
                        evidence.reason = "TIMEOUT"
                        break
                    deadline = min(session_deadline, now + timeout)
                    records = [
                        record
                        for record in evidence.action_dispatch
                        if record.command_index == command_index
                    ]
                    dispatch_event = "SENT"
                    for record in records:
                        dispatch_event = (
                            _dispatch(child, record, deadline)
                            if child.isalive()
                            else "EOF"
                        )
                        if dispatch_event != "SENT":
                            break
                    if dispatch_event != "SENT":
                        reader.collect_available()
                        event = (
                            "EOF"
                            if dispatch_event == "EOF" or not child.isalive()
                            else "TIMEOUT"
                        )
                        evidence.interactions.append(
                            Interaction(command.text, event, "command dispatch")
                        )
                        evidence.reason = event
                        _observe_terminal(
                            child,
                            evidence,
                            f"After input {command_index} dispatch stopped",
                        )
                        break
                    evidence.dispatched.append(command.text)
                    evidence.undispatched.pop(0)
                    event = reader.wait(command.prompt, deadline)
                    evidence.interactions.append(
                        Interaction(command.text, event, command.prompt or "EOF")
                    )
                    evidence.reason = event
                    _observe_terminal(
                        child, evidence, f"After input {command_index} wait"
                    )
                    if event != "PROMPT":
                        break
            if evidence.reason == "PROMPT":
                evidence.reason = "COMPLETED"
            # Slave EOF can precede the kernel making an exiting child waitable.
            # Give status a short grace within the existing interaction deadline;
            # EOF from a live process must still never turn into blocking waitpid.
            if evidence.reason == "EOF":
                status_deadline = min(deadline, time.monotonic() + EOF_STATUS_GRACE)
                while child.isalive() and time.monotonic() < status_deadline:
                    time.sleep(
                        min(POLL_INTERVAL, max(0.0, status_deadline - time.monotonic()))
                    )
            # Preserve observed termination separately from cleanup-generated signals.
            if not child.isalive():
                evidence.exit_status = child.exitstatus
                evidence.signal_status = child.signalstatus
        except Exception as exc:
            evidence.reason = "ERROR"
            evidence.error = f"{type(exc).__name__}: {exc}"
            evidence.notes += (
                f"Session preparation/execution in {directory}: {evidence.error}",
            )
        finally:
            evidence.interaction_seconds = time.monotonic() - interaction_started
            try:
                if child is not None:
                    _cleanup(child, evidence)
            finally:
                # A partial preparation failure still retains both available phases.
                if not evidence.file_observations:
                    evidence.file_observations = tuple(
                        session_fixtures.snapshot(
                            Path(directory), fixture.path, "before"
                        )
                        for fixture in fixture_plan
                    )
                evidence.file_observations += tuple(
                    session_fixtures.snapshot(Path(directory), fixture.path, "after")
                    for fixture in fixture_plan
                )
    return evidence
