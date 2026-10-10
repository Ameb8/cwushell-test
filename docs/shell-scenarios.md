# Prompt, termination, and system-command evidence

`cwushell_test.shell_scenarios` supplies immutable `PROMPT_CASES` (T1, ten
cases), `TERMINATION_CASES` (T2, five cases), and `SYSTEM_CASES` (T6, twelve
cases). Identifiers are stable within each suite. These definitions cover every
T1/T2/T6 input in specification section 6. The [full workflow](workflow.md)
provides full battery registration and CLI orchestration.

Each `ShellScenario.run(target, timeout=10.0, max_output_bytes=1048576)` launches
one fresh session through the existing PTY helper and returns `CaseEvidence`
with the original command tuple and helper result. It passes fixture and initial
environment settings into the shared lifecycle; the evidence adapter inherits
the helper's context and snapshots and preserves its diagnostic notes. No
verification commands or final exit inputs are appended.

```python
from pathlib import Path
from cwushell_test.shell_scenarios import PROMPT_CASES, SYSTEM_CASES

prompt = PROMPT_CASES[1].run(Path("./cwushell"), timeout=5)
copy = SYSTEM_CASES[7].run(Path("./cwushell"), timeout=5)
print(prompt.summary, copy.file_observations)
```

T1 starts with a command-free startup observation. Custom `prompt myprompt>` and
bare `prompt` share a session, waiting for literal `myprompt>` and `cwushell>`
respectively. Each of the six whitespace inputs uses its own session. Multiple
spaces are exactly three ASCII spaces per boundary; tab inputs contain actual
tabs. The existing report renderer labels its escaped `\t` representation and
preserves multiple spaces without changing dispatched input.

T2 waits for EOF after each terminating input. Only `/bin/true` then `exit` and
`/bin/false` then `exit` share their respective sessions. Observed exit status,
signal, synchronization events, and cleanup termination remain separate helper
fields. No expected exit values are stored or compared by the scenarios.

T6.ls receives its own fresh `LISTING_FIXTURES`: `fixture_alpha.txt` contains
`b"cwushell-test alpha listing fixture\n"` and `fixture_beta.txt` contains
`b"cwushell-test beta listing fixture\n"`. It dispatches only `ls`; fixture
context and before/after snapshots are separate from the actual terminal
transcript. No listing order or layout is required. Standalone T6.echo dispatches
exactly `echo fixture_alpha fixture_beta` in a separate fresh directory, using
plain arguments without quoting, expansion, or options. T1 echo inputs remain
unchanged. Ignored commands can still record COMPLETED/PROMPT, without an output
judgment.

T6's cat/cp/rm each receive the complete fresh `EXTERNAL_FIXTURES` set:
`source.txt` contains `b"cwushell-test source fixture\n"`, `removable.txt` contains
`b"cwushell-test removable fixture\n"`, and `copied.txt` is initially absent.
The helper snapshots these before launch and after process cleanup and PTY
closure, before removing the directory. Observations come from the harness,
without student-shell verification commands. File effects, including absent or
unchanged files, are retained without interpretation.

The cd sequence receives an empty `fixture_dir`. Export removes any inherited
`CWUSHELL_TEST_EXPORT`; unset starts with `CWUSHELL_TEST_UNSET=fixture_value`.
Each sequence has its own session, waits for the default prompt after the first
command, and records the subsequent pwd/printenv output. Initial settings appear
in case evidence. Host utility validation (including `printenv`) belongs to #9.
The case notes record the specification's coverage limits: representative
internal-command tests exclude comprehensive Bash built-ins, aliases, script
sourcing, and job control, and do not establish full Bash compatibility. The
standalone pwd/echo observations cover internal or external implementations.

Missing startup prompts use the helper's first-command fallback; startup-only
cases send nothing. Later timeouts stop the sequence and retain undispatched
commands. Early exit, crashes, arbitrary diagnostics, output truncation, and
different file effects retain the helper's evidence. Subsequent independent
cases can run after cleanup. Synchronization is the only prompt matching;
there are no output predicates or correctness statuses.

## Verification of issue #4

Run `task test -- tests/test_shell_scenarios.py`, `task test`, and `task check`.
The executable `tests/fixtures/scenario_shell.py` records exact inputs, PID,
directory, and initial environment through real Linux PTYs. Tests retain
finally ownership of each process group and use the repository's finite outer
timeout. Synthetic fixture assertions verify the harness, not student output.

