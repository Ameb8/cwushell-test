# Case evidence and Markdown reporting

`cwushell_test.evidence` defines the evidence contract for scenario runners,
fixture collectors, and the workflow. `cwushell_test.reporting` renders and writes
it without launching processes or collecting host metadata. The [workflow](workflow.md) supplies suite registration, metadata collection,
progress, and CLI exit handling.

## Producer interfaces

Construct one `CaseEvidence` per independent session with a stable `case_id`,
`suite_id` (T1–T6), description, original tuple of `pty_session.Command` objects,
and the returned `pty_session.Evidence`. Commands preserve actual tabs and all
spaces. The adapter wraps the helper result directly: startup/command
`Interaction` events, wait targets, raw output, fully dispatched and remaining
undispatched lines, process observations, and cleanup fields remain available.
No second PTY implementation or live process is needed to construct these models.

The helper's `reason` is preserved. Summary labels include all observed event
reasons, plus `PROCESS_EXIT` when `exit_status` is present, `SIGNAL` when
`signal_status` is present, `INCOMPLETE_DISPATCH` for remaining commands, and
`CLEANUP_ERROR` for a cleanup diagnostic. EOF is terminal closure, which alone
does not prove process termination. Cleanup-phase termination never becomes an
observed exit or crash. An initial TIMEOUT and later COMPLETED remain visible
together. `case.summary` exposes identifiers, title, ordered labels and events,
observed statuses, and dispatch counts for terminal presentation.

Fixture collection (#10) supplies these fields on the returned PTY `Evidence`.
`CaseEvidence` inherits them when its corresponding context fields are empty;
explicitly supplied context remains supported. The shared models are defined in
`cwushell_test.fixtures` and re-exported from `cwushell_test.evidence`.

The fixture fields are:

- `Fixture(path, kind, contents)`: initial file/directory/absent settings;
  file contents are bytes, and absent/directory fixtures have no contents.
- `controlled_environment`: explicitly controlled initial values, including the
  helper's terminal/locale settings; a `None` value means initially absent.
  This is not a dump of the inherited environment.
- `FileObservation(path, phase, exists, contents, error)`: `before` means before
  launch; `after` means after process cleanup and PTY closure, before removing
  the session directory. `exists=None` means unknown. `contents=None` means not
  collected, whereas `b""` records an empty file. Errors preserve diagnostics
  alongside any available observations. Collect these directly from the harness;
  the model and renderer do not compare before/after contents or judge them.
- `notes`: additional execution/fixture-preparation diagnostics.

The helper supplies `working_directory`; fixture collectors must record all
settings used, even though the directory is removed after cleanup. The workflow
supplies `ExecutionMetadata(timestamp, target, target_architecture,
kernel_version, timeout, max_output_bytes, host_architecture=...)` and the ordered cases in `Report`.
Use a timezone-aware execution timestamp and the resolved target path. The
architecture describes the target binary; the renderer does not infer it from
the host. Metadata limits describe the run; each session's capture notes also
use its helper result's actual limit and retained raw-byte count.

## Rendering and writing

```python
from cwushell_test.evidence import CaseEvidence, Report
from cwushell_test.reporting import ReportWriteError, render_report, write_report

case = CaseEvidence("T1.tabs.cpu", "T1", "Tab-separated CPU input",
                    tuple(commands), session_result)
report = Report(metadata, (case,))
markdown = render_report(report)
try:
    destination = write_report(report, configuration.output)
except ReportWriteError as error:
    # The workflow displays this diagnostic and exits 1.
    print(error)
```

`render_report` includes execution metadata, a row for every case, and detailed
session context, commands, combined PTY terminal output, capture notes,
harness-collected file observations, and execution/cleanup notes. COMPLETED is
explained as execution completion only. No correctness predicates or scores are
computed. Text printed by a target remains labeled as student evidence.

Commands use a labeled escaped representation: actual tabs appear as `\t` and
literal backslashes as `\\`, preserving the distinction. All multiple spaces
remain intact. Each fully dispatched input has one LF appended by the helper;
rendering does not modify the dispatch plan. A timed-out partial dispatch remains
in `undispatched`, and the report explains that it may have been partially sent.

Terminal text uses the helper's ANSI removal, UTF-8 replacement decoding, and LF
normalization. Fixture contents have a readable UTF-8 view plus an exact bytes
representation, preserving invalid bytes and original file line endings. Dynamic
backtick fences are longer than any run in their contents. All variable metadata
and diagnostics use these fences, and table punctuation/whitespace uses numeric
HTML entities to prevent injected rows, links, headings, or HTML. A delimiter
newline before the closing fence is formatting, not another observed output byte.

`write_report` writes UTF-8 Markdown to the selected `Path` and returns its
absolute destination. Resolve the configured output path relative to invocation
before sessions begin. Paths with spaces work normally. Existing files are
replaced as requested by `-o`; missing parent directories are not created.
Filesystem/encoding errors raise `ReportWriteError` with the selected path,
underlying reason, and remediation. The writer does not choose a CLI exit code.

## Verification of issue #3

Run `task test -- tests/test_reporting.py`, then `task check`.

| Acceptance criterion | Focused evidence |
| --- | --- |
| Section 7.2 metadata and each session's context | Metadata/context test covers timestamp, target, architecture, kernel, limits, working directory, fixtures and controlled environment |
| Every case, simultaneous execution events, completion-only labels | T1–T6 grouping test and parametrized completed/timeout/exit/signal/EOF/incomplete evidence tests; summary contract assertions |
| Exact input, cleaned output, undispatched commands, execution/cleanup notes | Metadata/input test, event tests, truncation/cleanup test, startup fallback test |
| Combined terminal evidence and harness file evidence | Metadata/output and fixture observation tests |
| Explicit capture limit/count and independent event retention | Truncation/cleanup test |
| Escaped tabs and preserved spaces without changing input | Metadata/input and hostile-evidence tests |
| Arbitrary backticks, multiline text, Markdown and unusual output remain inert | Hostile-evidence test checks fence length, table row/cell integrity and entity round trip; fixture test covers invalid bytes |
| Synthetic execution variants without a target binary | All report tests construct helper evidence directly |
| Selected paths and actionable errors | Real temporary-directory write with spaces; missing-parent/directory errors and injected permission diagnostic |
| Repository tooling | Focused pytest and full lint/format/typecheck/test gate |

These checks verify harness recording/rendering, not student output. Fixture
collection, scenario execution, and CLI integration are verified separately by
their focused tests and the full workflow tests.
