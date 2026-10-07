"""Real Linux PTY contract checks independent of suites and scoring."""

import ctypes
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path

import pytest

from cwushell_test import pty_session as pty
from cwushell_test.evidence import CaseEvidence
from cwushell_test.fixtures import (
    CD_FIXTURES,
    EXPORT_ENVIRONMENT,
    EXTERNAL_FIXTURES,
    UNSET_ENVIRONMENT,
    Fixture,
)
from cwushell_test.pty_session import Command, clean_output, run_session

SHELL = Path(__file__).parent / "fixtures" / "mock_shell.py"
pytestmark = pytest.mark.integration
# Scheduling tolerance is additional to the separately bounded 0.4s cleanup.
SCHEDULING_TOLERANCE = 0.25


@pytest.fixture(autouse=True)
def owned_sessions(monkeypatch):
    """Test-side containment still runs after assertions or outer timeout failures."""
    # Test-only subreaper owns orphaned fixture descendants, even on hosts whose
    # PID 1 does not reap zombies. Production does not adopt arbitrary children.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
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
        try:
            for child in children:
                assert child.pid is not None
                assert child.pid != os.getpgrp()
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.close(force=True)
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    members = group_members(child.pid)
                    if not members:
                        break
                    for pid in members:
                        try:
                            os.waitpid(pid, os.WNOHANG)
                        except ChildProcessError:
                            pass
                    time.sleep(0.01)
                assert not group_members(child.pid)
        finally:
            assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def group_members(pgid):
    members = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            continue
        if int(fields[2]) == pgid:
            members[int(entry.name)] = fields[0]
    return members


def assert_released(result, children):
    assert result.pid is not None
    with pytest.raises(ProcessLookupError):
        os.kill(result.pid, 0)
    child = children[-1]
    assert child.closed
    assert child.child_fd == -1
    assert result.direct_child_reaped
    with pytest.raises(ChildProcessError):
        os.waitpid(result.pid, os.WNOHANG)
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


def test_executable_path_with_spaces_and_quotes(tmp_path: Path, owned_sessions):
    target = tmp_path / "shell with 'quotes' and spaces"
    shutil.copyfile(SHELL, target)
    target.chmod(0o700)
    result = run_session(target, [Command("exit", None)], timeout=1)
    assert result.dispatched == ["exit"]
    assert result.exit_status == 42
    assert result.error is None
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


def test_startup_only_missing_prompt_is_bounded(owned_sessions):
    # Allow the synthetic Python target to initialize before asserting its text.
    timeout = 1.0
    result = run_session(
        SHELL, timeout=timeout, environment={**os.environ, "MOCK_MODE": "hang"}
    )
    assert result.reason == "TIMEOUT"
    assert result.dispatched == []
    assert result.output == "startup evidence\n"
    assert result.interaction_seconds <= timeout + SCHEDULING_TOLERANCE
    assert result.cleanup_seconds <= 2 * pty.CLEANUP_GRACE + SCHEDULING_TOLERANCE
    assert_released(result, owned_sessions)


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
        {"max_output_bytes": 1.5},
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


