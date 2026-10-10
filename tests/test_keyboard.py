"""DEL, BS, and cursor plans, real incoming bytes, failure paths, and equivalent safe reports."""

import json
import os
import signal
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pytest

from cwushell_test import pty_session as pty
from cwushell_test.evidence import CaseEvidence, ExecutionMetadata, Report
from cwushell_test.html_reporting import render_html_report
from cwushell_test.reporting import render_report
from cwushell_test.runner import SUITES
from cwushell_test.shell_scenarios import PROMPT_CASES

SHELL = Path(__file__).parent / "fixtures" / "keyboard_shell.py"


@pytest.fixture(params=["del", "bs", "cursor"])
def keyboard_case(request):
    return next(
        case
        for case in PROMPT_CASES
        if case.case_id
        == (
            "T1.cursor-insertion"
            if request.param == "cursor"
            else f"T1.backspace-{request.param}"
        )
    )


@pytest.fixture
def exact_input(keyboard_case):
    if keyboard_case.case_id == "T1.cursor-insertion":
        return b"echo helo\x1b[D\x1b[D\x1b[Cl\n"
    return (
        b"echo hellx"
        + (b"\x08" if keyboard_case.case_id.endswith("bs") else b"\x7f")
        + b"o\n"
    )


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def owned_sessions(monkeypatch):
    children = []
    spawn = pty.pexpect.spawn

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(pty.pexpect, "spawn", record)
    monkeypatch.setenv("KEYBOARD_MODE", "edit")
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


def report_for(case: CaseEvidence) -> Report:
    return Report(
        ExecutionMetadata(
            datetime.now(timezone.utc), SHELL, "synthetic", "Linux", 1, 4096
        ),
        (case,),
    )


def incoming(case):
    return [
        bytes.fromhex(line.split()[1])
        for line in case.session.output.splitlines()
        if line.startswith("BYTES ")
    ]


def test_exact_keyboard_actions_and_raw_editing_evidence(keyboard_case, exact_input):
    assert (
        sum(
            case.case_id == keyboard_case.case_id
            for _, cases in SUITES
            for case in cases
        )
        == 1
    )
    actions = keyboard_case.commands[0].actions
    assert [(a.kind, a.data) for a in actions] == (
        [
            ("type", b"echo helo"),
            ("key", b"\x1b[D"),
            ("key", b"\x1b[D"),
            ("key", b"\x1b[C"),
            ("type", b"l"),
            ("enter", b"\n"),
        ]
        if keyboard_case.case_id == "T1.cursor-insertion"
        else [
            ("type", b"echo hellx"),
            ("key", exact_input[10:11]),
            ("type", b"o"),
            ("enter", b"\n"),
        ]
    )
    case = keyboard_case.run(SHELL, timeout=1)
    session = case.session
    assert incoming(case) == [exact_input, b"echo keyboard_alive\n"]
    lines = [
        json.loads(line[5:])
        for line in session.output.splitlines()
        if line.startswith("LINE ")
    ]
    assert lines == ["echo hello", "echo keyboard_alive"]
    assert session.dispatched == [c.text for c in keyboard_case.commands]
    assert not session.undispatched
    assert all(
        record.sent_bytes == len(record.action.data)
        for record in session.action_dispatch
    )
    assert [event.reason for event in session.interactions] == ["PROMPT"] * 3
    assert session.controlled_environment["TERM"] == "xterm"
    assert all(
        dict(o.modes)["ECHO"] is False
        for o in session.terminal_observations
        if not o.error
    )
    assert dict(session.terminal_observations[1].modes)["ICANON"] is False
    assert session.terminal_observations[1].verase == b"\x7f"
    assert (
        b"\x1b[D" if keyboard_case.case_id == "T1.cursor-insertion" else b"\x08 \x08"
    ) in session.raw_output
    assert session.direct_child_reaped and not Path(session.working_directory).exists()
    assert session.signal_status is None
    for rendered in (
        render_report(report_for(case)),
        render_html_report(report_for(case)),
    ):
        assert "Action dispatch accounting" in rendered
        if keyboard_case.case_id == "T1.cursor-insertion":
            assert "Fully sent; 9/9 bytes" in rendered
            assert "CSI D" in rendered and "CSI C" in rendered
            assert "does not reconstruct the visual screen" in rendered
            continue
        assert "Fully sent; 10/10 bytes" in rendered
        assert "Canonical terminal-driver erase behavior" in rendered
        assert (
            f"Observed VERASE equals {'BS' if exact_input[10] == 8 else 'DEL'}"
            in rendered
        )
        assert "optional" in rendered.lower()


