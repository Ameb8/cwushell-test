"""Exact dispatch and direct observations for T1/T2/T6 through Linux PTYs."""

import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cwushell_test import fixtures
from cwushell_test import pty_session as pty
from cwushell_test import shell_scenarios as scenarios
from cwushell_test.evidence import ExecutionMetadata, Report
from cwushell_test.reporting import render_report

SHELL = Path(__file__).parent / "fixtures" / "scenario_shell.py"
ALL_CASES = (
    scenarios.PROMPT_CASES + scenarios.TERMINATION_CASES + scenarios.SYSTEM_CASES
)


def test_exact_inventory_and_wait_targets():
    assert [[c.text for c in case.commands] for case in scenarios.PROMPT_CASES] == [
        [],
        ["prompt myprompt>", "prompt"],
        ["cpuinfo   -c   -t"],
        ["cpuinfo\t-c\t-t"],
        ["meminfo   -t   -u"],
        ["meminfo\t-t\t-u"],
        ["echo   alpha   beta"],
        ["echo\talpha\tbeta"],
    ]
    assert [c.prompt for c in scenarios.PROMPT_CASES[1].commands] == [
        "myprompt>",
        "cwushell>",
    ]
    assert [
        [c.text for c in case.commands] for case in scenarios.TERMINATION_CASES
    ] == [
        ["exit 42"],
        ["exit -10"],
        ["exit"],
        ["/bin/true", "exit"],
        ["/bin/false", "exit"],
    ]
    assert all(case.commands[-1].prompt is None for case in scenarios.TERMINATION_CASES)
    assert [[c.text for c in case.commands] for case in scenarios.SYSTEM_CASES] == [
        ["bogus_cmd_xyz"],
        ["cpuinfo -z"],
        ["meminfo -x"],
        ["ls"],
        ["pwd"],
        ["echo fixture_alpha fixture_beta"],
        ["cat source.txt"],
        ["cp source.txt copied.txt"],
        ["rm removable.txt"],
        ["cd fixture_dir", "pwd"],
        ["export CWUSHELL_TEST_EXPORT=fixture_value", "printenv CWUSHELL_TEST_EXPORT"],
        ["unset CWUSHELL_TEST_UNSET", "printenv CWUSHELL_TEST_UNSET"],
    ]
    assert len({case.case_id for case in ALL_CASES}) == 25
    for suite, cases in (
        ("T1", scenarios.PROMPT_CASES),
        ("T2", scenarios.TERMINATION_CASES),
        ("T6", scenarios.SYSTEM_CASES),
    ):
        assert all(case.suite_id == suite for case in cases)
    for case in ALL_CASES:
        for command in case.commands:
            if command.text.startswith("exit"):
                assert command.prompt is None
            elif command.text != "prompt myprompt>":
                assert command.prompt == "cwushell>"


def test_adapter_preserves_evidence_and_context(monkeypatch):
    result = pty.Evidence(
        17,
        raw_output=b"arbitrary",
        reason="ERROR",
        error="launch diagnostic",
        fixtures=fixtures.CD_FIXTURES,
        notes=("preparation diagnostic",),
        cleanup_error="cleanup diagnostic",
    )
    calls = []

    def run(target, commands, **kwargs):
        calls.append((target, commands, kwargs))
        return result

    monkeypatch.setattr(scenarios, "run_session", run)
    definition = scenarios.SYSTEM_CASES[9]
    case = definition.run(SHELL, timeout=0.5, max_output_bytes=17)
    assert calls == [
        (
            SHELL,
            definition.commands,
            {
                "timeout": 0.5,
                "max_output_bytes": 17,
                "fixtures": fixtures.CD_FIXTURES,
                "controlled_environment": {},
            },
        )
    ]
    assert case.session is result
    assert case.commands is definition.commands
    assert case.fixtures is result.fixtures
    assert case.notes == result.notes + definition.notes
    assert "CLEANUP_ERROR" in case.summary.outcomes


