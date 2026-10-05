"""Bounded, evidence-only PTY interactions for one independent scenario."""

import errno
import math
import os
import re
import select
import signal
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import pexpect

READ_BYTES = 4096
CLEANUP_GRACE = 0.2  # TERM and KILL each get this bounded grace period.
POLL_INTERVAL = 0.01
EOF_STATUS_GRACE = 0.05
# Complete ECMA-48 CSI, control strings, and ordinary ESC sequences. Streaming
# state below also removes an incomplete escape at the retained prefix boundary.
ANSI = re.compile(
    rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|"
    rb"[\]PX^_](?:[^\x1b\x07]|\x1b(?!\\))*(?:\x07|\x1b\\)|"
    rb"(?![\[\]PX^_])[ -/]*[0-~])"
)


@dataclass(frozen=True)
class Command:
    """One line of input; None means wait for EOF instead of a literal prompt."""

    text: str
    prompt: str | None = "cwushell>"


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

    def wait(self, prompt: str | None, deadline: float) -> str:
        needle = prompt.encode("utf-8") if prompt is not None else None
        tail = b""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "TIMEOUT"
            # Read the pexpect-owned descriptor directly. pexpect's read path
            # sets ptyprocess.flag_eof, which turns subsequent isalive() calls
            # into blocking waitpid even if a live process merely closed its TTY.
            readable, _, _ = select.select([self.child.child_fd], [], [], remaining)
            if not readable:
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
            capacity = self.evidence.max_output_bytes - len(self.evidence.raw_output)
            self.evidence.raw_output += data[:capacity]
            if len(data) > capacity:
                self.evidence.truncated = True
            cleaned = self.cleaner.feed(data)
            if needle is not None:
                window = tail + cleaned
                if needle in window:
                    return "PROMPT"
                tail = window[-(len(needle) - 1) :] if len(needle) > 1 else b""


def _dispatch(child: pexpect.spawn, text: str, deadline: float) -> bool:
    """Bound even writes to a target that stops reading its terminal."""
    data = (text + "\n").encode("utf-8")
    offset = 0
    while offset < len(data):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        _, writable, _ = select.select([], [child.child_fd], [], remaining)
        if writable:
            try:
                offset += os.write(child.child_fd, data[offset : offset + READ_BYTES])
            except BlockingIOError:
                continue
    return True


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
) -> Evidence:
    """Execute a finite plan in a fresh temporary directory and return evidence.

    Startup timeout permits the spec's first-command fallback. All later timeouts
    stop dispatch. EOF is recorded even when unexpected; it is never a timeout.
    An optional smaller total budget can stop a stateful sequence early.
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
    if max_output_bytes <= 0:
        raise ValueError("capture limit must be positive")
    if not initial_prompt or any(command.prompt == "" for command in plan):
        raise ValueError("expected prompts must be nonempty literals")
    if any("\n" in command.text or "\r" in command.text for command in plan):
        raise ValueError("commands must contain exactly one input line")
    executable = target.resolve()
    evidence = Evidence(max_output_bytes, undispatched=[c.text for c in plan])
    env = dict(os.environ if environment is None else environment)
    env.update(TERM="dumb", LC_ALL="C", LANG="C")
    child: pexpect.spawn | None = None
    started = time.monotonic()
    interaction_started = started
    with tempfile.TemporaryDirectory(prefix="cwushell-test-") as directory:
        evidence.working_directory = directory
        try:
            child = pexpect.spawn(
                str(executable),
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
            reader = _Reader(child, evidence)
            deadline = min(session_deadline, interaction_started + timeout)
            event = reader.wait(initial_prompt, deadline)
            if event == "TIMEOUT" and not child.isalive():
                event = "EOF"
            evidence.interactions.append(Interaction(None, event, initial_prompt))
            evidence.reason = event
            if event != "EOF":
                for command in plan:
                    now = time.monotonic()
                    if now >= session_deadline:
                        evidence.reason = "TIMEOUT"
                        break
                    deadline = min(session_deadline, now + timeout)
                    if not _dispatch(child, command.text, deadline):
                        evidence.interactions.append(
                            Interaction(command.text, "TIMEOUT", "command dispatch")
                        )
                        evidence.reason = "TIMEOUT"
                        break
                    evidence.dispatched.append(command.text)
                    evidence.undispatched.pop(0)
                    event = reader.wait(command.prompt, deadline)
                    evidence.interactions.append(
                        Interaction(command.text, event, command.prompt or "EOF")
                    )
                    evidence.reason = event
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
        finally:
            evidence.interaction_seconds = time.monotonic() - interaction_started
            if child is not None:
                _cleanup(child, evidence)
    return evidence
