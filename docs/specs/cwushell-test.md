# Specification: `cwushell-test` Test Harness

**Course:** CS 470 – Operating Systems (Fall 2026)  
**Target Assignment:** Lab 1 (`cwushell` Mini Shell)  
**Document Status:** Final Specification  

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
   - Python 3.8+ (including the standard-library `argparse` module for CLI parsing)
   - `pexpect` library (terminal interaction wrapper over POSIX pseudo-terminals)

4. **Temporary Working Directory:** Each independent test session runs in a fresh temporary working directory created with `tempfile.TemporaryDirectory`. Populate it with a fixed set of known fixture files for external-command scenarios, and record those fixtures in the report. Resolve the target binary and report output paths relative to the invocation directory before spawning the shell; execute the binary by its absolute path. Use consistent terminal settings and explicitly controlled environment values where needed for repeatable interactions. Clean up the temporary directory after process cleanup, including on timeout or exception.

---

## 3. Command-Line Interface (CLI)

The CLI must use Python’s standard-library `argparse`, including generated help, displayed defaults, and invalid-argument handling.

### 3.1 Synopsis & Usage
```bash
cwushell-test [-h] [-o OUTPUT] [target]
```
*(or via Python: `python3 cwushell_test.py [-h] [-o OUTPUT] [target]`)*

### 3.2 Arguments and Options

| Argument / Flag | Type | Default | Description |
|---|---|---|---|
| `target` | Positional (optional) | `./cwushell` | Path to the pre-compiled student shell binary to execute. |
| `-o`, `--output` | Option (`FILE`) | `cwushell_test_report.md` | Path for the generated Markdown test report. |
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
- **Design:** Each test case (Prompt, Exit, CPU Info, Memory Info, Help, Error Handling) must spawn its own dedicated instance of `cwushell`, perform its operations, capture output, and terminate. A crash or hanging process in Test 1 will not prevent Tests 2 through 6 from executing.

### 4.3 Strict Wall-Clock Timeouts
- Every interaction and session is bound by a strict timeout (e.g., 2.0 seconds per command or test block).
- If a student binary hangs (for instance, an unhandled `EOF` in a `while(1)` loop, or blocking on `wait()` for an orphaned child), the harness triggers an automatic interrupt, terminates the process, records a `TIMEOUT` status, and advances to the next test case.

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
   - *Design:* Commands are dispatched sequentially with micro-delays or prompt acknowledgments between commands, allowing student child processes to fork, execute, and exit cleanly.

4. **Line-Ending Normalization:**
   - *Problem:* PTY drivers translate `\n` to `\r\n` (CRLF).
   - *Design:* The helper normalizes all line endings to standard Unix `\n` for consistent report formatting.

5. **Guaranteed Cleanup with TERM/KILL Escalation:**
   - *Problem:* When student programs enter infinite loops or fork child processes without waiting, normal `close()` calls can leave processes running.
   - *Design:* Spawn the shell in an isolated process group and track its process group ID (`pgid`). In a guaranteed cleanup path (`finally` or a context manager), send `SIGTERM` to that group, allow a bounded grace period, then send `SIGKILL` to the group if necessary. Reap the direct child and close the PTY before removing the temporary working directory. Cleanup runs after normal completion, timeout, exceptions, and user interruption, including when the shell has exited but other group members remain. Record cleanup actions separately from the shell’s observed exit status or signal.
   - *Scope:* Process-group termination covers descendants that remain in that group. It does not guarantee termination of descendants that create a different process group or session, and reaping the direct child does not reap all descendants.

---

## 6. Test Suite Specifications

The harness executes six test suites organized by assignment feature. These suites collect evidence only; they do not assign points, check output correctness, or mark implementations as passing or failing. Independent scenarios use separate shell sessions; related command sequences share a session when needed to observe state changes.

| ID | Test Suite | Scenarios Recorded |
|---|---|---|
| **T1** | Prompt Management | Initial prompt; custom prompt via `prompt myprompt>`; reset via `prompt`; commands with multiple spaces/tabs. |
| **T2** | Process Termination | `exit 42`; `exit -10`; bare `exit` after a command that returns a failure status. Record the observed exit status without comparing it to an expected value. |
| **T3** | CPU Information | `cpuinfo -c`, `cpuinfo -t`, `cpuinfo -n`, `cpuinfo -ct`, and `cpuinfo -c -t`. |
| **T4** | Memory Information | `meminfo -t`, `meminfo -u`, `meminfo -c`, `meminfo -tu`, and `meminfo -tuc`. |
| **T5** | Help & Manual System | `manual`, `cpuinfo -h`, `cpuinfo --help`, and `meminfo -h`. Capture documentation output without judging its content or formatting. |
| **T6** | Error Handling & System Commands | `bogus_cmd_xyz`, `cpuinfo -z`, `meminfo -x`, and external commands `ls`, `pwd`, and `echo`. Record output and execution events without judging whether an error or usage message is correct. |

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
2. **Execution Summary Table:**
   - List each test case and its execution outcome, such as `COMPLETED`, `TIMEOUT`, `PROCESS_EXIT`, or `SIGNAL`.
   - These labels describe observed execution events only. `COMPLETED` does not imply correct output.
   - No grades, points, provisional scores, or `PASS`/`PARTIAL`/`FAIL` correctness statuses.
3. **Detailed Evidence Sections (Per Test Case):**
   - **Dispatched Commands:** Exact commands sent to the shell.
   - **Observed Terminal Output:** Captured terminal text from the student binary, cleaned of ANSI escapes and normalized to Unix line endings, formatted inside Markdown code blocks. PTY output may combine stdout and stderr; the report must identify it as terminal output rather than claim they are captured separately.
   - **Execution Notes:** Observed process exit status, terminating signal, timeout, incomplete command dispatch, and cleanup actions where applicable. Notes must not assess stdout correctness.

---

## 8. Edge Cases and Safeguards

| Scenario | Risk | Mitigation |
|---|---|---|
| **Infinite Loop / Unhandled `EOF`** | Runner freezes indefinitely when shell encounters end-of-file. | Hard 2.0s timeout per session; guaranteed process-group cleanup with bounded `SIGTERM` / `SIGKILL` escalation. |
| **Segfault on Built-in Command** | Shell crashes abruptly. | Exit code check on the process (`WIFSIGNALED`); logs crash signal (e.g., `SIGSEGV`) in the report and proceeds to next test. |
| **Student uses `GNU readline`** | Terminal escape codes pollute text and break readability. | Regex sanitizer strips all ANSI sequences from raw buffer before report generation. |
| **Student shell ignores `exit`** | Process remains alive after test concludes. | Guaranteed post-session cleanup sends `SIGTERM`, escalates to `SIGKILL` if needed, and reaps the direct child. |
| **Interleaved Stdin/Stdout** | Echoed input confused with student output. | Terminal echo disabled (`sh.setecho(False)`) at PTY initialization. |
