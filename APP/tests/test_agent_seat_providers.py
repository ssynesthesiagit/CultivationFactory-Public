"""Transport contracts without opening sockets or running real model CLIs."""
import json
import os
import subprocess
import sys
import time
import pytest

from agent_seats.providers import complete
import agent_seats.providers as providers


def test_http_environment_key_and_vision_contract(monkeypatch):
    monkeypatch.setenv("FAKE_MODEL_KEY", "unit-test-placeholder")
    captured = {}
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return json.dumps({"choices": [{"message": {"content": '{"plan":[]}'}}], "usage": {"total_tokens": 7}}).encode()
    def request(req, timeout):
        captured.update(url=req.full_url, body=json.loads(req.data), headers=dict(req.header_items()), timeout=timeout)
        return Response()
    monkeypatch.setattr(providers.urllib.request, "urlopen", request)
    text, usage = complete({"kind": "openai_compatible", "base_url": "http://unit.test/v1", "model": "fake",
                            "key_env": "FAKE_MODEL_KEY", "timeout_s": 2, "vision": True}, "safe actor view", b"png")
    assert text == '{"plan":[]}' and usage == {"total_tokens": 7}
    assert captured["url"] == "http://unit.test/v1/chat/completions"
    assert captured["timeout"] == 2
    assert captured["headers"]["Authorization"] == "Bearer unit-test-placeholder"
    content = captured["body"]["messages"][0]["content"]
    assert content[0]["text"] == "safe actor view"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("high_fd", [
    False,
    pytest.param(True, marks=pytest.mark.skipif(sys.platform != "linux", reason="Linux pipe descriptor regression")),
])
def test_cli_reads_stdin_uses_argv_and_deadline(tmp_path, monkeypatch, high_fd):
    if high_fd:
        import fcntl
        import resource

        soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft_limit != resource.RLIM_INFINITY and soft_limit <= 1024:
            pytest.skip("Process descriptor limit is too low to exercise fd 1024.")
        popen = subprocess.Popen

        def open_high_stdout(*args, **kwargs):
            process = popen(*args, **kwargs)
            with process.stdout as stdout:
                fd = fcntl.fcntl(stdout, fcntl.F_DUPFD_CLOEXEC, 1024)
            process.stdout = os.fdopen(fd, "rb")
            return process

        monkeypatch.setattr(subprocess, "Popen", open_high_stdout)

    script = tmp_path / "fake seat.py"
    script.write_text("import json, sys\nprint(json.dumps([sys.argv[1:], sys.stdin.read()]))\n")
    argument = "literal with spaces; no shell"
    answer, usage = complete({"kind": "cli", "command": [sys.executable, str(script), argument],
                              "timeout_s": 3}, "actor prompt")
    assert json.loads(answer) == [[argument], "actor prompt"], answer
    assert usage is None, usage


def test_cli_timeout_is_reported_as_a_deadline(tmp_path):
    script = tmp_path / "slow.py"
    # EOF before exit must not bypass the deadline either.
    script.write_text("import os, time\nos.close(1)\ntime.sleep(10)\n")
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="deadline"):
        complete({"kind": "cli", "command": [sys.executable, str(script)], "timeout_s": 1}, "prompt")
    assert time.monotonic() - started < 5, "CLI did not return near its one-second deadline"

    import threading
    before = set(threading.enumerate())
    script.write_text("import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'])\ntime.sleep(5)\n")
    with pytest.raises(TimeoutError, match="deadline"):
        complete({"kind": "cli", "command": [sys.executable, str(script)], "timeout_s": 1}, "prompt")
    assert not [t for t in threading.enumerate() if t not in before and t.name.startswith("Thread-")], "reader thread survived timeout"


def test_missing_providers_file_means_no_models(tmp_path):
    from agent_seats.providers import ProviderRegistry
    registry = ProviderRegistry(tmp_path / "absent.json")
    assert registry.load() == {}
    assert registry.public() == []
