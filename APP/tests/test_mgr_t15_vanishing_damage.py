"""Native damage on another creature's turn and failed Concentration saves."""
from tests.h1_support import sheet
from tests.hunt12_support import hit_dice
from tests.test_mgr_t15_vanishing_native import setup, activate, held, TRUE_SIGHT_FEATURES
from tests.worker2_support import OWNER, FOE, candidate, settle, reload, turn


def attack(engine, actor, target):
    return next(c for c in engine.legal_candidates() if c.actor_id == actor and c.target_ids == (target,)
        and c.source_definition_id in engine.action_catalog
        and (engine.action_catalog[c.source_definition_id].resolution_kind == "ATTACK"
             or any(e.get("type") == "attack" for e in
                    (engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("effects", []))))


def test_damage_only_on_another_turn_reveals_then_restores(tmp_path, monkeypatch):
    hit_dice(monkeypatch, save_roll=20)
    combat, table, mid = setup(tmp_path, ["FIRE_TAL_BURNING_WEAPON"], owner_kit={
        "starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu"}]}})
    activate(combat, table, mid)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    # Burning Weapon asks which strike burns; choose the Fu (Short Axe) explicitly (a declined imbue imbues nothing).
    settle(table, mid, candidate(combat, mid, "Burning Weapon").candidate_id,
           choices={"choice:fire.imbue_weapon": "tianxia.mortal.weapon.fu"})
    axe = [c for c in reload(tmp_path, mid).legal_candidates() if c.actor_id == OWNER and c.target_ids == (FOE,)
           and c.display_name.startswith("Fu (Short Axe) attack")]
    assert axe, "the imbued Fu (Short Axe) strike must be offered"
    settle(table, mid, axe[0].candidate_id, choices={})
    engine = reload(tmp_path, mid)
    assert held(engine.state.actors[FOE], "burning")
    assert not held(engine.state.actors[OWNER], "invisible")
    mark = len(engine.events)
    # The owner's turn ends (restoring Invisible), then Burn alone deals damage
    # at the foe's next turn start. No attack or forced save causes that reveal.
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    after = reload(tmp_path, mid)
    events = after.events[mark:]
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == OWNER for e in events)
    assert not any(e.event_type in {"ATTACK_ROLLED", "SAVE_ROLLED", "ZONE_CREATED"} for e in events)
    assert not held(after.state.actors[OWNER], "invisible")
    assert held(after.state.actors[OWNER], "vanishing_state")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert held(reload(tmp_path, mid).state.actors[OWNER], "invisible")


def test_concentration_loss_does_not_restore_at_turn_end(tmp_path, monkeypatch):
    hit_dice(monkeypatch, save_roll=1)
    foe = sheet(TRUE_SIGHT_FEATURES, cl=14)
    combat, table, mid = setup(tmp_path, foe_sheet=foe)
    activate(combat, table, mid)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    mark = len(reload(tmp_path, mid).events)
    settle(table, mid, attack(reload(tmp_path, mid), FOE, OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.actor_id == OWNER for e in engine.events[mark:])
    assert not held(engine.state.actors[OWNER], "vanishing_state")
    assert not held(engine.state.actors[OWNER], "invisible")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert not held(reload(tmp_path, mid).state.actors[OWNER], "invisible")
