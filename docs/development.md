# Development conventions

## Status and scope

The development tooling is configured in `Taskfile.yml`, `pyproject.toml`, and
`uv.lock`. The CLI skeleton, bounded PTY helper, and focused synthetic fixture
tests are implemented; suite execution and reporting remain pending. See the
[PTY interface](pty-session.md) for the helper contract and measured bounds. All verification commands now have meaningful sources
and tests to check. The temporary runner validates configuration and exits 1
without executing a target or writing a report; see the [README](../README.md).

The [harness specification](specs/cwushell-test.md) defines runtime behavior and
student-shell evidence collection. This guide defines how contributors and agents
develop and verify the harness itself. Keep lasting conventions here; use
implementation issues to track the remaining program work.

## Toolchain and dependencies

- Use Task v3 with a root `Taskfile.yml` as the shared command interface.
- Use uv for Python environment management, dependency resolution, and execution.
  Declare dependencies and tool configuration in `pyproject.toml`; commit
  `uv.lock` and keep `.venv/` ignored. Avoid parallel requirements files.
- Target Linux and Python 3.14+. Set `requires-python = ">=3.14"` and use the
  committed `.python-version` to select Python 3.14 for development. uv can
  download that interpreter if it is not installed. Ruff and mypy also target
  Python 3.14.
- Declare `pexpect` as a runtime dependency. Declare pytest, pytest-timeout, Ruff,
  mypy, and `types-pexpect` in the `dev` dependency group; they are not required to
  collect student-shell evidence.
- Use `uv sync --locked` and `uv run --locked` for routine setup and tasks.
  A stale or missing lockfile must fail with an actionable error rather than
  silently updating dependency versions. Update dependencies deliberately with
  uv and review the resulting manifest and lockfile changes together.

