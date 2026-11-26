"""Transport contracts without opening sockets or running real model CLIs."""
import json
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


def test_cli_reads_stdin_uses_argv_and_deadline(tmp_path):
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


def test_missing_providers_file_means_no_models(tmp_path):
    from agent_seats.providers import ProviderRegistry
    registry = ProviderRegistry(tmp_path / "absent.json")
    assert registry.load() == {}
    assert registry.public() == []
