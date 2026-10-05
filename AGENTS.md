# Repository Guidelines

## Project Structure & Module Organization

This repository contains documentation and configured development tooling; the harness is not implemented yet. `README.md` describes the project’s purpose; `docs/specs/cwushell-test.md` defines the planned harness behavior, CLI, suites, and reporting requirements. Consult the specification before implementing changes. No harness source code or executable tests are present yet; `tests/README.md` defines test conventions. Keep assignment materials and student submissions out of version control; `assignment/` is ignored.

## Build, Test, and Development Commands

Development tooling is configured in `Taskfile.yml`, `pyproject.toml`, and `uv.lock`. Follow [docs/development.md](docs/development.md): Task v3, uv, pytest, pytest-timeout, Ruff, and mypy are the chosen standards. The project is a standalone script, with no packaging build backend. The specification targets Linux with Python 3.14+ and `pexpect`. Student `cwushell` binaries must be compiled externally.

The development commands are `task setup`, `task test`, `task lint`, `task format`, `task format:check`, `task typecheck`, and `task check`. Agents should run `task test` after behavior changes and `task check` before handing off Python changes using the configured tooling. These checks test the harness and must not require student binaries. `task typecheck` currently exits nonzero because no Python sources exist; `task test` exits nonzero because no tests exist. `task check` propagates these failures; report them explicitly until meaningful code and tests exist. Run `task setup` for locked dependencies and never suppress empty-suite failures.

Once the specified entry point exists, these are the intended commands:

- `python3 cwushell_test.py --help`: display CLI options and defaults.
- `python3 cwushell_test.py ./cwushell`: collect evidence using the default settings.
- `python3 cwushell_test.py /path/to/cwushell -o report.md --timeout 5 --max-output-bytes 65536`: customize the report, interaction deadline, and capture limit.

These commands are planned interfaces, not currently runnable project tooling.

## Coding Style & Naming Conventions

For new Python code, use four spaces for indentation, `snake_case` for functions and modules, and `PascalCase` for classes. Keep CLI parsing, PTY execution, scenario definitions, and Markdown reporting clearly separated. Use descriptive Markdown headings and fenced command examples in documentation. Ruff is the configured linter and formatter; use `task lint`, `task format`, and `task format:check` according to [docs/development.md](docs/development.md).

Harness functions must annotate parameters and return values; `task typecheck` enforces this with mypy targeting Python 3.14. Tests and fixtures under `tests/` may omit function annotations, but their bodies are still checked. Annotate fixture parameters when useful for stronger checking. Do not suppress missing imports globally; use the configured `types-pexpect` stubs.

## Testing Guidelines

Use pytest for harness tests under `tests/`, with descriptive `test_*.py` filenames, fixtures, and plain assertions. Configure discovery to avoid collecting `cwushell_test.py`. No coverage threshold is required. Cover monotonic deadlines, continuous output, capture truncation, prompt synchronization, process cleanup, and continuation after crashes using synthetic programs rather than student submissions. Preserve the specification’s T1–T6 scenario coverage and fresh sessions for independent cases. Follow the isolation and outer-timeout requirements in [docs/development.md](docs/development.md).

## Commit & Pull Request Guidelines

History uses Conventional Commits, including `docs(spec): clarify harness test and execution requirements` and `chore: add lightweight .gitignore`. Follow `type(scope): concise description`, with scope optional. Keep commits focused. Pull requests should explain changed behavior, reference relevant specification sections and issues, and state validation performed or unavailable.

## Evidence & Configuration

Reports collect observations for manual review; never assign grades or automated correctness statuses. Execute targets through PTYs, enforce bounded cleanup, and label truncated output. Keep student binaries, transcripts, and generated reports out of commits unless explicitly approved for inclusion.
