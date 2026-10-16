"""Fold Prison isolates a saved table target from manual and AI attacks."""
import pytest
from combat.ext.spatial_absence import ABSENT

from tests.test_hunt32_edge import EDGE, FOE, OWNER, act, match, reload

PRISON = "tianxia.talent.space.fold_prison"
ALLY = "actor:factory.h32-ally"
SCRIPT = "tianxia.subpath.qi.calligraphy_cultivator.feature.heaven_s_script"


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("imprisoned", [True, False])
def test_prison_blocks_map_owned_glass_on_table_movement(tmp_path, mode, imprisoned):
    """Map ownership must survive the synthetic self-caster used for terrain."""
    combat, table, mid = match(tmp_path, [PRISON] if imprisoned else [], allies=True,
                               ally_mode=mode, map_terrain=[{
                                   "terrain": "shattered glass terrain",
                                   "cells": [[x, y] for x in range(3, 9) for y in range(4, 9)], "pb": 3}])
    if imprisoned:
        assert act(table, mid, "Fold Prison", FOE)["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"
    if mode == "MANUAL":
        assert act(table, mid)["status"] == "COMMITTED"
    else:
        for _ in range(12):
            assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
            if table.state(mid)["menu"]["actor_id"] != ALLY:
                break
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    victim = engine.state.actors[FOE]
    hp = victim.current_hp
    start = len(engine.events)
    # The printed folded victim has disappeared; its initiative slot stays,
    # but there is no body that can walk through the ordinary map.
    state = table.state(mid)
    menu = state["menu"]
    if imprisoned:
        assert not any(c.kind == "MOVE" for c in engine.legal_candidates())
        assert victim.current_hp == hp
        assert any(c.condition_id == ABSENT for c in victim.conditions.values())
        return
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == "system:combat.movement" and c.destination is not None
                     and 3 <= c.destination.x < 9 and 4 <= c.destination.y < 9)
    answers = []
    for _ in range(8):
        result = table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        answers.append({**result["reaction"]["context"], "selection": "DECLINE", "option_ids": []})
    assert result["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == hp - (0 if imprisoned else 3)
    hits = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"
            and e.source_definition_id == "system:battlefield.terrain" and FOE in e.target_ids]
    assert bool(hits) is not imprisoned
    triggers = [e for e in engine.events[start:] if e.event_type == "PASSIVE_TRIGGERED"
                and e.source_definition_id == "system:battlefield.terrain" and FOE in e.target_ids]
    assert bool(triggers) is not imprisoned


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("imprisoned", [True, False])
def test_prison_blocks_unsaved_area_damage_and_conditions(tmp_path, mode, imprisoned):
    """An actual compiled area packet must respect cover without needing a save."""
    combat, table, mid = match(tmp_path, [PRISON] if imprisoned else [],
                               allies=True, ally_mode=mode, ally_mids=[],
                               ally_setup_actions=[{'name': 'Unsaved area probe', 'economy': 'ACTION',
                                   'target': 'CELL', 'radius_ft': 20, 'any_cell': False,
                                   'player_only': False, 'expected_damage': 100,
                                   'typed': {'area': {'shape': 'sphere', 'size_ft': 20}},
                                   'effects': [{'type': 'damage', 'dice': {'count': 1, 'sides': 4, 'modifier': 3},
                                                'damage_types': ['force'], 'applies_to': 'target'},
                                               {'type': 'condition', 'condition': 'prone',
                                                'duration': 'until_removed', 'applies_to': 'target'}]}],
                               extra_foes=[("actor:factory.h32-visible-foe", 1000)])
    # The reviewed Heaven Character menu now separates its printed choices
    # and no longer supplies the old unsaved damage+Prone packet. This sealed
    # synthetic probe preserves that general Fold Prison regression exactly.
    packet_source = next(action.source_definition_id for action in reload(combat, tmp_path, mid).action_catalog.values()
                         if action.display_name == 'Unsaved area probe')
    if imprisoned:
        assert act(table, mid, "Fold Prison", FOE)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    before = engine.state.actors[FOE].model_dump(mode="json")
    assert act(table, mid)["status"] == "COMMITTED"
    start = len(reload(combat, tmp_path, mid).events)
    if mode == "MANUAL":
        state = table.state(mid)
        menu = state["menu"]
        group = next(g for g in menu["actions"] if g["label"] == "Unsaved area probe")
        option = next(o for o in group["options"] if o.get("destination") == before["position"])
        assert table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], [])["status"] == "COMMITTED"
    else:
        for _ in range(12):
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            assert result["status"] == "COMMITTED"
            if any(packet_source == e.source_definition_id and e.event_type == "DAMAGE_ROLLED"
                   for e in combat._load_session(mid).engine.events[start:]):
                break
    engine = reload(combat, tmp_path, mid)
    events = engine.events[start:]
    assert any(packet_source == e.source_definition_id and e.event_type == "DAMAGE_ROLLED" for e in events)
    after = engine.state.actors[FOE]
    if not imprisoned:
        assert after.current_hp < before["current_hp"], "Unimprisoned area recipients must still take damage"
        assert any(c.condition_id == "condition:typed.prone" for c in after.conditions.values())
        return
    assert not any(FOE in e.target_ids and packet_source == e.source_definition_id
                   and e.event_type in ("DAMAGE_COMMITTED", "CONDITION_APPLIED", "MODIFIER_APPLIED", "ACTOR_MOVED")
                   for e in events), "The folded loop must exclude outside area effects, even without a save"
    assert after.current_hp == before["current_hp"]
    assert after.position.model_dump(mode="json") == before["position"]
    assert {k: c.model_dump(mode="json") for k, c in after.conditions.items()} == before["conditions"]
    assert not after.modifiers


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_prison_blocks_outside_targeting_until_victims_turn_ends(tmp_path, mode):
    combat, table, mid = match(tmp_path, [PRISON], allies=True, ally_mode=mode)
    assert act(table, mid, "Fold Prison", FOE)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    assert any(c.condition_id == ABSENT for c in engine.state.actors[FOE].conditions.values())
    assert act(table, mid)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == ALLY
    assert not any(FOE in c.target_ids for c in engine.legal_candidates()), "Prison must protect its victim from outside targets"
    if mode == "LOCAL_AUTO":
        start = len(engine.events)
        for _ in range(12):
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            assert result["status"] == "COMMITTED"
            if result["state"]["menu"]["actor_id"] != ALLY:
                break
        engine = reload(combat, tmp_path, mid)
        assert not any(e.actor_id == ALLY and FOE in e.target_ids and e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED")
                       for e in engine.events[start:])
    else:
        assert act(table, mid)["status"] == "COMMITTED"
    # The affected creature's existing expiry/repeat-save processing releases it.
    assert table.state(mid)["menu"]["actor_id"] == FOE
    assert act(table, mid)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    assert not any(c.condition_id == ABSENT for c in engine.state.actors[FOE].conditions.values())
    assert any(c.display_name == "Spatial Edge" and c.target_ids == (FOE,) for c in engine.legal_candidates())


