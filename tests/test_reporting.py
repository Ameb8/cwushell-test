"""Synthetic report contracts: no target process or student binary is needed."""

import html
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cwushell_test.evidence import (
    CaseEvidence,
    ExecutionMetadata,
    FileObservation,
    Fixture,
    Report,
)
from cwushell_test.pty_session import Command, Evidence, Interaction
from cwushell_test.reporting import ReportWriteError, render_report, write_report


def report_for(*cases: CaseEvidence) -> Report:
    return Report(
        ExecutionMetadata(
            datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc),
            Path("/target path/cwushell"),
            "ELF x86-64",
            "Linux 6.8.0",
            0.25,
            64,
        ),
        cases,
    )


def case_for(session: Evidence) -> CaseEvidence:
    return CaseEvidence(
        "T1.tabs",
        "T1",
        "Whitespace evidence",
        (Command("echo\talpha   beta"),),
        session,
    )


def test_metadata_context_commands_and_cleaned_terminal_evidence():
    session = Evidence(
        64,
        raw_output=b"\x1b[32mstudent\x1b[0m\r\ntext\r",
        dispatched=["echo\talpha   beta"],
        interactions=[
            Interaction(None, "PROMPT", "cwushell>"),
            Interaction("echo\talpha   beta", "PROMPT", "cwushell>"),
        ],
        reason="COMPLETED",
        working_directory="/tmp/session space",
    )
    case = replace(
        case_for(session),
        fixtures=(
            Fixture("source.txt", "file", b"fixed\n"),
            Fixture("fixture_dir", "directory"),
            Fixture("copied.txt", "absent"),
        ),
        controlled_environment={
            "TERM": "dumb",
            "CWUSHELL_TEST_EXPORT": None,
            "CWUSHELL_TEST_UNSET": "fixture_value",
        },
    )
    rendered = render_report(report_for(case))
    for value in (
        "2026-10-06T12:30:00+00:00",
        "/target path/cwushell",
        "ELF x86-64",
        "Linux 6.8.0",
        "0.25",
        "64",
        "/tmp/session space",
        "source.txt",
        "fixture_dir",
        "copied.txt",
        "CWUSHELL_TEST_EXPORT",
        "Absent",
        "fixture_value",
        "Combined PTY terminal output",
        "student\ntext\n",
        f"Retained raw-byte count: {len(session.raw_output)}",
        "Escaped input representation",
        "echo\\talpha   beta",
        "COMPLETED means execution completion only",
    ):
        assert value in rendered
    assert "\x1b" not in rendered
    assert session.dispatched == ["echo\talpha   beta"]
    assert case.commands[0].text == "echo\talpha   beta"
    assert (
        "PASS" not in rendered and "PARTIAL" not in rendered and "FAIL" not in rendered
    )
    summary_line = html.unescape(
        next(line for line in rendered.splitlines() if line.startswith("| T1 |"))
    )
    assert "T1.tabs" in summary_line and "Startup: PROMPT" in summary_line
    assert case.summary.dispatched_count == 1


@pytest.mark.parametrize(
    "reason,events,exit_status,signal_status,undispatched,expected",
    [
        (
            "COMPLETED",
            [Interaction(None, "PROMPT", "cwushell>")],
            None,
            None,
            [],
            ("COMPLETED", "PROMPT"),
        ),
        (
            "TIMEOUT",
            [Interaction("echo", "TIMEOUT", "changed>")],
            None,
            None,
            ["never"],
            ("TIMEOUT", "INCOMPLETE_DISPATCH"),
        ),
        (
            "EOF",
            [Interaction(None, "EOF", "cwushell>")],
            17,
            None,
            ["echo"],
            ("EOF", "PROCESS_EXIT", "INCOMPLETE_DISPATCH"),
        ),
        (
            "EOF",
            [Interaction("crash", "EOF", "cwushell>")],
            None,
            11,
            ["never"],
            ("EOF", "SIGNAL", "INCOMPLETE_DISPATCH"),
        ),
        (
            "COMPLETED",
            [
                Interaction(None, "TIMEOUT", "cwushell>"),
                Interaction("echo", "PROMPT", "cwushell>"),
            ],
            None,
            None,
            [],
            ("COMPLETED", "TIMEOUT", "PROMPT"),
        ),
        ("EOF", [Interaction("exit", "EOF", "EOF")], None, None, [], ("EOF",)),
        (
            "TIMEOUT",
            [Interaction("long input", "TIMEOUT", "command dispatch")],
            23,
            None,
            ["long input", "never"],
            ("TIMEOUT", "PROCESS_EXIT", "INCOMPLETE_DISPATCH"),
        ),
    ],
)
def test_all_simultaneous_observations_survive_summary_and_details(
    reason, events, exit_status, signal_status, undispatched, expected
):
    session = Evidence(
        64,
        interactions=events,
        reason=reason,
        exit_status=exit_status,
        signal_status=signal_status,
        undispatched=undispatched,
    )
    case = case_for(session)
    assert case.summary.outcomes == expected
    assert case.summary.events == tuple(events)
    assert case.summary.exit_status == exit_status
    assert case.summary.signal_status == signal_status
    rendered = render_report(report_for(case))
    summary_line = html.unescape(
        next(line for line in rendered.splitlines() if line.startswith("| T1 |"))
    )
    for label in expected:
        assert label in summary_line
    for event in events:
        assert event.reason in rendered and event.waiting_for in rendered
    for command in undispatched:
        assert command in rendered
    if exit_status is None and signal_status is None:
        assert "PROCESS_EXIT" not in case.summary.outcomes
        assert "SIGNAL" not in case.summary.outcomes


