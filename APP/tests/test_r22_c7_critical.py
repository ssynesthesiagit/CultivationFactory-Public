"""Integrated C7 riders retain the existing per-hit critical context on the table."""
import pytest

from tests.hunt12_support import ME, FOE, fight, candidate, send, reload, hit_dice
from tests.test_lock2_persistence import act

MASK = "tianxia.subpath.body.oni_blood.feature.oni_mask"
IRON = "tianxia.path.body_refining.feature.iron_fist"


@pytest.mark.parametrize("critical", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_oni_mask_hit_dice_follow_critical_through_table_reload(tmp_path, monkeypatch, critical, automatic):
    combat, table, mid = fight(tmp_path, [MASK, IRON])
    mask = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                if a.owner_id == ME and ((a.parameters or {}).get("typed") or {}).get("source") == MASK)
    assert act(table, mid, mask.source_definition_id)["status"] == "COMMITTED"
    hit_dice(monkeypatch, critical=critical)
    strike = candidate(combat, mid, lambda c: ".natural.iron_fist" in c.source_definition_id
                       and "#" not in c.source_definition_id and tuple(c.target_ids) == (FOE,))
    if automatic:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, strike, auto=automatic)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    rider = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
             and str(e.payload.get("expression", "")).endswith("d6+0")]
    assert len(rider) == 1
    assert rider[0].payload["expression"] == ("2d6+0" if critical else "1d6+0")
    session = combat._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("use_it", [False, True])
def test_pressure_payment_is_optional_and_survives_reload_before_answer(tmp_path, monkeypatch, use_it):
    from tests.test_log1_pressure_expiry import pressure_fight, PLAYER, STAMINA
    from tests.test_log1_pressure_choices import attack_candidate
    combat, table, mid = pressure_fight(tmp_path, monkeypatch, "speed", False)
    args = attack_candidate(combat, table, mid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    from tests.iron_fist_support import answering_iron_fist  # the Iron Fist strike's damage-type question (L45)
    strike = answering_iron_fist(lambda answers: table.act(*args, answers))
    result = strike([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["choice"]["allow_decline"]
    assert "1 Stamina" in prompt["moment"] and "Pressure Target" in prompt["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.hunt12_support import ROOT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    answer = {**prompt["context"], "selection": "USE" if use_it else "DECLINE",
              "option_ids": ["use"] if use_it else []}
    prior = (table.state(mid).get('pending_action') or {}).get('reactions') or []
    assert answering_iron_fist(lambda answers: table.act(*args, answers), initial_answers=prior)([answer])["status"] == "COMMITTED"
    session = combat._load_session(mid)
    assert session.engine.state.actors[PLAYER].resources[STAMINA] == 30 - int(use_it)
    assert session.mechanical.replay()["status"] == "PASS"


def test_c7_thunder_gain_respects_native_miss_journal_and_exception():
    from tests.test_lock4_unbroken_bolt import fight as bolt_fight, miss, ME as OWNER, POOL, BONE
    from combat.ext.thunder_charges import gain
    engine = bolt_fight()
    owner = engine.state.actors[OWNER]
    assert not miss(engine) and owner.resources[POOL] == 1
    assert not gain(engine, owner, "test:c7-normal")
    assert owner.resources[POOL] == 1
    assert gain(engine, owner, BONE, normal=False)
    assert owner.resources[POOL] == 2
    gains = [e for e in engine.events if e.event_type == "RESOURCE_GAINED" and e.actor_id == OWNER]
    assert [(e.source_definition_id, e.payload["gained"]) for e in gains] == [
        ("tianxia.subpath.body.adamant_thunderbolt_body.feature.body_of_the_unbroken_bolt", 1), (BONE, 1)]
