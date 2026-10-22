"""Coagulate regressions that exercise the live plug-in, effect and clinical roster.

Each test calls the real code path it guards: the compile_action / compile_actions
hooks on real ActionDefinition rows, the registered coagulate_end_ordinary_bleeding
effect with the shared needle.ask and condition removal, and the sealed clinical
roster reader. A recording engine and a monkeypatched ask stand in for the table,
so these run on public CI without private fixtures or git history.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from combat import typed_executor
from combat.clinical_sources import SETUP, attach_sources, ordinary_bleeding_instances
from combat.gate5_service import CombatService
from combat.ext import blood_base, effects, needle
from combat.gate2_runtime_models import ActionDefinition, EconomyKind

COAGULATE = "BLOOD_BASE_COAGULATE"
END_ORDINARY = "coagulate_end_ordinary_bleeding"
BLEEDING = "condition:typed.bleeding"
CASTER = "actor:caster"
PATIENT = "actor:patient"


def coagulate_action():
    """A real ActionDefinition shaped like the printed Coagulate End Bleeding option."""
    typed = {"source": COAGULATE, "option_of": COAGULATE, "numbers": {}, "riders": [], "duration": {"kind": "instant"},
             "effects": [
                 {"type": "requires_thread", "evidence": "One creature bearing your Blood Thread"},
                 {"type": "remove_condition", "condition": "bleeding", "applies_to": "target",
                  "evidence": "end one ordinary bleeding effect"}]}
    return ActionDefinition(
        source_definition_id=f"action:typed.{COAGULATE}.end_bleeding", display_name="Coagulate: End Bleeding",
        owner_id=CASTER, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
        range_ft=30, costs=((f"resource:core.cp", 1),), parameters={"typed": typed})


def bleeding(source_definition_id, source_actor_id=CASTER):
    return SimpleNamespace(condition_id=BLEEDING, source_definition_id=source_definition_id,
                           source_actor_id=source_actor_id, instance_id=None)


class Engine:
    """Records exact-instance removals; the real condition_ownership.remove_instance calls into this."""

    def __init__(self, roster=None):
        self.typed_bundle_documents = roster or []
        self.removed = []

    def _remove_condition_instance(self, target, instance_id, source_id, **kwargs):
        self.removed.append((target.entity_id, instance_id, source_id))
        return True


def roster(*rows):
    return [{"actor_id": PATIENT, SETUP: list(rows)}]


def row(rule_id, *, category="ordinary_bleeding", readers=(CASTER,), label="Cut"):
    return {"source_id": f"src:{rule_id}", "rule_id": rule_id, "subject": PATIENT, "label": label,
            "category": category, "readers": list(readers)}


def holder(conditions):
    return SimpleNamespace(entity_id=PATIENT, display_name="Patient", active=True, conditions=conditions)


def ctx(engine, target):
    return SimpleNamespace(engine=engine, intent=None, actor=SimpleNamespace(entity_id=CASTER, display_name="Caster"),
                           action=SimpleNamespace(display_name="Coagulate"), source="action:test.coagulate",
                           rider=lambda text: None, target=target)


@pytest.fixture
def ask_log(monkeypatch):
    calls = []

    def set_answer(answer):
        def fake_ask(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
            calls.append({"options": list(options), "labels": kwargs.get("labels"), "default": kwargs.get("default"),
                          "allow_decline": kwargs.get("allow_decline")})
            return list(answer(options))
        monkeypatch.setattr(needle, "ask", fake_ask)
        monkeypatch.setattr(needle, "checkpoint_id", lambda *a, **k: "checkpoint:test")
        monkeypatch.setattr(typed_executor, "_default_subject", lambda c, e, harmful: [c.target])
    set_answer.calls = calls
    return set_answer


def test_end_bleeding_mode_is_replaced_by_ordinary_only_effect():
    """Regression: the printed End Bleeding mode ended every Bleeding instance via remove_condition."""
    wrapped = blood_base.coagulate_consent(coagulate_action(), {})
    rows = wrapped.parameters["typed"]["effects"]
    choice = next(r for r in rows if r["type"] == "choose_willing")
    kinds = [r["type"] for r in choice["effects"]]
    assert END_ORDINARY in kinds
    assert "remove_condition" not in kinds


def test_coagulate_wrapper_is_idempotent():
    once = blood_base.coagulate_consent(coagulate_action(), {})
    assert blood_base.coagulate_consent(once, {}) is None


def test_non_coagulate_actions_untouched():
    other = coagulate_action().model_copy(update={"parameters": {"typed": {"source": "BLOOD_BASE_BLOOD_THREAD"}}})
    assert blood_base.coagulate_consent(other, {}) is None


def test_hostile_recipient_sibling_is_added_via_willing_clone_path():
    """Guard: compile_actions adds an explicit hostile-recipient sibling, marked as the willing clone."""
    info = {"actions": [coagulate_action()]}
    siblings = blood_base.coagulate_willing_non_allies(info) or []
    assert siblings, "a hostile willing-recipient sibling must be offered"
    assert all(s.source_definition_id.endswith("#willing_non_ally") for s in siblings)


def test_effect_is_registered_for_typed_rows():
    assert END_ORDINARY in effects()


def test_offers_only_ordinary_readable_bleeding_and_declines_by_default(ask_log):
    """Regression: the old hook read available_bleeding (never produced) and asked with no ordinary filter."""
    engine = Engine(roster(row("rule.cut", label="Cut"), row("rule.other", category="other", label="Other"),
                           row("rule.unreadable", readers=(), label="Unreadable")))
    conditions = {
        "i-cut": SimpleNamespace(**{**bleeding("rule.cut").__dict__}),
        "i-other": SimpleNamespace(**{**bleeding("rule.other").__dict__}),
        "i-unreadable": SimpleNamespace(**{**bleeding("rule.unreadable").__dict__}),
    }
    target = holder(conditions)
    ask_log(lambda options: [])
    blood_base.end_one_ordinary_bleeding(ctx(engine, target), {"type": END_ORDINARY, "applies_to": "target"})
    call = ask_log.calls[0]
    assert call["options"] == ["i-cut"]
    assert call["default"] == "decline"
    assert call["allow_decline"] is True
    assert engine.removed == []


def test_selected_bleeding_ends_with_source_and_no_type_error(ask_log):
    """Regression: remove_instance was called with three arguments and raised TypeError on the first choice."""
    engine = Engine(roster(row("rule.cut")))
    target = holder({"i-cut": SimpleNamespace(**bleeding("rule.cut").__dict__)})
    ask_log(lambda options: ["i-cut"])
    blood_base.end_one_ordinary_bleeding(ctx(engine, target), {"type": END_ORDINARY})
    assert engine.removed == [(PATIENT, "i-cut", "action:test.coagulate")]


def test_no_ordinary_instance_offers_nothing(ask_log):
    engine = Engine(roster())
    target = holder({"i-x": SimpleNamespace(**bleeding("rule.unknown").__dict__)})
    ask_log(lambda options: ["i-x"])
    blood_base.end_one_ordinary_bleeding(ctx(engine, target), {"type": END_ORDINARY})
    assert ask_log.calls == []
    assert engine.removed == []


def test_clinical_roster_requires_category_source_and_reader():
    engine = Engine(roster(row("rule.cut"), row("rule.unreadable", readers=()), row("rule.other", category="other")))
    target = holder({
        "i-cut": SimpleNamespace(**bleeding("rule.cut").__dict__),
        "i-unreadable": SimpleNamespace(**bleeding("rule.unreadable").__dict__),
        "i-other": SimpleNamespace(**bleeding("rule.other").__dict__),
        "i-unsealed": SimpleNamespace(**bleeding("rule.none").__dict__),
    })
    assert ordinary_bleeding_instances(engine, target, CASTER) == {"i-cut": "Cut"}


def test_gm_source_file_is_sealed_on_the_real_match_path_and_ends_the_wound(tmp_path, ask_log):
    """Regression: nothing called attach_sources, so every real fight had an empty roster.

    Drives CombatService._finish_factory_match (the shared create path for Factory fights) with a
    recording persistence, then ends the sealed wound with the sealed bundles.
    """
    source = tmp_path / "sources.json"
    source.write_text(json.dumps([row("rule.cut", label="Cut")]))
    source.chmod(0o600)
    saved = {}
    session = SimpleNamespace(match_id="match:test", store=SimpleNamespace(match_dir=tmp_path))

    def create_match(**kwargs):
        saved.update(kwargs)
        return session

    service = SimpleNamespace(
        persistence=SimpleNamespace(create_match=create_match), userdata_root=tmp_path,
        _catalog_cache={"encounters": [{"stable_id": "encounter:test"}]},
        _snapshot_match_visuals=lambda match_id: {}, _write_metadata=lambda match_id, metadata: None,
        _match_view=lambda session, metadata: {"match_id": session.match_id},
    )
    bundle = {"actor_id": PATIENT, "bundle_sha256": "x", "typed_authority_sha256": "t", "diagnostics": {},
              "actor_template": {"display_name": "Patient"}}
    CombatService._finish_factory_match(
        service, [bundle], [PATIENT, CASTER], {}, {}, {"stable_id": "arena:test"}, [], [],
        control_modes=None, match_seed="seed", display_name="Test", maximum_rounds=5,
        clinical_source_file=str(source))

    sealed = saved["typed_bundles"]
    assert sealed[0][SETUP][0]["rule_id"] == "rule.cut"
    engine = Engine(list(sealed))
    target = holder({"i-cut": SimpleNamespace(**bleeding("rule.cut").__dict__)})
    ask_log(lambda options: options[:1])
    blood_base.end_one_ordinary_bleeding(ctx(engine, target), {"type": END_ORDINARY})
    assert engine.removed == [(PATIENT, "i-cut", "action:test.coagulate")]


def test_attach_sources_refuses_group_readable_file(tmp_path):
    source = tmp_path / "sources.json"
    source.write_text("[]")
    source.chmod(0o640)
    with pytest.raises(ValueError, match="private owner file"):
        attach_sources([{"actor_id": PATIENT}], source_file=source, primary_actor_ids=[PATIENT])


def test_attach_sources_seals_private_roster(tmp_path):
    source = tmp_path / "sources.json"
    import json
    source.write_text(json.dumps([row("rule.cut")]))
    source.chmod(0o600)
    sealed = attach_sources([{"actor_id": PATIENT, "bundle_sha256": "x"}], source_file=source,
                            primary_actor_ids=[PATIENT, CASTER])
    assert sealed[0][SETUP] and sealed[0][SETUP][0]["rule_id"] == "rule.cut"
    assert "bundle_sha256" in sealed[0] and sealed[0]["bundle_sha256"] != "x"
