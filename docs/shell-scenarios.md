# Prompt, termination, and system-command evidence

`cwushell_test.shell_scenarios` supplies immutable `PROMPT_CASES` (T1, eight
cases), `TERMINATION_CASES` (T2, five cases), and `SYSTEM_CASES` (T6, twelve
cases). Identifiers are stable within each suite. These definitions cover every
T1/T2/T6 input in specification section 6. Full battery registration and CLI
orchestration remain with #9.

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
| Complete inventory, exact spaces/tabs, independent sessions | Inventory and all-input integration checks cover 25 fresh PIDs/directories and exact received lines, with no appended commands |
| Requested/reset prompts and state observation pacing | Wait-target assertions, received directory/environment observations, and synthetic early-input detector |
| Report compatibility, no output judgments | All-case report check, adapter identity/context test, and deviation checks retaining exit 7, arbitrary pwd/echo output, and unchanged files |
| Startup fallback and stopped sequences | Startup-only/missing/early-exit checks; mismatch, continuous-output timeout, and crash tests for each two-command prompt/cd/export/unset sequence |
| Later independent cases survive faults | Each sequence fault is followed by a fresh pwd case and both cases render into the report |
| File lifecycle and isolation | Independent cat/cp/rm snapshots, launch/cleanup ordering instrumentation, and a real TERM handler changing copied contents during cleanup |
| Exit, signal, and cleanup remain separate | All five T2 status observations; unexpected exit values; SIGSEGV and ignored-exit timeout; cleanup-only status/signal checks |
| Initial directory/environment and coverage limits | Conflicting inherited environment tests, empty-directory observation, case context and rendered coverage note |
| Configured tooling | Focused and complete pytest, Ruff lint/format checks, and mypy via Task |
