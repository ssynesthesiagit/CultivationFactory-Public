"""Synthetic regressions for the three shared engine boundaries in ASTRAFIX3."""
from contextlib import nullcontext
import json
from threading import Event, RLock, Thread, current_thread
from types import SimpleNamespace

import pytest

from combat import ext, typed_executor, typed_reactions


def test_plugin_loading_is_reentrant_serialized_and_failure_is_sticky(monkeypatch):
    # Use the real loader and registry API, but no real module imports or global
    # importlib patches. Each scenario has a fresh, disposable registry.
    for failure in (None, RuntimeError("broken plug-in"), ext.ControllerPause()):
        entered, release, reader_waiting = Event(), Event(), Event()
        imported, answers, errors = [], {}, {}

        class ObservedLock:
            def __init__(self):
                self.lock = RLock()

            def __enter__(self):
                if current_thread().name == "astra-reader":
                    reader_waiting.set()
                self.lock.acquire()

            def __exit__(self, *args):
                self.lock.release()

        monkeypatch.setattr(ext, "_LOAD_LOCK", ObservedLock(), raising=False)
        monkeypatch.setattr(ext, "_LOADED", False)
        monkeypatch.setattr(ext, "_LOADING", False, raising=False)
        monkeypatch.setattr(ext, "_LOAD_ERROR", None, raising=False)
        for registry in ("_EFFECTS", "_EFFECT_HARM", "_EFFECT_FORGE_REJECTION"):
            monkeypatch.setattr(ext, registry, {})

        def import_plugin(name):
            imported.append(name)
            if name.endswith(".first"):
                ext.effect("first")(lambda *args: None)
                # Circular discovery on this thread can read its own registrations.
                assert tuple(ext.effects()) == ("first",)
                entered.set()
                assert release.wait(5), "test did not release the importer"
            elif failure is not None:
                raise failure
            else:
                ext.effect("last")(lambda *args: None)

        monkeypatch.setattr(ext, "importlib", SimpleNamespace(import_module=import_plugin))
        monkeypatch.setattr(ext, "pkgutil", SimpleNamespace(
            iter_modules=lambda path: [SimpleNamespace(name="last"), SimpleNamespace(name="first")]))

        def read_registry():
            name = current_thread().name
            try:
                answers[name] = tuple(ext.effects())
            except BaseException as exc:
                errors[name] = exc

        loader = Thread(target=read_registry, name="astra-loader", daemon=True)
        reader = Thread(target=read_registry, name="astra-reader", daemon=True)
        loader.start()
        try:
            assert entered.wait(5), errors
            reader.start()
            assert reader_waiting.wait(5), "another thread bypassed initialization"
            assert not answers and not errors
            assert ext._LOADED is False
        finally:
            release.set()
            loader.join(5)
            if reader.ident is not None:
                reader.join(5)
        assert not loader.is_alive() and not reader.is_alive()
        assert imported == ["combat.ext.first", "combat.ext.last"]
        assert ext._LOADING is False
        if failure is None:
            assert errors == {}
            assert answers == {"astra-loader": ("first", "last"), "astra-reader": ("first", "last")}
            assert ext._LOADED is True
            assert tuple(ext.effects()) == ("first", "last")
        else:
            assert answers == {}
            assert errors == {"astra-loader": failure, "astra-reader": failure}
            assert ext._LOADED is False
            for query in (ext.load_plug_ins, ext.effects, lambda: ext.has("anything")):
                with pytest.raises(type(failure)) as caught:
                    query()
                assert caught.value is failure
        assert imported == ["combat.ext.first", "combat.ext.last"], "never retry partial imports"


