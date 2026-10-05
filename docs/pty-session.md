# PTY interaction contract

`pty_session.run_session` runs one finite scenario through a real Linux pexpect
PTY and returns `Evidence` after cleanup. It has no suite definitions, CLI
integration, report generation, or output judgments. The CLI runner remains a
stub until the workflow task connects these components. Start a fresh session for
each independent case; share commands only to observe state changes.

```python
from pathlib import Path
from pty_session import Command, run_session

result = run_session(
    Path("./cwushell"),
    [Command("prompt custom>", "custom>"),
     Command("prompt"),
     Command("exit 42", None)],
    timeout=5.0,
    max_output_bytes=65536,
)
print(result.dispatched, result.reason, result.output)
```

Each `Command` contains exact single-line input (including spaces and actual
tabs), and the literal prompt expected after it. `None` means expected EOF;
prompt changes must be specified explicitly. The default initial and command
prompt is `cwushell>`. Prompts match literal substrings after streaming ANSI
removal, even across reads and beyond the capture limit. This synchronizes input;
it cannot distinguish a prompt from identical text printed by a command. Do not
interpret a prompt match as a correctness judgment.

The initial prompt wait gets `timeout` seconds. If it expires, its `TIMEOUT`
observation remains in `interactions`, and the first command is sent anyway as
required by spec section 5.1. A startup-only scenario stops there. EOF at startup
stops dispatch. Each later command gets one deadline starting before its first
write, encompassing dispatch and all output reads. Prompt timeout stops the
sequence and retains the remaining commands in `undispatched`. EOF completes
collection immediately, including unexpected EOF; `waiting_for` distinguishes
expected EOF from a prompt wait interrupted by process termination.

The monotonic session allowance starts when pexpect returns the spawned PTY.
It defaults to `(1 + planned command count) * timeout`; optional `session_timeout`
can make it smaller. Reads, partial output, and new commands cannot reset it.
pexpect's synchronous fork/exec launch is measured separately as `launch_seconds`
(and is outside the interaction allowance); on the verification host it takes
about 0.8 seconds because the inherited descriptor limit is 524288. No target
input or output collection occurs before the interaction clock starts. This
launch boundary follows the spec's **interaction** budget, rather than promising
a wall-clock bound on OS process creation. Target writes use a nonblocking PTY
and deadline-bound readiness checks; sends do not use pexpect's default delay.

`Evidence` retains raw terminal-output bytes up to `max_output_bytes`, counting
startup, prompts, and all command output together. `raw_output` is a prefix;
`truncated` must be displayed by future report consumers together with the limit
and `len(raw_output)`. `output` decodes UTF-8 with replacement, strips ANSI
sequences (including incomplete sequences at truncation), and normalizes CRLF
and CR to LF. Stdout and stderr are combined terminal output. Terminal echo is
disabled at launch and explicitly before input; dispatched commands are recorded
separately and never inferred from output. A target can itself print its input.
The streaming reader retains at most one 4096-byte read and a prompt-sized tail
besides the bounded evidence prefix; it does not use pexpect's accumulating
`expect` buffer. Reads use deadline-bound descriptor readiness and nonblocking
`os.read` on the pexpect-owned PTY; this avoids ptyprocess changing to blocking
`waitpid` after EOF from a still-live process. Unterminated terminal control
strings consume constant state.

`reason` is `COMPLETED` (observed final prompt), `EOF`, `TIMEOUT`, or `ERROR`.
`interactions` records startup and command events with the relevant wait target.
`dispatched` contains fully sent lines; a dispatch timeout can have sent a partial
line, which remains in `undispatched` and is identified by its interaction event.
`error` describes execution exceptions. Invalid limits, empty prompts, and
multiline inputs raise `ValueError` before spawning. Other exceptions return
error evidence; interruption propagates after cleanup. Observed `exit_status`
and `signal_status` are sampled before cleanup, so a cleanup signal is never
presented as an observed crash. After EOF, nonblocking status polls get at most
0.05 seconds within the existing interaction deadline to account for the kernel
making an exiting child waitable. Difficult lifecycle reporting is owned by #7.

Targets resolve to absolute paths before launch and run in fresh
`TemporaryDirectory` instances. The helper sets terminal size to 24×80 and
`TERM=dumb`, `LC_ALL=C`, and `LANG=C`. Other environment values are inherited,
or callers can provide a complete `environment` mapping. Scenario fixture
preparation and file-state reporting will need their own seam in later tasks.
`working_directory` records the path, which is removed after cleanup.

The forkpty launcher is verified to create a group whose ID equals the child PID;
no `preexec_fn=os.setpgrp` is used. Cleanup signals that group with TERM and KILL,
with at most 0.2 seconds of grace per signal, reaps the direct child using
nonblocking status checks, and closes the PTY. `cleanup_actions` records signals
separately. `interaction_seconds` and `cleanup_seconds` record measured durations.
Linux integration tests allow 0.25 seconds of scheduling tolerance beyond the
interaction allowance plus the separate 0.4-second cleanup budget. Group signals
cover members that remain in that group; detached descendants and reaping all
descendant zombies are outside this guarantee. #7 strengthens lifecycle handling
and checks difficult descendant/termination paths before suites depend on #2.

## Focused verification

```bash
task setup
task test -- tests/test_pty_session.py
task check
```

The executable `tests/fixtures/mock_shell.py` supports normal interaction,
explicit prompt changes, split ANSI prompts, slow/partial output, continuous and
trickling output, capture floods, missing startup prompts, hangs, and crashes.
Set `MOCK_MODE=ansi`, `missing`, or `hang` to choose startup behavior; the default
is normal. It is repository-owned synthetic code and uses no student binary.
The `paced` command watches for early input before emitting its next prompt,
providing cross-process evidence of sequential dispatch. All tests have the
repository's 60-second outer timeout and test-side finally cleanup.

The acceptance checks map to tests as follows:

| Requirement | Fixture checks |
|---|---|
| Initial/changed prompts and EOF | `test_initial_changed_reset_prompts_and_expected_eof` |
| Sequential dispatch | `test_sequential_pacing_and_partial_output` |
| Echo-free, cleaned startup evidence | The pacing test and `test_ansi_prompt_and_startup_capture`, plus cleaning cases |
| Deadlines despite output or hangs | `test_output_does_not_extend_interaction_deadline`, `test_total_session_budget_is_not_reset` |
| Missing/mismatched prompts | Fallback, mismatched command, and startup-only checks |
| Safe cleanup and retained evidence | Exception, crash/fresh-session, and descriptor/process assertions |
| Bounded capture with synchronization | `test_prompt_synchronization_after_capture_truncation` |

A measured Linux run with `timeout=0.2`, `session_timeout=0.35`, and a 64-byte
capture limit recorded these bounds (startup plus command collection is included
in interaction time):

| Fixture | Launch | Interaction | Cleanup | Reason |
|---|---:|---:|---:|---|
| Continuous output | 0.818 s | 0.326 s | 0.011 s | TIMEOUT |
| Partial trickling output | 0.794 s | 0.323 s | 0.011 s | TIMEOUT |
| Silent hang | 0.771 s | 0.350 s | 0.011 s | TIMEOUT |

These measurements are examples, not guarantees of scheduling latency. Deadline
assertions enforce the documented allowance and tolerance on every test run.
Additional checks cover startup exit, interruption, EOF from a still-live process,
repeated descriptor release, and deliberately interleaved input proving that the
pacing fixture detects the defect it is intended to catch.
