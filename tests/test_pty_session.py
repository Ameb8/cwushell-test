"""Real Linux PTY contract checks independent of suites and scoring."""

import os
import signal
import time
from pathlib import Path

import pytest

import pty_session as pty
from pty_session import Command, clean_output, run_session

SHELL = Path(__file__).parent / "fixtures" / "mock_shell.py"
pytestmark = pytest.mark.integration
# Scheduling tolerance is additional to the separately bounded 0.4s cleanup.
SCHEDULING_TOLERANCE = 0.25


@pytest.fixture(autouse=True)
def owned_sessions(monkeypatch):
    """Test-side containment still runs after assertions or outer timeout failures."""
    children = []
    spawn = pty.pexpect.spawn

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(pty.pexpect, "spawn", record)
    try:
        yield children
    finally:
        for child in children:
            try:
                assert child.pid is not None
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.close(force=True)


def assert_released(result, children):
    assert result.pid is not None
    with pytest.raises(ProcessLookupError):
        os.kill(result.pid, 0)
    child = children[-1]
    assert child.closed
    assert child.child_fd == -1
    assert not Path(result.working_directory).exists()


def test_initial_changed_reset_prompts_and_expected_eof(owned_sessions):
    result = run_session(
        SHELL,
        [
            Command("prompt new>", "new>"),
            Command("hello", "new>"),
            Command("prompt"),
            Command("exit", None),
        ],
        timeout=1,
    )
    assert [event.reason for event in result.interactions] == [
        "PROMPT",
        "PROMPT",
        "PROMPT",
        "PROMPT",
        "EOF",
    ]
    assert result.reason == "EOF"
    assert result.exit_status == 42
    assert result.signal_status is None
    assert result.undispatched == []
    assert result.output.startswith("startup evidence\n")
    assert "goodbye\n" in result.output
    assert "hello" not in result.output
    assert_released(result, owned_sessions)


def test_sequential_pacing_and_partial_output():
    result = run_session(
        SHELL, [Command("paced"), Command("slow"), Command("unique input")], timeout=1
    )
    assert result.reason == "COMPLETED"
    assert result.dispatched == ["paced", "slow", "unique input"]
    assert "begin\nend\ncwushell>partial output\n" in result.output
    assert "INTERLEAVED" not in result.output
    assert "unique input" not in result.output
    assert "student response" in result.output


def test_ansi_prompt_and_startup_capture():
    result = run_session(
        SHELL,
        [Command("ansi")],
        timeout=1,
        environment={**os.environ, "MOCK_MODE": "ansi"},
    )
    assert result.reason == "COMPLETED"
    assert result.output == "startup evidence\ncwushell>meaningful\n\ncwushell>"
    assert b"\x1b[32m" in result.raw_output
    assert "\x1b" not in result.output


@pytest.mark.parametrize("command", ["stream", "trickle"])
def test_output_does_not_extend_interaction_deadline(command, owned_sessions):
    started = time.monotonic()
    result = run_session(
        SHELL,
        [Command(command), Command("never sent")],
        timeout=0.2,
        max_output_bytes=64,
    )
    elapsed = time.monotonic() - started - result.launch_seconds
    assert result.reason == "TIMEOUT"
    assert result.dispatched == [command]
    assert result.undispatched == ["never sent"]
    assert len(result.raw_output) <= 64
    if command == "stream":
        assert result.truncated
    assert elapsed <= 0.2 + SCHEDULING_TOLERANCE + 2 * pty.CLEANUP_GRACE
    assert_released(result, owned_sessions)


def test_prompt_synchronization_after_capture_truncation():
    result = run_session(
        SHELL, [Command("flood"), Command("exit", None)], timeout=1, max_output_bytes=17
    )
    assert result.reason == "EOF"
    assert result.raw_output == b"startup evidence\r"
    assert result.truncated
    assert result.dispatched == ["flood", "exit"]
    assert result.max_output_bytes == 17
    assert result.exit_status == 42


@pytest.mark.parametrize("mode", ["normal", "missing", "hang"])
def test_total_session_budget_is_not_reset(mode, owned_sessions):
    started = time.monotonic()
    result = run_session(
        SHELL,
        [Command("slow")] * 10,
        timeout=0.2,
        session_timeout=0.35,
        environment={**os.environ, "MOCK_MODE": mode},
    )
    elapsed = time.monotonic() - started - result.launch_seconds
    assert result.reason == "TIMEOUT"
    assert result.interaction_seconds <= 0.35 + SCHEDULING_TOLERANCE
    assert result.cleanup_seconds <= 2 * pty.CLEANUP_GRACE + SCHEDULING_TOLERANCE
    assert elapsed <= 0.35 + 2 * pty.CLEANUP_GRACE + SCHEDULING_TOLERANCE
    assert result.undispatched
    assert_released(result, owned_sessions)


def test_initial_missing_prompt_uses_first_command_fallback():
    result = run_session(
        SHELL,
        [Command("hello"), Command("exit", None)],
        timeout=0.15,
        environment={**os.environ, "MOCK_MODE": "missing"},
    )
    assert result.interactions[0].reason == "TIMEOUT"
    assert result.dispatched == ["hello", "exit"]
    assert result.reason == "EOF"
    assert result.output.startswith("startup evidence\nstudent response\n")