@pytest.mark.parametrize(
    "mode",
    ["unsupported", "different-verase"],
)
def test_unsupported_and_different_verase_are_recorded(
    monkeypatch, mode, keyboard_case, exact_input
):
    resulting = exact_input[:-1].decode()
    erase = b"\x7f" if exact_input[10] == 8 else b"\x08"
    monkeypatch.setenv(
        "KEYBOARD_MODE",
        ("verase-del" if exact_input[10] == 8 else "verase-bs")
        if mode == "different-verase"
        else mode,
    )
    case = keyboard_case.run(SHELL, timeout=1)
    assert incoming(case) == [exact_input, b"echo keyboard_alive\n"]
    assert "LINE " + json.dumps(resulting) in case.session.output
    assert case.session.reason == "COMPLETED"
    if mode == "different-verase":
        assert case.session.terminal_observations[1].verase == erase
        for rendered in (
            render_report(report_for(case)),
            render_html_report(report_for(case)),
        ):
            assert "False" in rendered and (
                repr(erase) in rendered or escape(repr(erase)) in rendered
            )
    assert "echo hello" not in case.session.output


@pytest.mark.parametrize(
    "mode, reason", [("timeout", "TIMEOUT"), ("exit", "EOF"), ("crash", "EOF")]
)
def test_stopped_recovery_and_later_fresh_case(
    monkeypatch, mode, reason, keyboard_case, exact_input
):
    monkeypatch.setenv("KEYBOARD_MODE", mode)
    broken = keyboard_case.run(SHELL, timeout=0.25)
    assert broken.session.reason == reason
    assert incoming(broken) == [exact_input]
    assert broken.session.undispatched == ["echo keyboard_alive"]
    assert all(
        r.sent_bytes == 0
        for r in broken.session.action_dispatch
        if r.command_index == 2
    )
    assert broken.session.interactions[-1].command == keyboard_case.commands[0].text
    assert broken.session.raw_output
    assert broken.session.direct_child_reaped
    if mode == "exit":
        assert broken.session.exit_status == 7
    elif mode == "crash":
        assert broken.session.signal_status == signal.SIGSEGV
    else:
        assert broken.session.signal_status is None
        assert broken.session.cleanup_signal_status == signal.SIGTERM
    monkeypatch.setenv("KEYBOARD_MODE", "edit")
    later = keyboard_case.run(SHELL, timeout=1)
    assert later.session.pid != broken.session.pid
    assert later.session.working_directory != broken.session.working_directory
    assert later.session.reason == "COMPLETED"
    for rendered in (
        render_report(report_for(broken)),
        render_html_report(report_for(broken)),
    ):
        assert "Undispatched; 0/19 bytes" in rendered
        assert "remaining=b" in rendered
        assert "echo keyboard_alive" in rendered
        assert "Sequence stopped" in rendered
        assert reason in rendered


def test_real_partial_action_dispatch_is_bounded(monkeypatch, keyboard_case):
    monkeypatch.setenv("KEYBOARD_MODE", "blocked")
    commands = (
        pty.Command(
            "blocked action plan",
            actions=(pty.Action("type", b"x" * 131072), pty.Action("enter", b"\n")),
        ),
        pty.Command("echo keyboard_alive"),
    )
    result = pty.run_session(
        SHELL, commands, timeout=0.2, terminal_type="xterm", max_output_bytes=16
    )
    assert result.reason == "TIMEOUT"
    assert 0 < result.action_dispatch[0].sent_bytes < 131072
    assert all(r.sent_bytes == 0 for r in result.action_dispatch[1:])
    assert result.undispatched == [c.text for c in commands]
    assert result.interactions[-1].waiting_for == "command dispatch"
    assert result.interaction_seconds <= 0.4 + 0.25
    assert result.direct_child_reaped
    case = CaseEvidence("T1.partial", "T1", "Partial action", commands, result)
    for rendered in (
        render_report(report_for(case)),
        render_html_report(report_for(case)),
    ):
        assert "Partially sent" in rendered and "Undispatched" in rendered
    monkeypatch.setenv("KEYBOARD_MODE", "edit")
    assert keyboard_case.run(SHELL, timeout=1).session.reason == "COMPLETED"


def test_keystrokes_share_original_deadline(monkeypatch, keyboard_case):
    dispatch = pty._dispatch
    deadlines = []

    def slow_dispatch(child, record, deadline):
        deadlines.append(deadline)
        time.sleep(0.07)  # Deliberate dispatch latency, not fixture synchronization.
        return dispatch(child, record, deadline)

    monkeypatch.setattr(pty, "_dispatch", slow_dispatch)
    case = keyboard_case.run(SHELL, timeout=0.2)
    assert len(deadlines) == 3 and len(set(deadlines)) == 1
    assert case.session.reason == "TIMEOUT"
    assert [
        r.sent_bytes
        for r in case.session.action_dispatch[: len(keyboard_case.commands[0].actions)]
    ] == (
        [9, 3, 0, 0, 0, 0]
        if keyboard_case.case_id == "T1.cursor-insertion"
        else [10, 1, 0, 0]
    )
    assert case.session.undispatched == [c.text for c in keyboard_case.commands]
    assert case.session.interactions[-1].waiting_for == "command dispatch"
    assert case.session.interaction_seconds <= 0.4 + 0.25


