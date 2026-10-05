# CWUShell Test

CWUShell Test is a program designed to test accuracy of implementation of "cwushell", the lab 1 assignment for CS470.001 at CWU (fall 2026 quarter). 

This program does not output grades for the assignment. All test cases are manually reviewed by me, with my results submitted to the course's proffesor for final grading.

Lab assignment documentation and student work is not included in this repository. 

The purpose of this program is to ensure all submissions are tested deterministaclly, helping minimize the chance for testing errors. Any failed test cases will be re-run manually to determine whether the issue is from the submission or the test program itself.

Passing all test cases does not guarantee that a submission is implemented fully and correctly.

## Development

The harness is not implemented yet. Development tooling is ready: use Linux,
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
checks, mypy type checking, and tests. `task typecheck` currently returns nonzero
because there are no Python sources; `task test` returns nonzero because there
are no tests. `task check` propagates these failures. Add meaningful code and
tests with the implementation.

See the [harness specification](docs/specs/cwushell-test.md) for planned behavior
and [development conventions](docs/development.md) for dependency management,
pytest tests, Ruff and mypy configuration, and agent verification requirements.
