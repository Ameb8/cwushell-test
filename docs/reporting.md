# Case evidence and report rendering

`cwushell_test.evidence` defines the evidence contract for scenario runners,
fixture collectors, and the workflow. `cwushell_test.reporting` renders and writes
it as Markdown or standalone HTML without launching processes or collecting host metadata. The [workflow](workflow.md) supplies suite registration, metadata collection,
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

`write_report(report, output, report_format="markdown")` writes UTF-8 Markdown or HTML to the selected `Path` and returns its
absolute destination. Resolve the configured output path relative to invocation
before sessions begin. Paths with spaces work normally. Existing files are
replaced as requested by `-o`; missing parent directories are not created.
Filesystem/encoding errors raise `ReportWriteError` with the selected path,
underlying reason, and remediation. The writer does not choose a CLI exit code.

## HTML presentation

Use `--report-format html` from the CLI. Its default destination is
`cwushell_test_report.html`; `-o` selects any explicit path without changing
its extension. Markdown remains the default format.

`cwushell_test.html_reporting.render_html_report(report)` produces a standalone
HTML document. Both renderers share metadata, case summary values, and the full
case evidence traversal. HTML escapes every variable value into text, preserves
preformatted evidence and command whitespace, and embeds its CSS and navigation
script without external assets.

The initial view is a scan table with every case in report order across T1–T6.
Each row shows its identifier and description, fully dispatched inputs, remaining
undispatched inputs (including potentially partial dispatch), execution labels,
observed exit status or terminating signal, capture notes, and a short combined
stdout + stderr terminal preview. Exit statuses are observations, including
intentional exits; printed diagnostics remain evidence rather than harness
judgments. Startup timeouts remain visible even when later execution completes.
Cleanup signals do not count as observed terminating signals.

Previews show at most three lines and 480 characters. A shortened preview says
that more captured output is available in full evidence. This is separate from
capture truncation, which labels the retained raw-byte prefix, configured limit,
and discarded further output. Whitespace remains preformatted; actual input
tabs appear as `\t`, and literal backslashes as `\\`.

Each case has a keyboard-accessible native **Read full evidence** disclosure.
Opening it exposes all existing evidence sections: full retained output, planned
and dispatched commands and wait targets, session context, initial fixtures and
controlled environment, file observations, capture notes, execution events, and
cleanup diagnostics. Evidence sections can be collapsed individually. Execution
metadata is available above the table. Expand all / Collapse all controls are
available, and printing includes all cases and evidence regardless of filters.

Search matches case identifiers, descriptions, original and escaped inputs,
full retained output (including text beyond the preview), file observations,
session context, and execution/cleanup diagnostics. Suite and Show filters combine
with search; Show can select timeouts / terminating signals or unreviewed cases.
The live count reports matching cases out of the total and the total reviewed.
Checking **Reviewed** means the reviewer inspected the case; it assigns no
correctness status or grade. Review progress is held only in the current page
and **resets on reload**. Filtering preserves review and disclosure state.

All styles and scripts are embedded; local `file://` reports need no network or
server. Without JavaScript, the entire table, metadata, and native evidence
disclosures remain usable; search, filters, and review tracking are hidden.
On smaller screens, controls wrap and the table scrolls horizontally in a
keyboard-focusable region. Evidence text wraps and full terminal output can be
scrolled with the keyboard. Variable content is escaped as text; scripts do not
interpret evidence as HTML.

Run `task test -- tests/test_html_reporting.py tests/test_cli.py` for evidence
preservation, hostile text escaping, report order, preview/capture distinctions,
input whitespace, event filter classification, native disclosure structure,
format selection, default destinations, explicit paths, and write errors. The
full synthetic HTML CLI run in `tests/test_runner.py` verifies all 60 cases reach
the HTML report. Browser verification should also exercise combined filters,
search beyond previews and in file/cleanup evidence, review/reload behavior,
keyboard disclosures, printing, and small-screen scrolling on local files.

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

## Keyboard evidence and raw terminal view (#46, #47)

Cases with explicit actions display planned interaction labels, ordered typed
text/key/Enter actions, exact escaped input bytes including LF, and byte-level
fully sent/partial/remaining action accounting. Labels do not claim an edited
command was observed. The recovery input and triggering execution event remain
visible when dispatch stops. Existing line-based consumers retain their input
presentation. `CaseEvidence.has_action_plan` selects this presentation;
`raw_output_escaped` exposes an ASCII bytes literal from the bounded raw prefix.

Both formats include read-only terminal-setting snapshots, controlled TERM and
key profile, observed VERASE and DEL/BS equality, and optional-usability context.
The cleaned transcript and full escaped raw-byte view refer to the same retained
capture; ANSI, CR, backspace and invalid UTF-8 remain inspectable. Dynamic fences
and HTML escaping keep this text inert. HTML full-evidence disclosures include
both views and all action/terminal fields in local search through their text
content, independently of scan-preview shortening and capture truncation.
