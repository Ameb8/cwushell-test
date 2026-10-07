# Harness tests

Add meaningful `test_*.py` tests here as harness behavior is implemented. Run the
complete suite with `task test`, or select tests with `task test -- -k cleanup`.
The CLI checks are in `test_cli.py`; run them with
`task test -- tests/test_cli.py`. They cover both entry points, defaults and paths
with spaces, syntax errors, invalid targets, environment validation, and the
temporary runner's absence of execution or report writes. Platform and Python
version rejection are unit-tested by substituting environment values; real CLI
subprocess checks run on Linux with the configured Python interpreter. Both
`python -m cwushell_test` and the installed `cwushell-test` command are tested
from temporary directories outside the checkout. Run `task setup` first to
install the `src/` package; tests do not alter Python's import path.

Use pytest fixtures and plain assertions. Mark real PTY tests with
`@pytest.mark.integration`; these tests still run in the default suite. Synthetic
programs belong under `tests/fixtures/` and must not contain student submissions
or private assignment materials.

Mypy checks test bodies through `task typecheck`; test and fixture functions may
omit annotations. Annotate fixture parameters when useful for checking the objects
they provide. Synthetic programs under `tests/fixtures/` are excluded from mypy
discovery because they may deliberately simulate faulty behavior.

Every test has a 60-second outer timeout using pytest-timeout's Linux signal
method. Use `@pytest.mark.timeout(seconds)` for a justified, finite override.
Choose harness deadlines well below that outer timeout so cleanup has time to
run. Fixtures must clean up their process groups in `finally` blocks, including
after an assertion or timeout failure. Avoid programs that move to another
process group or session unless the test explicitly owns and cleans them up.

See [development conventions](../docs/development.md) and the
[harness specification](../docs/specs/cwushell-test.md) for required coverage.

The bounded PTY contract checks are in `test_pty_session.py`. Run
`task test -- tests/test_pty_session.py`; see the [helper interface and measured
bounds](../docs/pty-session.md) for fixture modes, evidence fields, and the
acceptance-criteria mapping. These Linux checks use the executable
`fixtures/mock_shell.py` independently of suites or scoring.

Lifecycle checks also fork synthetic descendants, verify the actual process
group through `/proc`, exercise TERM/KILL escalation after the leader exits,
and check direct-child reaping and fresh sessions after faults. The test-side
containment fixture temporarily enables Linux child-subreaper mode and reaps only
owned fixture groups; it restores the previous setting afterward. This avoids
accumulating orphan zombies on hosts with a non-reaping PID 1 and is deliberately
absent from the production helper.

The case model/report checks are in `test_reporting.py`. Run
`task test -- tests/test_reporting.py`; see the [report contract](../docs/reporting.md)
for producer interfaces and the issue #3 acceptance mapping. These tests construct
synthetic evidence without launching a target and exercise Markdown containment,
concurrent execution observations, capture labels, fixtures, and report I/O.

Fixture lifecycle checks also live in `test_pty_session.py`; select them with
`task test -- tests/test_pty_session.py -k fixture`. They verify direct harness
observations and session isolation, controlled initial environments, and snapshot
ordering through real PTYs and synthetic filesystem changes, including changes
during cleanup. See the [fixture lifecycle contract](../docs/pty-session.md) for
the fixed fixture bytes, diagnostic behavior, and failure-path coverage.

CPU, memory, and help scenario checks live in `test_information_scenarios.py`.
Run `task test -- tests/test_information_scenarios.py`; the
[scenario interface and acceptance mapping](../docs/information-scenarios.md)
describe the exact T3–T5 inventories and their evidence adapter. These tests use
`fixtures/information_shell.py` through real PTYs to record all 33 exact inputs,
verify independent sessions, and retain arbitrary output and fault events while
continuing later cases. They do not invoke the full CLI workflow.
