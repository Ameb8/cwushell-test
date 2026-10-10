"""Prompt, termination, and system-command evidence (specification T1/T2/T6)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping

from cwushell_test.evidence import CaseEvidence
from cwushell_test.fixtures import (
    CD_FIXTURES,
    EXPORT_ENVIRONMENT,
    EXTERNAL_FIXTURES,
    LISTING_FIXTURES,
    UNSET_ENVIRONMENT,
    Fixture,
)
from cwushell_test.pty_session import Action, Command, run_session

BUILTIN_COVERAGE_NOTE = (
    "These are representative internal-command observations; coverage does not "
    "include every Bash built-in, aliases, script sourcing, or job control, and "
    "does not establish full Bash compatibility. Standalone pwd and echo record "
    "behavior whether implemented internally or through external programs."
)


@dataclass(frozen=True)
class ShellScenario:
    """One fresh session, sharing input only for a state-observation sequence."""

    case_id: str
    suite_id: str
    title: str
    commands: tuple[Command, ...]
    fixtures: tuple[Fixture, ...] = ()
    controlled_environment: Mapping[str, str | None] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    terminal_type: Literal["dumb", "xterm"] = "dumb"

    def run(
        self,
        target: Path,
        *,
        timeout: float = 10.0,
        max_output_bytes: int = 1048576,
    ) -> CaseEvidence:
        """Use the shared lifecycle and retain all observations without judgments."""
        session = run_session(
            target,
            self.commands,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            fixtures=self.fixtures,
            controlled_environment=self.controlled_environment,
            terminal_type=self.terminal_type,
        )
        return CaseEvidence(
            self.case_id,
            self.suite_id,
            self.title,
            self.commands,
            session,
            notes=session.notes + self.notes,
        )


def _case(
    suite: str, name: str, text: str, *, title: str | None = None
) -> ShellScenario:
    return ShellScenario(f"{suite}.{name}", suite, title or text, (Command(text),))


PROMPT_CASES = (
    ShellScenario("T1.startup", "T1", "Initial prompt", ()),
    ShellScenario(
        "T1.prompt-reset",
        "T1",
        "Custom prompt and reset",
        (Command("prompt myprompt>", "myprompt>"), Command("prompt")),
    ),
    _case("T1", "spaces.cpu", "cpuinfo   -c   -t"),
    _case("T1", "tabs.cpu", "cpuinfo\t-c\t-t", title="Tab-separated CPU input"),
    _case("T1", "spaces.memory", "meminfo   -t   -u"),
    _case("T1", "tabs.memory", "meminfo\t-t\t-u", title="Tab-separated memory input"),
    _case("T1", "spaces.echo", "echo   alpha   beta"),
    _case("T1", "tabs.echo", "echo\talpha\tbeta", title="Tab-separated echo input"),
    ShellScenario(
        "T1.backspace-del",
        "T1",
        "Optional interactive usability: trailing-character deletion using DEL",
        (
            Command(
                "DEL backspace editing",
                actions=(
                    Action("type", b"echo hellx"),
                    Action("key", b"\x7f"),
                    Action("type", b"o"),
                    Action("enter", b"\n"),
                ),
            ),
            Command("echo keyboard_alive"),
        ),
        terminal_type="xterm",
        notes=(
            "Optional interactive-usability observation: assignment.md does not "
            "explicitly mandate cursor editing/history. Intended resulting line: "
            "echo hello (planned intent, not observed input or output).",
            "Canonical terminal-driver erase behavior may account for deletion; "
            "success alone does not establish a student-implemented line editor. "
            "A cleaned transcript alone cannot establish editing behavior. "
            "Unsupported input is recorded for manual review without grading.",
            "TERM=xterm is a controlled exception to TERM=dumb, compatible with "
            "xterm key sequences. DEL is sent literally with no VERASE remapping. "
            "No editing mode is forced; only normal launch echo suppression is used.",
        ),
    ),
    ShellScenario(
        "T1.backspace-bs",
        "T1",
        "Optional interactive usability: trailing-character deletion using BS",
        (
            Command(
                "BS backspace editing",
                actions=(
                    Action("type", b"echo hellx"),
                    Action("key", b"\x08"),
                    Action("type", b"o"),
                    Action("enter", b"\n"),
                ),
            ),
            Command("echo keyboard_alive"),
        ),
        terminal_type="xterm",
        notes=(
            "Optional interactive-usability observation: assignment.md does not "
            "explicitly mandate cursor editing/history. Intended resulting line: "
            "echo hello (planned intent, not observed input or output).",
            "Canonical terminal-driver erase behavior may account for deletion; "
            "success alone does not establish a student-implemented line editor. "
            "A cleaned transcript alone cannot establish editing behavior. "
            "Unsupported input is recorded for manual review without grading.",
            "TERM=xterm is a controlled exception to TERM=dumb, compatible with "
            "xterm key sequences. BS is sent literally with no VERASE remapping. "
            "No editing mode is forced; only normal launch echo suppression is used.",
        ),
    ),
    ShellScenario(
        "T1.cursor-insertion",
        "T1",
        "Optional interactive usability: left/right cursor movement and insertion",
        (
            Command(
                "Left twice, Right once, insert l",
                actions=(
                    Action("type", b"echo helo"),
                    Action("key", b"\x1b[D"),
                    Action("key", b"\x1b[D"),
                    Action("key", b"\x1b[C"),
                    Action("type", b"l"),
                    Action("enter", b"\n"),
                ),
            ),
            Command("echo keyboard_alive"),
        ),
        terminal_type="xterm",
        notes=(
            "Optional interactive-usability observation: assignment.md does not "
            "explicitly mandate cursor editing/history. Intended resulting line: "
            "echo hello (planned intent, not observed input or output). Left twice, "
            "Right once, then insert l before the final o.",
            "TERM=xterm is a controlled exception to TERM=dumb. Left uses CSI D "
            "(ESC [ D); Right uses CSI C (ESC [ C), sent literally without remapping. "
            "No editing mode is forced; only normal launch echo suppression is used. "
            "Terminal-driver behavior may contribute to editing.",
            "The cleaned transcript does not reconstruct the visual screen and "
            "alone cannot establish editing behavior. Inspect escaped raw cursor "
            "and redraw bytes alongside actual output. Unsupported input, including "
            "escape bytes treated as ordinary input, is recorded without grading.",
        ),
    ),
)

TERMINATION_CASES = (
    ShellScenario("T2.exit-42", "T2", "exit 42", (Command("exit 42", None),)),
    ShellScenario("T2.exit-negative", "T2", "exit -10", (Command("exit -10", None),)),
    ShellScenario("T2.exit", "T2", "Startup exit", (Command("exit", None),)),
    ShellScenario(
        "T2.true-exit",
        "T2",
        "/bin/true then exit",
        (Command("/bin/true"), Command("exit", None)),
    ),
    ShellScenario(
        "T2.false-exit",
        "T2",
        "/bin/false then exit",
        (Command("/bin/false"), Command("exit", None)),
    ),
)

SYSTEM_CASES = (
    _case("T6", "unknown", "bogus_cmd_xyz"),
    _case("T6", "cpu-invalid", "cpuinfo -z"),
    _case("T6", "memory-invalid", "meminfo -x"),
    ShellScenario("T6.ls", "T6", "ls", (Command("ls"),), LISTING_FIXTURES),
    _case("T6", "pwd", "pwd"),
    _case("T6", "echo", "echo fixture_alpha fixture_beta"),
    ShellScenario(
        "T6.cat",
        "T6",
        "cat source.txt",
        (Command("cat source.txt"),),
        EXTERNAL_FIXTURES,
    ),
    ShellScenario(
        "T6.cp",
        "T6",
        "cp source.txt copied.txt",
        (Command("cp source.txt copied.txt"),),
        EXTERNAL_FIXTURES,
    ),
    ShellScenario(
        "T6.rm",
        "T6",
        "rm removable.txt",
        (Command("rm removable.txt"),),
        EXTERNAL_FIXTURES,
    ),
    ShellScenario(
        "T6.cd",
        "T6",
        "Directory change then pwd",
        (Command("cd fixture_dir"), Command("pwd")),
        CD_FIXTURES,
        notes=(BUILTIN_COVERAGE_NOTE,),
    ),
    ShellScenario(
        "T6.export",
        "T6",
        "Export then printenv",
        (
            Command("export CWUSHELL_TEST_EXPORT=fixture_value"),
            Command("printenv CWUSHELL_TEST_EXPORT"),
        ),
        controlled_environment=EXPORT_ENVIRONMENT,
        notes=(BUILTIN_COVERAGE_NOTE,),
    ),
    ShellScenario(
        "T6.unset",
        "T6",
        "Unset then printenv",
        (Command("unset CWUSHELL_TEST_UNSET"), Command("printenv CWUSHELL_TEST_UNSET")),
        controlled_environment=UNSET_ENVIRONMENT,
        notes=(BUILTIN_COVERAGE_NOTE,),
    ),
)
