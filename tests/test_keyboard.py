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


@pytest.fixture(params=["T1.history-up", "T1.history-navigation"])
def history_case(request):
    return next(c for c in PROMPT_CASES if c.case_id == request.param)


def history_inputs(history_case):
    return [
        b"".join(action.data for action in command.input_actions)
        for command in history_case.commands
    ]


def test_history_exact_bytes_pacing_isolated_home_and_separate_output(
    monkeypatch, tmp_path, history_case
):
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    (real_home / ".history").write_bytes(b"private user history\n")
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("HISTFILE", str(real_home / ".history"))
    monkeypatch.setenv("BASH_ENV", str(real_home / "startup"))
    dispatch = pty._dispatch
    setup_seen = 0
    navigation_index = len(history_case.commands) - 1
    dispatch_deadlines = []
    wait_deadlines = []
    wait = pty._Reader.wait

    def observe_wait(reader, prompt, deadline):
        nonlocal setup_seen
        event = wait(reader, prompt, deadline)
        wait_deadlines.append(deadline)
        if (
            b'LINE "echo history_one"' in reader.evidence.raw_output
            and event == "PROMPT"
        ):
            setup_seen += 1
        return event

    def observe_dispatch(child, record, deadline):
        if record.command_index == navigation_index:
            dispatch_deadlines.append(deadline)
            assert (
                setup_seen == navigation_index - 1
            )  # A returning setup prompt precedes Up, not just text.
        return dispatch(child, record, deadline)

    monkeypatch.setattr(pty._Reader, "wait", observe_wait)
    monkeypatch.setattr(pty, "_dispatch", observe_dispatch)
    case = history_case.run(SHELL, timeout=1)
    session = case.session
    assert history_case.commands[-2].actions == (
        *(pty.Action("key", b"\x1b[A"),) * (navigation_index - 1),
        *((pty.Action("key", b"\x1b[B"),) if navigation_index == 3 else ()),
        pty.Action("enter", b"\n"),
    )
    assert incoming(case) == history_inputs(history_case)
    assert len(dispatch_deadlines) == len(history_case.commands[-2].actions)
    assert set(dispatch_deadlines) == {wait_deadlines[navigation_index]}
    assert len(wait_deadlines) == len(history_case.commands) + 1
    assert [e.reason for e in session.interactions] == ["PROMPT"] * (
        len(history_case.commands) + 1
    )
    slices = [
        session.raw_output[e.retained_start : e.retained_end]
        for e in session.interactions
    ]
    assert b"BYTES 6563686f20686973746f72795f6f6e650a" in slices[1]
    assert b"BYTES 1b5b410a" not in slices[1]
    navigation = slices[navigation_index]
    expected_marker = b"history_two" if navigation_index == 3 else b"history_one"
    assert b"BYTES " + history_inputs(history_case)[-2].hex().encode() in navigation
    assert b'LINE "echo ' + expected_marker + b'"' in navigation
    assert expected_marker + b"\r\n" in navigation
    assert b"\r\x1b[K" in navigation
    assert b"keyboard_alive" not in navigation
    if navigation_index == 3:
        assert b'LINE "echo history_two"' in slices[2]
        assert b"BYTES 1b5b411b5b411b5b420a" not in slices[2]
        assert (
            b"\r\x1b[Kecho history_two\r\n"
            b"\r\x1b[Kecho history_one\r\n"
            b"\r\x1b[Kecho history_two\r\n"
        ) in navigation
    assert b"".join(slices) == session.raw_output
    assert session.controlled_environment["HOME"] == session.working_directory
    assert (
        session.controlled_environment["HISTFILE"]
        == session.working_directory + "/.history"
    )
    assert session.controlled_environment["BASH_ENV"] is None
    assert (real_home / ".history").read_bytes() == b"private user history\n"
    assert not next(o for o in case.file_observations if o.phase == "before").exists
    created = next(o for o in case.file_observations if o.path == ".synthetic_history")
    assert created.phase == "after" and created.contents == (
        b"echo history_one\necho history_two\necho history_two\n"
        if navigation_index == 3
        else b"echo history_one\necho history_one\n"
    )
    assert not Path(session.working_directory).exists() and session.direct_child_reaped
    assert session.controlled_environment["TERM"] == "xterm"
    assert dict(session.terminal_observations[1].modes)["ICANON"] is False
    assert (
        sum(c.case_id == history_case.case_id for _, cases in SUITES for c in cases)
        == 1
    )
    for rendered in (
        render_report(report_for(case)),
        render_html_report(report_for(case)),
    ):
        assert "Separate interaction terminal evidence" in rendered
        assert "Interaction raw terminal bytes" in rendered
        assert "CSI A" in rendered and "fresh empty HOME" in rendered
        if navigation_index == 3:
            assert "CSI B" in rendered and "echo history_two" in rendered
            assert (
                repr(b"\x1b[A\x1b[A\x1b[B\n") in rendered
                or escape(repr(b"\x1b[A\x1b[A\x1b[B\n")) in rendered
            )
        assert "\x1b" not in rendered
        assert "\\xff" in rendered and "\\x08" in rendered
    html = render_html_report(report_for(case))
    assert escape(case.raw_output_escaped) in html
    assert case.raw_output_escaped in render_report(report_for(case))
    assert "</code><script>hostile</script>" not in html
    assert "Preview shortened" in html and "Capture not truncated" in html
    assert "row.textContent" in html
    for rendered in (render_report(report_for(case)), html):
        assert ".synthetic_history" in rendered and "Fully sent; 3/3 bytes" in rendered
        assert (
            "optional" in rendered.lower()
            and "Remaining undispatched commands" in rendered
        )


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("unsupported", "COMPLETED"),
        ("timeout", "TIMEOUT"),
        ("exit", "EOF"),
        ("crash", "EOF"),
        ("startup_exit", "EOF"),
        ("missing", "COMPLETED"),
    ],
)
def test_history_unsupported_faults_fallback_and_fresh_continuation(
    monkeypatch, mode, reason, history_case
):
    monkeypatch.setenv("KEYBOARD_MODE", mode)
    case = history_case.run(SHELL, timeout=1 if mode == "missing" else 0.3)
    assert case.session.reason == reason
    if mode == "startup_exit":
        assert not incoming(case) and len(case.session.undispatched) == len(
            history_case.commands
        )
    else:
        assert (
            incoming(case)[: len(history_case.commands) - 1]
            == history_inputs(history_case)[:-1]
        )
        assert (
            "LINE " + json.dumps(history_inputs(history_case)[-2][:-1].decode())
            in case.session.output
        )
        if reason != "COMPLETED":
            assert case.session.undispatched == ["echo keyboard_alive"]
            assert all(
                r.sent_bytes == 0
                for r in case.session.action_dispatch
                if r.command_index == len(history_case.commands)
            )
        else:
            assert incoming(case)[-1] == b"echo keyboard_alive\n"
    if mode == "exit":
        assert case.session.exit_status == 7
    if mode == "crash":
        assert case.session.signal_status == signal.SIGSEGV
    if mode == "timeout":
        assert case.session.signal_status is None
        assert case.session.cleanup_signal_status == signal.SIGTERM
    monkeypatch.setenv("KEYBOARD_MODE", "edit")
    later = history_case.run(SHELL, timeout=1)
    assert later.session.reason == "COMPLETED"
    assert later.session.pid != case.session.pid
    assert later.session.working_directory != case.session.working_directory
    for rendered in (
        render_report(report_for(case)),
        render_html_report(report_for(case)),
    ):
        assert reason in rendered and "Action dispatch accounting" in rendered