See the official [uv locking and syncing documentation](https://docs.astral.sh/uv/concepts/projects/sync/)
and [Python version status](https://devguide.python.org/versions/).

## Task command contract

Use Linux with Python 3.14+ (or let uv install a compatible interpreter),
[Task v3](https://taskfile.dev/docs/installation), and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Then run:

```bash
task setup
task lint
task format:check
task typecheck
task test
```

`task setup` installs runtime and development dependencies into `.venv/`.
Tasks run from the repository root, propagate failures, and do not require manual
virtual-environment activation. Inspect available tasks with `task --list`.
The project uses the [uv build backend](https://docs.astral.sh/uv/concepts/build-backend/)
and a `src/` package layout. `task setup` installs `src/cwushell_test/` in editable
mode and creates the `cwushell-test` console command from
`cwushell_test.cli:main`. `python -m cwushell_test` reaches the same entry point
through `__main__.py`. Keep `__init__.py` free of execution side effects.

Harness modules belong under `src/cwushell_test/`; tests belong under `tests/`.
Pytest imports the installed package without adding the repository or `src/`
to `pythonpath`. This ensures subprocess checks can exercise both installed
entry points from temporary directories outside the checkout. Use `uv build`
to produce a source distribution and wheel when needed; keep `dist/` ignored.
Mypy uses `src/` as its source root; the package's `py.typed` marker makes its
annotations available to installed consumers as well.

Use current stable tool releases within the manifest's declared version ranges.
`uv.lock` pins the resolved versions and hashes for reproducibility; routine
commands do not update dependencies. To update deliberately, run
`uv lock --upgrade` followed by `task setup`, review the lockfile changes, and
run `task check`. Revisit version ranges when adopting a new major tool release.

Run the skeleton with
`uv run --locked python -m cwushell_test ./cwushell` or
`uv run --locked cwushell-test ./cwushell`.
Student binaries must still be compiled externally. Runtime fixture observations
will also require the Linux utilities named in the specification, including
`printenv`; those utilities are not needed for the current CLI checks.

| Command | Required behavior |
|---|---|
| `task setup` | Run `uv sync --locked` to create or synchronize the development environment. |
| `task test` | Run `uv run --locked pytest` against the complete harness test suite. |
| `task test -- -k cleanup` | Forward arguments after `--` to pytest using Task's `CLI_ARGS`; allow focused tests without changing the full-suite default. |
| `task lint` | Run `uv run --locked ruff check .`; report violations without editing files. |
| `task format` | Run `uv run --locked ruff format .`; format Python files in place. |
| `task format:check` | Run `uv run --locked ruff format --check .`; check formatting without editing files. |
| `task typecheck` | Run `uv run --locked mypy .`; check types and require annotations on harness functions. |
| `task check` | Run lint, formatting checks, type checking, and the complete test suite, in sequence; fail if any check fails. |

Verification tasks must execute on every invocation; do not use Task caching to
skip tests or checks. Do not suppress pytest's nonzero exit when no tests are
collected. `task test` tests the harness and must never require a student binary
or automatically collect evidence from student submissions.

Agents should use `task test` after behavior changes and `task check` before
handoff of Python changes. Report the commands run and their results. If checks
cannot run or no tests exist, state that limitation explicitly.

## Test standard

Use pytest as the sole test runner. Prefer function-based tests, plain `assert`
statements, pytest fixtures, and parametrization. Standard-library helpers such as
`unittest.mock` remain available; do not introduce a separate `unittest` runner.
Place tests under `tests/` with descriptive `test_*.py` filenames, and configure
pytest discovery with `testpaths = ["tests"]` so application modules under
`src/` are not collected as tests.

Test observable harness behavior. Unit tests cover CLI validation, scenario
definitions, output normalization, capture limits, and Markdown reporting. Linux
integration tests use small synthetic programs owned by the repository, launched
through the real PTY helper, to cover deadlines, continuous output, prompt
synchronization after truncation, termination, process-group cleanup, and
continuation after crashes. These integration tests belong in the default
`task test` run; they do not require assignment materials or student submissions.

Use isolated temporary directories and controlled environments. Clean up child
processes even when assertions fail. The configured pytest-timeout plugin gives
every test a 60-second outer timeout using Linux signals, independent of the
harness deadline, so a broken harness
timeout cannot hang the runner. A test may use `@pytest.mark.timeout(seconds)`
for a justified, finite override; do not disable the timeout. Avoid arbitrary
sleeps as synchronization and allow reasonable scheduling tolerance in
elapsed-time assertions.

Preserve T1–T6 scenario coverage and independent sessions as defined in the spec.
Tests may pass or fail when checking the harness; generated student reports must
continue to record observations without grading or correctness judgments. No
coverage percentage is required initially; prioritize the specified safeguards
and regression tests for defects.

## Linting and formatting standard

Use Ruff for both linting and formatting. Configure it in `pyproject.toml` with
`target-version = "py314"`, line length 88, and lint rule families `E4`, `E7`, `E9`,
`F`, and `I` for basic errors, undefined or unused names, and import ordering.
Use Ruff's default formatting style and four-space indentation. Exclude
`assignment/` and generated evidence directories from tool discovery. Keep any
rule suppression narrow and explain its purpose.

`task format` formats code but does not fix lint violations or sort imports.
Apply lint fixes explicitly when needed and review them. Do not add Black, isort,
or another formatter alongside Ruff without revising this convention.

See the official [Ruff configuration](https://docs.astral.sh/ruff/configuration/)
and [formatter documentation](https://docs.astral.sh/ruff/formatter/).

## Type checking standard

Use mypy to check harness code and tests. Harness functions must annotate their
parameters and return values, including `-> None` for functions that return
nothing. Mypy checks unannotated function bodies too. Tests and fixtures under
`tests/` may omit function annotations, but type errors in their bodies are still
reported. Annotate fixture parameters when useful for checking the objects they
provide; unannotated parameters are treated as `Any` and limit what can be checked.

Mypy targets Python 3.14 and uses the current stable release series declared in
the manifest, with the exact version recorded in `uv.lock`. `types-pexpect`
provides type stubs for the runtime dependency; do not suppress missing imports
globally. Keep any `# type: ignore[code]` narrow and explain why it is needed.
Unused ignores are reported.

Namespace packages and explicit package bases keep tests identified as `tests.*`
without requiring `tests/__init__.py`. Automatic discovery excludes virtual
environments, assignment materials, generated evidence, and `tests/fixtures/`
synthetic programs (which may deliberately simulate faulty behavior). Exclusion
controls discovery, not imports: avoid importing those synthetic programs into
harness code or test modules. Do not place harness implementation under `tests/`.

Run `task typecheck` for type checking alone, or `task check` for all verification.
Do not add dummy source files or suppress empty-suite failures. Ruff handles
linting and formatting; annotation rules are enforced by mypy rather than
enabling Ruff's `ANN` rules.

See the official [mypy configuration reference](https://mypy.readthedocs.io/en/stable/config_file.html)
for annotation requirements and per-module overrides.

## Remaining implementation work

Add meaningful tests alongside each harness behavior; do not add placeholder
tests or suppress empty-suite failures. The test structure and integration-test
conventions are documented in [tests/README.md](../tests/README.md).

## Continuous integration

[The CI workflow](../.github/workflows/ci.yml) runs on pull requests targeting
`main`, pushes to `main` (including merges), and merge queues.
It installs Task v3 and uv on Linux, installs Python from `.python-version`, and
runs `task setup` with the committed lockfile. It then runs `task lint`,
`task format:check`, `task typecheck`, and `task test`. Each check runs even if an
earlier check fails; any failure fails the `checks` job. Formatting is checked
without modifying files, and student binaries are not required.

GitHub branch protection for `main` requires the `checks` status check from GitHub
Actions, requires branches to be up to date before merging, and applies to
administrators too. This is repository configuration, separate from the workflow
file; forks must configure their own branch protection to enforce the same gate.

The CLI skeleton and tests run in these checks without student binaries.

Keep student binaries and generated evidence out of version control. The default
report, root `cwushell` binary, `reports/`, and `transcripts/` are ignored. Put
custom report paths beneath `reports/` to keep them out of commits.
