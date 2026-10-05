# CWUShell Test

CWUShell Test is a program designed to test accuracy of implementation of "cwushell", the lab 1 assignment for CS470.001 at CWU (fall 2026 quarter). 

This program does not output grades for the assignment. All test cases are manually reviewed by me, with my results submitted to the course's proffesor for final grading.

Lab assignment documentation and student work is not included in this repository. 

The purpose of this program is to ensure all submissions are tested deterministaclly, helping minimize the chance for testing errors. Any failed test cases will be re-run manually to determine whether the issue is from the submission or the test program itself.

Passing all test cases does not guarantee that a submission is implemented fully and correctly.

## Development

The CLI skeleton and bounded PTY interaction helper are implemented. Suite
execution and Markdown reporting are still pending. The helper interface and
focused fixture checks are documented in [docs/pty-session.md](docs/pty-session.md). Use Linux and Python 3.14+, as
required by the current
[canonical specification](docs/specs/cwushell-test.md). The original issue's
Python 3.8 target predates that requirement.

## CLI skeleton

After `task setup`, display help through either entry point:

```bash
uv run --locked python cwushell_test.py --help
uv run --locked ./cwushell-test --help
```

The repository launcher can also be placed on `PATH` to invoke `cwushell-test`.
With Python 3.14+ available, `python3 cwushell_test.py --help` works directly.
No package installation or build backend is needed.

```bash
uv run --locked ./cwushell-test
uv run --locked python cwushell_test.py "/path with spaces/cwushell" \
  -o "reports/evidence with spaces.md" --timeout 5 --max-output-bytes 65536
```

The optional target defaults to `./cwushell`; output defaults to
`cwushell_test_report.md`, timeout to 10.0 seconds, and capture limit to 1048576
bytes. Paths resolve relative to the invocation directory. Targets must already
be compiled externally and be regular executable files. Timeout must be positive
and finite; capture limit must be a positive integer.

**Temporary behavior:** a valid invocation reaches `run(Configuration)` and exits
1 with an explicit diagnostic that execution and reporting are not implemented.
It launches no student session and writes no report. Help exits 0, invalid syntax
exits 2, and target or environment errors exit 1 with stderr diagnostics. Exit 0
for an actual run remains reserved for completed execution and report generation.
The runner receives an immutable configuration containing absolute target and
output paths and the two interaction limits.

## Verification

Development tooling uses Linux,
Python 3.14+, [Task v3](https://taskfile.dev/docs/installation), and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
task setup
task lint
task format:check
task typecheck
task test
```

`task setup` installs locked dependencies into `.venv/`; no activation is needed.
Use `task format` to format Python files and `task check` to run lint, formatting
checks, mypy type checking, and tests. Run focused CLI checks with
`task test -- tests/test_cli.py`. These checks use synthetic executables in
temporary directories and require no student submissions.

See the [harness specification](docs/specs/cwushell-test.md) for planned behavior
and [development conventions](docs/development.md) for dependency management,
pytest tests, Ruff and mypy configuration, and agent verification requirements.