| Acceptance criterion | Test evidence |
| --- | --- |
| Complete inventory, exact spaces/tabs, independent sessions | Inventory and all-input integration checks cover 27 fresh PIDs/directories and exact received lines, with no appended commands |
| Requested/reset prompts and state observation pacing | Wait-target assertions, received directory/environment observations, and synthetic early-input detector |
| Report compatibility, no output judgments | All-case report check, adapter identity/context test, and deviation checks retaining exit 7, arbitrary pwd/echo output, and unchanged files |
| Startup fallback and stopped sequences | Startup-only/missing/early-exit checks; mismatch, continuous-output timeout, and crash tests for each two-command prompt/cd/export/unset sequence |
| Later independent cases survive faults | Each sequence fault is followed by a fresh pwd case and both cases render into the report |
| File lifecycle and isolation | Independent cat/cp/rm snapshots, launch/cleanup ordering instrumentation, and a real TERM handler changing copied contents during cleanup |
| Exit, signal, and cleanup remain separate | All five T2 status observations; unexpected exit values; SIGSEGV and ignored-exit timeout; cleanup-only status/signal checks |
| Initial directory/environment and coverage limits | Conflicting inherited environment tests, empty-directory observation, case context and rendered coverage note |
| Configured tooling | Focused and complete pytest, Ruff lint/format checks, and mypy via Task |


## Verification of issue #17

Controlled-command regressions use the synthetic shell's actual directory listing
and received echo arguments. They compare complete retained terminal evidence,
including returned prompts, and also run a mode that silently ignores the commands.
Both modes retain the same execution observations and fixture context; no output
correctness label is introduced. Small-capture tests cover startup exit, crashes,
continuous output timeouts, prompt detection after truncation, and a subsequent
independent case with no leaked listing fixtures. Full CLI/report checks cover all
60 cases and distinguish fully sent input from input left undispatched by startup
exit. Tests keep process ownership in the existing finally-cleanup fixtures.

## Optional DEL usability observation (#46)

`T1.backspace-del` is a fresh independent session with `TERM=xterm`. It sends
four ordered actions: type `b"echo hellx"`, key `b"\x7f"` exactly once, type
`b"o"`, and Enter `b"\n"`. The intended resulting line is `echo hello`; this
is planned intent and is never inserted into observed output. After a returning
prompt, `echo keyboard_alive` plus LF is sent in that same session. Timeout,
exit or crash stops recovery and records its undispatched state.

This is optional interactive usability, not an assignment grading requirement:
assignment.md does not explicitly mandate cursor editing/history. Canonical
terminal-driver erase behavior can account for deletion; success alone does not
establish a student-implemented line editor. The observed VERASE and whether it
equals DEL are shown without remapping. A cleaned transcript alone cannot
establish editing behavior. No BS, arrow/history, Ctrl-C, EOF, or job-control
probe is added by this case.

`tests/test_keyboard.py` uses `fixtures/keyboard_shell.py`, a byte-oriented
synthetic program requiring neither student binaries nor readline. Tests verify
exact incoming bytes and supported deletion, unsupported editing and differing
VERASE, timeout/exit/crash recovery suppression and later fresh sessions, real
partial dispatch against a stopped reader, and one deadline across keystrokes.
Existing scenario and CLI tests verify canonical-driver deletion and all 60
normal workflow cases. Both renderers are checked for exact raw control/ANSI and
invalid UTF-8 preservation, hostile text containment, capture bounds, and preview
shortening distinct from raw truncation. Test-side finally cleanup owns each
synthetic group; finite outer timeouts remain enabled.

### Issue #46 acceptance mapping

