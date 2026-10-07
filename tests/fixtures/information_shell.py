#!/usr/bin/env python3
"""Synthetic command recorder and fault injection for information scenarios."""

import json
import os
import signal
import sys


def emit(text):
    sys.stdout.write(text)
    sys.stdout.flush()


mode = os.environ.get("INFORMATION_MODE", "record")
if mode == "startup_exit":
    emit("startup diagnostic\n")
    sys.exit(19)
if mode != "missing":
    emit("cwushell>")

for line in sys.stdin:
    command = line.removesuffix("\n")
    if mode in ("record", "faults", "missing"):
        emit(json.dumps([command, os.getpid(), os.getcwd()]) + "\n")
    if mode == "faults":
        if command == "cpuinfo -c":
            os.kill(os.getpid(), signal.SIGSEGV)
        if command == "cpuinfo -t":
            while True:
                emit("x" * 4096)
        if command == "cpuinfo -n":
            emit("x" * 100000)
    if mode == "help_events":
        if command.startswith("exit "):
            emit("help terminated\n")
            sys.exit(23)
        if command.startswith("prompt "):
            emit("changed> ")
            continue
    if mode == "arbitrary":
        emit("bananas = -???\nno units; no sections\n")
    if mode == "formatted":
        emit("\x1b[31m```\r\n# unusual | layout\x1b[0m\n")
    if mode == "diagnostic":
        sys.stderr.write("unsupported option; synthetic diagnostic\n")
        sys.stderr.flush()
    emit("cwushell>")
