"""Independent CPU, memory, and help evidence cases (specification T3–T5)."""

from dataclasses import dataclass
from pathlib import Path

from cwushell_test.evidence import CaseEvidence
from cwushell_test.pty_session import Command, run_session


@dataclass(frozen=True)
class InformationScenario:
    """One exact input in one fresh session, without output expectations."""

    case_id: str
    suite_id: str
    title: str
    commands: tuple[Command, ...]

    def run(
        self,
        target: Path,
        *,
        timeout: float = 10.0,
        max_output_bytes: int = 1048576,
    ) -> CaseEvidence:
        """Retain the helper result directly, including faults and cleanup."""
        session = run_session(
            target,
            self.commands,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )
        return CaseEvidence(
            self.case_id, self.suite_id, self.title, self.commands, session
        )


def _case(suite: str, name: str, text: str) -> InformationScenario:
    return InformationScenario(f"{suite}.{name}", suite, text, (Command(text),))


CPU_CASES = (
    _case("T3", "c", "cpuinfo -c"),
    _case("T3", "t", "cpuinfo -t"),
    _case("T3", "n", "cpuinfo -n"),
    _case("T3", "ct", "cpuinfo -ct"),
    _case("T3", "c-t", "cpuinfo -c -t"),
    _case("T3", "cn", "cpuinfo -cn"),
    _case("T3", "c-n", "cpuinfo -c -n"),
    _case("T3", "tn", "cpuinfo -tn"),
    _case("T3", "t-n", "cpuinfo -t -n"),
    _case("T3", "ctn", "cpuinfo -ctn"),
    _case("T3", "c-t-n", "cpuinfo -c -t -n"),
)

MEMORY_CASES = (
    _case("T4", "t", "meminfo -t"),
    _case("T4", "u", "meminfo -u"),
    _case("T4", "c", "meminfo -c"),
    _case("T4", "tu", "meminfo -tu"),
    _case("T4", "t-u", "meminfo -t -u"),
    _case("T4", "tc", "meminfo -tc"),
    _case("T4", "t-c", "meminfo -t -c"),
    _case("T4", "uc", "meminfo -uc"),
    _case("T4", "u-c", "meminfo -u -c"),
    _case("T4", "tuc", "meminfo -tuc"),
    _case("T4", "t-u-c", "meminfo -t -u -c"),
)

HELP_CASES = (
    _case("T5", "manual", "manual"),
    _case("T5", "cpuinfo", "cpuinfo"),
    _case("T5", "cpuinfo-h", "cpuinfo -h"),
    _case("T5", "cpuinfo-help", "cpuinfo --help"),
    _case("T5", "meminfo", "meminfo"),
    _case("T5", "meminfo-h", "meminfo -h"),
    _case("T5", "meminfo-help", "meminfo --help"),
    _case("T5", "exit-h", "exit -h"),
    _case("T5", "exit-help", "exit --help"),
    _case("T5", "prompt-h", "prompt -h"),
    _case("T5", "prompt-help", "prompt --help"),
)
