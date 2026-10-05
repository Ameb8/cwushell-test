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
making an exiting child waitable. Cleanup takes another nonblocking status
snapshot before signaling, including on exception paths. A termination first
observed after the pre-signal snapshot is recorded in `cleanup_exit_status` or
`cleanup_signal_status`, never substituted for the observed student termination.
These fields describe the cleanup phase, without claiming a causal attribution
for a process that exited concurrently with a harness signal.

Targets resolve to absolute paths before launch and run in fresh
`TemporaryDirectory` instances. The helper sets terminal size to 24×80 and
`TERM=dumb`, `LC_ALL=C`, and `LANG=C`. Other environment values are inherited,
or callers can provide a complete `environment` mapping. Scenario fixture
preparation and file-state reporting will need their own seam in later tasks.
`working_directory` records the path, which is removed after cleanup.

The forkpty launcher is verified at launch to create a session and group whose
IDs equal the child PID, distinct from the harness group. No `preexec_fn=os.setpgrp`
is used. `pgid` records only verified ownership. If ownership verification fails,
the helper records `ERROR` and terminates only its still-waitable direct child,
without sending any signal to the unverified group.

Cleanup runs in `finally` after completion, EOF, timeout, exceptions, and
interruption. It signals the verified group with TERM and then KILL if the group
still exists, with at most 0.2 seconds of monotonic grace per signal. Group
existence is checked independently of the leader: an exited leader does not
imply its children are gone. Nonblocking pexpect status checks reap the direct
child; `direct_child_reaped` records that result. `cleanup_actions` records group
signals as `SIGTERM` / `SIGKILL` and ownership-failure fallback signals as
`DIRECT_CHILD_SIGTERM` / `DIRECT_CHILD_SIGKILL`. `cleanup_error` identifies a
cleanup exception or a direct child still live at the deadline. Future report
consumers should retain these diagnostics.

The helper closes pexpect's owned PTY file object directly and marks both wrappers
closed, avoiding `pexpect.close()`'s implicit HUP/CONT/INT signals and sleeps.
Repeated teardown and subsequent `close()` calls are harmless. The temporary
working directory is removed after process cleanup and PTY closure.
`interaction_seconds` and `cleanup_seconds` record measured durations separately;
`launch_seconds` records process creation. Linux integration tests allow 0.25
seconds of scheduling tolerance beyond the interaction allowance and the separate
0.4-second cleanup budget.

Group signals cover descendants that remain in that group. Descendants creating
another group or session are explicitly outside this guarantee. Reaping the
direct child does not reap arbitrary descendants: orphan zombies are their new
parent's responsibility. `killpg(pgid, 0)` includes zombies, so their presence can
consume both cleanup grace periods even after all live members have died. The
tests verify no live owned group members remain; a test-only Linux subreaper
adopts and reaps the synthetic orphans to avoid depending on the host's PID 1.
The production helper does not install a subreaper or implement a general sandbox.

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

## Lifecycle verification (#7)

The synthetic fixture commands include `child_exit` (leader exits 23),
`child_exit_resist` (a survivor ignores TERM and HUP), `child_exit_tty_resist`
(the survivor also retains the PTY, preventing EOF), `child_crash_resist`,
`child_hang_resist`, `child_ready_resist`, and `resist` (the leader ignores TERM).
A pipe handshake establishes that the descendant's signal handlers are installed
before the leader reports its PID/group or exits; these tests do not rely on
sleeping long enough for a forked child to become ready.

| Issue acceptance criterion | Linux verification |
|---|---|
| Preserve normal exit and signal separately from cleanup | Existing exit/crash checks; parametrized fault-group check; exception after observed exit |
| Cleanup after EOF, timeout, crash, exception, or exited leader | Fault-group check including a survivor retaining the PTY; surviving-member exception check; interruption check |
| TERM-resistant group members leave no live survivors | Fault-group and exception checks inspect `/proc` group membership after cleanup |
| Reap only the directly waitable child | Release assertions verify `waitpid` reports no child; test-side subreaper separately reaps adopted fixtures |
| Idempotent close; no unrelated/harness group targeting | Fault-group check repeats cleanup/close; unverified-group checks protect the harness and a live unrelated sentinel |
| No PTY descriptor accumulation; subsequent sessions work | Repeated fault-group runs compare `/proc/self/fd` counts and execute a fresh exit session after each fault |
| Separate timing and explicit containment limit | Evidence fields, timing assertions, measurements below, and scope documented above |

Run `task test -- tests/test_pty_session.py` for both interaction and lifecycle
checks. The complete `task check` also validates the CLI boundary and static
checks. No suite implementation, student binaries, scoring, or detached-process
containment is required by these checks.

A Linux / Python 3.14.6 verification run with `timeout=0.3` and one command per
session recorded the following (each run also verified no live group members,
a reaped direct child, and a succeeding fresh session):

| Fixture | Launch | Interaction | Cleanup | Observed termination | Cleanup-phase direct-child signal |
|---|---:|---:|---:|---|---|
| `child_exit` | 0.782 s | 0.193 s | 0.401 s | exit 23 | — |
| `child_exit_resist` | 0.782 s | 0.194 s | 0.401 s | exit 23 | — |
| `child_exit_tty_resist` | 0.809 s | 0.461 s | 0.404 s | exit 23, interaction TIMEOUT | — |
| `child_crash_resist` | 0.781 s | 0.160 s | 0.401 s | SIGSEGV | — |
| `child_hang_resist` | 0.811 s | 0.456 s | 0.401 s | interaction TIMEOUT | SIGTERM |
| `resist` | 0.778 s | 0.445 s | 0.213 s | interaction TIMEOUT | SIGKILL |

All six runs sent group TERM and KILL. For `child_exit`, TERM terminated the
survivor, but its adopted zombie kept the group visible until the test-side parent
reaped it after measurement. The test-side subreaper was enabled for measurement
as in the integration fixtures. These measurements are examples with scheduling
variation; the automated tests enforce the allowances, independently of the
launch duration.
