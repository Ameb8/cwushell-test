# Specification: `cwushell-test` Test Harness

**Course:** CS 470 – Operating Systems (Fall 2026)  
**Target Assignment:** Lab 1 (`cwushell` Mini Shell)  
**Document Status:** Final Specification  

---

## 1. Overview and Objectives

The `cwushell-test` program is an automated testing harness designed to evaluate student implementations of the `cwushell` command interpreter against the requirements and rubric specified in [Operating_Systems_Lab_1_Fall_2026.md](file:///Users/pattycrowder/Documents/Alex_Documents/cwu/470-TA/lab-1/Operating_Systems_Lab_1_Fall_2026.md).

### Primary Objectives
- **Automated Execution:** Execute a standardized test suite against a pre-compiled `cwushell` binary without requiring manual input entry.
- **Fault-Tolerant Isolation:** Run every rubric test case in an independent process session to prevent crashes, memory faults, or deadlocks in one test from contaminating others.
- **Defensive Timeout Enforcement:** Enforce strict wall-clock time limits on all interactions to neutralize infinite loops, unhandled EOF hangs, and deadlocks.
- **Readable Markdown Reporting:** Generate an evidence-backed Markdown report per test run that displays the exact student outputs alongside rubric criteria for rapid verification and grading.

---

## 2. Environment and Assumptions

1. **Target Platform:** Linux environment (native Linux host, VM, or WSL). The harness relies on standard Linux kernel behaviors and virtual filesystems (e.g., `/proc/cpuinfo`, `/proc/meminfo`) expected by the assignment.
2. **Pre-Built Binaries:** The harness tests an already compiled binary executable named `cwushell`. The path to the binary can be passed via command-line argument (defaulting to `./cwushell`). Build system operations (e.g., `make`, `gcc`) are handled externally prior to running this harness.
3. **Dependencies:**
   - Python 3.8+
   - `pexpect` library (terminal interaction wrapper over POSIX pseudo-terminals)

---

## 3. Core Architectural Principles

### 3.1 Pseudo-Terminal (PTY) Interaction via `pexpect`
Standard I/O redirection using traditional pipes (`subprocess.PIPE`) causes the C standard I/O library to switch from line buffering to block buffering. Because student shells typically print prompts (such as `cwushell>`) without a trailing newline (`\n`), piped harnesses hang waiting for a buffer flush.

`cwushell-test` must execute the target binary inside an emulated POSIX Pseudo-Terminal (PTY) using Python's `pexpect`. This guarantees:
- `isatty()` returns `true` inside the student process.
- Prompts and diagnostic outputs flush immediately to the harness.
- Shell behaviors accurately mirror real-world user terminal interaction.

### 3.2 Session Isolation (Per-Case Independence)
Student shells are prone to segmentation faults, signal misconfigurations, or command execution stalls. 
- **Rule:** Under no circumstances should the entire test battery run within a single ongoing shell instance.
- **Design:** Each test case (Prompt, Exit, CPU Info, Memory Info, Help, Error Handling) must spawn its own dedicated instance of `cwushell`, perform its operations, capture output, and terminate. A crash or hanging process in Test 1 will not prevent Tests 2 through 6 from executing.

### 3.3 Strict Wall-Clock Timeouts
- Every interaction and session is bound by a strict timeout (e.g., 2.0 seconds per command or test block).
- If a student binary hangs (for instance, an unhandled `EOF` in a `while(1)` loop, or blocking on `wait()` for an orphaned child), the harness triggers an automatic interrupt, terminates the process, records a `TIMEOUT` status, and advances to the next test case.

---

## 4. Hardened PTY Helper: Purpose and Design

To eliminate common compatibility traps found in student-written shells, all interactions with the shell binary must be routed through a dedicated execution helper.

### 4.1 Responsibilities and Design Goals

1. **Disabling Local Terminal Echo:**
   - *Problem:* PTY devices echo all sent keystrokes back to stdout by default. If the harness sends `cpuinfo -c`, the PTY echoes `cpuinfo -c\r\n`. Any naive check for `cpuinfo` in the captured text would mistakenly flag the echoed input as valid output.
   - *Design:* The helper explicitly disables echo on the spawned terminal immediately after launch (`setecho(False)`).

2. **ANSI Escape Sequence Sanitization:**
   - *Problem:* Students utilizing GNU `readline` or custom prompt styling output terminal color codes and cursor movement escape sequences (e.g., `\x1b[0m`, `\x1b[K`).
   - *Design:* The helper applies regex sanitization to strip all ANSI terminal sequences before storing or analyzing captured text.

3. **Synchronized Command Pacing (Step-and-Wait):**
   - *Problem:* Feeding multiple commands simultaneously into stdin risks input interleaving, buffer overflow, or child processes stealing subsequent commands from the parent shell.
   - *Design:* Commands are dispatched sequentially with micro-delays or prompt acknowledgments between commands, allowing student child processes to fork, execute, and exit cleanly.

4. **Line-Ending Normalization:**
   - *Problem:* PTY drivers translate `\n` to `\r\n` (CRLF).
   - *Design:* The helper normalizes all line endings to standard Unix `\n` to simplify reporting and comparison.

5. **Guaranteed Process Tree Termination (Zombie Reaping):**
   - *Problem:* When student programs enter infinite loops or fork child processes without waiting, normal `close()` calls leave orphan processes running.
   - *Design:* The helper tracks the process group ID (`pgid`) and issues `SIGTERM` / `SIGKILL` to the entire process group upon completion or timeout, ensuring zero leftover background processes.

---

## 5. Test Suite Specifications

The harness executes six isolated test suites, mapping directly to the assignment rubric (10 points total):

| ID | Test Suite | Rubric Item | Points | Key Scenarios Tested |
|---|---|---|---|---|
| **T1** | Prompt Management | Prompt Command | 1.0 | <ul><li>Verify initial prompt matches `cwushell>`</li><li>Set custom prompt via `prompt myprompt>`</li><li>Reset to default via `prompt`</li><li>Verify whitespace tolerance (multiple spaces/tabs)</li></ul> |
| **T2** | Process Termination | Exit Command | 1.0 | <ul><li>Exit with specific numeric argument (`exit 42`) -> verify process exit status == 42</li><li>Exit with negative status (`exit -10`)</li><li>Exit with last command status (`exit` after failed command)</li></ul> |
| **T3** | CPU Information | `cpuinfo` Command | 3.0 | <ul><li>Clock frequency (`cpuinfo -c`) [1 pt]</li><li>CPU type / brand (`cpuinfo -t`) [1 pt]</li><li>Number of cores (`cpuinfo -n`) [1 pt]</li><li>Combined switches (`cpuinfo -ct`, `cpuinfo -c -t`)</li></ul> |
| **T4** | Memory Information | `meminfo` Command | 3.0 | <ul><li>Total RAM in bytes (`meminfo -t`) [1 pt]</li><li>Used RAM in bytes (`meminfo -u`) [1 pt]</li><li>L2 cache size/core in bytes (`meminfo -c`) [1 pt]</li><li>Combined switches (`meminfo -tu`, `meminfo -tuc`)</li></ul> |
| **T5** | Help & Manual System | Help Mechanism | 1.0 | <ul><li>Global help documentation (`manual`)</li><li>Command-specific manual page (`cpuinfo -h`, `cpuinfo --help`, `meminfo -h`)</li><li>Verification that man-page style formatting is present</li></ul> |
| **T6** | Error Handling & System Commands | Error Handling | 1.0 | <ul><li>Non-existent command execution (`bogus_cmd_xyz`) produces error without crashing</li><li>Invalid switches (`cpuinfo -z`, `meminfo -x`) produce warning/usage message</li><li>Standard external command execution (`ls`, `pwd`, `echo`)</li></ul> |

---

## 6. Output Reporting Specification

### 6.1 Report Generation
Running `cwushell-test` automatically generates a single formatted Markdown report (e.g., `cwushell_test_report.md` or `report_<binary_name>.md`).

### 6.2 Markdown Report Structure
The generated report must contain:

1. **Header & Execution Metadata:**
   - Date and time of execution
   - Path to evaluated binary
   - Target architecture and OS kernel version
2. **Executive Scorecard Table:**
   - Summary table listing each rubric category, maximum points, provisional earned points, and status (`PASS`, `PARTIAL`, `FAIL`, `TIMEOUT`).
   - Total calculated score out of 10.0 points.
3. **Detailed Evidence Sections (Per Test Case):**
   - **Dispatched Commands:** Exact commands sent to the shell.
   - **Observed Terminal Output:** Verbatim captured text from the student binary (cleaned of ANSI escapes, formatted inside markdown code blocks).
   - **Evaluation Criteria & Notes:** Specific indicators verified (e.g., exit code return values, expected unit strings such as bytes or GHz, presence of usage warnings).

---

## 7. Edge Cases and Safeguards

| Scenario | Risk | Mitigation |
|---|---|---|
| **Infinite Loop / Unhandled `EOF`** | Runner freezes indefinitely when shell encounters end-of-file. | Hard 2.0s timeout per session; automatic `os.killpg(pgid, SIGKILL)` on timeout. |
| **Segfault on Built-in Command** | Shell crashes abruptly. | Exit code check on the process (`WIFSIGNALED`); logs crash signal (e.g., `SIGSEGV`) in the report and proceeds to next test. |
| **Student uses `GNU readline`** | Terminal escape codes pollute text and break readability. | Regex sanitizer strips all ANSI sequences from raw buffer before report generation. |
| **Student shell ignores `exit`** | Process remains alive after test concludes. | Explicit post-session cleanup forcibly reaps child process if alive. |
| **Interleaved Stdin/Stdout** | Echoed input confused with student output. | Terminal echo disabled (`sh.setecho(False)`) at PTY initialization. |
