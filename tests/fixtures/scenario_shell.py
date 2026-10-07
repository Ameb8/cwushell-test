#!/usr/bin/env python3
"""Synthetic T1/T2/T6 recorder with state changes and deliberate deviations."""

import json
import os
import select
import shutil
import signal
import sys
from pathlib import Path


def emit(text):
    sys.stdout.write(text)
    sys.stdout.flush()


mode = os.environ.get("SCENARIO_MODE", "record")
if log_path := os.environ.get("SCENARIO_LOG"):
    with open(log_path, "a") as log:
        log.write(json.dumps([os.getpid(), os.getpgrp(), os.getcwd()]) + "\n")
emit(
    "INITIAL "
    + json.dumps(
        {
            "pid": os.getpid(),
            "cwd": os.getcwd(),
            "export": os.environ.get("CWUSHELL_TEST_EXPORT"),
            "unset": os.environ.get("CWUSHELL_TEST_UNSET"),
            "fixture_dir": (
                list(Path("fixture_dir").iterdir())
                if Path("fixture_dir").exists()
                else None
            ),
        }
    )
    + "\n"
)
if mode == "startup_exit":
    sys.exit(19)
prompt = "cwushell>"
status = 0
if mode not in ("missing", "integration"):
    emit(prompt)

for line in sys.stdin:
    command = line.removesuffix("\n")
    # Avoid synchronizing on a requested prompt printed as part of this record.
    # JSON decoding still returns the exact received command.
    received = json.dumps([command, os.getpid(), os.getcwd()]).replace(">", "\\u003e")
    emit("RECEIVED " + received + "\n")
    if mode == "integration":
        if command == "prompt myprompt>":
            emit("unexpected> diagnostic\n")
            continue
        if command == "meminfo   -t   -u":
            os.kill(os.getpid(), signal.SIGSEGV)
        if command == "cpuinfo -c":
            while True:
                emit("x" * 4096)
        if command == "cpuinfo   -c   -t":
            emit("bounded flood prefix\n" + "x" * 16384 + "\n")
    if mode == "crash":
        os.kill(os.getpid(), signal.SIGSEGV)
    if mode == "hang":
        while True:
            emit("x" * 4096)
    if mode == "mismatch":
        emit("unexpected> diagnostic\n")
        continue
    if mode == "deviation":
        emit("arbitrary diagnostic; no promised file effect\n")
        if command.startswith("exit"):
            sys.exit(7)
        emit(prompt)
        continue
    if mode == "ignored_exit" and command.startswith("exit"):
        emit("exit ignored\ncwushell>")
        continue
    if command == "prompt myprompt>":
        prompt = "myprompt>"
    elif command == "prompt":
        prompt = "cwushell>"
    elif command in ("exit -h", "exit --help"):
        # Arbitrary documentation output remains evidence, without predicates.
        emit("\x1b[31modd ``` documentation | output\x1b[0m\n")
    elif command.startswith("exit"):
        fields = command.split()
        sys.exit(int(fields[1]) % 256 if len(fields) > 1 else status)
    elif command == "/bin/true":
        status = 0
    elif command == "/bin/false":
        status = 1
    elif command == "cat source.txt":
        emit(Path("source.txt").read_text())
    elif command == "cp source.txt copied.txt":
        shutil.copyfile("source.txt", "copied.txt")
        if mode in ("cleanup_effect", "integration"):

            def terminate(signum, frame):
                Path("copied.txt").write_bytes(b"cleanup contents\n")
                sys.exit(0)

            signal.signal(signal.SIGTERM, terminate)
    elif command == "rm removable.txt":
        Path("removable.txt").unlink()
    elif command == "cd fixture_dir":
        os.chdir("fixture_dir")
    elif command == "pwd":
        emit(os.getcwd() + "\n")
    elif command == "export CWUSHELL_TEST_EXPORT=fixture_value":
        os.environ["CWUSHELL_TEST_EXPORT"] = "fixture_value"
    elif command == "unset CWUSHELL_TEST_UNSET":
        os.environ.pop("CWUSHELL_TEST_UNSET", None)
    elif command.startswith("printenv "):
        value = os.environ.get(command.split()[1])
        emit(f"ENVIRONMENT {json.dumps(value)}\n")
    elif command == "echo":
        emit("\n")
    else:
        emit("synthetic output for " + json.dumps(command) + "\n")
    # Detect input arriving before the preceding command's returning prompt.
    if select.select([sys.stdin], [], [], 0)[0]:
        emit("EARLY INPUT\n")
    emit(prompt)
