"""Recording checks for T3–T5, independent of CLI orchestration."""

import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cwushell_test import information_scenarios as scenarios
from cwushell_test import pty_session as pty
from cwushell_test.evidence import ExecutionMetadata, Report
from cwushell_test.reporting import render_report

SHELL = Path(__file__).parent / "fixtures" / "information_shell.py"
ALL_CASES = scenarios.CPU_CASES + scenarios.MEMORY_CASES + scenarios.HELP_CASES


def test_exact_inventory():
    expected = (
        (
            "T3",
            scenarios.CPU_CASES,
            [
                "cpuinfo -c",
                "cpuinfo -t",
                "cpuinfo -n",
                "cpuinfo -ct",
                "cpuinfo -c -t",
                "cpuinfo -cn",
                "cpuinfo -c -n",
                "cpuinfo -tn",
                "cpuinfo -t -n",
                "cpuinfo -ctn",
                "cpuinfo -c -t -n",
            ],
        ),
        (
            "T4",
            scenarios.MEMORY_CASES,
            [
                "meminfo -t",
                "meminfo -u",
                "meminfo -c",
                "meminfo -tu",
                "meminfo -t -u",
                "meminfo -tc",
                "meminfo -t -c",
                "meminfo -uc",
                "meminfo -u -c",
                "meminfo -tuc",
                "meminfo -t -u -c",
            ],
        ),
        (
            "T5",
            scenarios.HELP_CASES,
            [
                "manual",
                "cpuinfo",
                "cpuinfo -h",
                "cpuinfo --help",
                "meminfo",
                "meminfo -h",
                "meminfo --help",
                "exit -h",
                "exit --help",
                "prompt -h",
                "prompt --help",
            ],
        ),
    )
    for suite, cases, commands in expected:
        assert len(cases) == 11
        assert [case.commands[0].text for case in cases] == commands
        assert all(case.suite_id == suite for case in cases)
        assert all(len(case.commands) == 1 for case in cases)
        assert all(case.commands[0].prompt == "cwushell>" for case in cases)
    assert len({case.case_id for case in ALL_CASES}) == 33


def test_adapter_preserves_helper_contract(monkeypatch):
    result = pty.Evidence(
        17,
        raw_output=b"diagnostic",
        truncated=True,
        undispatched=["manual"],
        reason="ERROR",
        error="launch diagnostic",
        interactions=[pty.Interaction(None, "EOF", "cwushell>")],
        exit_status=19,
        cleanup_actions=["SIGTERM"],
        cleanup_error="cleanup note",
    )
    calls = []

    def run(target, commands, **kwargs):
        calls.append((target, commands, kwargs))
        return result

    monkeypatch.setattr(scenarios, "run_session", run)
    definition = scenarios.HELP_CASES[0]
    case = definition.run(SHELL, timeout=0.5, max_output_bytes=17)
    assert calls == [
        (SHELL, definition.commands, {"timeout": 0.5, "max_output_bytes": 17})
    ]
    assert case.session is result
    assert case.commands is definition.commands
    assert case.case_id == definition.case_id
    assert case.title == "manual"
    assert case.summary.events == tuple(result.interactions)
    assert case.summary.outcomes == (
        "ERROR",
        "EOF",
        "PROCESS_EXIT",
        "INCOMPLETE_DISPATCH",
        "CLEANUP_ERROR",
    )


@pytest.fixture
def owned_sessions(monkeypatch):
    """No descendants are spawned; own each real PTY even on test failure."""
    children = []
    spawn = pty.pexpect.spawn

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(pty.pexpect, "spawn", record)
    monkeypatch.setenv("INFORMATION_MODE", "record")
    try:
        yield children
    finally:
        for child in children:
            assert child.pid is not None
            assert child.pid != os.getpgrp()
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.close(force=True)


def assert_released(case, children):
    session = case.session
    assert session.direct_child_reaped
    assert session.cleanup_error is None
    assert not Path(session.working_directory).exists()
    assert all(child.closed and child.child_fd == -1 for child in children)
    with pytest.raises(ProcessLookupError):
        os.kill(session.pid, 0)


@pytest.mark.integration
def test_every_case_dispatches_in_a_fresh_session(owned_sessions):
    cases = []
    for definition in ALL_CASES:
        case = definition.run(SHELL, timeout=1)
        cases.append(case)
        session = case.session
        assert session.reason == "COMPLETED"
        assert session.dispatched == [definition.commands[0].text]
        assert session.undispatched == []
        observed = json.loads(session.output.removeprefix("cwushell>").splitlines()[0])
        assert observed == [
            definition.commands[0].text,
            session.pid,
            session.working_directory,
        ]
        assert_released(case, owned_sessions)
    assert len(owned_sessions) == 33
    assert len({case.session.pid for case in cases}) == 33
    assert len({case.session.working_directory for case in cases}) == 33


