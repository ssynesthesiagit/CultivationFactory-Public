"""Bounded response transport shared by creation AI and combat-seat providers.

HTTP clients stay with their callers: creation's injected httpx client forbids
redirects/proxy environment; seats retain urllib's owner-configured egress.
The shared interface consumes injectable byte chunks, accepts each caller's
limit/error, and neither retries nor interprets completion/usage envelopes.
Only the two seat protocols share the urllib JSON adapter.
"""
from collections.abc import Iterable
import json
import os
import queue
import select
import threading
import shutil
import subprocess
import tempfile
import time
import urllib.request


def bounded_response(chunks: Iterable[bytes], *, limit: int, too_large: Exception) -> bytes:
    """Collect at most limit bytes; stop on the first overflowing chunk."""
    parts = []
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > limit:
            raise too_large
        parts.append(chunk)
    return b"".join(parts)


def validate_cli_argv(argv) -> None:
    """Accept an argv array only, with authentication owned by the CLI."""
    if (not isinstance(argv, (list, tuple)) or not argv
            or not all(isinstance(arg, str) and "\0" not in arg for arg in argv) or not argv[0]):
        raise ValueError("CLI command must be a nonempty argv array reading stdin.")
    if any(arg.partition("=")[0] in {"--api-key", "--token", "--access-token", "--password"} for arg in argv):
        raise ValueError("CLI credentials must come from its account configuration or environment.")


def cli_completion(argv, prompt: str, *, timeout: float, limit: int = 1024 * 1024, cwd=None) -> str:
    """Send a prompt on stdin, bound stdout as it arrives, and never log stderr.

    Spool input separately so an early or chatty reply cannot deadlock on a
    full stdin pipe. The same deadline covers reads and process exit.
    """
    validate_cli_argv(argv)
    executable = shutil.which(argv[0])
    if not executable:
        raise FileNotFoundError("The model CLI is not installed or is not on PATH.")
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("The model CLI deadline expired.")
        return seconds

    with tempfile.TemporaryFile() as stdin:
        stdin.write(prompt.encode("utf-8"))
        stdin.seek(0)
        with subprocess.Popen(argv, executable=os.path.abspath(executable), stdin=stdin,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=cwd) as process:
            stopped = threading.Event()
            try:
                # Pipe handles are not selectable on Windows. A bounded queue
                # applies backpressure while the caller enforces the deadline.
                output = queue.Queue(maxsize=1)
                def read_pipe():
                    try:
                        while True:
                            if os.name == "nt":
                                import ctypes
                                import msvcrt
                                available = ctypes.c_ulong()
                                handle = msvcrt.get_osfhandle(process.stdout.fileno())
                                if not ctypes.windll.kernel32.PeekNamedPipe(
                                    ctypes.c_void_p(handle), None, 0, None, ctypes.byref(available), None
                                ):
                                    chunk = b""
                                elif not available.value:
                                    if stopped.wait(0.05):
                                        return
                                    continue
                                else:
                                    chunk = os.read(process.stdout.fileno(), min(available.value, 64 * 1024))
                            else:
                                if not select.select([process.stdout], [], [], 0.05)[0]:
                                    if stopped.is_set():
                                        return
                                    continue
                                chunk = os.read(process.stdout.fileno(), 64 * 1024)
                            while not stopped.is_set():
                                try:
                                    output.put(chunk, timeout=0.1)
                                    break
                                except queue.Full:
                                    continue
                            if not chunk or stopped.is_set():
                                return
                    except OSError as exc:
                        if not stopped.is_set():
                            try:
                                output.put(exc, timeout=0.1)
                            except queue.Full:
                                pass

                reader = threading.Thread(target=read_pipe, daemon=True)
                reader.start()
                def chunks():
                    while True:
                        try:
                            chunk = output.get(timeout=remaining())
                        except queue.Empty:
                            raise TimeoutError("The model CLI deadline expired.") from None
                        if isinstance(chunk, OSError):
                            raise chunk
                        if not chunk:
                            return
                        yield chunk

                raw = bounded_response(chunks(), limit=limit, too_large=ValueError("The model CLI answer is too large."))
                if process.wait(timeout=remaining()):
                    raise ValueError("The model CLI exited without an answer. Check that you are signed in.")
            except subprocess.TimeoutExpired:
                raise TimeoutError("The model CLI deadline expired.") from None
            finally:
                stopped.set()
                if process.returncode is None:
                    process.kill()
                reader.join()
            try:
                return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            except UnicodeDecodeError:
                raise ValueError("The model CLI answer is not UTF-8 text.") from None


def urllib_json(request, timeout, *, too_large: str):
    """Read one seat reply, preserving urllib errors, egress and close timing."""
    limit = 1024 * 1024
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(limit + 1)
    return json.loads(bounded_response((raw,), limit=limit, too_large=ValueError(too_large)))
