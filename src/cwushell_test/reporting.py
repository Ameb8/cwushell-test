"""Render evidence as inert Markdown and write the configured report path."""

import re
from pathlib import Path

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


def _case(case: CaseEvidence, index: int) -> str:
    session = case.session
    result = f"### Case {index}\n\n"
    for label, value in (
        ("Case identifier", case.case_id),
        ("Suite", case.suite_id),
        ("Description", case.title),
        ("Session working directory", session.working_directory),
    ):
        result += _field(label, value)
    result += "#### Initial fixtures and controlled environment\n\n"
    if not case.fixtures:
        result += "No fixtures recorded.\n\n"
    for fixture in case.fixtures:
        result += _field("Fixture path", fixture.path)
        result += _field("Fixture kind", fixture.kind)
        if fixture.contents is not None:
            result += _field(
                "Initial contents (exact bytes representation)", repr(fixture.contents)
            )
    if not case.controlled_environment:
        result += "No controlled environment settings recorded.\n\n"
    for key, initial_value in case.controlled_environment.items():
        result += _field("Environment variable", key)
        result += _field(
            "Initial value", "Absent" if initial_value is None else initial_value
        )

    result += _commands("Planned commands", [command.text for command in case.commands])
    for index, command in enumerate(case.commands, 1):
        result += _field(
            f"Planned input {index} wait target",
            command.prompt if command.prompt is not None else "EOF",
        )
    result += _commands("Dispatched commands (fully sent)", session.dispatched)
    result += _commands("Remaining undispatched commands", session.undispatched)
    if session.undispatched:
        result += (
            "Incomplete command sequence. A command dispatch timeout can send a "
            "partial line; that input remains in the undispatched list.\n\n"
        )

    result += "#### Combined PTY terminal output\n\n"
    result += (
        "Student terminal evidence; stdout and stderr share the PTY. "
        "ANSI sequences are removed, UTF-8 decoding replaces invalid bytes, "
        "and line endings are normalized to LF. Evidence text is not a harness judgment.\n\n"
    )
    result += _block(session.output) + "\n"
    result += "#### Capture notes\n\n"
    result += (
        "TRUNCATED: retained raw terminal-output prefix only.\n\n"
        if session.truncated
        else "Terminal capture was not truncated.\n\n"
    )
    result += f"Configured raw-byte limit: {session.max_output_bytes}. Retained raw-byte count: {len(session.raw_output)}.\n\n"
    result += "Events and command dispatch are recorded independently of capture truncation.\n\n"

    result += "#### Harness-collected fixture evidence\n\n"
    if not case.file_observations:
        result += "No file observations recorded.\n\n"
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
            result += "Contents were not collected.\n\n"
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

    result += "#### Execution and cleanup notes\n\n"
    result += _field("Observed execution labels", ", ".join(case.summary.outcomes))
    for index, event in enumerate(session.interactions, 1):
        result += _field(
            f"Event {index} phase", "Startup" if event.command is None else "Command"
        )
        result += _field("Event observation", event.reason)
        result += _field("Wait target", event.waiting_for)
        if event.command is not None:
            result += _commands("Event input", [event.command])
    if (
        session.interactions
        and session.interactions[0].reason == "TIMEOUT"
        and session.dispatched
    ):
        result += "Initial prompt timeout was retained; command dispatch continued using startup fallback.\n\n"
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
    result += (
        "Cleanup-phase statuses are separate from observed process termination.\n\n"
    )
    if not session.cleanup_actions:
        result += "No cleanup actions recorded.\n\n"
    for action in session.cleanup_actions:
        result += _field("Cleanup action", action)
    for note in case.notes:
        result += _field("Execution note", note)
    return result


def render_report(report: Report) -> str:
    """Render all recorded cases without collecting metadata or launching a PTY."""
    metadata = report.metadata
    result = "# CWUShell execution evidence\n\n"
    result += (
        "For manual review. Execution labels describe observations only. "
        "COMPLETED means execution completion only; it does not imply correct output. "
        "PROMPT means synchronization, EOF means terminal closure, PROCESS_EXIT "
        "means an observed exit status, and SIGNAL means an observed terminating signal. "
        "Multiple observations can coexist, including TIMEOUT and COMPLETED.\n\n"
        "## Execution metadata\n\n"
    )
    for label, value in (
        ("Execution timestamp", metadata.timestamp.isoformat()),
        ("Target binary path", metadata.target),
        ("Target architecture", metadata.target_architecture),
        ("Host architecture", metadata.host_architecture),
        ("OS kernel version", metadata.kernel_version),
        ("Configured interaction timeout (seconds)", metadata.timeout),
        ("Configured per-session capture limit (raw bytes)", metadata.max_output_bytes),
    ):
        result += _field(label, value)
    result += "## Execution summary\n\n"
    result += "| Suite | Case | Description | Observed execution labels | Events | Exit status | Signal | Fully dispatched / undispatched |\n"
    result += "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    for case in report.cases:
        summary = case.summary
        events = "; ".join(
            f"{'Startup' if event.command is None else 'Command'}: {event.reason}; wait target: {event.waiting_for}"
            for event in summary.events
        )
        values = (
            summary.suite_id,
            summary.case_id,
            summary.title,
            ", ".join(summary.outcomes),
            events,
            "Not observed" if summary.exit_status is None else str(summary.exit_status),
            "Not observed"
            if summary.signal_status is None
            else str(summary.signal_status),
            f"{summary.dispatched_count} / {summary.undispatched_count}",
        )
        result += "| " + " | ".join(_cell(value) for value in values) + " |\n"
    result += "\n## Detailed case evidence\n\n"
    for index, case in enumerate(report.cases, 1):
        result += _case(case, index)
    return result


class ReportWriteError(Exception):
    """Actionable report I/O diagnostic for the workflow's exit-1 handling."""


def write_report(report: Report, output: Path) -> Path:
    """Write UTF-8 Markdown to the caller's selected path; return its absolute path.

    The workflow resolves paths relative to invocation before running sessions.
    Missing parent directories are reported, not silently created.
    """
    try:
        destination = output.resolve()
        destination.write_text(render_report(report), encoding="utf-8", newline="\n")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReportWriteError(
            f"Cannot write Markdown report to {str(output)!r}: {exc}. "
            "Check that the parent directory exists and the destination is a writable file."
        ) from exc
    return destination
