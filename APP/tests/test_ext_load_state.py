"""The extension registry must not announce a partial startup as complete."""

from collections import defaultdict
from types import SimpleNamespace
from pathlib import Path
import threading

import pytest

import combat.ext as ext


def test_create_app_fails_before_starting_threads_when_plugin_load_fails(tmp_path, monkeypatch):
    from app import api
    from app.core import Settings

    error = ValueError("broken plug-in")
    started = []

    def fail_load():
        raise error

    monkeypatch.setattr(api, "load_plug_ins", fail_load)
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path)
    with pytest.raises(ValueError, match="broken plug-in") as caught:
        api.create_app(settings)
    assert caught.value is error
    assert not started


@pytest.fixture
def isolated_loader(monkeypatch):
    monkeypatch.setattr(ext, "_LOADED", False)
    monkeypatch.setattr(ext, "_LOADING_THREAD", None)
    monkeypatch.setattr(ext, "_LOAD_ERROR", None)
    monkeypatch.setattr(ext, "_HOOKS", defaultdict(list))
    monkeypatch.setattr(
        ext, "pkgutil",
        SimpleNamespace(iter_modules=lambda path: [SimpleNamespace(name=n) for n in ("b", "a")]),
    )
    return monkeypatch


def test_failed_import_never_publishes_partial_registry(isolated_loader):
    calls = []

    def import_module(name):
        calls.append(name)
        if name.endswith(".a"):
            ext._HOOKS["example"].append(lambda: None)
        else:
            raise ValueError("broken plug-in")

    isolated_loader.setattr(ext, "importlib", SimpleNamespace(import_module=import_module))
    with pytest.raises(ValueError, match="broken plug-in"):
        ext.load_plug_ins()
    assert not ext._LOADED
    with pytest.raises(RuntimeError, match="previously failed") as error:
        ext.load_plug_ins()
    assert isinstance(error.value.__cause__, ValueError)
    assert calls == ["combat.ext.a", "combat.ext.b"]


def test_reentrant_and_concurrent_load_do_not_publish_partial_registry(isolated_loader):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    failures = []

    def import_module(name):
        calls.append(name)
        if name.endswith(".a"):
            ext.load_plug_ins()  # Same-thread plug-in recursion must be harmless.
            entered.set()
            assert release.wait(5)

    isolated_loader.setattr(ext, "importlib", SimpleNamespace(import_module=import_module))

    def load():
        try:
            ext.load_plug_ins()
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=load)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match="in progress"):
            ext.load_plug_ins()
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert not failures
    ext.load_plug_ins()
    assert ext._LOADED
    assert calls == ["combat.ext.a", "combat.ext.b"]
