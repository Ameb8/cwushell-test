"""Full Linux CLI/report verification using repository-owned synthetic targets."""

import html
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from cwushell_test import cli, pty_session, runner

SHELL = Path(__file__).parent / "fixtures" / "scenario_shell.py"
SCRIPT = Path(__file__).parents[1] / "cwushell_test.py"
INVENTORY = tuple(case for _, cases in runner.SUITES for case in cases)
pytestmark = pytest.mark.integration


def summary_rows(markdown: str) -> list[list[str]]:
    return [
        [html.unescape(value.strip()) for value in line.strip("|").split("|")]
        for line in markdown.splitlines()
        if line.startswith("| T")
    ]


def details(markdown: str) -> list[str]:
    return markdown.split("### Case ")[1:]


def assert_complete_report(markdown: str, terminal: str, target: Path, output: Path):
    rows = summary_rows(markdown)
    assert len(rows) == len(INVENTORY) == 58
    assert [row[1] for row in rows] == [case.case_id for case in INVENTORY]
    assert len(details(markdown)) == 58
    assert f"Target binary: {target}" in terminal
    assert f"Host architecture: {platform.machine()}" in terminal
    assert f"Markdown report: {output}" in terminal
    assert "Execution summary: 58 cases" in terminal
    for suite in range(1, 7):
        assert f"Executing T{suite}:" in terminal
    for row, detail in zip(rows, details(markdown), strict=True):
        line = next(
            line for line in terminal.splitlines() if line.startswith(row[1] + ":")
        )
        assert row[3] in line
        events = row[4].split("; ")
        for observation, wait in zip(events[::2], events[1::2], strict=True):
            reason = observation.split(": ")[-1]
            waiting_for = wait.removeprefix("wait target: ")
            assert f": {reason} (wait {waiting_for!r})" in line
        assert f"exit={None if row[5] == 'Not observed' else row[5]}" in line
        assert f"signal={None if row[6] == 'Not observed' else row[6]}" in line
        dispatched, undispatched = row[7].split(" / ")
        assert f"dispatched={dispatched}, undispatched={undispatched}" in line
        for label in (
            "Session working directory",
            "Initial fixtures and controlled environment",
            "Dispatched commands (fully sent)",
            "Combined PTY terminal output",
            "Capture notes",
            "Harness-collected fixture evidence",
            "Execution and cleanup notes",
            "Owned process group",
            "Direct child reaped",
            "Cleanup-phase signal",
        ):
            assert label in detail
        assert "Direct child reaped:\n\n```text\nTrue\n```" in detail
    for label in (
        "Execution timestamp",
        "Target binary path",
        "Target architecture",
        "Host architecture",
        "OS kernel version",
        "Configured interaction timeout",
        "Configured per-session capture limit",
    ):
        assert label in markdown
    assert "Interpreted script" in markdown
    assert platform.release() in markdown


@pytest.fixture
def recorded_groups(tmp_path: Path, monkeypatch):
    """Finally ownership of subprocess targets, even if a CLI assertion fails."""
    log = tmp_path / "groups.jsonl"
    monkeypatch.setenv("SCENARIO_LOG", str(log))
    monkeypatch.setenv("SCENARIO_MODE", "record")
    try:
        yield log
    finally:
        for pid, pgid, directory in read_groups(log):
            assert pid == pgid and pgid != os.getpgrp()
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def read_groups(log: Path) -> list[list]:
    return (
        [json.loads(line) for line in log.read_text().splitlines()]
        if log.exists()
        else []
    )


def assert_groups_released(log: Path, count: int):
    groups = read_groups(log)
    assert len(groups) == count
    assert len({record[2] for record in groups}) == count
    pgids = {record[1] for record in groups}
    for _, _, directory in groups:
        assert not Path(directory).exists()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            continue
        assert int(fields[2]) not in pgids or fields[0] == "Z"


