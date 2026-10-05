"""CLI configuration seam for the CWUShell evidence harness."""

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
        epilog=(
            "CLI skeleton only: execution and reporting are not implemented. "
            "A valid invocation exits 1 without launching the target or writing a report."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "target", nargs="?", default="./cwushell", help="Pre-compiled shell binary"
    )
    parser.add_argument(
        "-o", "--output", default="cwushell_test_report.md", help="Markdown report path"
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
    output = Path(args.output).resolve()
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
    return Configuration(target, output, args.timeout, args.max_output_bytes)


def run(config: Configuration) -> int:
    """Temporary runner seam; later tasks supply execution and reporting."""
    print(
        f"cwushell-test: configuration validated for {config.target}. "
        "Execution and reporting are not implemented; "
        "no student session was launched and no report was written.",
        file=sys.stderr,
    )
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        config = validate_configuration(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"cwushell-test: {exc}", file=sys.stderr)
        return 1
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