def test_prison_source_ownership_area_saves_and_concentration_release(tmp_path):
    from combat.ext.spatial_absence import subjects as absence_area_subject, recipients as absence_recipient
    from combat.typed_executor import Context

    combat, table, mid = match(tmp_path, [PRISON], allies=True)
    assert act(table, mid, "Fold Prison", FOE)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    owner, victim = engine.state.actors[OWNER], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if (a.parameters.get("typed") or {}).get("source") == PRISON)
    ctx = Context(engine, owner, action, None, action.parameters["typed"], [victim], victim, {})
    # Fresh Fold Prison is routed through the shared absence provider. The
    # legacy adapter intentionally recognizes only old Incapacitated saves.
    assert absence_area_subject(ctx, {"type": "save"}, victim) is False
    assert absence_recipient(engine, owner, victim, action) is False
    assert absence_recipient(engine, owner, engine.state.actors[ALLY], action) is None
    assert "total cover" in next(c.data["label"] for c in victim.conditions.values() if c.condition_id == ABSENT)
    # Supplementary engine lifecycle check on a reloaded scratch fight, not a table commit claim.
    engine._end_concentration(owner, "TEST_RELEASE")
    assert absence_recipient(engine, owner, victim, action) is None
    engine._apply_condition(victim, "condition:typed.incapacitated", "test:unrelated", OWNER,
                            expires_on="END_OF_HOLDER_NEXT_TURN")
    assert absence_recipient(engine, owner, victim, action) is None


def test_zone_isolation_retains_origin_without_masking_existing_conditions(tmp_path):
    """Supplementary pure eligibility/lifecycle checks on a reloaded scratch table."""
    from combat import zones

    combat, table, mid = match(tmp_path, [PRISON], allies=True, map_terrain=[{
        "terrain": "shattered glass terrain", "cells": [[5, 6]], "pb": 3}])
    assert act(table, mid, "Fold Prison", FOE)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    owner, victim = engine.state.actors[OWNER], engine.state.actors[FOE]
    [ground] = zones.map_zones(engine)
    before = ground.model_dump(mode="json")
    assert not zones.subject_allowed(engine, ground, victim)
    assert zones.subject_allowed(engine, ground, owner)
    # A victim-owned map zone is still outside the loop, and cannot affect
    # either its own trapped owner or other creatures while that owner is held.
    owned = ground.model_copy(update={"owner_id": FOE})
    assert not zones.subject_allowed(engine, owned, owner)
    assert not zones.subject_allowed(engine, owned, victim)
    assert ground.model_dump(mode="json") == before  # a pure query consumes no trigger
    engine._apply_condition(victim, "condition:typed.burning", "test:prior_burn", OWNER,
                            expires_on="UNTIL_REMOVED")
    burn = next(c.instance_id for c in victim.conditions.values() if c.condition_id.endswith("burning"))
    assert burn in victim.conditions
    engine._end_concentration(owner, "TEST_RELEASE")
    assert zones.subject_allowed(engine, ground, victim)
    assert zones.subject_allowed(engine, owned, owner)
    assert burn in victim.conditions  # isolation never clears a victim-carried effect
    engine._apply_condition(victim, "condition:typed.incapacitated", "test:unrelated", OWNER,
                            expires_on="END_OF_HOLDER_NEXT_TURN")
    assert zones.subject_allowed(engine, ground, victim)