@pytest.mark.parametrize("mode", ["edit", "key_exit"])
def test_history_dispatch_deadline_or_exit_leaves_enter_and_recovery_unsent(
    monkeypatch, mode, history_case
):
    monkeypatch.setenv("KEYBOARD_MODE", mode)
    dispatch = pty._dispatch
    deadlines = []

    def delay_after_up(child, record, deadline):
        if record.command_index == len(history_case.commands) - 1:
            deadlines.append(deadline)
        event = dispatch(child, record, deadline)
        if record.action.data == b"\x1b[A":
            if mode == "edit":
                time.sleep(max(0, deadline - time.monotonic()) + 0.01)
            else:
                while child.isalive() and time.monotonic() < deadline:
                    time.sleep(0.001)
        return event

    monkeypatch.setattr(pty, "_dispatch", delay_after_up)
    case = history_case.run(SHELL, timeout=0.3)
    assert case.session.reason == ("TIMEOUT" if mode == "edit" else "EOF")
    records = [
        r
        for r in case.session.action_dispatch
        if r.command_index >= len(history_case.commands) - 1
    ]
    assert [r.sent_bytes for r in records] == [3] + [0] * (
        len(history_case.commands[-2].actions) + 1
    )
    assert len(set(deadlines)) == 1
    assert case.session.undispatched == [c.text for c in history_case.commands[-2:]]
    assert case.session.interactions[-1].waiting_for == "command dispatch"
    assert case.session.direct_child_reaped
    for rendered in (
        render_report(report_for(case)),
        render_html_report(report_for(case)),
    ):
        assert "Fully sent; 3/3 bytes" in rendered
        assert "Undispatched; 0/1 bytes" in rendered
        assert "Undispatched; 0/19 bytes" in rendered
        assert "Sequence stopped" in rendered and "remaining=b" in rendered


def test_history_bounded_raw_views_and_interaction_ranges(history_case):
    case = history_case.run(SHELL, timeout=1, max_output_bytes=140)
    assert case.session.reason == "COMPLETED" and case.session.truncated
    assert len(case.session.raw_output) == 140
    assert all(
        e.retained_start is not None
        and e.retained_end is not None
        and 0 <= e.retained_start <= e.retained_end <= 140
        for e in case.session.interactions
    )
    assert (
        case.session.interactions[-1].retained_start
        == case.session.interactions[-1].retained_end
        == 140
    )
    for rendered in (
        render_report(report_for(case)),
        render_html_report(report_for(case)),
    ):
        assert "empty slices after truncation" in rendered
        assert "TRUNCATED" in rendered and "Retained raw-byte count: 140" in rendered
        assert "\x1b" not in rendered
        assert (
            "</code><script>hostile</script>" not in rendered
            or rendered == render_report(report_for(case))
        )


def test_home_inventory_is_bounded_and_does_not_follow_links(tmp_path):
    from cwushell_test.fixtures import snapshot_home

    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "history").write_bytes(b"private history")
    (home / "linked").symlink_to(outside, target_is_directory=True)
    (home / "fifo").parent.mkdir(exist_ok=True)
    os.mkfifo(home / "fifo")
    nested = home / ".config"
    nested.mkdir()
    (nested / "custom-history").write_bytes(b"owned history\n")
    observations, notes = snapshot_home(home)
    assert (
        next(o for o in observations if o.path == ".config/custom-history").contents
        == b"owned history\n"
    )
    assert not any(o.contents == b"private history" for o in observations)
    assert next(o for o in observations if o.path == "linked").error
    assert next(o for o in observations if o.path == "fifo").error
    assert not notes
    for index in range(140):
        (home / f"entry{index}").touch()
    observations, notes = snapshot_home(home)
    assert len(observations) <= 129  # 128 discovered entries plus explicit .history.
    assert "HOME inventory truncated at 128 entries" in notes