@pytest.fixture
def owned_sessions(monkeypatch):
    """These fixtures never fork; retain finally ownership even on test failure."""
    children = []
    spawn = pty.pexpect.spawn

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(pty.pexpect, "spawn", record)
    monkeypatch.setenv("SCENARIO_MODE", "record")
    try:
        yield children
    finally:
        for child in children:
            assert child.pid is not None and child.pid != os.getpgrp()
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.close(force=True)


def records(case, prefix):
    # Prompts do not have newlines; the fixture's record marker delimits JSON.
    return [
        json.loads(part.splitlines()[0])
        for part in case.session.output.split(prefix)[1:]
    ]


def assert_released(case, children):
    assert case.session.direct_child_reaped
    assert case.session.cleanup_error is None
    assert not Path(case.session.working_directory).exists()
    assert all(child.closed and child.child_fd == -1 for child in children)
    with pytest.raises(ProcessLookupError):
        os.kill(case.session.pid, 0)


def markdown_for(cases):
    return render_report(
        Report(
            ExecutionMetadata(
                datetime.now(timezone.utc),
                SHELL.resolve(),
                "synthetic",
                "Linux",
                1,
                1048576,
            ),
            tuple(cases),
        )
    )


@pytest.mark.integration
def test_all_exact_inputs_independent_sessions_and_report(owned_sessions, monkeypatch):
    # Deliberately conflict with export's required initial setting.
    monkeypatch.setenv("CWUSHELL_TEST_EXPORT", "inherited_value")
    monkeypatch.delenv("CWUSHELL_TEST_UNSET", raising=False)
    cases = []
    for definition in ALL_CASES:
        case = definition.run(SHELL, timeout=1)
        cases.append(case)
        session = case.session
        assert session.dispatched == [c.text for c in definition.commands]
        assert session.undispatched == []
        assert records(case, "INITIAL ")[0]["entries"] == sorted(
            fixture.path for fixture in definition.fixtures if fixture.kind != "absent"
        )
        received = records(case, "RECEIVED ")
        assert [row[0] for row in received] == session.dispatched
        assert all(row[1] == session.pid for row in received)
        assert "EARLY INPUT" not in session.output
        if case.suite_id == "T2":
            assert session.reason == "EOF"
            assert session.interactions[-1].waiting_for == "EOF"
            assert session.signal_status is None
            assert session.cleanup_signal_status is None
        else:
            assert session.reason == "COMPLETED"
        assert_released(case, owned_sessions)
    assert len(owned_sessions) == 25
    assert len({case.session.pid for case in cases}) == 25
    assert len({case.session.working_directory for case in cases}) == 25
    assert [case.session.exit_status for case in cases[8:13]] == [42, 246, 0, 0, 1]
    prompt = cases[1]
    assert [event.waiting_for for event in prompt.session.interactions] == [
        "cwushell>",
        "myprompt>",
        "cwushell>",
    ]
    cd, export, unset = cases[-3:]
    assert records(cd, "INITIAL ")[0]["fixture_dir"] == []
    assert (
        records(cd, "RECEIVED ")[1][2] == cd.session.working_directory + "/fixture_dir"
    )
    assert cd.fixtures == fixtures.CD_FIXTURES
    assert records(export, "INITIAL ")[0]["export"] is None
    assert export.controlled_environment["CWUSHELL_TEST_EXPORT"] is None
    assert records(export, "ENVIRONMENT ") == ["fixture_value"]
    assert records(unset, "INITIAL ")[0]["unset"] == "fixture_value"
    assert unset.controlled_environment["CWUSHELL_TEST_UNSET"] == "fixture_value"
    assert records(unset, "ENVIRONMENT ") == [None]
    for case in cases[19:22]:
        assert case.fixtures == fixtures.EXTERNAL_FIXTURES
        before = {o.path: o for o in case.file_observations if o.phase == "before"}
        after = {o.path: o for o in case.file_observations if o.phase == "after"}
        assert before["source.txt"].contents == b"cwushell-test source fixture\n"
        assert before["removable.txt"].contents == b"cwushell-test removable fixture\n"
        assert before["copied.txt"].exists is False
        assert all(o.error is None for o in case.file_observations)
        if case.case_id == "T6.cp":
            assert after["copied.txt"].contents == before["source.txt"].contents
        elif case.case_id == "T6.rm":
            assert after["removable.txt"].exists is False
        else:
            assert after["source.txt"].contents == before["source.txt"].contents
    markdown = markdown_for(cases)
    assert "Escaped input representation" in markdown
    # Command representations escape tabs; terminal listing tabs remain evidence.
    for section in markdown.split("#### Planned commands")[1:]:
        assert "\t" not in section.split("#### Combined PTY terminal output", 1)[0]
    for case in cases:
        assert case.case_id in markdown
        for command in case.commands:
            assert command.text.replace("\t", "\\t") in markdown
        for outcome in case.summary.outcomes:
            assert outcome in markdown
    assert scenarios.BUILTIN_COVERAGE_NOTE in markdown
    assert "CWUSHELL_TEST_EXPORT" in markdown and "fixture_dir" in markdown


