#!/usr/bin/env python3
"""Reusable PTY shell with modes selected by MOCK_MODE (no student code)."""

import os
import select
import signal
import sys
import time

mode = os.environ.get("MOCK_MODE", "normal")
prompt = "cwushell>"


def emit(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def show_prompt():
    if mode == "ansi":
        for part in ("\x1b[", "32m", prompt[:4], prompt[4:], "\x1b[0m"):
            emit(part)
    else:
        emit(prompt)


emit("startup evidence\n")
if mode == "startup_exit":
    sys.exit(17)
if mode == "hang":
    while True:
        select.select([], [], [], 3600)
if mode != "missing":
    show_prompt()


def input_lines():
    # Read exactly one line without TextIO prefetch hiding queued later input
    # from paced's descriptor-readiness check.
    line = bytearray()
    while True:
        value = os.read(0, 1)
        if not value:
            return
        line.extend(value)
        if value == b"\n":
            yield line.decode("utf-8")
            line.clear()


for line in input_lines():
    command = line.rstrip("\n")
    if command.startswith("child_"):
        ready_read, ready_write = os.pipe()
        descendant = os.fork()
        if descendant == 0:
            os.close(ready_read)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            if command.endswith("resist"):
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if "_tty" not in command:
                for descriptor in (0, 1, 2):
                    os.close(descriptor)
            os.write(ready_write, b"ready")
            os.close(ready_write)
            while True:
                signal.pause()
        os.close(ready_write)
        os.read(ready_read, 5)
        os.close(ready_read)
        emit(f"member {descendant} group {os.getpgid(descendant)}\n")
        if command.startswith("child_exit"):
            sys.exit(23)
        if command.startswith("child_crash"):
            os.kill(os.getpid(), signal.SIGSEGV)
        if command.startswith("child_hang"):
            while True:
                signal.pause()
        show_prompt()
        continue
    if command == "resist":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        emit("ignoring TERM\n")
        while True:
            signal.pause()
    if command == "exit":
        emit("goodbye\n")
        sys.exit(42)
    if command == "close_tty":
        for descriptor in (0, 1, 2):
            os.close(descriptor)
        while True:
            select.select([], [], [], 3600)
    if command == "crash":
        os.kill(os.getpid(), 11)
    if command == "slow":
        for part in ("partial ", "output\n"):
            emit(part)
            time.sleep(0.08)
    elif command == "stream":
        while True:
            emit("x" * 4096)
    elif command == "trickle":
        while True:
            emit("part\n")
            time.sleep(0.03)
    elif command == "flood":
        emit("x" * 100000 + "\n")
    elif command.startswith("prompt "):
        prompt = command[7:]
    elif command == "prompt":
        prompt = "cwushell>"
    elif command == "paced":
        emit("begin\n")
        # Any queued input before completion proves the harness interleaved commands.
        ready, _, _ = select.select([sys.stdin], [], [], 0.08)
        emit("INTERLEAVED\n" if ready else "end\n")
    elif command == "ansi":
        emit("\x1b]0;title\x07\x1b[31mmeaningful\x1b[0m\r\n")
    else:
        emit("student response\n")
    show_prompt()
