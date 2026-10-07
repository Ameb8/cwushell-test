# Repository Guidelines

## Project Structure & Module Organization

The complete CLI and bounded PTY helper are implemented in `src/cwushell_test/`. Keep application modules inside this package: `cli.py` owns configuration and CLI parsing, `runner.py` owns suite orchestration, `pty_session.py` owns PTY execution, and `__main__.py` delegates module invocation to the CLI. Scenario definitions and Markdown reporting have separate modules here. `README.md` describes the project’s purpose; `docs/specs/cwushell-test.md` defines harness behavior, CLI, suites, and reporting requirements. Consult the specification before implementing changes. Harness tests and synthetic programs live under `tests/`; `tests/README.md` defines test conventions. Keep assignment materials and student submissions out of version control; `assignment/` is ignored.

## Build, Test, and Development Commands

Development tooling is configured in `Taskfile.yml`, `pyproject.toml`, and `uv.lock`. Follow [docs/development.md](docs/development.md): Task v3, uv, pytest, pytest-timeout, Ruff, and mypy are the chosen standards. The project is an installable Python package using the uv build backend and a `src/` layout. The specification targets Linux with Python 3.14+ and `pexpect`. Student `cwushell` binaries must be compiled externally.

The development commands are `task setup`, `task test`, `task lint`, `task format`, `task format:check`, `task typecheck`, and `task check`. Agents should run `task test` after behavior changes and `task check` before handing off Python changes using the configured tooling. These checks test the harness and must not require student binaries. Run `task setup` to install the package in editable mode with locked dependencies; tests must import the installed package without `pythonpath` overrides. Never suppress empty-suite failures.

After `task setup`, these commands use the installed package:

- `uv run --locked python -m cwushell_test --help`: display CLI options and defaults.
- `uv run --locked python -m cwushell_test ./cwushell`: collect evidence using the default settings.
- `uv run --locked python -m cwushell_test /path/to/cwushell -o report.md --timeout 5 --max-output-bytes 65536`: customize the report, interaction deadline, and capture limit.

The CLI executes all T1–T6 cases and generates a Markdown evidence report; completed runs exit 0 even when student-process timeouts or crashes are recorded. Module invocation and the installed console command share `cwushell_test.cli:main`.

## Coding Style & Naming Conventions

For new Python code, use four spaces for indentation, `snake_case` for functions and modules, and `PascalCase` for classes. Keep CLI parsing, PTY execution, scenario definitions, and Markdown reporting clearly separated. Use descriptive Markdown headings and fenced command examples in documentation. Ruff is the configured linter and formatter; use `task lint`, `task format`, and `task format:check` according to [docs/development.md](docs/development.md).

Harness functions must annotate parameters and return values; `task typecheck` enforces this with mypy targeting Python 3.14. Tests and fixtures under `tests/` may omit function annotations, but their bodies are still checked. Annotate fixture parameters when useful for stronger checking. Do not suppress missing imports globally; use the configured `types-pexpect` stubs.

## Testing Guidelines

Use pytest for harness tests under `tests/`, with descriptive `test_*.py` filenames, fixtures, and plain assertions. Keep discovery under `tests/` rather than application modules in `src/`. No coverage threshold is required. Cover monotonic deadlines, continuous output, capture truncation, prompt synchronization, process cleanup, and continuation after crashes using synthetic programs rather than student submissions. Preserve the specification’s T1–T6 scenario coverage and fresh sessions for independent cases. Follow the isolation and outer-timeout requirements in [docs/development.md](docs/development.md).

## Commit & Pull Request Guidelines

History uses Conventional Commits, including `docs(spec): clarify harness test and execution requirements` and `chore: add lightweight .gitignore`. Follow `type(scope): concise description`, with scope optional. Keep commits focused. Pull requests should explain changed behavior, reference relevant specification sections and issues, and state validation performed or unavailable.

## Evidence & Configuration

Reports collect observations for manual review; never assign grades or automated correctness statuses. Execute targets through PTYs, enforce bounded cleanup, and label truncated output. Keep student binaries, transcripts, and generated reports out of commits unless explicitly approved for inclusion.