@pytest.mark.parametrize(
    "command, reason, status, death, forced",
    [
        ("child_exit", "EOF", 23, None, False),
        ("child_exit_resist", "EOF", 23, None, True),
        ("child_exit_tty_resist", "TIMEOUT", 23, None, True),
        ("child_crash_resist", "EOF", None, signal.SIGSEGV, True),
        ("child_hang_resist", "TIMEOUT", None, None, True),
        ("child_ready_resist", "COMPLETED", None, None, True),
        ("resist", "TIMEOUT", None, None, True),
    ],
)
def test_fault_group_cleanup_and_fresh_session(
    command, reason, status, death, forced, owned_sessions
):
    before = len(list(Path("/proc/self/fd").iterdir()))
    for _ in range(2):
        result = run_session(
            SHELL,
            [Command(command, None if reason == "EOF" else "cwushell>")],
            timeout=0.3,
        )
        assert result.reason == reason
        assert result.exit_status == status
        assert result.signal_status == death
        assert result.pgid == result.pid
        assert result.pgid != os.getpgrp()
        assert result.cleanup_error is None
        assert "SIGTERM" in result.cleanup_actions
        if forced:
            assert "SIGKILL" in result.cleanup_actions
        if status is not None or death is not None:
            assert result.cleanup_exit_status is None
            assert result.cleanup_signal_status is None
        else:
            assert result.cleanup_signal_status in (signal.SIGTERM, signal.SIGKILL)
        assert result.cleanup_seconds <= 2 * pty.CLEANUP_GRACE + SCHEDULING_TOLERANCE
        assert result.interaction_seconds <= 0.6 + SCHEDULING_TOLERANCE
        members = re.search(r"member (\d+) group (\d+)", result.output)
        if command.startswith("child_"):
            assert members is not None
            assert int(members[2]) == result.pgid
        assert all(state == "Z" for state in group_members(result.pgid).values())
        assert_released(result, owned_sessions)
        saved = (
            list(result.cleanup_actions),
            result.cleanup_seconds,
            result.exit_status,
            result.signal_status,
        )
        pty._cleanup(owned_sessions[-1], result)
        owned_sessions[-1].close()
        assert (
            result.cleanup_actions,
            result.cleanup_seconds,
            result.exit_status,
            result.signal_status,
        ) == saved
        fresh = run_session(SHELL, [Command("exit", None)], timeout=1)
        assert fresh.exit_status == 42
        assert fresh.reason == "EOF"
        assert_released(fresh, owned_sessions)
    assert len(list(Path("/proc/self/fd").iterdir())) == before


def test_exception_with_surviving_group_member(monkeypatch, owned_sessions):
    wait = pty._Reader.wait

    def broken_after_ready(self, prompt, deadline):
        event = wait(self, prompt, deadline)
        if self.evidence.interactions:
            raise RuntimeError("fault after descendant ready")
        return event

    monkeypatch.setattr(pty._Reader, "wait", broken_after_ready)
    result = run_session(SHELL, [Command("child_ready_resist")], timeout=1)
    assert result.reason == "ERROR"
    assert result.cleanup_actions == ["SIGTERM", "SIGKILL"]
    assert result.exit_status is None
    assert result.signal_status is None
    assert result.cleanup_error is None
    assert all(state == "Z" for state in group_members(result.pgid).values())
    assert_released(result, owned_sessions)
    monkeypatch.setattr(pty._Reader, "wait", wait)
    assert run_session(SHELL, [Command("exit", None)], timeout=1).exit_status == 42


@pytest.mark.parametrize("unrelated", [False, True])
def test_unverified_group_never_signaled(monkeypatch, owned_sessions, unrelated):
    sentinel = None
    unowned_pgid = os.getpgrp()
    if unrelated:
        sentinel = pty.pexpect.spawn(
            sys.executable, ["-c", "import signal; signal.pause()"]
        )
        assert sentinel.pid is not None
        unowned_pgid = sentinel.pid
    calls = []
    killpg = os.killpg

    def record_group(pgid, sig):
        calls.append(pgid)
        return killpg(pgid, sig)

    monkeypatch.setattr(pty.os, "getpgid", lambda pid: unowned_pgid)
    monkeypatch.setattr(pty.os, "killpg", record_group)
    result = run_session(SHELL, timeout=1)
    assert result.reason == "ERROR"
    assert result.pgid is None
    assert calls == []
    if sentinel is not None:
        assert sentinel.isalive()
    assert result.cleanup_error is None
    assert_released(result, owned_sessions)
    monkeypatch.undo()
    assert run_session(SHELL, [Command("exit", None)], timeout=1).exit_status == 42


def test_exception_after_observed_exit_retains_status(monkeypatch, owned_sessions):
    wait = pty._Reader.wait

    def broken_after_exit(self, prompt, deadline):
        event = wait(self, prompt, deadline)
        if event == "EOF":
            deadline = time.monotonic() + 0.2
            while self.child.isalive() and time.monotonic() < deadline:
                time.sleep(0.001)
            raise RuntimeError("fault after observed exit")
        return event

    monkeypatch.setattr(pty._Reader, "wait", broken_after_exit)
    result = run_session(SHELL, [Command("exit", None)], timeout=1)
    assert result.reason == "ERROR"
    assert result.exit_status == 42
    assert result.signal_status is None
    assert result.cleanup_signal_status is None
    assert_released(result, owned_sessions)


