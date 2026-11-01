"""Printed Extra Attack counts and readable labels survive table commit/reload."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act

PLAYER, FOE = "actor:factory.log1-extra", "actor:factory.log1-extra-target"
IRON = "tianxia.path.body_refining.feature.iron_fist"
EXTRA = "tianxia.path.body_refining.feature.extra_attack"


@pytest.mark.parametrize("cl,owns_extra,count,augmented", [(10, True, 2, False), (11, True, 3, False),
                                                          (17, True, 4, False), (17, False, 1, False),
                                                          (10, True, 2, True)])
def test_extra_attack_count_and_labels_after_table_reload(tmp_path, monkeypatch, cl, owns_extra, count, augmented):
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        # Each ordinary attack is resolved normally, with deterministic hit/damage rolls.
        # The augmented case reproduces the reported first hit, second miss.
        prior = sum(e.event_type == "ATTACK_ROLLED" and e.actor_id == PLAYER for e in engine.events)
        script(engine, [1 if augmented and prior else 19, *([1] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    doc = sheet([IRON, *([EXTRA] if owns_extra else []),
                 *(["TAL_VOID_NULLIFYING_STRIKE"] if augmented else [])], cl=cl)
    doc["identity"]["display_name"] = "Extra Attack Player"
    doc["ability_scores_and_statistics"]["primary_resource"]["definitions"] = [{"name": "Stamina", "max": 30}]
    foe = sheet([], cl=cl)
    foe["identity"]["display_name"] = "Extra Attack Target"
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    bundle = compile_character(doc, actor_id=PLAYER)
    name = "Iron Fist attack" + (" + Nullifying Strike: Hollowed (2 Stamina)" if augmented else "")
    action = next(a for a in bundle["action_catalog"] if a["display_name"] == name)
    attack = next(e for e in action["parameters"]["typed"]["effects"] if e["type"] == "attack")
    assert attack["count"] == count
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [bundle, compile_character(foe, actor_id=FOE)],
        [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="LOG1-EXTRA",
        display_name="Extra Attack regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    before = dict(combat._load_session(mid).engine.state.actors[PLAYER].resources)
    state = table.state(mid)
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.display_name == name)
    from tests.iron_fist_support import answering_iron_fist  # each strike's damage-type question (L45)
    assert answering_iron_fist(lambda answers: table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                               state["menu"]["state_version"], state["last_sequence"], answers))()["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    boundary = fresh.history(mid)["boundaries"][-1]
    events = [e for e in boundary["events"] if e["event_type"] == "ATTACK_ROLLED"]
    assert len(events) == count
    assert [int(e["payload"]["reason"].rsplit(":", 1)[-1]) for e in events] == list(range(1, count + 1))
    assert all(e["actor_id"] == PLAYER and e["target_ids"] == [FOE] for e in events)
    assert len({e["source_definition_id"] for e in events}) == 1
    attacks = [e["summary"] for e in boundary["feed"] if e["event_type"] == "ATTACK_ROLLED"]
    assert len(attacks) == count
    assert "additional attack" not in attacks[0]
    for index, summary in enumerate(attacks[1:], 2):
        assert f"{name} — additional attack {index} vs Extra Attack Target" in summary
    loaded = fresh._load_session(mid)
    actor = loaded.engine.state.actors[PLAYER]
    assert actor.resources == {pool: value - (2 if augmented and pool == "resource:core.stamina" else 0)
                               for pool, value in before.items()}
    assert not actor.action_available
    assert actor.bonus_action_available
    if augmented:
        assert [e["payload"]["provisional_hit"] for e in events] == [True, False]
        saves = [e for e in boundary["events"] if e["event_type"] == "SAVE_ROLLED"]
        assert len(saves) == 1
        assert saves[0]["source_definition_id"] == "passive:TAL_VOID_NULLIFYING_STRIKE"
    assert loaded.mechanical.replay()["status"] == "PASS"
