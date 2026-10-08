"""Full evidence workflow: host validation, suite orchestration, and presentation."""

import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cwushell_test.evidence import CaseEvidence, ExecutionMetadata, Report
from cwushell_test.information_scenarios import CPU_CASES, HELP_CASES, MEMORY_CASES
from cwushell_test.reporting import ReportWriteError, write_report
from cwushell_test.shell_scenarios import (
    PROMPT_CASES,
    SYSTEM_CASES,
    TERMINATION_CASES,
)

if TYPE_CHECKING:
    from cwushell_test.cli import Configuration

SUITES = (
    ("T1", PROMPT_CASES),
    ("T2", TERMINATION_CASES),
    ("T3", CPU_CASES),
    ("T4", MEMORY_CASES),
    ("T5", HELP_CASES),
    ("T6", SYSTEM_CASES),
)


def validate_runtime() -> None:
    """Reject unavailable host prerequisites before launching any target session."""
    for utility in ("ls", "pwd", "echo", "cat", "cp", "rm", "printenv"):
        if shutil.which(utility) is None:
            raise RuntimeError(
                f"required host utility {utility!r} is unavailable; "
                "install it and include its executable directory in PATH"
            )
    for executable in ("/bin/true", "/bin/false"):
        if not Path(executable).is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError(f"required host executable is unavailable: {executable}")


def target_architecture(target: Path) -> str:
    """Read the bounded ELF header; never equate an unknown target with the host."""
    with target.open("rb") as stream:
        header = stream.read(20)
    if header.startswith(b"#!"):
        return "Interpreted script; architecture depends on its interpreter"
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[5] not in (1, 2):
        return "Unknown (no recognized ELF architecture header)"
    machine = int.from_bytes(header[18:20], "little" if header[5] == 1 else "big")
    name = {
        3: "x86",
        8: "MIPS",
        20: "PowerPC",
        21: "PowerPC64",
        40: "ARM",
        62: "x86_64",
        183: "AArch64",
        243: "RISC-V",
        258: "LoongArch",
    }.get(machine, f"Unknown ELF machine {machine}")
    bits = {1: "32-bit", 2: "64-bit"}.get(header[4], "unknown ELF class")
    return f"{name} ({bits}, ELF machine {machine})"


def execute(config: "Configuration") -> int:
    """Finish all independent student cases; invocation failures remain exit 1."""
    validate_runtime()
    metadata = ExecutionMetadata(
        datetime.now(timezone.utc),
        config.target,
        target_architecture(config.target),
        platform.release(),
        config.timeout,
        config.max_output_bytes,
        host_architecture=platform.machine(),
    )
    print(f"Target binary: {config.target}", flush=True)
    print(f"Host architecture: {metadata.host_architecture}", flush=True)
    cases: list[CaseEvidence] = []
    for suite_id, scenarios in SUITES:
        print(f"Executing {suite_id}: {len(scenarios)} independent cases", flush=True)
        for scenario in scenarios:
            case = scenario.run(
                config.target,
                timeout=config.timeout,
                max_output_bytes=config.max_output_bytes,
            )
            cases.append(case)
            if case.session.reason == "ERROR" or case.session.cleanup_error:
                raise RuntimeError(
                    f"harness preparation, launch, execution, or cleanup error in "
                    f"{case.case_id} for {config.target}: "
                    f"{case.session.error or case.session.cleanup_error}; "
                    "check the target's executable format/interpreter and host "
                    "permissions/resources"
                )
    report = Report(metadata, tuple(cases))
    try:
        destination = write_report(report, config.output, config.report_format)
    except ReportWriteError as exc:
        raise RuntimeError(str(exc)) from exc
    print(f"Execution summary: {len(report.cases)} cases", flush=True)
    for case in report.cases:
        summary = case.summary
        events = "; ".join(
            f"{'Startup' if event.command is None else repr(event.command)}: "
            f"{event.reason} (wait {event.waiting_for!r})"
            for event in summary.events
        )
        print(
            f"{summary.case_id}: {', '.join(summary.outcomes)}; {events}; "
            f"exit={summary.exit_status}, signal={summary.signal_status}; "
            f"dispatched={summary.dispatched_count}, "
            f"undispatched={summary.undispatched_count}",
            flush=True,
        )
    label = "HTML" if config.report_format == "html" else "Markdown"
    print(f"{label} report: {destination}", flush=True)
    return 0