@pytest.mark.parametrize("fault", ["blocked_dispatch", "ignored_exit"])
def test_dispatch_and_expected_exit_faults_are_contained(fault, owned_sessions):
    before = len(list(Path("/proc/self/fd").iterdir()))
    blocked_line = "x" * (128 * 1024)
    for _ in range(2):
        plan = (
            [Command("stop_reading"), Command(blocked_line), Command("never")]
            if fault == "blocked_dispatch"
            else [Command("exit", None), Command("never")]
        )
        result = run_session(
            SHELL,
            plan,
            timeout=0.2,
            session_timeout=0.5,
            max_output_bytes=128,
            environment={
                **os.environ,
                "MOCK_MODE": "ignore_exit" if fault == "ignored_exit" else "normal",
            },
        )
        assert result.reason == "TIMEOUT"
        assert result.interactions[-1].reason == "TIMEOUT"
        if fault == "blocked_dispatch":
            assert result.interactions[-1].waiting_for == "command dispatch"
            assert result.dispatched == ["stop_reading"]
            assert result.undispatched == [blocked_line, "never"]
            assert "not reading\n" in result.output
            assert "x" not in result.output  # Raw input still has echo disabled.
        else:
            assert result.interactions[-1].waiting_for == "EOF"
            assert result.dispatched == ["exit"]
            assert result.undispatched == ["never"]
            assert "exit ignored\ncwushell>" in result.output
        assert result.exit_status is None
        assert result.signal_status is None
        assert result.cleanup_signal_status == signal.SIGTERM
        assert result.cleanup_error is None
        assert result.interaction_seconds <= 0.5 + SCHEDULING_TOLERANCE
        assert result.cleanup_seconds <= 2 * pty.CLEANUP_GRACE + SCHEDULING_TOLERANCE
        assert not group_members(result.pgid)
        assert_released(result, owned_sessions)

        fresh = run_session(
            SHELL,
            [Command("prompt recovered>", "recovered>"), Command("exit", None)],
            timeout=1,
        )
        assert fresh.reason == "EOF"
        assert fresh.exit_status == 42
        assert [event.reason for event in fresh.interactions] == [
            "PROMPT",
            "PROMPT",
            "EOF",
        ]
        assert "prompt recovered>" not in fresh.output
        assert fresh.pid != result.pid
        assert fresh.working_directory != result.working_directory
        assert_released(fresh, owned_sessions)
    assert len(list(Path("/proc/self/fd").iterdir())) == before


def observation(result, path, phase):
    return next(
        item
        for item in result.file_observations
        if item.path == path and item.phase == phase
    )


def test_fixture_isolation_and_case_contract(owned_sessions):
    first = run_session(
        SHELL, [Command("fixture_mutate")], fixtures=EXTERNAL_FIXTURES, timeout=1
    )
    second = run_session(SHELL, fixtures=EXTERNAL_FIXTURES, timeout=1)
    assert first.working_directory != second.working_directory
    for result in (first, second):
        assert (
            observation(result, "source.txt", "before").contents
            == EXTERNAL_FIXTURES[0].contents
        )
        assert (
            observation(result, "removable.txt", "before").contents
            == EXTERNAL_FIXTURES[1].contents
        )
        assert observation(result, "copied.txt", "before").exists is False
        assert not Path(result.working_directory).exists()
    assert observation(first, "source.txt", "after").contents == b"changed\x00bytes\r\n"
    assert (
        observation(first, "copied.txt", "after").contents
        == EXTERNAL_FIXTURES[0].contents
    )
    assert observation(first, "removable.txt", "after").exists is False
    assert (
        observation(second, "source.txt", "after").contents
        == EXTERNAL_FIXTURES[0].contents
    )
    assert observation(second, "removable.txt", "after").exists is True
    assert observation(second, "copied.txt", "after").exists is False
    case = CaseEvidence(
        "synthetic", "T6", "Fixture observations", (Command("fixture_mutate"),), first
    )
    assert case.fixtures == first.fixtures == EXTERNAL_FIXTURES
    assert case.file_observations == first.file_observations
    assert case.controlled_environment == first.controlled_environment
    assert first.dispatched == ["fixture_mutate"]
    assert_released(second, owned_sessions)


