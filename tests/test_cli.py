"""CLI checks use disposable synthetic executables, never student submissions."""

import subprocess
import sys
from pathlib import Path

import pytest

from cwushell_test import cli


@pytest.fixture(params=["module", "console", "script"])
def invocation(request):
    if request.param == "module":
        return [sys.executable, "-m", "cwushell_test"]
    if request.param == "script":
        return [sys.executable, str(Path(__file__).parents[1] / "cwushell_test.py")]
    return [str(Path(sys.executable).with_name("cwushell-test"))]


@pytest.fixture
def target(tmp_path: Path) -> Path:
    binary = tmp_path / "shell with spaces"
    binary.write_text("#!/bin/sh\nprintf launched > launched\n", encoding="utf-8")
    binary.chmod(0o700)
    return binary


def test_help_without_target(invocation, tmp_path: Path):
    result = subprocess.run(
        invocation + ["--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    for default in ("./cwushell", "cwushell_test_report.md", "10.0", "1048576"):
        assert default in result.stdout
    assert "T1–T6" in result.stdout


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


def test_missing_host_utilities_do_not_execute_or_write_report(
    invocation, target: Path
):
    output = target.parent / "existing report.md"
    output.write_text("preserve existing evidence", encoding="utf-8")
    result = subprocess.run(
        invocation + [str(target), "-o", str(output)],
        cwd=target.parent,
        # Both installed entry points run from outside the repository.
        env={"PATH": str(Path(sys.executable).parent)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "required host utility" in result.stderr
    assert "PATH" in result.stderr
    assert not (target.parent / "launched").exists()
    assert output.read_text(encoding="utf-8") == "preserve existing evidence"
    assert not (target.parent / "cwushell_test_report.md").exists()


def test_path_resolution_error_is_diagnostic(target: Path, monkeypatch, capsys):
    def denied(path: Path) -> Path:
        raise PermissionError("cannot access invocation directory")

    monkeypatch.setattr(Path, "resolve", denied)
    assert cli.main([str(target)]) == 1
    assert "cannot access invocation directory" in capsys.readouterr().err


def test_checkout_launcher_preserves_installed_package_imports():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from cwushell_test.cli import main; print(main.__module__)",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "cwushell_test.cli"


@pytest.mark.parametrize(
    "report_format,extension", [("markdown", "md"), ("html", "html")]
)
@pytest.mark.parametrize("selected_path", [None, "report with spaces.custom"])
def test_report_format_configuration(
    target: Path, monkeypatch, report_format, extension, selected_path
):
    monkeypatch.chdir(target.parent)
    argv = [str(target), "--report-format", report_format]
    if selected_path is not None:
        argv += ["-o", selected_path]
    config = cli.validate_configuration(cli.create_parser().parse_args(argv))
    assert config.report_format == report_format
    assert config.output == target.parent / (
        selected_path or f"cwushell_test_report.{extension}"
    )


def test_unknown_report_format_exits_two(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--report-format", "pdf"])
    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