def test_startup_fallback_is_visible_with_later_completion():
    case = case_for(
        Evidence(
            64,
            dispatched=["echo"],
            reason="COMPLETED",
            interactions=[
                Interaction(None, "TIMEOUT", "cwushell>"),
                Interaction("echo", "PROMPT", "cwushell>"),
            ],
        )
    )
    rendered = render_report(report_for(case))
    assert "Initial prompt timeout was retained" in rendered
    assert "startup fallback" in rendered
    assert case.summary.outcomes == ("COMPLETED", "TIMEOUT", "PROMPT")


def test_truncation_keeps_dispatch_events_and_cleanup_separate():
    session = Evidence(
        4,
        raw_output=b"head",
        truncated=True,
        dispatched=["echo"],
        undispatched=["later"],
        reason="TIMEOUT",
        interactions=[Interaction("echo", "TIMEOUT", "custom>")],
        cleanup_actions=["SIGTERM", "SIGKILL"],
        cleanup_signal_status=9,
        cleanup_error="still live",
        error="read diagnostic",
        direct_child_reaped=False,
        pid=100,
        pgid=100,
        launch_seconds=0.1,
        interaction_seconds=0.25,
        cleanup_seconds=0.4,
    )
    case = case_for(session)
    rendered = render_report(report_for(case))
    for value in (
        "TRUNCATED",
        "Configured raw-byte limit: 4",
        "Retained raw-byte count: 4",
        "head",
        "echo",
        "later",
        "custom>",
        "SIGTERM",
        "SIGKILL",
        "still live",
        "read diagnostic",
        "0.1",
        "0.25",
        "0.4",
    ):
        assert value in rendered
    assert "SIGNAL" not in case.summary.outcomes
    assert "CLEANUP_ERROR" in case.summary.outcomes
    assert "Cleanup-phase signal:\n\n```text\n9\n```" in rendered
    assert "Observed terminating signal:\n\n```text\nNot observed\n```" in rendered


def test_fixture_observations_preserve_absent_empty_changed_and_error():
    observations = (
        FileObservation("source.txt", "before", True, b"old\n"),
        FileObservation("source.txt", "after", True, b"new\xff\n"),
        FileObservation("copied.txt", "before", False),
        FileObservation("copied.txt", "after", True, b""),
        FileObservation("unreadable", "after", None, error="permission denied"),
    )
    case = replace(case_for(Evidence(64)), file_observations=observations)
    rendered = render_report(report_for(case))
    for value in (
        "Harness-collected fixture evidence",
        "Before launch",
        "After process/PTY cleanup, before directory removal",
        "old\n",
        "new\ufffd\n",
        "b'new\\xff\\n'",
        "b''",
        "Unknown",
        "False",
        "permission denied",
        "Contents were not collected",
    ):
        assert value in rendered
    assert case.file_observations == observations


def test_arbitrary_evidence_cannot_escape_fences_or_summary_table():
    hostile = "```\n# PASS | <script>alert(1)</script>\n``````\n[link](url) & *bold* _text_ \\ ! ~\n~~~\n"
    session = Evidence(
        1024,
        raw_output=hostile.encode(),
        dispatched=[r"echo literal\t" + "\t   `"],
        reason="COMPLETED",
        cleanup_actions=[hostile],
    )
    case = replace(
        case_for(session),
        case_id=hostile,
        suite_id=hostile,
        title=hostile,
        notes=(hostile,),
        file_observations=(
            FileObservation(hostile, "after", True, hostile.encode(), hostile),
        ),
    )
    rendered = render_report(report_for(case))
    # Untrusted evidence is always fenced with more backticks than its content.
    assert f"```````text\n{hostile}```````\n" in rendered
    table = rendered.split("## Execution summary\n\n", 1)[1].split(
        "\n## Detailed case evidence", 1
    )[0]
    rows = table.strip().splitlines()
    assert len(rows) == 3
    assert all(row.count("|") == 9 for row in rows)
    assert "<script>" not in table and "`" not in table
    assert html.unescape(rows[2]).count(hostile) == 3
    assert r"echo literal\\t\t   `" in rendered
    assert session.dispatched[0] == r"echo literal\t" + "\t   `"


def test_every_case_is_listed_and_grouped_without_suite_registration():
    cases = tuple(
        replace(
            case_for(Evidence(64, reason="COMPLETED")),
            suite_id=f"T{index}",
            case_id=f"T{index}.case",
        )
        for index in range(1, 7)
    )
    rendered = render_report(report_for(*cases))
    assert rendered.count("### Case ") == 6
    for case in cases:
        assert case.case_id in html.unescape(rendered)


def test_selected_output_path_with_spaces_receives_utf8_markdown(tmp_path: Path):
    parent = tmp_path / "reports with spaces"
    parent.mkdir()
    output = parent / "evidence report.md"
    report = report_for(case_for(Evidence(64, raw_output="café\n".encode())))
    assert write_report(report, output) == output.resolve()
    assert output.read_bytes() == render_report(report).encode("utf-8")
    assert b"\r\n" not in output.read_bytes()


@pytest.mark.parametrize("kind", ["missing_parent", "directory", "permission"])
def test_write_errors_have_path_reason_and_action(tmp_path: Path, monkeypatch, kind):
    output = tmp_path / "selected report.md"
    if kind == "missing_parent":
        output = tmp_path / "missing" / "selected report.md"
    elif kind == "directory":
        output.mkdir()
    else:

        def denied(*args, **kwargs):
            raise PermissionError("injected permission denied")

        monkeypatch.setattr(Path, "write_text", denied)
    with pytest.raises(ReportWriteError) as caught:
        write_report(report_for(), output)
    diagnostic = str(caught.value)
    assert str(output) in diagnostic
    assert "parent directory exists" in diagnostic and "writable file" in diagnostic
    assert isinstance(caught.value.__cause__, OSError)
