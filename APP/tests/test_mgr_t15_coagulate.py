"""Coagulate regressions that exercise the live plug-in and effect, and a saved fight through the table.

Each unit test calls the real code path it guards: the compile_action / compile_actions hooks on real
ActionDefinition rows, and the registered coagulate_end_ordinary_bleeding effect with the shared needle.ask and
condition removal. A recording engine and a monkeypatched ask stand in for the table.

The end-to-end tests build their own Blood fight from public helpers (h1_support, auto11_service_support,
cw2_service_support, test_table_advance is not used) and press the real table buttons on a saved match with a
real Bleeding instance and a real Blood Thread, then cold-reload it. They do not import any other test module.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import blood_base, effects, needle
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests import auto11_service_support as S
from tests.cw2_service_support import add_action, seal
from tests.h1_support import ROOT, sheet

COAGULATE = "BLOOD_BASE_COAGULATE"
END_ORDINARY = "coagulate_end_ordinary_bleeding"
BLEEDING = "condition:typed.bleeding"
CASTER = "actor:caster"
PATIENT = "actor:patient"
THREAD = "Blood Thread"
BLOOD_TALENTS = ["BLOOD_BASE_BLOOD_THREAD", "BLOOD_BASE_COAGULATE"]


def coagulate_action():
    """A real ActionDefinition shaped like the printed Coagulate End Bleeding option."""
    typed = {"source": COAGULATE, "option_of": COAGULATE, "numbers": {}, "riders": [], "duration": {"kind": "instant"},
             "effects": [
                 {"type": "requires_thread", "evidence": "One creature bearing your Blood Thread"},
                 {"type": "remove_condition", "condition": "bleeding", "applies_to": "target",
                  "evidence": "end one Bleeding effect"}]}
    return ActionDefinition(
        source_definition_id=f"action:typed.{COAGULATE}.end_bleeding", display_name="Coagulate: End Bleeding",
        owner_id=CASTER, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
        range_ft=30, costs=(("resource:core.cp", 1),), parameters={"typed": typed})


def bleeding(source_definition_id, source_actor_id=CASTER):
    return SimpleNamespace(condition_id=BLEEDING, source_definition_id=source_definition_id,
                           source_actor_id=source_actor_id, instance_id=None, data=None)


class Engine:
    """Records exact-instance removals; the real condition_ownership.remove_instance calls into this."""

    def __init__(self):
        self.removed = []

    def _remove_condition_instance(self, target, instance_id, source_id, **kwargs):
        self.removed.append((target.entity_id, instance_id, source_id))
        return True


def holder(conditions):
    return SimpleNamespace(entity_id=PATIENT, display_name="Patient", active=True, conditions=conditions)


def ctx(engine, target, riders=None):
    riders = [] if riders is None else riders
    return SimpleNamespace(engine=engine, intent=None, actor=SimpleNamespace(entity_id=CASTER, display_name="Caster"),
                           action=SimpleNamespace(display_name="Coagulate"), source="action:test.coagulate",
                           rider=riders.append, target=target)


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


def test_end_bleeding_mode_is_replaced_by_one_bleeding_effect():
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


def test_end_bleeding_offers_every_bleeding_instance_and_declines_by_default(ask_log):
    """Regression: with no sealed roster, the old code offered nothing, so End Bleeding ended nothing in a real fight.

    Every Bleeding instance the target carries is offered, each with its own label, and the choice declines by default.
    """
    engine = Engine()
    target = holder({
        "i-a": SimpleNamespace(**{**bleeding("rule.a").__dict__}),
        "i-b": SimpleNamespace(**{**bleeding("rule.b").__dict__}),
    })
    ask_log(lambda options: [])
    blood_base.end_one_ordinary_bleeding(ctx(engine, target), {"type": END_ORDINARY, "applies_to": "target"})
    call = ask_log.calls[0]
    assert call["options"] == ["i-a", "i-b"]
    assert set(call["labels"]) == {"i-a", "i-b"} and all(call["labels"].values())
    assert call["default"] == "decline"
    assert call["allow_decline"] is True
    assert engine.removed == []


def test_selected_bleeding_ends_with_source_and_no_type_error(ask_log):
    """Regression: remove_instance was called with three arguments and raised TypeError on the first choice."""
    engine = Engine()
    target = holder({"i-cut": SimpleNamespace(**bleeding("rule.cut").__dict__)})
    ask_log(lambda options: ["i-cut"])
    blood_base.end_one_ordinary_bleeding(ctx(engine, target), {"type": END_ORDINARY})
    assert engine.removed == [(PATIENT, "i-cut", "action:test.coagulate")]


def test_no_bleeding_offers_nothing_and_says_so(ask_log):
    engine = Engine()
    riders = []
    ask_log(lambda options: ["i-x"])
    blood_base.end_one_ordinary_bleeding(ctx(engine, holder({}), riders), {"type": END_ORDINARY})
    assert ask_log.calls == []
    assert engine.removed == []
    assert any("has no Bleeding effect" in r for r in riders), riders


def test_no_clinical_roster_path_is_left():
    """Regression (finding 1): the roster module and its doc were a second, GM-only source for the same choice."""
    assert importlib.util.find_spec("combat.clinical_sources") is None
    assert "clinical" not in Path(blood_base.__file__).read_text().lower()


def test_lane_tests_import_no_other_test_module():
    """Regression (finding 3): importing test_c5_review / test_mgr_t14_blood_base tied these tests to private history."""
    text = Path(__file__).read_text()
    assert ("from tests import " + "test_") not in text
    assert ("import tests." + "test_") not in text


# ---- End-to-end: a real saved Blood fight, a real Bleeding instance, the real table buttons, cold reload ----

def blood_sheet(name):
    """A Blood base caster: the Thread and Coagulate talents as automatic components of the sphere."""
    doc = sheet([], cl=10, dc=16, key="CON", name=name)
    doc["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.blood"], "learned_talent_record_ids": [],
                                  "automatic_sphere_component_record_ids": BLOOD_TALENTS}
    return doc


def fight(tmp_path, seed):
    """The caster (who knows Coagulate) against a patient, both compiled from real sheets in a saved match.

    The caster's free setup actions are the only way to place the Thread (a mark) and a Bleeding instance on the
    patient; each is an ordinary typed effect, so the Bleeding is a real condition instance, not a stub.
    """
    caster, patient = S.THIEF, S.VICTIM
    docs = {caster: blood_sheet("Caster"), patient: sheet([], name="Patient", cl=10)}
    bundles = [compile_character(docs[who], actor_id=who, reaction_plan={"ask": True}) for who in (caster, patient)]
    add_action(bundles[0], "Prepare thread", [{"type": "mark", "mark": THREAD, "applies_to": "target",
                                              "duration": {"kind": "hours", "amount": 1}}], target="HOSTILE_ENTITY")
    add_action(bundles[0], "Prepare wound", [{"type": "condition", "condition": "bleeding", "applies_to": "target",
                                             "expires_on": "UNTIL_REMOVED"}], target="HOSTILE_ENTITY")
    for i, bundle in enumerate(bundles):
        bundle["actor_template"].update(initiative_bonus=1000 if not i else -1000, maximum_hp=2000)
        seal(bundle)
    combat = CombatService(ROOT, tmp_path / "combat")
    session = combat.persistence.create_match(
        match_seed=seed, typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [caster, patient], "team_by_actor": {caster: "team:a", patient: "team:b"},
                      "starting_positions": {caster: {"x": 3, "y": 6}, patient: {"x": 4, "y": 6}}})
    combat._read_metadata(session.match_id, session)
    for who in (caster, patient):
        combat.set_controller_mode(session.match_id, actor_id=who, controller_mode="MANUAL")
    table = TabletopService(combat, combat.userdata_root)
    return combat, table, session.match_id, caster, patient


def bleeding_on(engine, who):
    return sorted(iid for iid, c in engine.state.actors[who].conditions.items() if c.condition_id == BLEEDING)


def coagulate_end_bleeding(table, mid, patient, accept):
    """Press Coagulate: End Bleeding on the patient.

    The willing consent is accepted. The one-Bleeding choice takes the first offered instance when accepted, and
    declines (returns None) otherwise.
    """
    def answer(prompt):
        choice = prompt.get("choice") or {}
        options = [row["id"] for row in choice.get("options") or []]
        if "accept" in options or "refuse" in options:
            return "accept"
        return options[0] if accept and options else None
    return S.play(table, mid, S.candidate(table, mid, "Coagulate: End Bleeding", target=patient), answer)


def _prepare_fight(tmp_path, seed):
    combat, table, mid, caster, patient = fight(tmp_path, seed)
    S.to_thief(table, mid)
    for label in ("Prepare thread", "Prepare wound"):
        S.play(table, mid, S.candidate(table, mid, label, target=patient))
    assert bleeding_on(S.engine(combat, mid), patient), "the patient must carry a real Bleeding instance before Coagulate"
    return combat, table, mid, caster, patient


def test_end_bleeding_on_a_saved_fight_ends_the_chosen_bleeding_and_survives_reload(tmp_path):
    """Regression (finding 2): the old test pressed the button on a foe with no Bleeding and passed trivially.

    Accepting the Bleeding choice ends that instance through the table path, and a cold reload keeps the result.
    """
    combat, table, mid, caster, patient = _prepare_fight(tmp_path, "COAGULATE-T15-ACCEPT")
    before = bleeding_on(S.engine(combat, mid), patient)
    coagulate_end_bleeding(table, mid, patient, accept=True)
    assert bleeding_on(S.engine(combat, mid), patient) == [], "accepting must end the one Bleeding instance"
    cold = CombatService(combat.source_root, combat.userdata_root)
    assert cold.replay(mid)["status"] == "PASS"
    assert bleeding_on(S.engine(cold, mid), patient) == [], f"reload must keep it ended (was {before})"


def test_end_bleeding_declined_on_a_saved_fight_keeps_the_bleeding_and_survives_reload(tmp_path):
    """Declining the Bleeding choice ends nothing (the decline default), and a cold reload keeps the wound."""
    combat, table, mid, caster, patient = _prepare_fight(tmp_path, "COAGULATE-T15-DECLINE")
    before = bleeding_on(S.engine(combat, mid), patient)
    coagulate_end_bleeding(table, mid, patient, accept=False)
    assert bleeding_on(S.engine(combat, mid), patient) == before, "declining must keep the Bleeding"
    cold = CombatService(combat.source_root, combat.userdata_root)
    assert cold.replay(mid)["status"] == "PASS"
    assert bleeding_on(S.engine(cold, mid), patient) == before
