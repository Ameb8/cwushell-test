# Specification: `cwushell-test` Test Harness

**Course:** CS 470 – Operating Systems (Fall 2026)  
**Target Assignment:** Lab 1 (`cwushell` Mini Shell)  
**Document Status:** Final Specification  

**Development conventions:** [Tooling, harness tests, and contributor commands](../development.md).
These conventions govern development of the harness; the requirements below
govern its runtime behavior and student-shell evidence collection.

---

## 1. Overview and Objectives

The `cwushell-test` program is an automated testing harness designed to collect execution evidence from student implementations of the `cwushell` command interpreter against the requirements and rubric specified in [Operating_Systems_Lab_1_Fall_2026.md](file:///Users/pattycrowder/Documents/Alex_Documents/cwu/470-TA/lab-1/Operating_Systems_Lab_1_Fall_2026.md).

The program does not score implementations or determine whether their stdout is correct. It records test cases, dispatched commands, observed terminal output, and execution events for manual review. Prompt matching may be used to synchronize interactions, but must never produce correctness judgments.

### Primary Objectives
- **Automated Execution:** Execute a standardized test suite against a pre-compiled `cwushell` binary without requiring manual input entry.
- **Fault-Tolerant Isolation:** Run every test case in an independent process session to prevent crashes, memory faults, or deadlocks in one test from contaminating others.
- **Defensive Timeout Enforcement:** Enforce strict wall-clock time limits on all interactions to neutralize infinite loops, unhandled EOF hangs, and deadlocks.
- **Readable Markdown Reporting:** Generate an evidence-backed Markdown report per test run that displays test cases and captured student outputs for manual review, without scores or automated correctness judgments.

---

## 2. Environment and Assumptions

1. **Target Platform:** Linux environment (native Linux host, VM, or WSL). The harness relies on standard Linux kernel behaviors and virtual filesystems (e.g., `/proc/cpuinfo`, `/proc/meminfo`) expected by the assignment.
2. **Pre-Built Binaries:** The harness tests an already compiled binary executable named `cwushell`. The path to the binary can be passed via command-line argument (defaulting to `./cwushell`). Build system operations (e.g., `make`, `gcc`) are handled externally prior to running this harness.
3. **Dependencies:**
   - Python 3.14+ (including the standard-library `argparse` module for CLI parsing)
   - `pexpect` library (terminal interaction wrapper over POSIX pseudo-terminals)

4. **Temporary Working Directory:** Each independent test session runs in a fresh temporary working directory created with `tempfile.TemporaryDirectory`. Populate it with a fixed set of known fixture files for external-command scenarios, and record those fixtures in the report. Resolve the target binary and report output paths relative to the invocation directory before spawning the shell; execute the binary by its absolute path. Use consistent terminal settings and explicitly controlled environment values where needed for repeatable interactions. Clean up the temporary directory after process cleanup, including on timeout or exception.

---

## 3. Command-Line Interface (CLI)

The CLI must use Python’s standard-library `argparse`, including generated help, displayed defaults, and invalid-argument handling.

### 3.1 Synopsis & Usage
```bash
cwushell-test [-h] [-o OUTPUT] [--timeout SECONDS] [--max-output-bytes BYTES] [target]
```
*(or via Python: `python3 cwushell_test.py [-h] [-o OUTPUT] [--timeout SECONDS] [--max-output-bytes BYTES] [target]`)*

### 3.2 Arguments and Options

| Argument / Flag | Type | Default | Description |
|---|---|---|---|
| `target` | Positional (optional) | `./cwushell` | Path to the pre-compiled student shell binary to execute. |
| `-o`, `--output` | Option (`FILE`) | `cwushell_test_report.md` | Path for the generated Markdown test report. |
| `--timeout` | Option (`SECONDS`) | `10.0` | Positive, finite number of seconds allowed for the initial prompt wait and for each dispatched command, including single-command scenarios and exit commands. |
| `--max-output-bytes` | Option (`BYTES`) | `1048576` (1 MiB) | Positive integer limiting retained raw terminal-output bytes per session, before decoding, ANSI sanitization, or line-ending normalization. |
| `-h`, `--help` | Flag | — | Display help message with usage instructions and defaults. |

### 3.3 Exit Codes
- `0`: Harness completed execution and generated the test report (including runs that record student-process timeouts or crashes).
- `1`: Invocation or environment error (e.g., target binary does not exist or lacks execute permissions).
- `2`: Invalid command-line arguments or syntax.

### 3.4 Terminal Output and Execution Behavior
- **Execution Progress:** Displays execution header (target binary, host architecture) followed by live status updates as each isolated test suite (`T1` through `T6`) executes.
- **Terminal Summary:** Prints a summary of executed test cases and execution events (such as timeouts or crashes), followed by the destination path of the generated Markdown report. No scores or correctness statuses are printed.

---

## 4. Core Architectural Principles

### 4.1 Pseudo-Terminal (PTY) Interaction via `pexpect`
Standard I/O redirection using traditional pipes (`subprocess.PIPE`) causes the C standard I/O library to switch from line buffering to block buffering. Because student shells typically print prompts (such as `cwushell>`) without a trailing newline (`\n`), piped harnesses hang waiting for a buffer flush.

`cwushell-test` must execute the target binary inside an emulated POSIX Pseudo-Terminal (PTY) using Python's `pexpect`. This guarantees:
- `isatty()` returns `true` inside the student process.
- Prompts and diagnostic outputs flush immediately to the harness.
- Shell behaviors accurately mirror real-world user terminal interaction.

### 4.2 Session Isolation (Per-Case Independence)
Student shells are prone to segmentation faults, signal misconfigurations, or command execution stalls. 
- **Rule:** Under no circumstances should the entire test battery run within a single ongoing shell instance.
- **Design:** Each independent test scenario must spawn its own dedicated instance of `cwushell`, perform its operations, capture output, and terminate. Suites group scenarios for organization and reporting; they do not share a shell instance across independent scenarios. A crash or hang in one scenario must not prevent remaining scenarios, including those in the same suite, from executing. A command sequence may share a session when needed to observe state changes.

### 4.3 Strict Wall-Clock Timeouts
- The initial prompt wait and every dispatched command have a wall-clock deadline controlled by `--timeout` (default: 10.0 seconds). This applies to single-command scenarios, every command in a shared-session sequence, and commands intended to terminate the shell. Measure deadlines using a monotonic clock; incoming output does not restart or extend them.
- Start each command deadline when dispatch begins. Bound command dispatch itself and all subsequent output collection by that deadline. Observe a returning prompt or process exit within the deadline; never wait indefinitely for additional output or termination. Retain the observed event without judging correctness.
- If a command deadline expires, record a `TIMEOUT` event identifying the command and what the harness was waiting for, stop the scenario, retain captured output, record any undispatched commands, and run guaranteed process-group cleanup before advancing to the next scenario. A timeout waiting for a prompt does not establish that the student process is hung. Expiration of the initial prompt wait follows the first-command fallback in Section 5.1.
- Each session has a finite number of commands and at most one initial prompt wait. Its interaction budget is therefore at most `(1 + number of planned commands) × timeout`, followed by separately bounded TERM/KILL cleanup, reaping, and PTY closure. A hung single-command scenario cannot continue indefinitely or require manual interruption.

---

## 5. Hardened PTY Helper: Purpose and Design

To eliminate common compatibility traps found in student-written shells, all interactions with the shell binary must be routed through a dedicated execution helper.

### 5.1 Responsibilities and Design Goals

1. **Disabling Local Terminal Echo:**
   - *Problem:* PTY devices echo all sent keystrokes back to stdout by default. If the harness sends `cpuinfo -c`, the PTY echoes `cpuinfo -c\r\n`. Echoed input would obscure which text was actually emitted by the implementation.
   - *Design:* The helper explicitly disables echo on the spawned terminal immediately after launch (`setecho(False)`).

2. **ANSI Escape Sequence Sanitization:**
   - *Problem:* Students utilizing GNU `readline` or custom prompt styling output terminal color codes and cursor movement escape sequences (e.g., `\x1b[0m`, `\x1b[K`).
   - *Design:* The helper applies regex sanitization to strip all ANSI terminal sequences before including captured text in the report.

3. **Synchronized Command Pacing (Step-and-Wait):**
   - *Problem:* Feeding multiple commands simultaneously into stdin risks input interleaving, buffer overflow, or child processes stealing subsequent commands from the parent shell.
   - *Design:* In shared-session sequences, wait for the next prompt before dispatching another command. The wait uses the command's deadline under `--timeout` (default: 10.0 seconds), without starting a second deadline after dispatch. If the prompt is not observed within that deadline, stop the sequence, retain captured output, record the synchronization timeout and remaining undispatched commands, and clean up the session. Continue all remaining independent scenarios. After a prompt-change command, wait for the requested new prompt; after bare `prompt`, wait for the default prompt.
   - *Initial Prompt:* Before the first command in a scenario, wait for the literal default prompt `cwushell>` up to `--timeout`. If that prompt is not observed by the deadline but the process is still running, dispatch the first command anyway. Record that the expected initial prompt was not observed within the deadline, retain all captured terminal output, and do not treat the missing prompt as a correctness judgment or as a reason to skip command testing. If the process has already exited, record its termination and the undispatched command instead. The initial-prompt-only scenario records the startup observation without dispatching a command.

4. **Line-Ending Normalization:**
   - *Problem:* PTY drivers translate `\n` to `\r\n` (CRLF).
   - *Design:* The helper normalizes all line endings to standard Unix `\n` for consistent report formatting.

5. **Guaranteed Cleanup with TERM/KILL Escalation:**
   - *Problem:* When student programs enter infinite loops or fork child processes without waiting, normal `close()` calls can leave processes running.
   - *Design:* Spawn the shell in an isolated process group and track its process group ID (`pgid`). In a guaranteed cleanup path (`finally` or a context manager), send `SIGTERM` to that group, allow a bounded grace period, then send `SIGKILL` to the group if necessary. Reap the direct child and close the PTY before removing the temporary working directory. Cleanup runs after normal completion, timeout, exceptions, and user interruption, including when the shell has exited but other group members remain. Record cleanup actions separately from the shell’s observed exit status or signal.
   - *Scope:* Process-group termination covers descendants that remain in that group. It does not guarantee termination of descendants that create a different process group or session, and reaping the direct child does not reap all descendants.

6. **Bounded Output Capture:**
   - *Design:* Retain at most `--max-output-bytes` (default: 1 MiB) of raw terminal output per session, including startup and all commands in a shared-session sequence. Retain the prefix; once the limit is reached, continue reading and discarding excess output until the command completes or its existing deadline expires. Reaching the limit alone does not end the scenario or restart its deadline.
   - *Synchronization:* Prompt detection must continue after capture truncation, using bounded streaming buffers rather than retaining all discarded output in `pexpect` or another intermediate buffer. Output processing must continue to check deadlines even during continuous output.
   - *Reporting:* Clearly label truncated transcripts and state the configured capture limit and retained byte count. Record process events and command dispatch independently of transcript truncation. Never silently present a truncated transcript as complete.

---

## 6. Test Suite Specifications

The harness executes six test suites organized by assignment feature. These suites collect evidence only; they do not assign points, check output correctness, or mark implementations as passing or failing. Every required command option must have an independent test scenario in a fresh shell session. Combined-option scenarios are additional tests and do not replace individual-option coverage. Related command sequences share a session only when needed to observe state changes.

| ID | Test Suite | Scenarios Recorded |
|---|---|---|
| **T1** | Prompt Management & Whitespace | Initial prompt; custom prompt via `prompt myprompt>`; reset via `prompt`; six independent whitespace scenarios specified below. |
| **T2** | Process Termination | Five independent scenarios: `exit 42`; `exit -10`; bare `exit` immediately after startup; `/bin/true` followed by bare `exit`; `/bin/false` followed by bare `exit`. The latter two sequences each share a session to observe propagation of the previous command's status. `/bin/true` returns 0 and `/bin/false` returns 1. Record the observed shell exit status without comparing it to an expected value. |
| **T3** | CPU Information | Individual options: `cpuinfo -c`, `cpuinfo -t`, `cpuinfo -n`. Combined options: `cpuinfo -ct`, `cpuinfo -c -t`, `cpuinfo -cn`, `cpuinfo -c -n`, `cpuinfo -tn`, `cpuinfo -t -n`, `cpuinfo -ctn`, `cpuinfo -c -t -n`. Each command runs in an independent session. |
| **T4** | Memory Information | Individual options: `meminfo -t`, `meminfo -u`, `meminfo -c`. Combined options: `meminfo -tu`, `meminfo -t -u`, `meminfo -tc`, `meminfo -t -c`, `meminfo -uc`, `meminfo -u -c`, `meminfo -tuc`, `meminfo -t -u -c`. Each command runs in an independent session. |
| **T5** | Help & Manual System | `manual`, bare `cpuinfo`, `cpuinfo -h`, `cpuinfo --help`, bare `meminfo`, `meminfo -h`, `meminfo --help`, `exit -h`, `exit --help`, `prompt -h`, and `prompt --help`, each in an independent session. Capture documentation output without judging its content or formatting. |
| **T6** | Error Handling & System Commands | `bogus_cmd_xyz`, `cpuinfo -z`, `meminfo -x`, and system commands `ls`, `pwd`, `echo`, `cat`, `cp`, and `rm`, each in an independent session. For fixture scenarios, dispatch `cat source.txt`, `cp source.txt copied.txt`, or `rm removable.txt` in separate temporary working directories. Additional independent scenarios exercise `cd`, `export`, and `unset` using the shared-session sequences specified below. Record terminal output, execution events, and relevant file state before and after without judging correctness. |

**Assignment interpretation for no-argument commands:** The assignment's explicit definitions of bare `exit` (terminate the shell) and bare `prompt` (restore the default prompt) take precedence over its general instruction that commands without parameters show help. Test these behaviors in T2 and T1 respectively. T5 records the `-h` and `--help` forms for both commands in independent sessions, including any observed termination or prompt change, without judging correctness.

**Whitespace scenarios (T1):** Each of these six inputs runs in a fresh session. Multiple-space inputs contain exactly three ASCII spaces at each argument boundary. In the table, `\t` represents one actual tab character sent to the shell, not a literal backslash followed by `t`.

| Command | Multiple-space input | Tab-separated input (escaped representation) |
|---|---|---|
| CPU information | `cpuinfo   -c   -t` | `cpuinfo\t-c\t-t` |
| Memory information | `meminfo   -t   -u` | `meminfo\t-t\t-u` |
| System command | `echo   alpha   beta` | `echo\talpha\tbeta` |

The report's command description shows tabs using the escaped representation `\t` and labels that representation explicitly. Preserve multiple spaces and do not replace actual tabs with the characters `\t` when dispatching input.

**External-command fixtures:** Prepare `source.txt` and `removable.txt` with fixed, documented text contents in each applicable temporary working directory; `copied.txt` is initially absent. Each `cat`, `cp`, and `rm` scenario receives its own fresh fixtures. The harness records relevant file existence and contents before launch and after process cleanup, before removing the temporary directory. File-state observations are collected directly by the harness and identified separately from student terminal output; they must not depend on sending additional verification commands to the student shell or produce correctness judgments.

**Built-in command scenarios:** Each of the following starts a fresh shell session. Commands within a scenario share that session to observe state changes and follow the command pacing and deadlines in Sections 4.3 and 5.1.

- **Directory change:** Create an empty `fixture_dir` beneath the session's temporary working directory. Dispatch `cd fixture_dir`, then `pwd`, and capture the observed terminal output.
- **Environment export:** Ensure `CWUSHELL_TEST_EXPORT` is absent from the shell's initial environment. Dispatch `export CWUSHELL_TEST_EXPORT=fixture_value`, then `printenv CWUSHELL_TEST_EXPORT`, and capture the observed terminal output.
- **Environment removal:** Launch the shell with `CWUSHELL_TEST_UNSET=fixture_value` in its environment. Dispatch `unset CWUSHELL_TEST_UNSET`, then `printenv CWUSHELL_TEST_UNSET`, and capture the observed terminal output.

Record these initial environment settings and directory fixtures in the report. The host must provide `printenv` for the environment observations. These are representative tests of the assignment's broad requirement to execute existing internal commands; coverage does not include every Bash built-in, aliases, script sourcing, or job control, and does not establish full Bash compatibility. The standalone `pwd` and `echo` scenarios record behavior whether the student shell implements them internally or invokes external programs.

---

## 7. Output Reporting Specification

### 7.1 Report Generation
Running `cwushell-test` automatically generates a single formatted Markdown report (defaulting to `cwushell_test_report.md`, customizable via the `-o` / `--output` flag).

### 7.2 Markdown Report Structure
The generated report must contain:

1. **Header & Execution Metadata:**
   - Date and time of execution
   - Path to executed binary
   - Target architecture and OS kernel version
   - Temporary working directory, fixture files, and controlled environment settings used for each session
   - Configured interaction timeout in seconds (`--timeout`)
   - Configured per-session output capture limit in bytes (`--max-output-bytes`)
2. **Execution Summary Table:**
   - List each test case and its execution outcome, such as `COMPLETED`, `TIMEOUT`, `PROCESS_EXIT`, or `SIGNAL`.
   - These labels describe observed execution events only. `COMPLETED` does not imply correct output.
   - No grades, points, provisional scores, or `PASS`/`PARTIAL`/`FAIL` correctness statuses.
3. **Detailed Evidence Sections (Per Test Case):**
   - **Dispatched Commands:** Exact commands sent to the shell.
   - **Observed Terminal Output:** Captured terminal text from the student binary, cleaned of ANSI escapes and normalized to Unix line endings, formatted inside Markdown code blocks. PTY output may combine stdout and stderr; the report must identify it as terminal output rather than claim they are captured separately.
   - **Capture Notes:** Whether terminal output was truncated, the configured byte limit, and the retained raw byte count for each session.
   - **Fixture Evidence (Where Applicable):** Relevant file existence and contents before launch and after process cleanup, collected by the harness and labeled separately from terminal output, without correctness judgments.
   - **Execution Notes:** Observed process exit status, terminating signal, timeout, incomplete command dispatch, and cleanup actions where applicable. Notes must not assess stdout correctness.

---

## 8. Edge Cases and Safeguards

| Scenario | Risk | Mitigation |
|---|---|---|
| **Infinite Loop / Unhandled `EOF`** | Runner freezes indefinitely when shell encounters end-of-file. | Configurable wall-clock deadlines on startup and every command, including single-command scenarios; guaranteed process-group cleanup with bounded `SIGTERM` / `SIGKILL` escalation. |
| **Continuous / Excessive Output** | Unbounded capture exhausts memory or makes the report unwieldy. | Configurable retained-output limit (default: 1 MiB per session); discard excess while continuing bounded prompt detection and enforcing the original command deadline; label truncation in the report. |
| **Segfault on Built-in Command** | Shell crashes abruptly. | Exit code check on the process (`WIFSIGNALED`); logs crash signal (e.g., `SIGSEGV`) in the report and proceeds to next test. |
| **Student uses `GNU readline`** | Terminal escape codes pollute text and break readability. | Regex sanitizer strips all ANSI sequences from raw buffer before report generation. |
| **Student shell ignores `exit`** | Process remains alive after test concludes. | Guaranteed post-session cleanup sends `SIGTERM`, escalates to `SIGKILL` if needed, and reaps the direct child. |
| **Interleaved Stdin/Stdout** | Echoed input confused with student output. | Terminal echo disabled (`sh.setecho(False)`) at PTY initialization. |