def test_fixture_environment_directory_and_relative_target(monkeypatch, owned_sessions):
    monkeypatch.setenv("CWUSHELL_TEST_EXPORT", "inherited")
    monkeypatch.setenv("CWUSHELL_TEST_UNSET", "inherited")
    monkeypatch.setenv("TERM", "inherited")
    result = run_session(
        SHELL.relative_to(Path.cwd()),
        [Command("fixture_state")],
        fixtures=CD_FIXTURES,
        controlled_environment={
            **EXPORT_ENVIRONMENT,
            **UNSET_ENVIRONMENT,
            "TERM": "override",
        },
        timeout=1,
    )
    assert f"cwd={result.working_directory}\n" in result.output
    assert "CWUSHELL_TEST_EXPORT=<absent>\n" in result.output
    assert "CWUSHELL_TEST_UNSET=fixture_value\n" in result.output
    assert "TERM=dumb\nLC_ALL=C\nLANG=C\n" in result.output
    assert "fixture_dir_empty=True\n" in result.output
    assert result.controlled_environment == {
        "CWUSHELL_TEST_EXPORT": None,
        "CWUSHELL_TEST_UNSET": "fixture_value",
        "TERM": "dumb",
        "LC_ALL": "C",
        "LANG": "C",
    }
    assert os.environ["CWUSHELL_TEST_EXPORT"] == "inherited"
    for phase in ("before", "after"):
        assert observation(result, "fixture_dir", phase).exists is True
        assert observation(result, "fixture_dir", phase).contents is None
    assert_released(result, owned_sessions)


def test_fixture_snapshot_after_cleanup_before_removal(monkeypatch, owned_sessions):
    from cwushell_test import fixtures

    snapshot = fixtures.snapshot
    phases = []

    def record(directory, path, phase):
        assert directory.exists()
        if phase == "before":
            assert owned_sessions == []
        else:
            assert owned_sessions[-1].closed
            with pytest.raises(ChildProcessError):
                os.waitpid(owned_sessions[-1].pid, os.WNOHANG)
        phases.append(phase)
        return snapshot(directory, path, phase)

    monkeypatch.setattr(fixtures, "snapshot", record)
    result = run_session(
        SHELL, [Command("fixture_term")], fixtures=EXTERNAL_FIXTURES, timeout=1
    )
    assert phases == ["before"] * 3 + ["after"] * 3
    assert (
        observation(result, "copied.txt", "after").contents
        == b"written during cleanup\n"
    )
    assert_released(result, owned_sessions)


@pytest.mark.parametrize("fault", ["stream", "crash", "exception"])
def test_fixture_observations_survive_execution_faults(
    fault, monkeypatch, owned_sessions
):
    if fault == "exception":
        original = pty._Reader.wait

        def fail_after_mutation(self, prompt, deadline):
            event = original(self, prompt, deadline)
            if self.evidence.dispatched:
                raise RuntimeError("injected after mutation")
            return event

        monkeypatch.setattr(pty._Reader, "wait", fail_after_mutation)
        commands = [Command("fixture_mutate")]
    else:
        commands = [Command("fixture_mutate"), Command(fault)]
    result = run_session(SHELL, commands, fixtures=EXTERNAL_FIXTURES, timeout=1)
    assert (
        result.reason
        == {"stream": "TIMEOUT", "crash": "EOF", "exception": "ERROR"}[fault]
    )
    assert (
        observation(result, "copied.txt", "after").contents
        == EXTERNAL_FIXTURES[0].contents
    )
    assert observation(result, "removable.txt", "after").exists is False
    assert_released(result, owned_sessions)