# Launch latency is separate from interaction/cleanup allowances; 58 real PTYs
# can take about 50 seconds on hosts with large descriptor limits.
@pytest.mark.timeout(180)
@pytest.mark.parametrize("entry", ["console", "module", "script"])
def test_full_cli_inventory(entry, tmp_path: Path, recorded_groups):
    target = tmp_path / "target with spaces"
    shutil.copyfile(SHELL, target)
    target.chmod(0o700)
    output = tmp_path / "report with spaces.md"
    if entry == "console":
        invocation = [str(Path(sys.executable).with_name("cwushell-test"))]
    elif entry == "module":
        invocation = [sys.executable, "-m", "cwushell_test"]
    else:
        invocation = [sys.executable, str(SCRIPT)]
    if entry == "module":
        # Default target/output and limits, from outside the checkout.
        target = target.rename(tmp_path / "cwushell")
        output = tmp_path / "cwushell_test_report.md"
        args = []
    else:
        args = [
            target.name,
            "-o",
            output.name,
            "--timeout",
            "1",
            "--max-output-bytes",
            "4096",
        ]
    result = subprocess.run(
        invocation + args, cwd=tmp_path, capture_output=True, text=True, timeout=150
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    markdown = output.read_text()
    assert_complete_report(markdown, result.stdout, target, output)
    assert (
        f"Configured interaction timeout (seconds):\n\n```text\n{10.0 if entry == 'module' else 1.0}\n```"
        in markdown
    )
    assert (
        f"Configured per-session capture limit (raw bytes):\n\n```text\n{1048576 if entry == 'module' else 4096}\n```"
        in markdown
    )
    sections = details(markdown)
    for scenario, section in zip(INVENTORY, sections, strict=True):
        for command in scenario.commands:
            assert command.text.replace("\t", "\\t") in section
        assert "EARLY INPUT" not in section
        assert "Remaining undispatched commands\n\nNone." in section
        received = [
            json.loads(part.splitlines()[0])[0]
            for part in section.split("RECEIVED ")[1:]
        ]
        assert received == [command.text for command in scenario.commands]
        initial = json.loads(section.split("INITIAL ", 1)[1].splitlines()[0])
        if scenario.case_id == "T6.cd":
            assert initial["fixture_dir"] == []
            assert json.loads(section.split("RECEIVED ")[-1].splitlines()[0])[2] == str(
                Path(initial["cwd"]) / "fixture_dir"
            )
        elif scenario.case_id == "T6.export":
            assert initial["export"] is None
            assert 'ENVIRONMENT "fixture_value"' in section
        elif scenario.case_id == "T6.unset":
            assert initial["unset"] == "fixture_value"
            assert "ENVIRONMENT null" in section
    # Direct observations come from the real fixture lifecycle, after cleanup.
    copy_section = sections[[case.case_id for case in INVENTORY].index("T6.cp")]
    assert "b'cwushell-test source fixture\\n'" in copy_section
    assert "After process/PTY cleanup, before directory removal" in copy_section
    assert "CWUSHELL_TEST_EXPORT" in markdown and "CWUSHELL_TEST_UNSET" in markdown
    assert "does not establish full Bash compatibility" in markdown
    assert_groups_released(recorded_groups, 58)


@pytest.mark.timeout(300)
def test_repeated_full_cli_faults_bounds_and_descriptor_release(
    tmp_path: Path, monkeypatch, capsys, recorded_groups
):
    # Actual main/report path in this process lets descriptor counts include all
    # PTYs. Capture returned evidence only for lifecycle and deadline assertions.
    original = pty_session.run_session
    sessions = []

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        sessions.append(result)
        return result

    monkeypatch.setattr("cwushell_test.shell_scenarios.run_session", record)
    monkeypatch.setattr("cwushell_test.information_scenarios.run_session", record)
    baseline = len(list(Path("/proc/self/fd").iterdir()))
    for mode in ("integration", "record"):
        monkeypatch.setenv("SCENARIO_MODE", mode)
        output = tmp_path / f"{mode}.md"
        timeout = 0.5 if mode == "integration" else 1.0
        assert (
            cli.main(
                [
                    str(SHELL),
                    "-o",
                    str(output),
                    "--timeout",
                    str(timeout),
                    "--max-output-bytes",
                    "1024",
                ]
            )
            == 0
        )
        terminal = capsys.readouterr()
        assert terminal.err == ""
        markdown = output.read_text()
        assert_complete_report(markdown, terminal.out, SHELL.resolve(), output)
        assert len(list(Path("/proc/self/fd").iterdir())) == baseline
        for scenario, session in zip(INVENTORY, sessions[-58:], strict=True):
            assert (
                session.interaction_seconds
                <= (1 + len(scenario.commands)) * timeout + 0.25
            )
            assert session.cleanup_seconds <= 2 * pty_session.CLEANUP_GRACE + 0.25
            assert len(session.raw_output) <= 1024
            assert session.direct_child_reaped and session.cleanup_error is None
            assert session.pgid is not None
            assert session.pid is not None
            with pytest.raises(ChildProcessError):
                os.waitpid(session.pid, os.WNOHANG)
        if mode == "integration":
            by_id = dict(
                zip([case.case_id for case in INVENTORY], sessions[-58:], strict=True)
            )
            assert by_id["T1.prompt-reset"].undispatched == ["prompt"]
            assert by_id["T1.spaces.cpu"].truncated
            assert by_id["T1.spaces.cpu"].reason == "COMPLETED"
            assert by_id["T1.spaces.memory"].signal_status == signal.SIGSEGV
            assert by_id["T3.c"].reason == "TIMEOUT"
            assert by_id["T3.c"].truncated
            assert by_id["T6.unset"].dispatched[-1] == "printenv CWUSHELL_TEST_UNSET"
            assert "Initial prompt timeout was retained" in markdown
            assert "TRUNCATED: retained raw terminal-output prefix only" in markdown
            assert "INCOMPLETE_DISPATCH" in terminal.out
            assert "b'cleanup contents\\n'" in markdown
    assert_groups_released(recorded_groups, 116)


def test_missing_printenv_is_actionable_before_launch(monkeypatch):
    original = shutil.which
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda name: None if name == "printenv" else original(name),
    )
    with pytest.raises(RuntimeError, match="printenv.*PATH"):
        runner.validate_runtime()


