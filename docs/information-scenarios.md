# CPU, memory, and help evidence scenarios

`cwushell_test.information_scenarios` supplies `CPU_CASES` (T3), `MEMORY_CASES`
(T4), and `HELP_CASES` (T5). Each immutable inventory contains exactly eleven
cases from specification section 6, including separate individual, joined-option,
and separate-option CPU/memory inputs. Case identifiers are stable within their
suite; the command itself is the case title. Bare `exit` and bare `prompt` belong
to T2 and T1 respectively and are absent from this inventory.

Each `InformationScenario.run(target, timeout=10.0, max_output_bytes=1048576)`
calls the existing PTY helper once with its exact one-command plan. It returns
`CaseEvidence` containing the original command tuple and unmodified helper
evidence. Every call therefore gets a fresh process session and temporary working
directory, and cleanup finishes before the evidence returns. No exit command or
verification input is appended. The helper retains startup fallback observations,
dispatch, terminal bytes, capture limits, process events, and cleanup separately.

```python
from pathlib import Path
from cwushell_test.information_scenarios import CPU_CASES

case = CPU_CASES[0].run(Path("./cwushell"), timeout=5, max_output_bytes=65536)
print(case.case_id, case.session.output, case.summary.outcomes)
```

All cases use the default literal `cwushell>` for interaction synchronization.
Help input that exits is retained as EOF and any observed process status. Help
input that changes the prompt retains the new terminal text; if the default
prompt does not return, the helper records the synchronization timeout and cleans
up. No arbitrary new prompt is inferred from output. Missing startup prompts use
the helper's first-command fallback; later timeouts stop the case. Remaining
undispatched input, including a command skipped because of startup termination,
stays in the helper evidence.

Output is never interpreted for numeric plausibility, units, host values,
components, completeness, or documentation layout. Empty output, diagnostics,
unusual formatting, and prompt/termination events are observations for manual
review. Capture truncation does not alter command/event recording or stop prompt
detection. Workflow registration, CLI orchestration, progress, and full-run report
integration remain owned by #9.

## Focused verification of issue #8

Run `task test -- tests/test_information_scenarios.py`, then `task check`.
The executable synthetic `tests/fixtures/information_shell.py` records exact
received lines, PID, and directory or injects output and process events. Tests
own each spawned process group in a `finally` cleanup fixture and use the
repository's finite outer timeout. No student binaries or full CLI workflow are
required.

| Acceptance criterion | Test evidence |
| --- | --- |
| Exact 11/11/11 inventory and independent dispatch | `test_exact_inventory`; all 33 commands received through real PTYs with distinct processes/directories |
| Arbitrary, empty, formatted, and diagnostic output | `test_output_is_evidence` covers all three suites without content judgments |
| Help exits and prompt changes retained | Both `-h` and `--help` forms for exit/prompt preserve status, output, wait target, and cleanup |
| Startup fallback, stopped dispatch, cleanup | Startup fallback/exit tests preserve simultaneous events and undispatched input; help prompt timeout checks cleanup |
| Crash/timeout/truncation continuation and report contract | Fault test proceeds within T3 and onward to T4/T5, checks bounded capture/timing and renders the returned evidence; adapter identity test preserves every helper field |
| Focused Linux tests and required tooling | Real PTYs, owned synthetic target, `task test`, and `task check` |
