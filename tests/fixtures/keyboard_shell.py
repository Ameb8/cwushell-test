#!/usr/bin/env python3
"""Byte-oriented synthetic keyboard behaviors without readline or student code."""

import json
import os
import signal
import termios
import time

mode = os.environ.get("KEYBOARD_MODE", "edit")
settings = termios.tcgetattr(0)
if mode in ("verase-bs", "canonical-bs"):
    settings[6][termios.VERASE] = b"\x08"
elif mode == "verase-del":
    settings[6][termios.VERASE] = b"\x7f"
elif mode not in ("canonical", "canonical-bs"):
    settings[3] &= ~(termios.ICANON | termios.ECHO)
    settings[6][termios.VMIN] = 1
    settings[6][termios.VTIME] = 0
termios.tcsetattr(0, termios.TCSANOW, settings)


def emit(data):
    os.write(1, data)


if mode == "startup_exit":
    emit(b"startup evidence\n")
    raise SystemExit(19)
if mode != "missing":
    emit(b"cwushell>")
if mode == "blocked":
    while True:
        time.sleep(1)

while True:
    incoming = bytearray()
    while True:
        value = os.read(0, 1)
        if not value:
            raise SystemExit(0)
        incoming.extend(value)
        if mode == "key_exit" and value in (b"\x7f", b"\x08"):
            emit(
                b"\nBYTES " + bytes(incoming).hex().encode() + b"\nkey exit evidence\n"
            )
            raise SystemExit(7)
        if value == b"\n":
            break
    edited = bytearray()
    for value in incoming[:-1]:
        if mode == "edit" and value in (127, 8):
            if edited:
                edited.pop()
            # Raw editing evidence remains inspectable even with launch echo off.
            emit(b"\x08 \x08")
        else:
            edited.append(value)
    emit(b"\nBYTES " + bytes(incoming).hex().encode() + b"\n")
    emit(b"LINE " + json.dumps(bytes(edited).decode()).encode() + b"\n")
    if mode == "exit":
        raise SystemExit(7)
    if mode == "crash":
        os.kill(os.getpid(), signal.SIGSEGV)
    if mode == "timeout":
        emit(b"partial evidence\n")
        while True:
            time.sleep(1)
    if bytes(edited).startswith(b"echo "):
        emit(bytes(edited)[5:] + b"\n")
    emit(b"\x1b[31mRAW\x1b[0m\r\x08\xff </code><script>hostile</script> ```\n")
    emit(b"cwushell>")