def test_effect_preparation_restores_exact_context_on_failure_and_nesting(monkeypatch):
    from combat import action_geometry, shot_geometry

    prior_instance = [{"type": "COLD", "amount": 9}]
    engine = SimpleNamespace(events=[], _effect_resolution_mode="prior",
                             _typed_damage_instance=prior_instance)
    outer = SimpleNamespace(engine=engine, actor=object(), source="outer", effect_resolution="delayed",
                            defeat_notification_scope={"drop": set(), "own_kill": set()})
    inner = SimpleNamespace(engine=engine, actor=outer.actor, source="inner", effect_resolution="ordinary",
                            defeat_notification_scope={"drop": set(), "own_kill": set()})
    portions = {"outer": [{"type": "FIRE", "amount": 3}],
                "inner": [{"type": "ACID", "amount": 4}]}
    fault = {}
    order = []
    opt_in = True

    def request(point, active_engine, ctx, effects):
        assert point == "damage_instance_requested" and active_engine is engine
        assert engine._effect_resolution_mode == ctx.effect_resolution
        order.append(("request", ctx.source))
        if fault.get("stage") == "request":
            raise fault["error"]
        return [True]

    def collect(ctx, effects):
        order.append(("collect", ctx.source))
        if fault.get("stage") == "collect":
            raise fault["error"]
        return portions[ctx.source]

    def body(ctx, effects):
        order.append(("dispatch", ctx.source))
        assert engine._effect_resolution_mode == ctx.effect_resolution
        assert engine._typed_damage_instance is (portions[ctx.source] if opt_in else None)
        if ctx is outer and opt_in:
            for stage in ("request", "collect"):
                for error in (ValueError(stage), ext.ControllerPause()):
                    fault.update(stage=stage, error=error)
                    with pytest.raises(type(error)) as caught:
                        typed_executor.run_effects(inner, [])
                    assert caught.value is error
                    assert engine._effect_resolution_mode == outer.effect_resolution
                    assert engine._typed_damage_instance is portions["outer"]
            fault.clear()
            typed_executor.run_effects(inner, [])
            assert engine._effect_resolution_mode == outer.effect_resolution
            assert engine._typed_damage_instance is portions["outer"]

    monkeypatch.setattr(ext, "has", lambda point: opt_in)
    monkeypatch.setattr(ext, "run", request)
    monkeypatch.setattr(ext, "iter_strict_all", lambda *args: ())
    monkeypatch.setattr(typed_executor, "_collect_damage_instance", collect)
    monkeypatch.setattr(typed_executor, "_run_effects_in_chain", body)
    monkeypatch.setattr(action_geometry, "attack", lambda *args: nullcontext())
    monkeypatch.setattr(shot_geometry, "attack_scope", lambda *args: nullcontext())

    for stage in ("request", "collect"):
        for error in (ValueError(stage), ext.ControllerPause()):
            fault.update(stage=stage, error=error)
            with pytest.raises(type(error)) as caught:
                typed_executor.run_effects(outer, [])
            assert caught.value is error
            assert engine._effect_resolution_mode == "prior"
            assert engine._typed_damage_instance is prior_instance
    fault.clear()
    order.clear()
    typed_executor.run_effects(outer, [])
    assert order[:3] == [("request", "outer"), ("collect", "outer"), ("dispatch", "outer")]
    assert order[-3:] == [("request", "inner"), ("collect", "inner"), ("dispatch", "inner")]
    assert engine._effect_resolution_mode == "prior"
    assert engine._typed_damage_instance is prior_instance
    # Nonconsumers still dispatch directly, without collecting or pre-rolling.
    opt_in = False
    order.clear()
    typed_executor.run_effects(outer, [])
    assert order == [("dispatch", "outer")]
    assert engine._effect_resolution_mode == "prior"
    assert engine._typed_damage_instance is prior_instance


def test_feature_duplicates_name_both_owners_and_leave_cached_map_intact(tmp_path, monkeypatch):
    # Both base/shard and shard/shard collisions, even with identical values.
    for base_owner in (True, False):
        for same_value in (True, False):
            root = tmp_path / f"rules-{base_owner}-{same_value}"
            directory = root / "feature_blocks.d"
            directory.mkdir(parents=True)
            base = root / "feature_blocks.json"
            first, second = directory / "a.json", directory / "b.json"
            original = {"block": "already_applied", "why": "synthetic feature"}
            base.write_text(json.dumps({"features": {"owned": original} if base_owner else {}}))
            first.write_text(json.dumps({"features": {} if base_owner else {"owned": original}}))
            second.write_text('{"features": {}}')
            monkeypatch.setattr(typed_reactions, "RULES_PATH", base)
            monkeypatch.setattr(typed_reactions, "_CACHE", {})
            cached = typed_reactions.rules()
            receipt = dict(typed_reactions._CACHE)
            assert cached["features"] == {"owned": original}
            duplicate = original if same_value else {"block": "defense"}
            # A valid new row loads before the error: it must not leak into the cache.
            first_rows = {} if base_owner else {"owned": original}
            first.write_text(json.dumps({"features": {**first_rows, "partial": original}}))
            second.write_text(json.dumps({"features": {"owned": duplicate}}))
            for _ in range(2):
                with pytest.raises(ValueError) as caught:
                    typed_reactions.rules()
                message = str(caught.value)
                assert "owned" in message
                assert str(base if base_owner else first) in message
                assert str(second) in message
                assert typed_reactions._CACHE == receipt
                assert typed_reactions._CACHE["data"] is cached
                assert cached["features"] == {"owned": original}
            second.write_text('{"features": {}}')
            reloaded = typed_reactions.rules()
            assert reloaded is not cached
            assert reloaded["features"] == {"owned": original, "partial": original}
