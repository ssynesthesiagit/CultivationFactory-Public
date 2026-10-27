"""Admission regressions: tiny children only, never combat or model services."""
import json
from contextlib import nullcontext
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from tests import queue_guard

APP = Path(__file__).resolve().parents[1]
MESSAGE = (
    "Run tests through the queue. Write the test files or node ids, one per line, to a list file "
    "under /var/tmp, then: cd APP && python3 /var/tmp/auto-tools/heavyq.py run --label <LANE>-<what> -- "
    "<venv python> /var/tmp/auto-audit/sweeprun/r25chunk.py <list file> <basetemp under /var/tmp>"
)
ADMISSION = ("HEAVY_QUEUE_INNER", "CI", "GITHUB_ACTIONS", "CF_ALLOW_DIRECT_TESTS")
DIRECT = "0::/user.slice/lanes.slice/lane.scope\n"
OWNER = "0::/user.slice/user" "@1000.service/app.slice/app-ghostty.scope\n"
CONTEXTS = [
    (DIRECT, {}, False),
    (DIRECT, {"HEAVY_QUEUE_INNER": "1", "CI": "true"}, False),
    (DIRECT, {"CI": "1"}, False),
    (DIRECT, {"GITHUB_ACTIONS": "1"}, False),
    (DIRECT, {"GITHUB_ACTIONS": "false"}, False),
    (DIRECT, {"GITHUB_ACTIONS": "true"}, False),
    ("0::/user.slice/pueued.service\n", {}, True),
    ("0::/user.slice/heavyq-abc.scope\n", {}, True),
    (None, {}, False),
    (None, {"GITHUB_ACTIONS": "true"}, True),
    (DIRECT, {"CF_ALLOW_DIRECT_TESTS": "1"}, False),
    (OWNER, {"CF_ALLOW_DIRECT_TESTS": "1"}, True),
    (OWNER, {"GITHUB_ACTIONS": "true"}, True),
    (OWNER, {}, False),
    (None, {"CF_ALLOW_DIRECT_TESTS": "1"}, True),
    ("0::/user.slice/lanes.slice/pueued.service\n", {"CF_ALLOW_DIRECT_TESTS": "1"}, True),
    ("0::/user.slice/lanes.slice/heavyq-abc.scope\n", {"GITHUB_ACTIONS": "true"}, True),
]