def test_fixture_partial_preparation_error(monkeypatch, owned_sessions):
    from cwushell_test import fixtures

    def fail(directory, plan):
        (directory / plan[0].path).write_bytes(b"partial")
        raise PermissionError("injected fixture write denied")

    monkeypatch.setattr(fixtures, "prepare", fail)
    result = run_session(SHELL, [Command("unused")], fixtures=EXTERNAL_FIXTURES)
    assert result.reason == "ERROR"
    assert result.error is not None and "fixture write denied" in result.error
    assert result.notes and result.working_directory in result.notes[0]
    assert result.undispatched == ["unused"]
    assert owned_sessions == []
    assert observation(result, "source.txt", "before").contents == b"partial"
    assert observation(result, "source.txt", "after").contents == b"partial"
    assert observation(result, "removable.txt", "before").exists is False
    assert not Path(result.working_directory).exists()


@pytest.mark.parametrize("command", ["fixture_fifo", "fixture_symlink"])
def test_fixture_nonregular_observations_are_bounded(command, owned_sessions):
    result = run_session(
        SHELL, [Command(command)], fixtures=EXTERNAL_FIXTURES, timeout=1
    )
    item = observation(result, "copied.txt", "after")
    assert item.exists is True
    assert item.contents is None
    assert item.error is not None and "Not a regular file" in item.error
    assert_released(result, owned_sessions)


def test_fixture_observation_error_retains_existence(monkeypatch, owned_sessions):
    from cwushell_test import fixtures

    original = fixtures.os.open

    def deny(path, flags, *args, **kwargs):
        if Path(path).name == "source.txt":
            raise PermissionError("injected read denied")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(fixtures.os, "open", deny)
    result = run_session(SHELL, fixtures=EXTERNAL_FIXTURES, timeout=1)
    assert result.reason == "COMPLETED"
    for phase in ("before", "after"):
        item = observation(result, "source.txt", phase)
        assert item.exists is True
        assert item.error is not None and "injected read denied" in item.error
        assert (
            observation(result, "removable.txt", phase).contents
            == EXTERNAL_FIXTURES[1].contents
        )
    assert_released(result, owned_sessions)


@pytest.mark.parametrize(
    "path", ["../outside", "/absolute", "nested/file", ".", "..", ""]
)
def test_fixture_unsafe_names_rejected_before_launch(path, owned_sessions):
    with pytest.raises(ValueError, match="relative names"):
        run_session(SHELL, fixtures=[Fixture(path, "absent")])
    assert owned_sessions == []


def test_fixture_launch_failure_retains_observations(tmp_path):
    result = run_session(tmp_path / "missing-target", fixtures=EXTERNAL_FIXTURES)
    assert result.reason == "ERROR"
    assert result.pid is None
    assert result.error is not None and "missing-target" in result.error
    assert (
        observation(result, "source.txt", "after").contents
        == EXTERNAL_FIXTURES[0].contents
    )
    assert not Path(result.working_directory).exists()


def test_fixture_interruption_snapshots_before_propagating(monkeypatch, owned_sessions):
    from cwushell_test import fixtures

    observations = []
    original = fixtures.snapshot

    def record(directory, path, phase):
        item = original(directory, path, phase)
        observations.append((directory, item))
        return item

    def interrupt(self, prompt, deadline):
        raise KeyboardInterrupt

    monkeypatch.setattr(fixtures, "snapshot", record)
    monkeypatch.setattr(pty._Reader, "wait", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_session(SHELL, fixtures=EXTERNAL_FIXTURES)
    assert [item.phase for directory, item in observations] == ["before"] * 3 + [
        "after"
    ] * 3
    assert owned_sessions[-1].closed
    assert all(not directory.exists() for directory, item in observations)


def test_fixture_empty_truncated_and_unknown_observations(tmp_path, monkeypatch):
    from cwushell_test import fixtures

    (tmp_path / "empty").write_bytes(b"")
    assert fixtures.snapshot(tmp_path, "empty", "before").contents == b""
    (tmp_path / "large").write_bytes(b"x" * (fixtures.FILE_CAPTURE_BYTES + 1))
    item = fixtures.snapshot(tmp_path, "large", "after")
    assert item.contents == b"x" * fixtures.FILE_CAPTURE_BYTES
    assert item.error is not None and "truncated" in item.error

    def deny(self):
        raise PermissionError("injected stat denied")

    monkeypatch.setattr(Path, "lstat", deny)
    item = fixtures.snapshot(tmp_path, "empty", "after")
    assert item.exists is None
    assert item.error is not None and "stat denied" in item.error
