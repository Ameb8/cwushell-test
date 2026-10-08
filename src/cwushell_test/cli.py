"""CLI configuration and entry point for the CWUShell evidence harness."""

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


@dataclass(frozen=True)
class Configuration:
    """Validated invocation paths and interaction limits for the runner."""

    target: Path
    output: Path
    timeout: float
    max_output_bytes: int
    report_format: str = "markdown"


def positive_seconds(value: str) -> float:
    """Parse the finite, positive interaction deadline."""
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive, finite number") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive, finite number")
    return seconds


def positive_bytes(value: str) -> int:
    """Parse the positive raw output capture limit."""
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if count <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return count


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cwushell-test",
        description="Configure CWUShell evidence collection for manual review.",
        epilog="Collect T1–T6 execution evidence for manual review, without scoring.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "target", nargs="?", default="./cwushell", help="Pre-compiled shell binary"
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=argparse.SUPPRESS,
        help="Report path (default: cwushell_test_report.md, or .html for HTML)",
    )
    parser.add_argument(
        "--report-format",
        choices=("markdown", "html"),
        default="markdown",
        help="Report format; HTML provides collapsible suites, cases, and sections",
    )
    parser.add_argument(
        "--timeout",
        type=positive_seconds,
        default=10.0,
        metavar="SECONDS",
        help="Positive, finite deadline for startup and each command",
    )
    parser.add_argument(
        "--max-output-bytes",
        type=positive_bytes,
        default=1048576,
        metavar="BYTES",
        help="Positive retained raw terminal-output byte limit per session",
    )
    return parser


def validate_configuration(args: argparse.Namespace) -> Configuration:
    """Resolve paths before any runner changes directory; never execute the target."""
    if sys.platform != "linux":
        raise ValueError("Linux is required; use a native Linux host, VM, or WSL")
    if sys.version_info < (3, 14):
        raise ValueError("Python 3.14+ is required; use task setup or Python 3.14+")
    target = Path(args.target).resolve()
    extension = "html" if args.report_format == "html" else "md"
    output = Path(
        getattr(args, "output", f"cwushell_test_report.{extension}")
    ).resolve()
    if not target.exists():
        raise ValueError(
            f"target does not exist: {target}; compile it externally first"
        )
    if not target.is_file():
        raise ValueError(f"target must be a regular executable file: {target}")
    if not os.access(target, os.X_OK):
        raise ValueError(
            f"target is not executable: {target}; check execute permissions"
        )
    return Configuration(
        target, output, args.timeout, args.max_output_bytes, args.report_format
    )


def run(config: Configuration) -> int:
    """Run all suites and write evidence using the validated invocation paths."""
    from cwushell_test.runner import execute

    return execute(config)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        config = validate_configuration(args)
        return run(config)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"cwushell-test: {exc}", file=sys.stderr)
        return 1