@pytest.mark.integration
@pytest.mark.parametrize(
    "definition",
    [scenarios.CPU_CASES[0], scenarios.MEMORY_CASES[0], scenarios.HELP_CASES[0]],
)
@pytest.mark.parametrize(
    "mode, output",
    [
        ("empty", "cwushell>cwushell>"),
        ("arbitrary", "cwushell>bananas = -???\nno units; no sections\ncwushell>"),
        ("formatted", "cwushell>```\n\n# unusual | layout\ncwushell>"),
        ("diagnostic", "cwushell>unsupported option; synthetic diagnostic\ncwushell>"),
    ],
)
def test_output_is_evidence(definition, mode, output, monkeypatch, owned_sessions):
    monkeypatch.setenv("INFORMATION_MODE", mode)
    case = definition.run(SHELL, timeout=1)
    assert case.session.output == output
    assert case.session.reason == "COMPLETED"
    assert case.summary.outcomes == ("COMPLETED", "PROMPT")
    assert_released(case, owned_sessions)


@pytest.mark.integration
@pytest.mark.parametrize("definition", scenarios.HELP_CASES[7:])
def test_help_exit_and_changed_prompt_are_observations(
    definition, monkeypatch, owned_sessions
):
    monkeypatch.setenv("INFORMATION_MODE", "help_events")
    case = definition.run(SHELL, timeout=0.3)
    assert case.session.dispatched == [definition.commands[0].text]
    assert case.session.undispatched == []
    if definition.commands[0].text.startswith("exit "):
        assert case.session.exit_status == 23
        assert "PROCESS_EXIT" in case.summary.outcomes
        assert case.session.reason == "EOF"
        assert "help terminated\n" in case.session.output
    else:
        assert case.session.output.endswith("changed> ")
        assert case.session.reason == "TIMEOUT"
        assert case.session.interactions[-1].waiting_for == "cwushell>"
        assert case.session.exit_status is None
        assert case.session.signal_status is None
        assert case.session.cleanup_actions == ["SIGTERM"]
    assert_released(case, owned_sessions)


@pytest.mark.integration
def test_startup_fallback_and_startup_exit(monkeypatch, owned_sessions):
    definition = scenarios.HELP_CASES[0]
    monkeypatch.setenv("INFORMATION_MODE", "missing")
    fallback = definition.run(SHELL, timeout=0.3)
    assert [event.reason for event in fallback.session.interactions] == [
        "TIMEOUT",
        "PROMPT",
    ]
    assert fallback.session.dispatched == ["manual"]
    assert fallback.summary.outcomes == ("COMPLETED", "TIMEOUT", "PROMPT")
    assert "manual" in fallback.session.output
    assert_released(fallback, owned_sessions)

    monkeypatch.setenv("INFORMATION_MODE", "startup_exit")
    exited = definition.run(SHELL, timeout=1)
    assert exited.session.dispatched == []
    assert exited.session.undispatched == ["manual"]
    assert exited.session.exit_status == 19
    assert exited.session.output == "startup diagnostic\n"
    assert "INCOMPLETE_DISPATCH" in exited.summary.outcomes
    assert_released(exited, owned_sessions)


@pytest.mark.integration
def test_faults_truncation_and_continuation_reach_report(monkeypatch, owned_sessions):
    monkeypatch.setenv("INFORMATION_MODE", "faults")
    definitions = scenarios.CPU_CASES[:4] + (
        scenarios.MEMORY_CASES[0],
        scenarios.HELP_CASES[0],
    )
    cases = []
    for definition in definitions:
        case = definition.run(SHELL, timeout=0.3, max_output_bytes=256)
        cases.append(case)
        assert case.session.dispatched == [definition.commands[0].text]
        assert case.session.undispatched == []
        assert_released(case, owned_sessions)
    crashed, timed_out, flooded, *later = cases
    assert crashed.session.signal_status == signal.SIGSEGV
    assert "cpuinfo -c" in crashed.session.output
    assert "SIGNAL" in crashed.summary.outcomes
    assert timed_out.session.reason == "TIMEOUT"
    assert timed_out.session.truncated
    assert timed_out.session.interaction_seconds <= 0.6 + 0.25
    assert timed_out.session.cleanup_seconds <= 0.4 + 0.25
    assert flooded.session.truncated
    assert flooded.session.reason == "COMPLETED"
    assert len(flooded.session.raw_output) == 256
    assert all(case.session.reason == "COMPLETED" for case in later)
    metadata = ExecutionMetadata(
        datetime.now(timezone.utc), SHELL.resolve(), "synthetic", "Linux", 0.3, 256
    )
    markdown = render_report(Report(metadata, tuple(cases)))
    for case in cases:
        assert case.case_id in markdown
        assert case.commands[0].text in markdown
        for outcome in case.summary.outcomes:
            assert outcome in markdown
    assert "truncated" in markdown.lower()
    assert "256" in markdown