def test_mismatched_command_prompt_stops_sequence_with_evidence():
    result = run_session(
        SHELL, [Command("hello", "wrong>"), Command("never")], timeout=0.15
    )
    assert result.reason == "TIMEOUT"
    assert result.interactions[-1].waiting_for == "wrong>"
    assert result.dispatched == ["hello"]
    assert result.undispatched == ["never"]
    assert "student response\ncwushell>" in result.output


def test_startup_only_missing_prompt_is_bounded():
    result = run_session(
        SHELL, timeout=0.15, environment={**os.environ, "MOCK_MODE": "hang"}
    )
    assert result.reason == "TIMEOUT"
    assert result.dispatched == []
    assert result.output == "startup evidence\n"


def test_exception_releases_session_preserves_evidence(monkeypatch, owned_sessions):
    wait = pty._Reader.wait

    def broken_read(self, prompt, deadline):
        if self.evidence.interactions:
            raise RuntimeError("injected read failure")
        return wait(self, prompt, deadline)

    monkeypatch.setattr(pty._Reader, "wait", broken_read)
    result = run_session(SHELL, [Command("hello")], timeout=1)
    assert result.reason == "ERROR"
    assert result.error == "RuntimeError: injected read failure"
    assert "startup evidence" in result.output
    assert result.dispatched == ["hello"]
    assert result.exit_status is None
    assert result.signal_status is None
    assert_released(result, owned_sessions)


def test_crash_does_not_prevent_fresh_session(owned_sessions):
    result = run_session(SHELL, [Command("crash"), Command("never")], timeout=1)
    assert result.reason == "EOF"
    assert result.signal_status == signal.SIGSEGV
    assert result.undispatched == ["never"]
    assert_released(result, owned_sessions)
    fresh = run_session(SHELL, [Command("hello")], timeout=1)
    assert fresh.reason == "COMPLETED"
    assert fresh.pid != result.pid
    assert fresh.working_directory != result.working_directory


def test_spawn_failure_retains_error_and_removes_directory(tmp_path):
    result = run_session(tmp_path / "missing")
    assert result.reason == "ERROR"
    assert result.error is not None
    assert result.pid is None
    assert not Path(result.working_directory).exists()


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"a\r\nb\rc\n", "a\nb\nc\n"),
        (b"\x1b[1;32mgreen\x1b[0m\x1b[K", "green"),
        (b"\x1b]title\x1b\\text\x1bPignored\x1b\\", "text"),
        (b"text\x1b]unterminated", "text"),
        (b"\x1b(Bplain\xff", "plain\ufffd"),
        ("café\tvalue".encode(), "café\tvalue"),
    ],
)
def test_cleaning_preserves_meaningful_text(raw, expected):
    assert clean_output(raw) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout": 0},
        {"timeout": float("nan")},
        {"session_timeout": float("inf")},
        {"session_timeout": 0},
        {"max_output_bytes": 0},
        {"initial_prompt": ""},
        {"commands": [Command("one\ntwo")]},
        {"commands": [Command("x", "")]},
    ],
)
def test_invalid_limits_and_plans_do_not_spawn(kwargs, owned_sessions):
    with pytest.raises(ValueError):
        run_session(SHELL, **kwargs)
    assert owned_sessions == []


def test_startup_exit_preserves_output_and_undispatched_commands(owned_sessions):
    result = run_session(
        SHELL,
        [Command("never")],
        timeout=1,
        environment={**os.environ, "MOCK_MODE": "startup_exit"},
    )
    assert result.reason == "EOF"
    assert result.exit_status == 17
    assert result.dispatched == []
    assert result.undispatched == ["never"]
    assert result.output == "startup evidence\n"
    assert_released(result, owned_sessions)


def test_eof_from_live_process_does_not_block_cleanup(owned_sessions):
    result = run_session(SHELL, [Command("close_tty", None)], timeout=0.2)
    assert result.reason == "EOF"
    assert result.exit_status is None
    assert result.signal_status is None
    assert result.interaction_seconds <= 0.2 + SCHEDULING_TOLERANCE
    assert_released(result, owned_sessions)


def test_interruption_propagates_after_cleanup(monkeypatch, owned_sessions):
    def interrupted(self, prompt, deadline):
        raise KeyboardInterrupt

    monkeypatch.setattr(pty._Reader, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_session(SHELL)
    child = owned_sessions[-1]
    assert child.closed
    assert child.child_fd == -1
    with pytest.raises(ProcessLookupError):
        assert child.pid is not None
        os.kill(child.pid, 0)


def test_repeated_sessions_release_descriptors():
    before = len(list(Path("/proc/self/fd").iterdir()))
    for _ in range(3):
        result = run_session(SHELL, [Command("hello")], timeout=1)
        assert result.reason == "COMPLETED"
        assert result.exit_status is None
        assert result.signal_status is None
        assert result.cleanup_actions
    after = len(list(Path("/proc/self/fd").iterdir()))
    assert after == before


def test_pacing_fixture_detects_deliberate_interleaving(tmp_path):
    child = pty.pexpect.spawn(str(SHELL.resolve()), cwd=str(tmp_path), echo=False)
    child.expect_exact(b"cwushell>", timeout=1)
    child.send(b"paced\nhello\n")
    child.expect_exact(b"INTERLEAVED", timeout=1)
