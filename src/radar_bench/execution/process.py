"""Bounded process execution for untrusted benchmark and provider commands."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess  # nosec B404 - argv is supplied as a validated array
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

CHUNK_BYTES = 64 * 1024
EXCERPT_BYTES = 4096


@dataclass(frozen=True)
class BoundedCapture:
    returncode: int | None
    output_bytes: int
    output_digest: str
    output_limit_exceeded: bool
    timed_out: bool
    excerpt: str
    payload: bytes = b""
    cleanup_error: str | None = None


def _terminate_tree(process: subprocess.Popen[bytes]) -> str | None:
    try:
        if os.name == "nt":
            completed = subprocess.run(  # nosec B603, B607 - fixed taskkill argv
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=10,
            )
            return None if completed.returncode == 0 else "TASKKILL_FAILED"
        killpg = getattr(os, "killpg", None)
        if not callable(killpg):
            return "PROCESS_GROUP_UNAVAILABLE"
        killpg(process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        return type(exc).__name__


def run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float,
    max_output_bytes: int,
    input_data: bytes | None = None,
) -> BoundedCapture:
    """Run an argv without unbounded pipes and kill its process group on limits."""

    if not argv or timeout <= 0 or max_output_bytes <= 0:
        raise ValueError("bounded process arguments and limits must be positive")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(  # nosec B603 - shell is explicitly disabled
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
        shell=False,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    streams: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    stream_hashers = {name: hashlib.sha256() for name in streams}
    stream_bytes = {name: 0 for name in streams}
    state = {"observed": 0, "overflow": False}
    lock = threading.Lock()

    def read_stream(name: str) -> None:
        pipe = getattr(process, name)
        if pipe is None:
            return
        try:
            while True:
                chunk = pipe.read(CHUNK_BYTES)
                if not chunk:
                    return
                stream_hashers[name].update(chunk)
                stream_bytes[name] += len(chunk)
                with lock:
                    state["observed"] += len(chunk)
                    remaining = max_output_bytes - len(streams["stdout"]) - len(streams["stderr"])
                    if remaining > 0:
                        streams[name].extend(chunk[:remaining])
                    if state["observed"] > max_output_bytes:
                        state["overflow"] = True
        finally:
            pipe.close()

    threads = [threading.Thread(target=read_stream, args=(name,), daemon=True) for name in streams]
    for thread in threads:
        thread.start()
    stdin = process.stdin
    if input_data is not None and stdin is not None:
        def write_input() -> None:
            try:
                stdin.write(input_data)
                stdin.close()
            except (BrokenPipeError, OSError):
                try:
                    stdin.close()
                except OSError:
                    pass

        threading.Thread(target=write_input, daemon=True).start()
    deadline = time.monotonic() + timeout
    timed_out = False
    cleanup_error: str | None = None
    while process.poll() is None:
        if state["overflow"]:
            cleanup_error = _terminate_tree(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            cleanup_error = _terminate_tree(process)
            break
        time.sleep(0.01)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        cleanup_error = cleanup_error or _terminate_tree(process)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cleanup_error = cleanup_error or "PROCESS_CLEANUP_TIMEOUT"
    for thread in threads:
        thread.join(timeout=10)
    combined = bytes(streams["stdout"] + streams["stderr"])
    aggregate = hashlib.sha256()
    for name in ("stdout", "stderr"):
        aggregate.update(name.encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(stream_bytes[name].to_bytes(16, "big"))
        aggregate.update(stream_hashers[name].digest())
    excerpt = combined[:EXCERPT_BYTES].decode("utf-8", errors="replace")
    return BoundedCapture(
        returncode=process.returncode,
        output_bytes=int(state["observed"]),
        output_digest="sha256:" + aggregate.hexdigest(),
        output_limit_exceeded=bool(state["overflow"]),
        timed_out=timed_out,
        excerpt=excerpt,
        payload=combined,
        cleanup_error=cleanup_error,
    )


__all__ = ["BoundedCapture", "run_bounded"]