@pytest.mark.integration
def test_file_snapshots_order_and_cleanup_effect(monkeypatch, owned_sessions):
    monkeypatch.setenv("SCENARIO_MODE", "cleanup_effect")
    order = []
    snapshot, spawn, cleanup = fixtures.snapshot, pty.pexpect.spawn, pty._cleanup

    def observe(directory, path, phase):
        assert directory.exists()
        order.append(phase)
        return snapshot(directory, path, phase)

    def launch(*args, **kwargs):
        order.append("launch")
        return spawn(*args, **kwargs)

    def finish(child, evidence):
        cleanup(child, evidence)
        assert child.closed and evidence.direct_child_reaped
        order.append("cleanup")

    monkeypatch.setattr(fixtures, "snapshot", observe)
    monkeypatch.setattr(pty.pexpect, "spawn", launch)
    monkeypatch.setattr(pty, "_cleanup", finish)
    case = scenarios.SYSTEM_CASES[7].run(SHELL, timeout=1)
    assert order == ["before"] * 3 + ["launch", "cleanup"] + ["after"] * 3
    copied = [o for o in case.file_observations if o.path == "copied.txt"]
    assert copied[0].exists is False
    assert copied[1].contents == b"cleanup contents\n"
    assert case.session.dispatched == ["cp source.txt copied.txt"]
    assert case.session.exit_status is None and case.session.signal_status is None
    assert case.session.cleanup_exit_status == 0
    assert_released(case, owned_sessions)


@pytest.mark.integration
def test_startup_only_fallback_and_early_exit(monkeypatch, owned_sessions):
    monkeypatch.setenv("SCENARIO_MODE", "missing")
    startup = scenarios.PROMPT_CASES[0].run(SHELL, timeout=0.3)
    assert startup.session.reason == "TIMEOUT"
    assert startup.session.dispatched == []
    assert len(startup.session.interactions) == 1
    fallback = scenarios.PROMPT_CASES[1].run(SHELL, timeout=0.3)
    assert [e.reason for e in fallback.session.interactions] == [
        "TIMEOUT",
        "PROMPT",
        "PROMPT",
    ]
    assert fallback.session.dispatched == ["prompt myprompt>", "prompt"]
    monkeypatch.setenv("SCENARIO_MODE", "startup_exit")
    early = scenarios.TERMINATION_CASES[3].run(SHELL, timeout=1)
    assert early.session.exit_status == 19
    assert early.session.dispatched == []
    assert early.session.undispatched == ["/bin/true", "exit"]
    for case in (startup, fallback, early):
        assert "INITIAL " in case.session.output
        assert_released(case, owned_sessions)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["mismatch", "hang", "crash"])