def test_launch_error_exits_one(tmp_path: Path, capsys):
    target = tmp_path / "invalid executable"
    target.write_text("#!/no/such/interpreter\n")
    target.chmod(0o700)
    assert cli.main([str(target), "-o", str(tmp_path / "report.md")]) == 1
    assert "launch" in capsys.readouterr().err
    assert not (tmp_path / "report.md").exists()


def test_target_architecture_uses_elf_not_host(tmp_path: Path):
    target = tmp_path / "header"
    for endian in ("little", "big"):
        header = bytearray(20)
        header[:6] = b"\x7fELF\x02" + (b"\x01" if endian == "little" else b"\x02")
        header[18:20] = (62).to_bytes(2, endian)
        target.write_bytes(header)
        assert runner.target_architecture(target) == "x86_64 (64-bit, ELF machine 62)"
    target.write_bytes(b"not ELF")
    assert runner.target_architecture(target).startswith("Unknown")


@pytest.mark.timeout(180)
def test_report_write_error_exits_one(tmp_path: Path, capsys, recorded_groups):
    output = tmp_path / "missing parent" / "report.md"
    assert cli.main([str(SHELL), "-o", str(output), "--timeout", "1"]) == 1
    terminal = capsys.readouterr()
    assert "Cannot write Markdown report" in terminal.err
    assert str(output) in terminal.err
    assert "parent directory" in terminal.err
    assert "Markdown report:" not in terminal.out
    assert_groups_released(recorded_groups, 58)