| Contract | Implementation and evidence |
| --- | --- |
| Exact DEL bytes, intended line kept separate, same-session recovery | Stable `T1.backspace-del` action tuple; byte-oriented supported/unsupported tests compare real incoming bytes, observed lines and recovery order |
| VERASE context without remapping, driver-editing limits, optional usability | Read-only snapshots and shared case notes; differing-VERASE and canonical-driver tests; both report views |
| CLI registration with existing T1–T6 retained, equivalent HTML/Markdown | Existing T1 inventory registration; 60-case console/module/script and HTML CLI checks; shared detailed traversal |
| Planned actions, exact bytes, fully sent/partial/remaining accounting | `Action`, `ActionDispatch`, `Command.input_actions`; reports and real blocked-reader test, independent of output cap |
| One original monotonic deadline, no between-key prompt waits, prompt-paced recovery | Shared `_dispatch` loop and original reader deadline; delayed-write deadline test and real recovery recording |
| Fresh sessions, startup synchronization/fallback, bounded capture/cleanup | Shared `run_session`; keyboard startup/fallback and failure tests plus existing isolation/process-group lifecycle tests |
| Initial/subsequent TERM/profile, flags and VERASE without forced editing | Controlled xterm exception, termios snapshots, raw-mode/different-erase/canonical-mode fixture checks |
| Exact bounded raw prefix alongside cleaned text, inert hostile content | `raw_output_escaped`, both shared renderers, control/ANSI/invalid-UTF-8/hostile-text test with a 140-byte cap |
| Prompt/exit/signal, capture counts/truncation, recovery and cleanup notes | Shared detailed evidence fields; timeout/exit/crash tests and existing report/lifecycle tests |
| Full evidence accessible/searchable, preview shortening distinct from truncation | Native HTML disclosures, existing text-content search; raw-view and preview tests, full CLI HTML checks |
| Stop affected sequence on fault, continue later fresh cases, separate cleanup signals | Timeout, partial-write, startup-exit, normal-exit and crash tests with recovery accounting; later independent fresh cases |
| No grades, output predicates or replacement evidence; sibling boundaries retained | Scenario stores input/context only; reports preserve actual evidence and label optional usability; no BS/history/signals/job-control scenarios added |

## Optional BS usability observation (#47)

`T1.backspace-bs` runs independently of DEL in a fresh PTY with `TERM=xterm`.
Its exact ordered plan is type `b"echo hellx"`, key `b"\x08"` once, type
`b"o"`, then Enter `b"\n"`; after the resulting prompt it sends
`echo keyboard_alive` plus LF in the same session. The intended line is
`echo hello`, labeled as planned intent rather than observed input or output.
No fixtures or student source are required.

Both reports show observed VERASE and its equality to BS without remapping the
key. Canonical terminal-driver erase can explain deletion when VERASE is BS;
when VERASE differs, BS may remain in the received line. The harness forces no
editing mode. This is optional interactive usability with the same assignment
and cleaned-transcript limitations documented for DEL above.

The shared action/deadline, terminal-snapshot, bounded raw/cleaned evidence,
cleanup, and report contracts above apply unchanged. `test_keyboard.py` runs
both variants through exact incoming-byte and supported editing checks,
unsupported and differing-VERASE modes, startup fallback/exit, timeout/crash/exit
recovery suppression, early exit between keys, real partial writes, shared
monotonic deadlines, and safe hostile/raw evidence in both renderers. Canonical
BS deletion is verified with a synthetic target that sets its own VERASE;
normal CLI tests also retain the differing default VERASE behavior without
forcing it. Full workflow checks include both cases among all 60 cases.

### Issue #47 acceptance mapping

| Contract | Implementation and verification |
| --- | --- |
| Literal BS once, distinct fresh case, intended line separate from actual output | `T1.backspace-bs` action tuple; exact-byte supported/unsupported and canonical-driver tests |
| Same-session recovery or undispatched recovery with triggering event | Prompt pacing; timeout/exit/crash, startup exit and between-key exit tests |
| Observed VERASE equals BS, terminal settings/profile and optional-usability caveats | Shared read-only snapshots, BS equality in both reports, differing-VERASE/canonical fixture tests and case notes |
| Ordered actions, explicit LF, shared deadline and partial/remaining accounting | Existing shared PTY contract; both-byte deadline tests and real blocked-reader partial dispatch |
| Raw and cleaned bounded evidence, inert controls/hostile text, capture and preview distinction | Both-byte raw-view tests, same retained prefix, shared report traversal and HTML full-evidence search |
| Prompt/exit/signal and separate cleanup evidence; later cases continue | Both-byte stopped-recovery tests with fresh later sessions, full workflow fault/lifecycle checks |
| CLI registration, both report formats, inventories and original T1–T6 retained | 60-case console/module/script Markdown and HTML runs, 27-case T1/T2/T6 inventory tests |
| No grades, comparisons or replacement output; excluded sibling probes absent | Input-only scenario definition and manual-review notes; no new cursor/history/signal/job-control cases |
