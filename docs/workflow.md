# Complete evidence workflow

`cwushell_test.runner` registers the existing inventories in T1–T6 order:
11 prompt/whitespace/usability, 5 termination, 11 CPU, 11 memory, 11 help, and 12
system-command cases. Every scenario invokes the shared PTY helper once. Only
the prompt/reset, previous-status/exit, cd/pwd, export/printenv, unset/printenv,
and independent DEL, BS, and cursor editing/recovery sequences share their own sessions.
No extra verification or exit input is added.

The CLI resolves invocation-relative paths and validates Linux, Python 3.14+,
and the target before running. The runner requires executable host utilities
`ls`, `pwd`, `echo`, `cat`, `cp`, `rm`, and `printenv` on PATH, plus `/bin/true`
and `/bin/false`. A missing prerequisite exits 1 before launching the target.
Preparation, launch, interaction infrastructure, cleanup, and report-write
errors also exit 1 with context and remediation. Student-process EOF, exit,
signal, missing prompts, and timeouts remain observations; they do not abort
later independent cases or change a completed run's exit 0. Argument errors
remain argparse exit 2. Missing output parents are diagnosed, not created.

The runtime header identifies the absolute target and host architecture. Suite
progress is flushed before execution, including when stdout is redirected.
The terminal summary uses each `CaseEvidence.summary`, the same data used by
the Markdown or HTML summary. It records simultaneous execution labels, interaction
events/wait targets, observed exit/signal, and dispatch counts. The destination
message uses the actual absolute path returned by the report writer.

Metadata records a timezone-aware UTC timestamp, absolute executed path, kernel
release, interaction/capture limits, and separate host/target architectures.
Target architecture comes from a bounded read of the ELF machine/class header,
including either byte order. Unknown machine numbers remain explicit; scripts
are labeled interpreted, without claiming their architecture is the host's.
An unreadable target is an invocation error. Each detailed case retains its
removed temporary directory, fixtures and controlled initial environment, exact
planned/dispatched/remaining commands, terminal evidence, capture notes, direct
file snapshots, interaction events, and separate execution/cleanup notes.

The helper's interaction bound remains `(1 + planned command count) * timeout`
per case. Launch latency is recorded separately, as are the bounded TERM/KILL
cleanup intervals (0.2 seconds each). Output capture keeps the configured raw
prefix while synchronization and deadline checks continue. File snapshots occur
after cleanup/PTY closure and before directory removal. Only members remaining
in the owned group are contained; detached descendants are outside the contract.

The checkout script `cwushell_test.py` delegates to the installed CLI. It removes
its own directory from module lookup so its name cannot shadow the installed
package; it does not add a source-path override. Console, module, and script
execution all require package installation. The same-named launcher is checked
in a separate mypy pass to avoid duplicate-module discovery.

## Reproducible synthetic runs

These commands use repository fixtures, never student submissions:

```bash
task setup
mkdir -p reports
uv run --locked cwushell-test tests/fixtures/scenario_shell.py \
  -o reports/synthetic.md --timeout 1 --max-output-bytes 4096
SCENARIO_MODE=integration uv run --locked python cwushell_test.py \
  tests/fixtures/scenario_shell.py -o reports/faults.md \
  --timeout 0.5 --max-output-bytes 1024
task test -- tests/test_cli.py tests/test_runner.py
task test
task check
```

Normal mode records exact received input, working directory, and initial
environment; it simulates file and environment effects. Integration mode omits
startup prompts, changes the prompt to an unexpected value in the reset case,
crashes on an early whitespace case, floods one returning-prompt case and one
timed-out CPU case, and changes a copied file during TERM cleanup. Later suites
still execute. Fixture output is evidence; tests assert harness recording and
execution, not assignment correctness.

Built-in coverage is representative: cd, export, unset, standalone pwd, and echo.
It excludes comprehensive Bash built-ins, aliases, script sourcing, and job
control, and does not establish Bash compatibility. The synthetic target does
not implement the assignment and its information/help output has no output
acceptance predicates.

## Issue #9 acceptance evidence

| Criterion | Implementation and verification |
| --- | --- |
| Both requested entry points, defaults, explicit limits, paths with spaces, CLI validation | `test_full_cli_inventory` uses console/module/script subprocesses outside the checkout, checks every actual received input and 61 case rows; `test_cli.py` retains argument/environment validation. The PTY launch quotes the sole executable for pexpect's command parser to preserve space-containing paths. |
| Header, live T1–T6 progress, case/event summary and actual destination | `runner.execute`; each full-run test checks header, suite updates, every summary row/event label, and writer destination. |
| Timestamp/path/architectures/kernel/limits and session context | Metadata collection, backward-compatible `host_architecture` field, detailed report context; full-run checks plus ELF byte-order/target-vs-host test. |
| Shared observed summaries and complete detailed evidence | Both presentations use `CaseEvidence.summary`; full-run checks compare labels/events and required sections, fixtures and environment. Existing renderer tests verify hostile/arbitrary text containment. |
| Exit 0 for student events; exits 1/2 for harness/invocation/syntax errors | Repeated fault run exits 0; actual invalid interpreter and report-write failure exit 1; missing-printenv and CLI validation tests cover prerequisites and exit 2. |
| Continue independent cases, retain undispatched inputs, bounded startup/command/cleanup | Fault run checks stopped reset input and final unset execution, every case's measured interaction allowance and separate cleanup bound. Existing focused tests cover startup exit and each state sequence fault. |
| Bounded floods, synchronization after truncation, separate cleanup signals | Fault run checks bounded prefix, returning prompt after a flood, timed-out continuous flood, truncation/report labels, crash signal; shared detailed notes and PTY tests distinguish cleanup-phase termination. |
| Snapshots after cleanup and controlled state isolation | Full runs use fixture lifecycle and record file contents changed by a real TERM handler; exact received inputs, empty directory/initial environment, post-cleanup snapshots are checked alongside focused fixture tests. |
| Repeated runs release owned groups and PTY descriptors | Two actual CLI/report runs in-process compare `/proc/self/fd`, direct-child reaping, removed directories, and `/proc` live-group membership. Subprocess tests retain test-side finally ownership of logged groups. Existing PTY tests cover TERM-resistant descendants within the same group. |
| Real Linux synthetic end-to-end verification and documented limits | `test_runner.py`, commands above, existing synthetic suites; `task test` and `task check` validate without assignment materials. |

Full-run tests have finite 180-second outer deadlines; the repeated two-run check
uses 300 seconds. These account for 61 separately measured PTY launches per run,
which can approach 50 seconds on hosts with large descriptor limits. Each
interaction and cleanup still uses the much shorter configured per-case bounds,
with 0.25 seconds of scheduling tolerance in test assertions.