@pytest.mark.parametrize(
    "definition", [scenarios.PROMPT_CASES[1], *scenarios.SYSTEM_CASES[-3:]]
)
def test_sequence_faults_stop_dispatch_and_continue(
    mode, definition, monkeypatch, owned_sessions
):
    monkeypatch.setenv("SCENARIO_MODE", mode)
    broken = definition.run(SHELL, timeout=0.3, max_output_bytes=512)
    assert broken.session.dispatched == [definition.commands[0].text]
    assert broken.session.undispatched == [definition.commands[1].text]
    assert broken.session.interactions[-1].waiting_for == definition.commands[0].prompt
    if mode == "crash":
        assert broken.session.signal_status == signal.SIGSEGV
        assert broken.session.exit_status is None
        assert "SIGNAL" in broken.summary.outcomes
    else:
        assert broken.session.reason == "TIMEOUT"
        assert (
            broken.session.exit_status is None and broken.session.signal_status is None
        )
        assert broken.session.cleanup_signal_status == signal.SIGTERM
    if mode == "hang":
        assert broken.session.truncated and len(broken.session.raw_output) == 512
        assert broken.session.interaction_seconds <= 0.9 + 0.25
    else:
        assert records(broken, "RECEIVED ")[0][0] == definition.commands[0].text
    monkeypatch.setenv("SCENARIO_MODE", "record")
    later = scenarios.SYSTEM_CASES[4].run(SHELL, timeout=1)
    assert later.session.reason == "COMPLETED"
    for case in (broken, later):
        assert_released(case, owned_sessions)
    markdown = markdown_for((broken, later))
    assert "INCOMPLETE_DISPATCH" in markdown
    assert definition.commands[1].text in markdown


@pytest.mark.integration
def test_deviations_remain_evidence(monkeypatch, owned_sessions):
    monkeypatch.setenv("SCENARIO_MODE", "deviation")
    cases = [
        definition.run(SHELL, timeout=1)
        for definition in (
            *scenarios.TERMINATION_CASES,
            *scenarios.SYSTEM_CASES[6:9],
            scenarios.SYSTEM_CASES[4],
            scenarios.SYSTEM_CASES[5],
        )
    ]
    assert all(case.session.exit_status == 7 for case in cases[:5])
    for case in cases[5:8]:
        before = [o for o in case.file_observations if o.phase == "before"]
        after = [o for o in case.file_observations if o.phase == "after"]
        assert [(o.path, o.exists, o.contents) for o in before] == [
            (o.path, o.exists, o.contents) for o in after
        ]
    for case in cases:
        assert "arbitrary diagnostic; no promised file effect" in case.session.output
        assert_released(case, owned_sessions)
    markdown = markdown_for(cases)
    assert "arbitrary diagnostic; no promised file effect" in markdown
    assert "Observed process exit status:\n\n```text\n7\n```" in markdown


@pytest.mark.integration
def test_exit_signal_and_ignored_exit_are_distinct(monkeypatch, owned_sessions):
    cases = []
    for mode in ("crash", "ignored_exit"):
        monkeypatch.setenv("SCENARIO_MODE", mode)
        case = scenarios.TERMINATION_CASES[0].run(SHELL, timeout=0.3)
        cases.append(case)
        assert case.session.exit_status is None
        assert case.session.dispatched == ["exit 42"]
        assert_released(case, owned_sessions)
    crashed, ignored = cases
    assert crashed.session.signal_status == signal.SIGSEGV
    assert crashed.session.cleanup_signal_status is None
    assert ignored.session.signal_status is None
    assert ignored.session.cleanup_signal_status == signal.SIGTERM
    assert ignored.session.reason == "TIMEOUT"
    assert ignored.session.interactions[-1].waiting_for == "EOF"
    assert "exit ignored" in ignored.session.output


