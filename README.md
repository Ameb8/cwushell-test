# CWUShell Test

CWUShell Test collects execution evidence from implementations of "cwushell", the lab 1 assignment for CS470.001 at CWU (fall 2026 quarter).

This program does not output grades for the assignment. All test cases are manually reviewed by me, with my results submitted to the course's proffesor for final grading.

Lab assignment documentation and student work is not included in this repository. 

The program runs standardized cases and records commands, terminal output, and execution events for manual review. It does not score submissions or decide whether their output is correct.

Completing a case does not establish that a submission is implemented correctly.

## Development

The CLI skeleton, bounded PTY interaction helper, and case evidence/Markdown
report pipeline are implemented, along with the independent
[T3–T5 CPU, memory, and help scenarios](docs/information-scenarios.md) and
[T1/T2/T6 prompt, termination, and system scenarios](docs/shell-scenarios.md).
Full battery registration and CLI integration are pending. The [report contract](docs/reporting.md)
describes the models and writer.
The helper interface and
focused fixture checks are documented in [docs/pty-session.md](docs/pty-session.md). Use Linux and Python 3.14+, as
required by the current
[canonical specification](docs/specs/cwushell-test.md).

The harness is an installable Python package with a `src/` layout:

```text
src/cwushell_test/
├── __init__.py
├── __main__.py       # python -m cwushell_test
├── cli.py            # argument parsing, configuration, runner entry point
├── evidence.py       # case, fixture, summary, and execution metadata contracts
├── information_scenarios.py # independent T3–T5 evidence cases
├── pty_session.py    # bounded interaction and process cleanup
├── reporting.py      # safe Markdown rendering and report writing
├── shell_scenarios.py # T1/T2/T6 evidence cases and state sequences
└── py.typed          # type information for package consumers
tests/
```

Add future scenario and reporting modules inside this package. Keep harness
tests and synthetic target programs under `tests/`.

## CLI skeleton

After `task setup`, display help through either entry point:

```bash
uv run --locked python -m cwushell_test --help
uv run --locked cwushell-test --help
```

`task setup` installs the package in editable mode and creates the console
command in `.venv/bin/`. With that environment activated, use
`python -m cwushell_test` or `cwushell-test` directly from any working directory.
Package installation is required; there are no root-level Python launchers.

```bash
uv run --locked cwushell-test
uv run --locked python -m cwushell_test "/path with spaces/cwushell" \
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
