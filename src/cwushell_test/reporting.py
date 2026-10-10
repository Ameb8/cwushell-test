"""Shared evidence presentation, Markdown rendering, and report writing."""

import re
from pathlib import Path
from typing import Protocol

from cwushell_test.evidence import CaseEvidence, Report


def _cell(value: str) -> str:
    """Encode punctuation/whitespace so arbitrary text cannot form table markup."""
    return "".join(
        character if character.isalnum() else f"&#{ord(character)};"
        for character in value
    )


def _block(value: str) -> str:
    """Use a fence longer than every backtick run, with a separate closing line."""
    longest = max((len(run) for run in re.findall(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    ending = "" if value.endswith("\n") else "\n"
    return f"{fence}text\n{value}{ending}{fence}\n"


def _field(label: str, value: object) -> str:
    return f"{label}:\n\n{_block(str(value))}\n"


def _commands(label: str, commands: list[str]) -> str:
    result = f"#### {label}\n\n"
    if not commands:
        return result + "None.\n\n"
    result += (
        "Escaped input representation: actual tabs are shown as `\\t`; "
        "backslashes as `\\\\`. Multiple spaces are preserved. "
        "The helper appends one LF to each fully dispatched input line.\n\n"
    )
    for index, command in enumerate(commands, 1):
        result += f"Input {index}:\n\n"
        result += _block(command.replace("\\", "\\\\").replace("\t", "\\t")) + "\n"
    return result


class EvidenceRenderer(Protocol):
    """Presentation operations shared by both detailed evidence formats."""

    def start_case(self, index: int) -> str: ...
    def text(self, value: str) -> str: ...
    def section(self, title: str) -> str: ...
    def field(self, label: str, value: object) -> str: ...
    def block(self, value: str) -> str: ...
    def commands(self, label: str, commands: list[str]) -> str: ...
    def finish_case(self) -> str: ...


class MarkdownRenderer:
    def start_case(self, index: int) -> str:
        return f"### Case {index}\n\n"

    def text(self, value: str) -> str:
        return value

    def section(self, title: str) -> str:
        return f"#### {title}\n\n"

    field = staticmethod(_field)
    block = staticmethod(_block)
    commands = staticmethod(_commands)

    def finish_case(self) -> str:
        return ""


def _case(
    case: CaseEvidence, index: int, renderer: EvidenceRenderer | None = None
) -> str:
    if renderer is None:
        renderer = MarkdownRenderer()
    _field = renderer.field
    _block = renderer.block
    _commands = renderer.commands
    session = case.session
    result = renderer.start_case(index)
    for label, value in (
        ("Case identifier", case.case_id),
        ("Suite", case.suite_id),
        ("Description", case.title),
        ("Session working directory", session.working_directory),
    ):
        result += _field(label, value)
    result += renderer.section("Initial fixtures and controlled environment")
    if not case.fixtures:
        result += renderer.text("No fixtures recorded.\n\n")
    for fixture in case.fixtures:
        result += _field("Fixture path", fixture.path)
        result += _field("Fixture kind", fixture.kind)
        if fixture.contents is not None:
            result += _field(
                "Initial contents (exact bytes representation)", repr(fixture.contents)
            )
    if not case.controlled_environment:
        result += renderer.text("No controlled environment settings recorded.\n\n")
    for key, initial_value in case.controlled_environment.items():
        result += _field("Environment variable", key)
        result += _field(
            "Initial value", "Absent" if initial_value is None else initial_value
        )

    if case.has_action_plan:
        result += renderer.section("Planned commands and ordered keystroke actions")
        result += renderer.text(
            "Interaction labels describe the plan, not observed edited commands. "
            "Type sends text bytes; Key sends a literal sequence; Enter sends one "
            "explicit LF. No LF is appended to other actions. Recovery waits for "
            "the preceding prompt. Each interaction has one original deadline.\n\n"
        )
        for input_index, command in enumerate(case.commands, 1):
            result += _field(f"Planned input {input_index} label", command.text)
            result += _field(
                "Exact planned input bytes",
                repr(b"".join(action.data for action in command.input_actions)),
            )
            for action_index, action in enumerate(command.input_actions, 1):
                result += _field(
                    f"Planned action {input_index}.{action_index} ({action.kind})",
                    repr(action.data),
                )
        for label, commands in (
            ("Dispatched commands (fully sent)", session.dispatched),
            ("Remaining undispatched commands", session.undispatched),
        ):
            result += renderer.section(label)
            result += _field("Interaction labels", repr(commands))
        result += renderer.section("Action dispatch accounting")
        for record in session.action_dispatch:
            size = len(record.action.data)
            state = (
                "Fully sent"
                if record.sent_bytes == size
                else "Partially sent"
                if record.sent_bytes
                else "Undispatched"
            )
            result += _field(
                f"Action {record.command_index}.{record.action_index} ({record.action.kind})",
                f"{state}; {record.sent_bytes}/{size} bytes; "
                f"sent={record.action.data[: record.sent_bytes]!r}; "
                f"remaining={record.action.data[record.sent_bytes :]!r}",
            )
        if session.undispatched:
            result += renderer.text(
                "Sequence stopped; recovery may remain undispatched. The execution "
                "events below identify the triggering wait or dispatch event.\n\n"
            )
    else:
        result += _commands(
            "Planned commands", [command.text for command in case.commands]
        )
        result += _commands("Dispatched commands (fully sent)", session.dispatched)
        result += _commands("Remaining undispatched commands", session.undispatched)
        if session.undispatched:
            result += renderer.text(
                "Incomplete command sequence. A command dispatch timeout can send a "
                "partial line; that input remains in the undispatched list.\n\n"
            )
    for input_index, command in enumerate(case.commands, 1):
        result += _field(
            f"Planned input {input_index} wait target",
            command.prompt if command.prompt is not None else "EOF",
        )
    result += renderer.section("Terminal settings (read-only observations)")
    result += _field("Terminal/key-sequence profile", session.terminal_profile)
    result += renderer.text(
        "TERM is the controlled launch environment value. Snapshots are taken "
        "through the owned PTY only; target changes between snapshots are not "
        "observable. No termios editing modes or erase keys are forced.\n\n"
    )
    for terminal_observation in session.terminal_observations:
        result += _field("Terminal snapshot phase", terminal_observation.phase)
        if terminal_observation.error is not None:
            result += _field(
                "Terminal snapshot unavailable", terminal_observation.error
            )
            continue
        result += _field(
            "Termios flags (iflag, oflag, cflag, lflag)", terminal_observation.flags
        )
        result += _field("Relevant termios modes", dict(terminal_observation.modes))
        result += _field(
            "Observed VERASE (exact bytes)", repr(terminal_observation.verase)
        )
        if case.has_action_plan:
            result += _field(
                "Observed VERASE equals DEL (\\x7f)",
                terminal_observation.verase == b"\x7f",
            )
            result += _field(
                "Observed VERASE equals BS (\\x08)",
                terminal_observation.verase == b"\x08",
            )

    result += renderer.section("Combined PTY terminal output")
    result += renderer.text(
        "Student terminal evidence; stdout and stderr share the PTY. "
        "ANSI sequences are removed, UTF-8 decoding replaces invalid bytes, "
        "and line endings are normalized to LF. Evidence text is not a harness judgment.\n\n"
    )
    result += _block(session.output) + "\n"
    result += renderer.section("Raw PTY terminal bytes (escaped representation)")
    result += renderer.text(
        "Exact raw bytes from the same bounded retained prefix as the cleaned "
        "transcript, shown as an ASCII bytes literal. Escapes preserve ANSI, CR, "
        "backspace and invalid UTF-8; no terminal controls execute here.\n\n"
    )
    result += _block(case.raw_output_escaped) + "\n"
    result += renderer.section("Capture notes")
    result += renderer.text(
        "TRUNCATED: retained raw terminal-output prefix only.\n\n"
        if session.truncated
        else "Terminal capture was not truncated.\n\n"
    )
    result += renderer.text(
        f"Configured raw-byte limit: {session.max_output_bytes}. Retained raw-byte count: {len(session.raw_output)}.\n\n"
    )
    result += renderer.text(
        "Events and command dispatch are recorded independently of capture truncation.\n\n"
    )
    if any(
        event.reason == "TIMEOUT"
        and event.waiting_for not in ("EOF", "command dispatch")
        for event in session.interactions
    ):
        result += renderer.text(
            "Prompt synchronization was not established before a deadline. "
            "Retained evidence may end before command output finished; the "
            "capture-limit note describes byte retention only.\n\n"
        )

    result += renderer.section("Harness-collected fixture evidence")
    if not case.file_observations:
        result += renderer.text("No file observations recorded.\n\n")
    for observation in case.file_observations:
        result += _field("Observed path", observation.path)
        result += _field(
            "Snapshot phase",
            "Before launch"
            if observation.phase == "before"
            else "After process/PTY cleanup, before directory removal",
        )
        result += _field(
            "Exists",
            "Unknown" if observation.exists is None else str(observation.exists),
        )
        if observation.contents is None:
            result += renderer.text("Contents were not collected.\n\n")
        else:
            result += _field(
                "Contents (UTF-8, invalid bytes replaced)",
                observation.contents.decode("utf-8", errors="replace"),
            )
            result += _field(
                "Contents (exact bytes representation)", repr(observation.contents)
            )
        if observation.error is not None:
            result += _field("Observation diagnostic", observation.error)

    result += renderer.section("Execution and cleanup notes")
    result += _field("Observed execution labels", ", ".join(case.summary.outcomes))
    for index, event in enumerate(session.interactions, 1):
        result += _field(
            f"Event {index} phase", "Startup" if event.command is None else "Command"
        )
        result += _field("Event observation", event.reason)
        result += _field("Wait target", event.waiting_for)
        if event.command is not None:
            if case.has_action_plan:
                result += _field("Event interaction label", event.command)
            else:
                result += _commands("Event input", [event.command])
    if (
        session.interactions
        and session.interactions[0].reason == "TIMEOUT"
        and session.dispatched
    ):
        result += renderer.text(
            "Initial prompt timeout was retained; command dispatch continued using startup fallback.\n\n"
        )
    for label, execution_value in (
        ("Helper final reason", session.reason),
        ("Observed process exit status", session.exit_status),
        ("Observed terminating signal", session.signal_status),
        ("Execution diagnostic", session.error),
        ("PID", session.pid),
        ("Owned process group", session.pgid),
        ("Launch seconds", session.launch_seconds),
        ("Interaction seconds", session.interaction_seconds),
        ("Cleanup seconds", session.cleanup_seconds),
        ("Direct child reaped", session.direct_child_reaped),
        ("Cleanup-phase exit status", session.cleanup_exit_status),
        ("Cleanup-phase signal", session.cleanup_signal_status),
        ("Cleanup diagnostic", session.cleanup_error),
    ):
        result += _field(
            label, "Not observed" if execution_value is None else execution_value
        )
    result += renderer.text(
        "Cleanup-phase statuses are separate from observed process termination.\n\n"
    )
    if not session.cleanup_actions:
        result += renderer.text("No cleanup actions recorded.\n\n")
    for cleanup_action in session.cleanup_actions:
        result += _field("Cleanup action", cleanup_action)
    for note in case.notes:
        result += _field("Execution note", note)
    return result + renderer.finish_case()


def _metadata_fields(report: Report) -> tuple[tuple[str, object], ...]:
    metadata = report.metadata
    return (
        ("Execution timestamp", metadata.timestamp.isoformat()),
        ("Target binary path", metadata.target),
        ("Target architecture", metadata.target_architecture),
        ("Host architecture", metadata.host_architecture),
        ("OS kernel version", metadata.kernel_version),
        ("Configured interaction timeout (seconds)", metadata.timeout),
        ("Configured per-session capture limit (raw bytes)", metadata.max_output_bytes),
    )


def _summary_values(case: CaseEvidence) -> tuple[str, ...]:
    summary = case.summary
    events = "; ".join(
        f"{'Startup' if event.command is None else 'Command'}: {event.reason}; wait target: {event.waiting_for}"
        for event in summary.events
    )
    return (
        summary.suite_id,
        summary.case_id,
        summary.title,
        ", ".join(summary.outcomes),
        events,
        "Not observed" if summary.exit_status is None else str(summary.exit_status),
        "Not observed" if summary.signal_status is None else str(summary.signal_status),
        f"{summary.dispatched_count} / {summary.undispatched_count}",
    )


def render_report(report: Report) -> str:
    """Render all recorded cases without collecting metadata or launching a PTY."""
    result = "# CWUShell execution evidence\n\n"
    result += (
        "For manual review. Execution labels describe observations only. "
        "COMPLETED means execution completion only; it does not imply correct output. "
        "PROMPT means synchronization, EOF means terminal closure, PROCESS_EXIT "
        "means an observed exit status, and SIGNAL means an observed terminating signal. "
        "Multiple observations can coexist, including TIMEOUT and COMPLETED.\n\n"
        "## Execution metadata\n\n"
    )
    for label, value in _metadata_fields(report):
        result += _field(label, value)
    result += "## Execution summary\n\n"
    result += "| Suite | Case | Description | Observed execution labels | Events | Exit status | Signal | Fully dispatched / undispatched |\n"
    result += "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    for case in report.cases:
        values = _summary_values(case)
        result += "| " + " | ".join(_cell(value) for value in values) + " |\n"
    result += "\n## Detailed case evidence\n\n"
    for index, case in enumerate(report.cases, 1):
        result += _case(case, index)
    return result


class ReportWriteError(Exception):
    """Actionable report I/O diagnostic for the workflow's exit-1 handling."""


def write_report(report: Report, output: Path, report_format: str = "markdown") -> Path:
    """Write the selected UTF-8 format; return the absolute destination.

    The workflow resolves paths relative to invocation before running sessions.
    Missing parent directories are reported, not silently created.
    """
    if report_format == "html":
        from cwushell_test.html_reporting import render_html_report

        content = render_html_report(report)
        label = "HTML"
    elif report_format == "markdown":
        content = render_report(report)
        label = "Markdown"
    else:
        raise ValueError(f"Unknown report format: {report_format!r}")
    try:
        destination = output.resolve()
        destination.write_text(content, encoding="utf-8", newline="\n")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReportWriteError(
            f"Cannot write {label} report to {str(output)!r}: {exc}. "
            "Check that the parent directory exists and the destination is a writable file."
        ) from exc
    return destination