def probe(tmp_path, entry, cgroup, admission):
    env = {k: v for k, v in os.environ.items()
           if k not in (*ADMISSION, "PYTEST_ADDOPTS", "PYTEST_PLUGINS")}
    env.update(admission, PYTHONPATH=str(APP), PYTHONDONTWRITEBYTECODE="1",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    # Actual queued children inherit an admitted cgroup. Model the direct shell
    # in the child; production exposes no environment knob for cgroup fixtures.
    driver = (
        "from pathlib import Path\n"
        "from tests import queue_guard\n"
        f"queue_guard.DIRECT_LOG = Path({str(tmp_path / 'direct.log')!r})\n"
        "original = Path.read_text\n"
        "def read(self, *a, **kw):\n"
        "    if str(self) == '/proc/self/cgroup':\n"
        + ("        raise OSError('unavailable')\n" if cgroup is None
           else f"        return {cgroup!r}\n")
        + "    return original(self, *a, **kw)\n"
        "Path.read_text = read\n" + entry
    )
    return subprocess.run([sys.executable, "-c", driver], cwd=APP, env=env,
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("cgroup,admission,allowed", CONTEXTS)
@pytest.mark.parametrize("entry", ["pytest_module", "pytest_main", "capture"])
def test_entry_points(tmp_path, cgroup, admission, allowed, entry):
    trivial = tmp_path / "test_trivial.py"
    trivial.write_text("def test_trivial():\n    assert True\n")
    args = ["-q", "-p", "no:cacheprovider", "-p", "tests.conftest",
            "--confcutdir=" + str(tmp_path), "--basetemp=" + str(tmp_path / "inner"), str(trivial)]
    if entry == "capture":
        code = "from tests.wall_height_stock_capture import main; main()"
    elif entry == "pytest_main":
        code = f"import pytest, sys; sys.exit(pytest.main({args!r}))"
    else:
        code = f"import runpy, sys; sys.argv = ['pytest', *{args!r}]; runpy.run_module('pytest', run_name='__main__')"
    result = probe(tmp_path, code, cgroup, admission)
    output = result.stdout + result.stderr
    if not allowed:
        assert result.returncode == (1 if entry == "capture" else 4), output
        assert MESSAGE in output
        assert "1 passed" not in output
    elif entry == "capture":
        assert "IndexError" in result.stderr, output
        assert MESSAGE not in output
    else:
        assert result.returncode == 0, output
        assert "1 passed" in output
    if allowed and admission.get("CF_ALLOW_DIRECT_TESTS") == "1" and "lanes.slice" not in (cgroup or ""):
        receipt = (tmp_path / "direct.log").read_text()
        assert len(receipt.splitlines()) == 1
        assert "CF_ALLOW_DIRECT_TESTS=1" in receipt and "pid=" in receipt
    else:
        assert not (tmp_path / "direct.log").exists()


def test_exact_refusal_message():
    assert queue_guard.QUEUE_MESSAGE == MESSAGE


@pytest.mark.parametrize("cgroup,admission,allowed", CONTEXTS)
def test_cgroup_read_once(tmp_path, monkeypatch, cgroup, admission, allowed):
    for key in ADMISSION:
        monkeypatch.delenv(key, raising=False)
    for key, value in admission.items():
        monkeypatch.setenv(key, value)
    reads = []

    def read(path, **kwargs):
        assert str(path) == "/proc/self/cgroup"
        reads.append(path)
        if cgroup is None:
            raise OSError("cgroup unavailable")
        return cgroup

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(queue_guard, "DIRECT_LOG", tmp_path / "direct.log")
    if allowed:
        queue_guard.require_test_queue()
    else:
        with pytest.raises(pytest.exit.Exception) as error:
            queue_guard.require_test_queue()
        assert error.value.returncode == 4
    assert len(reads) == 1


def test_override_receipts_every_use_and_fails_closed(tmp_path, monkeypatch):
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw:
                        OWNER if str(path) == "/proc/self/cgroup" else original(path, *a, **kw))
    monkeypatch.setenv("CF_ALLOW_DIRECT_TESTS", "1")
    target = tmp_path / "receipts" / "direct.log"
    monkeypatch.setattr(queue_guard, "DIRECT_LOG", target)
    queue_guard.require_test_queue()
    queue_guard.require_test_queue()
    assert len(target.read_text().splitlines()) == 2
    monkeypatch.setattr(queue_guard, "DIRECT_LOG", tmp_path)
    with pytest.raises(pytest.exit.Exception) as error:
        queue_guard.require_test_queue()
    assert error.value.returncode == 4
    assert str(error.value) == MESSAGE


def test_real_execution_context_and_inherited_child(capsys):
    """Keep a real receipt; synthetic cgroups above are not deployment proof."""
    github = os.environ.get("GITHUB_ACTIONS")
    try:
        cgroup = Path("/proc/self/cgroup").read_text()
    except OSError:
        cgroup = ""
    queued = "pueued.service" in cgroup or "heavyq-" in cgroup
    lane = "lanes.slice" in cgroup
    if not lane and not queued and github != "true" and os.environ.get("CF_ALLOW_DIRECT_TESTS") == "1":
        pytest.skip("Owner override admits this run; queued child inheritance needs a queue context")
    assert queued or (not lane and github == "true")
    env = {k: v for k, v in os.environ.items()
           if k not in ("HEAVY_QUEUE_INNER", "CI", "CF_ALLOW_DIRECT_TESTS")}
    result = subprocess.run(
        [sys.executable, "-c", "from tests.queue_guard import require_test_queue; require_test_queue()"],
        cwd=APP, env={**env, "PYTHONPATH": str(APP)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    with capsys.disabled():
        print("QUEUEGUARD_CONTEXT " + json.dumps({"host": socket.gethostname(),
              "cgroup": cgroup, "GITHUB_ACTIONS": github, "child_rc": result.returncode}), flush=True)


@pytest.mark.parametrize("cgroup,admission,skip", [
    (DIRECT, {"CF_ALLOW_DIRECT_TESTS": "1"}, None),
    (DIRECT, {"GITHUB_ACTIONS": "true"}, None),
    (OWNER, {"CF_ALLOW_DIRECT_TESTS": "1"}, True),
    (OWNER, {"GITHUB_ACTIONS": "true"}, False),
    (OWNER, {}, None),
    (None, {"CF_ALLOW_DIRECT_TESTS": "1"}, True),
    (None, {"GITHUB_ACTIONS": "true"}, False),
    ("0::/user.slice/heavyq-regression.scope\n", {"CF_ALLOW_DIRECT_TESTS": "1"}, False),
    ("0::/user.slice/pueued.service\n", {}, False),
])
def test_deployment_probe_supports_admitted_contexts(monkeypatch, capsys, cgroup, admission, skip):
    """The receipt test must respect every supported admission mode itself."""
    for key in ADMISSION:
        monkeypatch.delenv(key, raising=False)
    for key, value in admission.items():
        monkeypatch.setenv(key, value)
    original = Path.read_text

    def read(path, *args, **kwargs):
        if str(path) == "/proc/self/cgroup":
            if cgroup is None:
                raise OSError("cgroup unavailable")
            return cgroup
        return original(path, *args, **kwargs)

    calls = []

    def child(command, **kwargs):
        calls.append(command)
        # Queued/GitHub children must prove admission without the override.
        assert not any(key in kwargs["env"] for key in
                       ("HEAVY_QUEUE_INNER", "CI", "CF_ALLOW_DIRECT_TESTS"))
        assert kwargs["env"].get("GITHUB_ACTIONS") == admission.get("GITHUB_ACTIONS")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(subprocess, "run", child)
    # Synthetic receipts stay captured, so logs retain only deployment evidence.
    monkeypatch.setattr(capsys, "disabled", nullcontext)
    if skip is None:
        with pytest.raises(AssertionError):
            test_real_execution_context_and_inherited_child(capsys)
        assert calls == []
    elif skip:
        with pytest.raises(pytest.skip.Exception, match="queued child inheritance"):
            test_real_execution_context_and_inherited_child(capsys)
        assert calls == []
    else:
        test_real_execution_context_and_inherited_child(capsys)
        assert len(calls) == 1
