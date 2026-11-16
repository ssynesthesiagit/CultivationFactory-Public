"""Air cutting riders require damage from this strike, at the saved table."""
from types import SimpleNamespace

import pytest

from test_riders_c9 import ROOT, _portable, bundle


@pytest.mark.parametrize("talent", ["CUTTING_WIND", "VACUUM_NEEDLE"])
@pytest.mark.parametrize("vector", ["Push", "Pull", "Cut"])
@pytest.mark.parametrize("cl", [10, 11])
@pytest.mark.parametrize("damage_type", ["BLUDGEONING", "SLASHING"])
def test_slashing_riders_at_table_commit_reload_replay(tmp_path, talent, vector, cl, damage_type):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    _portable(tmp_path, "wind", ["TAL_AIR_" + talent], cl=cl, dc=60, sphere="tianxia.sphere.air")
    _portable(tmp_path, "rival", [], sphere=None, ac=0)
    wind, rival = [FACTORY_ACTOR_PREFIX + side for side in ("wind", "rival")]
    service = CombatService(ROOT, tmp_path)
    wind_bundle = bundle(["TAL_AIR_" + talent], actor_id=wind, cl=cl, dc=60, sphere="tianxia.sphere.air")
    # The printed damage choice is independent of Push/Pull/Cut. Seal each legal
    # choice into the fixture bundle so the table/replay exercises both types,
    # rather than the automatic selector's bludgeoning tie-break.
    for action in wind_bundle["action_catalog"]:
        if action["display_name"].startswith("Wind Lash:"):
            action["parameters"]["typed"]["effects"][0]["on_hit"][0]["damage_types"] = [damage_type.lower()]
    rival_bundle = bundle([], actor_id=rival, sphere=None, ac=0)
    service.tabletop_maps.save({"display_name": "C9 slashing yard", "width_squares": 20,
        "height_squares": 12, "walls": [], "starts": {"team1": [[3, 6]], "team2": [[8, 6]]}})
    arena = service.factory_arenas()["battlefield:map.c9-slashing-yard"]
    mid = service._finish_factory_match([wind_bundle, rival_bundle], [wind, rival],
        {wind: "team:1", rival: "team:2"}, {wind: {"x": 3, "y": 6}, rival: {"x": 8, "y": 6}},
        arena, [wind], [rival], control_modes={a: "MANUAL" for a in (wind, rival)},
        match_seed="C9-VECTORS", display_name="C9 slashing yard", maximum_rounds=5)["match_id"]
    table = TabletopService(service, tmp_path)

    def act(option):
        state = table.state(mid)
        return table.act(mid, option, state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"])

    for _ in range(6):
        state = table.state(mid)
        if state["menu"]["actor_id"] == wind:
            break
        act(state["menu"]["end_turn"])
    group = next(g for g in state["menu"]["actions"] if g["label"] == "Wind Lash: " + vector)
    option = next(o for o in group["options"] if rival in o["target_ids"])
    before = service._load_session(mid).engine.events[-1].sequence
    assert act(option["candidate_id"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    foe = loaded.engine.state.actors[rival]
    events = [e for e in loaded.engine.events if e.sequence > before]
    packets = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and rival in e.target_ids]
    assert packets and packets[0]["hp_damage"] > 0
    assert packets[0]["damage_type"] == damage_type
    assert len(packets) == (2 if damage_type == "SLASHING" else 1)
    if talent == "CUTTING_WIND" and damage_type == "SLASHING":
        assert packets[1]["hp_damage"] == 4  # Proficiency Bonus, retained independently of the base dice.
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"]
    if talent == "VACUUM_NEEDLE":
        assert bool(saves) == (damage_type == "SLASHING")
        healing = [m for m in foe.modifiers.values() if m.target_field == "healing_reduction"]
        assert bool(healing) == (damage_type == "SLASHING")
        if healing:
            assert healing[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert not any(c.condition_id.endswith("concentration_mode") for c in foe.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def event(kind, sequence, payload, *, source="lash", actor="wind", target="rival"):
    return SimpleNamespace(event_type=kind, sequence=sequence, payload=payload,
                           source_definition_id=source, actor_id=actor, target_ids=(target,))


@pytest.mark.parametrize("talent", ["CUTTING_WIND", "VACUUM_NEEDLE"])
@pytest.mark.parametrize("defense", ["immune", "temporary-hp"])
def test_slashing_damage_defenses_in_real_engine(talent, defense):
    from test_riders_c9 import air_fight, rig, use, ME, AN

    e = air_fight(["TAL_AIR_" + talent], cl=11, dc=60)
    foe = e.state.actors[AN]
    foe.armor_class = 0
    rig(e)
    for action in e.action_catalog.values():
        if action.owner_id == ME and action.display_name.startswith("Wind Lash:"):
            action.parameters["typed"]["effects"][0]["on_hit"][0]["damage_types"] = ["slashing"]
    if defense == "immune":
        e._add_modifier(foe, "test:immune", "damage_immunity", "SET", "SLASHING", "SELF", expires_on="UNTIL_REMOVED")
    else:
        foe.temporary_hp = 100
    events = use(e, "Wind Lash: Cut", target=AN)
    packets = [x.payload for x in events if x.event_type == "DAMAGE_COMMITTED" and AN in x.target_ids]
    assert len(packets) == (1 if defense == "immune" else 2)
    assert all(p["hp_damage"] == 0 for p in packets)
    assert (packets[0]["temporary_hp_absorbed"] > 0) == (defense == "temporary-hp")
    assert bool([m for m in foe.modifiers.values() if m.target_field == "healing_reduction"]) == (
        talent == "VACUUM_NEEDLE" and defense == "temporary-hp")


@pytest.mark.parametrize("kind,hp,temp,hit,allowed", [
    ("SLASHING", 3, 0, True, True), ("SLASHING", 0, 3, True, True),
    ("SLASHING", 0, 0, True, False), ("BLUDGEONING", 3, 0, True, False),
    ("SLASHING", 3, 0, False, False),
])
def test_snapshot_uses_only_current_positive_slashing_packet(kind, hp, temp, hit, allowed):
    from combat.ext.air_currents import slashing_hit, slashing_rider_allowed
    marker = {"air_slashing_rider": True}
    roll = {"reason": "ATTACK:lash:2"}
    # Old slashing damage and a different source/target must never qualify this strike.
    events = [event("DAMAGE_COMMITTED", 1, {"damage_type": "SLASHING", "hp_damage": 9}),
              event("ATTACK_ROLLED", 2, roll),
              event("DAMAGE_COMMITTED", 3, {"damage_type": "SLASHING", "hp_damage": 9}, source="other"),
              event("DAMAGE_COMMITTED", 4, {"damage_type": "SLASHING", "hp_damage": 9}, target="other"),
              event("DAMAGE_COMMITTED", 5, {"damage_type": kind, "hp_damage": hp, "temporary_hp_absorbed": temp})]
    target = SimpleNamespace(entity_id="rival", concentration=None, conditions={})
    ctx = SimpleNamespace(engine=SimpleNamespace(events=events), actor=SimpleNamespace(entity_id="wind"),
                          target=target, source="lash", attack_result=roll,
                          attack_effect={"on_hit": [marker]}, damage_cache={})
    slashing_hit(ctx, target, hit, False)
    # A later bonus cannot supply its own prerequisite.
    events.append(event("DAMAGE_COMMITTED", 6, {"damage_type": "SLASHING", "hp_damage": 9}))
    assert (slashing_rider_allowed(ctx, marker) is not False) == allowed
    assert slashing_rider_allowed(ctx, {}) is None  # Legacy/unrelated effects retain behavior.
    assert slashing_rider_allowed(ctx, {**marker, "air_requires_concentration": True}) is False
    # A later bludgeoning strike must reset the snapshot, even against the same target.
    ctx.attack_result = {"reason": "ATTACK:lash:3"}
    events.extend([event("ATTACK_ROLLED", 7, ctx.attack_result),
                   event("DAMAGE_COMMITTED", 8, {"damage_type": "BLUDGEONING", "hp_damage": 3})])
    slashing_hit(ctx, target, True, False)
    assert slashing_rider_allowed(ctx, marker) is False
