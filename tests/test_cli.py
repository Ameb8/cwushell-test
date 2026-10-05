"""CLI checks use disposable synthetic executables, never student submissions."""

import subprocess
import sys
from pathlib import Path

import pytest

import cwushell_test as cli

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def target(tmp_path: Path) -> Path:
    binary = tmp_path / "shell with spaces"
    binary.write_text("#!/bin/sh\nprintf launched > launched\n", encoding="utf-8")
    binary.chmod(0o700)
    return binary


@pytest.mark.parametrize("entrypoint", ["cwushell_test.py", "cwushell-test"])
def test_help_without_target(entrypoint, tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(ROOT / entrypoint), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    for default in ("./cwushell", "cwushell_test_report.md", "10.0", "1048576"):
        assert default in result.stdout
    assert "not implemented" in result.stdout


def test_default_configuration_reaches_runner(target: Path, monkeypatch):
    target.rename(target.parent / "cwushell")
    monkeypatch.chdir(target.parent)
    received: list[cli.Configuration] = []

    def record(config: cli.Configuration) -> int:
        received.append(config)
        return 1

    monkeypatch.setattr(cli, "run", record)
    assert cli.main([]) == 1
    assert received == [
        cli.Configuration(
            target.parent / "cwushell",
            target.parent / "cwushell_test_report.md",
            10.0,
            1048576,
        )
    ]


@pytest.mark.parametrize("output_flag", ["-o", "--output"])
def test_explicit_configuration_reaches_runner(target: Path, monkeypatch, output_flag):
    monkeypatch.chdir(target.parent)
    received: list[cli.Configuration] = []

    def record(config: cli.Configuration) -> int:
        received.append(config)
        return 1

    monkeypatch.setattr(cli, "run", record)
    assert (
        cli.main(
            [
                target.name,
                output_flag,
                "reports with spaces/evidence.md",
                "--timeout",
                "5.5",
                "--max-output-bytes",
                "65536",
            ]
        )
        == 1
    )
    assert received == [
        cli.Configuration(
            target,
            target.parent / "reports with spaces/evidence.md",
            5.5,
            65536,
        )
    ]


def test_absolute_paths(target: Path):
    output = target.parent / "report with spaces.md"
    config = cli.validate_configuration(
        cli.create_parser().parse_args([str(target), "-o", str(output)])
    )
    assert config.target == target
    assert config.output == output


@pytest.mark.parametrize(
    "argv",
    [
        ["--unknown"],
        ["--binary", "shell"],
        ["--verbose"],
        ["one", "two"],
        ["-o"],
        ["--time", "5"],
        *[["--timeout", value] for value in ("0", "-1", "nan", "inf", "1e999", "x")],
        *[["--max-output-bytes", value] for value in ("0", "-1", "1.5", "inf", "x")],
    ],
)
def test_invalid_syntax_exits_two(argv, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["missing", "non-executable", "directory"])
def test_invalid_target_exits_one(kind, tmp_path: Path, monkeypatch, capsys):
    target = tmp_path / kind
    if kind == "non-executable":
        target.write_text("synthetic target", encoding="utf-8")
        target.chmod(0o600)
    elif kind == "directory":
        target.mkdir()

    def unexpected_runner(config: cli.Configuration) -> int:
        pytest.fail("invalid target reached runner")

    monkeypatch.setattr(cli, "run", unexpected_runner)
    assert cli.main([str(target)]) == 1
    stderr = capsys.readouterr().err
    assert str(target) in stderr
    assert {
        "missing": "compile it externally",
        "non-executable": "check execute permissions",
        "directory": "regular executable file",
    }[kind] in stderr


@pytest.mark.parametrize("platform", ["darwin", "win32", "freebsd14"])
def test_unsupported_platform(target: Path, platform, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", platform)
    assert cli.main([str(target)]) == 1
    assert "Linux is required" in capsys.readouterr().err


def test_unsupported_python(target: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "version_info", (3, 13, 0))
    assert cli.main([str(target)]) == 1
    assert "Python 3.14+ is required" in capsys.readouterr().err


def test_help_bypasses_environment_validation(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "version_info", (3, 13, 0))
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])
    assert error.value.code == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("entrypoint", ["cwushell_test.py", "cwushell-test"])
def test_stub_does_not_execute_or_write_report(entrypoint, target: Path):
    command = [str(ROOT / entrypoint)]
    if entrypoint.endswith(".py"):
        command.insert(0, sys.executable)
    output = target.parent / "existing report.md"
    output.write_text("preserve existing evidence", encoding="utf-8")
    result = subprocess.run(
        command + [str(target), "-o", str(output)],
        cwd=target.parent,
        # Ensure the launcher selects the same interpreter as the test runner.
        env={"PATH": str(Path(sys.executable).parent)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "configuration validated" in result.stderr
    assert "no student session was launched and no report was written" in result.stderr
    assert not (target.parent / "launched").exists()
    assert output.read_text(encoding="utf-8") == "preserve existing evidence"
    assert not (target.parent / "cwushell_test_report.md").exists()


def test_path_resolution_error_is_diagnostic(target: Path, monkeypatch, capsys):
    def denied(path: Path) -> Path:
        raise PermissionError("cannot access invocation directory")

    monkeypatch.setattr(Path, "resolve", denied)
    assert cli.main([str(target)]) == 1
    assert "cannot access invocation directory" in capsys.readouterr().err
