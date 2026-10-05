# Harness tests

Add meaningful `test_*.py` tests here as harness behavior is implemented. Run the
complete suite with `task test`, or select tests with `task test -- -k cleanup`.
There are no harness tests yet; pytest's empty-suite exit remains nonzero.

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