@pytest.mark.integration
@pytest.mark.parametrize(
    "definition", [scenarios.SYSTEM_CASES[3], scenarios.SYSTEM_CASES[5]]
)
def test_controlled_listing_and_echo_evidence(definition, monkeypatch, owned_sessions):
    cases = []
    command = definition.commands[0].text
    for mode in ("record", "ignored_commands"):
        monkeypatch.setenv("SCENARIO_MODE", mode)
        case = definition.run(SHELL, timeout=1, max_output_bytes=4096)
        cases.append(case)
        session = case.session
        initial = records(case, "INITIAL ")[0]
        received = records(case, "RECEIVED ")
        assert received == (
            [[command, session.pid, session.working_directory]]
            if mode == "record"
            else []
        )
        dispatch_record = ""
        body = ""
        if mode == "record":
            dispatch_record = "RECEIVED " + json.dumps(received[0]) + "\n"
            body = (
                "fixture_beta.txt\tfixture_alpha.txt\n"
                if case.case_id == "T6.ls"
                else "fixture_alpha fixture_beta\n"
            )
        # Entire retained evidence, including both actual prompts and no PTY echo.
        assert session.output == (
            "INITIAL "
            + json.dumps(initial)
            + "\ncwushell>"
            + dispatch_record
            + body
            + "cwushell>"
        )
        assert not session.truncated
        assert session.dispatched == [command] and session.undispatched == []
        assert session.reason == "COMPLETED"
        assert [event.reason for event in session.interactions] == ["PROMPT", "PROMPT"]
        assert case.summary.outcomes == ("COMPLETED", "PROMPT")
        if case.case_id == "T6.ls":
            assert case.fixtures == fixtures.LISTING_FIXTURES
            assert initial["entries"] == ["fixture_alpha.txt", "fixture_beta.txt"]
            for phase in ("before", "after"):
                assert [
                    (o.path, o.exists, o.contents, o.error)
                    for o in case.file_observations
                    if o.phase == phase
                ] == [
                    (fixture.path, True, fixture.contents, None)
                    for fixture in fixtures.LISTING_FIXTURES
                ]
        else:
            assert initial["entries"] == []
            assert case.fixtures == () and case.file_observations == ()
            assert case.title == command
        markdown = markdown_for((case,))
        assert "```text\n" + session.output + "\n```" in markdown
        for heading in ("Planned commands", "Dispatched commands (fully sent)"):
            section = markdown.split("#### " + heading, 1)[1].split("#### ", 1)[0]
            assert "```text\n" + command + "\n```" in section
        assert_released(case, owned_sessions)
    assert cases[0].session.output != cases[1].session.output
    assert cases[0].fixtures == cases[1].fixtures
    assert cases[0].summary.outcomes == cases[1].summary.outcomes
    assert len({case.session.working_directory for case in cases}) == 2


@pytest.mark.integration
@pytest.mark.parametrize(
    "definition", [scenarios.SYSTEM_CASES[3], scenarios.SYSTEM_CASES[5]]
)
@pytest.mark.parametrize("mode", ["startup_exit", "crash", "hang", "record"])
def test_controlled_commands_faults_and_capture_bounds(
    definition, mode, monkeypatch, owned_sessions
):
    monkeypatch.setenv("SCENARIO_MODE", mode)
    timeout = 1.0 if mode == "startup_exit" else 0.3
    case = definition.run(SHELL, timeout=timeout, max_output_bytes=32)
    assert case.fixtures == definition.fixtures
    assert case.session.truncated and len(case.session.raw_output) == 32
    assert case.session.output.startswith("INITIAL ")
    assert case.session.dispatched == (
        [] if mode == "startup_exit" else [definition.commands[0].text]
    )
    assert case.session.undispatched == (
        [definition.commands[0].text] if mode == "startup_exit" else []
    )
    assert (
        case.session.reason
        == {
            "startup_exit": "EOF",
            "crash": "EOF",
            "hang": "TIMEOUT",
            "record": "COMPLETED",
        }[mode]
    )
    assert case.session.interaction_seconds <= 2 * timeout + 0.25
    if mode == "crash":
        assert case.session.signal_status == signal.SIGSEGV
    if definition.fixtures:
        assert len(case.file_observations) == 4
        assert all(o.exists and o.error is None for o in case.file_observations)
    markdown = markdown_for((case,))
    assert "TRUNCATED: retained raw terminal-output prefix only" in markdown
    assert_released(case, owned_sessions)
    monkeypatch.setenv("SCENARIO_MODE", "record")
    later = scenarios.SYSTEM_CASES[4].run(SHELL, timeout=1)
    assert later.session.reason == "COMPLETED"
    assert records(later, "INITIAL ")[0]["entries"] == []
    assert_released(later, owned_sessions)