def test_raw_views_are_inert_exact_and_same_bounded_prefix(keyboard_case):
    case = keyboard_case.run(SHELL, timeout=1, max_output_bytes=140)
    assert case.session.truncated and len(case.session.raw_output) == 140
    assert case.session.reason == "COMPLETED"
    assert b"\x1b" in case.session.raw_output and b"\xff" in case.session.raw_output
    markdown = render_report(report_for(case))
    html = render_html_report(report_for(case))
    assert case.raw_output_escaped in markdown
    assert escape(case.raw_output_escaped) in html
    assert "\\x1b" in markdown and "\\xff" in markdown and "\\x08" in markdown
    assert "</code><script>hostile</script>" not in html
    assert "\x1b" not in markdown + html
    assert "Retained raw-byte count: 140" in markdown + html
    assert "TRUNCATED" in markdown + html
    assert (
        "row.textContent" in html
    )  # Search indexes full retained raw/cleaned sections.
    full = keyboard_case.run(SHELL, timeout=1, max_output_bytes=4096)
    full.session.raw_output += (
        b"\n" + b"tail" * 300
    )  # Synthetic retained evidence for preview distinction.
    full.session.truncated = False
    html = render_html_report(report_for(full))
    assert "Preview shortened" in html and "Capture not truncated" in html
    assert escape(full.raw_output_escaped) in html


def test_canonical_driver_deletion_and_startup_fallback(
    monkeypatch, keyboard_case, exact_input
):
    if keyboard_case.case_id == "T1.cursor-insertion":
        monkeypatch.setenv("KEYBOARD_MODE", "canonical")
    else:
        monkeypatch.setenv(
            "KEYBOARD_MODE", "canonical-bs" if exact_input[10] == 8 else "canonical"
        )
    case = keyboard_case.run(SHELL, timeout=1)
    assert incoming(case) == [
        exact_input
        if keyboard_case.case_id == "T1.cursor-insertion"
        else b"echo hello\n",
        b"echo keyboard_alive\n",
    ]
    assert dict(case.session.terminal_observations[1].modes)["ICANON"] is True
    assert (
        b"".join(
            r.action.data[: r.sent_bytes]
            for r in case.session.action_dispatch[
                : len(keyboard_case.commands[0].actions)
            ]
        )
        == exact_input
    )
    monkeypatch.setenv("KEYBOARD_MODE", "missing")
    # This fixture intentionally omits its prompt; allow interpreter startup
    # before fallback so the byte-recorder has installed its input mode.
    fallback = keyboard_case.run(SHELL, timeout=1)
    assert fallback.session.interactions[0].reason == "TIMEOUT"
    assert incoming(fallback) == [exact_input, b"echo keyboard_alive\n"]
    assert fallback.session.reason == "COMPLETED"
    monkeypatch.setenv("KEYBOARD_MODE", "startup_exit")
    early = keyboard_case.run(SHELL, timeout=1)
    assert early.session.reason == "EOF" and early.session.exit_status == 19
    assert all(r.sent_bytes == 0 for r in early.session.action_dispatch)
    assert early.session.undispatched == [c.text for c in keyboard_case.commands]
    assert early.session.raw_output == b"startup evidence\r\n"


@pytest.mark.parametrize(
    "actions",
    [
        (pty.Action("type", b"x"),),
        (pty.Action("enter", b"\n"), pty.Action("enter", b"\n")),
        (pty.Action("type", b"x\ny"), pty.Action("enter", b"\n")),
        (pty.Action("key", b""), pty.Action("enter", b"\n")),
        (pty.Action("enter", b"\r"),),
    ],
)
def test_invalid_action_plans_rejected_before_launch(actions, owned_sessions):
    with pytest.raises(ValueError):
        pty.run_session(SHELL, [pty.Command("invalid", actions=actions)])
    assert not owned_sessions


def test_exit_during_keys_retains_available_output_and_unsent_actions(
    monkeypatch, keyboard_case, exact_input
):
    monkeypatch.setenv("KEYBOARD_MODE", "key_exit")
    dispatch = pty._dispatch

    def pause_after_key(child, record, deadline):
        event = dispatch(child, record, deadline)
        if record.action.data == (
            b"\x1b[D"
            if keyboard_case.case_id == "T1.cursor-insertion"
            else exact_input[10:11]
        ):
            # Fault injection: observe termination before the next action,
            # within the original deadline, even on a heavily scheduled host.
            while child.isalive() and time.monotonic() < deadline:
                time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))
        return event

    monkeypatch.setattr(pty, "_dispatch", pause_after_key)
    case = keyboard_case.run(SHELL, timeout=0.5)
    assert case.session.reason == "EOF" and case.session.exit_status == 7
    assert [
        r.sent_bytes
        for r in case.session.action_dispatch[: len(keyboard_case.commands[0].actions)]
    ] == (
        [9, 3, 0, 0, 0, 0]
        if keyboard_case.case_id == "T1.cursor-insertion"
        else [10, 1, 0, 0]
    )
    assert incoming(case) == [
        exact_input[:12]
        if keyboard_case.case_id == "T1.cursor-insertion"
        else exact_input[:11]
    ]
    assert "key exit evidence" in case.session.output
    assert case.session.undispatched == [c.text for c in keyboard_case.commands]
    assert case.session.interactions[-1].waiting_for == "command dispatch"
    assert case.session.signal_status is None and case.session.direct_child_reaped
