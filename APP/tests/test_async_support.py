"""ASGI harness must finish thread work when socket send() is refused."""
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]  # the child imports tests.*, whatever directory pytest runs from


def test_thread_completion_and_executor_shutdown_when_socket_send_is_refused():
    # A child-process deadline catches both a waiting request and Runner.close;
    # it also prevents a regression from stranding the whole pytest invocation.
    result = subprocess.run([sys.executable, "-c", """
import asyncio
from tests.asyncio_wakeup import WriteWakeupEventLoop
from tests.test_asyncio_wakeup import _SendRefusingSocket

class SendRefusedLoop(WriteWakeupEventLoop):
    def __init__(self):
        super().__init__()
        self._csock = _SendRefusingSocket(self._csock)

async def exercise():
    assert await asyncio.to_thread(lambda: 42) == 42

with asyncio.Runner(loop_factory=SendRefusedLoop) as runner:
    runner.run(exercise())
print('completed')
"""], cwd=APP_DIR, capture_output=True, text=True, timeout=5, check=True)
    assert result.stdout == "completed\n"
