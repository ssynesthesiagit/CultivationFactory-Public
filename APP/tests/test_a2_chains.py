"""Printed Chains effects through table transactions, cold reload and replay."""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.auto_worker1_support import LEFT, RIGHT, act, fight as service_fight, turn

BINDING = "tianxia.talent.chains.binding_chain"
SCRIPT = "tianxia.talent.chains.chain_script_seal"
PRISON = "tianxia.talent.chains.chain_prison"
SPATIAL = "condition:typed.chains_spatial_lock"


def fight(*args, **kwargs):
    """Optional red run seals exact base authority rows into synthetic bundles.

    This is data restoration, not a runtime patch or an exact-base engine run.
    The ordinary run always uses the real current compiler and authority.
    """
    import os
    if os.environ.get("A2CHAINS_BASE_DATA") == "1":
        import json
        import subprocess
        from pathlib import Path
        old = json.loads(subprocess.check_output(["git", "show",
            "8fee9da6:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"],
            cwd=Path(__file__).resolve().parents[2]))["mechanics"]
        prior = kwargs.get("bundle_edit")
        def restore(bundle):
            if prior:
                prior(bundle)
            for action in bundle["action_catalog"]:
                typed = action.get("parameters", {}).get("typed", {})
                key = typed.get("option_of") or typed.get("source")
                if key in old and (str(key).startswith("tianxia.talent.chains.")):
                    typed["effects"] = old[key].get("effects", [])
                    typed["riders"] = old[key].get("riders", [])
        kwargs["bundle_edit"] = restore
    return service_fight(*args, **kwargs)


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


@pytest.mark.parametrize("dc,condition", [(0, "bound"), (100, "restrained")])
def test_binding_chain_both_save_branches_reload_and_expire(tmp_path, dc, condition):
    combat, table, mid = fight(tmp_path, [BINDING], left_save_dc=dc)
    before = cold(tmp_path, mid).state.actors[LEFT].resources.copy()
    assert act(table, mid, "Binding Chain", target_id=RIGHT)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    assert any(c.condition_id == "condition:typed." + condition
               for c in engine.state.actors[RIGHT].conditions.values())
    assert sum(before.values()) - sum(engine.state.actors[LEFT].resources.values()) == 2
    turn(table, mid, RIGHT)
    assert any(c.condition_id == "condition:typed." + condition
               for c in cold(tmp_path, mid).state.actors[RIGHT].conditions.values())
    turn(table, mid, LEFT)
    assert not any(c.condition_id == "condition:typed." + condition
                   for c in cold(tmp_path, mid).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("talent,name", [(SCRIPT, "Chain-Script Seal"), (PRISON, "Chain Prison")])
@pytest.mark.parametrize("ai", [False, True])
def test_chains_failed_teleport_save_stops_paid_attempt_after_reload(tmp_path, talent, name, ai):
    def paid_teleport(bundle):
        for action in bundle["action_catalog"]:
            if action["display_name"] == "Cause":
                action["economy"] = "ACTION"
                action["costs"] = [["resource:core.qi", 1]]
    combat, table, mid = fight(tmp_path, [talent], cause=[
        {"type": "teleport", "applies_to": "self", "distance_ft": 15},
    ], cause_target="SELF", bundle_edit=paid_teleport)
    assert act(table, mid, name, target_id=RIGHT)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    assert any(c.condition_id == SPATIAL for c in engine.state.actors[RIGHT].conditions.values())
    turn(table, mid, RIGHT)
    loaded = cold(tmp_path, mid)
    saves = len([e for e in loaded.events if e.event_type == "SAVE_ROLLED"])
    actor = loaded.state.actors[RIGHT]
    before, qi = actor.position, actor.resources["resource:core.qi"]
    from tests.auto_worker1_support import resolve, action_sender
    resolve(action_sender(combat, table, mid, "Cause", ai=ai))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].position == before
    assert engine.state.actors[RIGHT].resources["resource:core.qi"] == qi - 1
    assert not engine.state.actors[RIGHT].action_available
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == saves + 1


def test_script_checks_only_first_teleport_each_round_and_records_usage(tmp_path):
    from tests.auto_worker1_support import resolve
    combat, table, mid = fight(tmp_path, [SCRIPT], cause=[
        {"type": "teleport", "applies_to": "self", "distance_ft": 15},
    ], cause_target="SELF")
    assert act(table, mid, "Chain-Script Seal", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Cause", answers))
    engine = cold(tmp_path, mid)
    held, = [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == SPATIAL]
    assert held.data["attempt_round"] == engine.state.round_number
    assert all(type(v) in (int, str) for v in held.data.values())
    prior = len([e for e in engine.events if e.event_type == "SAVE_ROLLED"])
    resolve(lambda answers: act(table, mid, "Cause", answers))
    engine = cold(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == prior
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Cause", answers))
    assert len([e for e in cold(tmp_path, mid).events if e.event_type == "SAVE_ROLLED"]) == prior + 1


@pytest.mark.parametrize("order", [
    ("Chain Prison", "Chain-Script Seal"),
    ("Chain-Script Seal", "Chain Prison"),
])
def test_overlapping_spatial_locks_consume_first_attempt_independent_of_order(tmp_path, order):
    from tests.auto_worker1_support import settle

    def setup_actions(bundle):
        # Cast both real authority effects on the same turn without altering
        # their save DC, costs, concentration or condition lifecycle.
        for action in bundle["action_catalog"]:
            if action["display_name"] in order:
                action["economy"] = "NONE"

    combat, table, mid = fight(tmp_path, [PRISON, SCRIPT], bundle_edit=setup_actions,
        right_score=240,
        prepare=[{"type": "condition", "condition": "test_chains_overlap_failure",
                  "duration": "until_removed",
                  "condition_data": {"rule": {"save_mode": {
                      "STR": "AUTO_FAIL", "CHA": "AUTO_FAIL"}}}}],
        cause=[
            {"type": "teleport", "applies_to": "self", "distance_ft": 15},
            # After the first attempt, the synthetic failure condition ends
            # through a journaled effect; the high underlying save succeeds.
            {"type": "remove_condition", "applies_to": "self",
             "condition": "test_chains_overlap_failure"},
        ], cause_target="SELF")
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    for name in order:
        assert act(table, mid, name, target_id=RIGHT)["status"] == "COMMITTED"
        cold(tmp_path, mid)
    turn(table, mid, RIGHT)
    engine = cold(tmp_path, mid)
    before = engine.state.actors[RIGHT].position
    prior = len([e for e in engine.events if e.event_type == "SAVE_ROLLED"])

    def destination(prompt):
        return [prompt["choice"]["options"][-1]["id"]]

    settle(lambda answers: act(table, mid, "Cause", answers), choose=destination)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].position == before
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == prior + 2
    seal, = [c for c in engine.state.actors[RIGHT].conditions.values()
             if c.condition_id == SPATIAL and c.data["ability"] == SCRIPT]
    assert seal.data["attempt_round"] == engine.state.round_number
    assert all(type(v) in (int, str) for v in seal.data.values())

    # A fresh service sees the consumed seal; only the prison saves again.
    from combat.tabletop_service import TabletopService
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    settle(lambda answers: act(table, mid, "Cause", answers), choose=destination)
    engine = cold(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == prior + 3
    assert engine.state.actors[RIGHT].position != before
    seal, = [c for c in engine.state.actors[RIGHT].conditions.values()
             if c.condition_id == SPATIAL and c.data["ability"] == SCRIPT]
    assert seal.data["attempt_round"] == engine.state.round_number


def test_recasting_script_refreshes_only_its_casters_seal_and_preserves_prison(tmp_path):
    combat, table, mid = fight(tmp_path, [SCRIPT, PRISON])
    assert act(table, mid, "Chain Prison", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert act(table, mid, "Chain-Script Seal", target_id=RIGHT)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    rows = [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == SPATIAL]
    assert {c.data["ability"] for c in rows} == {PRISON, SCRIPT}
    old = {c.data["ability"]: c.instance_id for c in rows}
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert act(table, mid, "Chain-Script Seal", target_id=RIGHT)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    rows = [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == SPATIAL]
    assert len(rows) == 2
    new = {c.data["ability"]: c.instance_id for c in rows}
    assert new[PRISON] == old[PRISON]
    assert new[SCRIPT] != old[SCRIPT]


@pytest.mark.parametrize("owns", [False, True])
def test_script_successful_initial_save_and_unowned_actor_can_teleport(tmp_path, owns):
    from tests.auto_worker1_support import resolve
    combat, table, mid = fight(tmp_path, [SCRIPT] if owns else [], left_save_dc=0,
        cause=[{"type": "teleport", "applies_to": "self", "distance_ft": 15}], cause_target="SELF")
    if owns:
        assert act(table, mid, "Chain-Script Seal", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    engine = cold(tmp_path, mid)
    assert not any(c.condition_id == SPATIAL for c in engine.state.actors[RIGHT].conditions.values())
    before = engine.state.actors[RIGHT].position
    def choose_destination(prompt):
        options = prompt["choice"]["options"]
        return [options[-1]["id"]]
    from tests.auto_worker1_support import settle
    settle(lambda answers: act(table, mid, "Cause", answers), choose=choose_destination)
    assert cold(tmp_path, mid).state.actors[RIGHT].position != before


@pytest.mark.parametrize("ending", ["concentration", "destruction"])
def test_prison_end_clears_all_restrictions(tmp_path, ending):
    combat, table, mid = fight(tmp_path, [PRISON], cause=[
        {"type": "object_damage", "flat": 1000, "damage_types": ["force"]}
        if ending == "destruction" else
        {"type": "damage", "flat": 1000, "damage_type": "FORCE", "applies_to": "target"},
    ], cause_target="OBJECT" if ending == "destruction" else "HOSTILE_ENTITY")
    assert act(table, mid, "Chain Prison", target_id=RIGHT)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    prison, = [o for o in engine.state.objects.values() if o.object_kind == "BOUND_CHAIN"]
    guarded = prison.component["bound"]["conditions"]
    assert len(guarded) == 3
    assert prison.ac == 17 and prison.maximum_hp == 8 * 15
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=prison.object_id if ending == "destruction" else LEFT)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    assert not set(guarded).intersection(engine.state.actors[RIGHT].conditions)
    assert engine.state.objects[prison.object_id].destroyed


def test_chain_armor_has_no_combat_reminders(tmp_path):
    from tests.test_auto26_chains import cast
    combat, table, mid = fight(tmp_path, ["tianxia.talent.chains.chain_armor"])
    cast(combat, table, mid, "Chain Armor")
    engine = cold(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT
                  and a.display_name == "Chain Armor")
    assert not action.parameters["typed"]["riders"]
    assert any(m.target_field == "armor_class" and m.value == 2 for m in engine.state.actors[LEFT].modifiers.values())


def test_destroying_prison_after_strength_escape_still_rings_prisoners_bell(tmp_path):
    bell = "tianxia.talent.chains.prisoner_s_bell"
    combat, table, mid = fight(tmp_path, [PRISON, bell], left_save_dc=0, right_score=60,
        prepare=[{"type": "condition", "condition": "test_initial_prison_failure",
                  "expires_on": "START_OF_TARGET_NEXT_TURN",
                  "condition_data": {"rule": {"save_mode": {"STR": "AUTO_FAIL"}}}}],
        cause=[{"type": "object_damage", "flat": 1000, "damage_types": ["force"]}],
        cause_target="OBJECT")
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    assert act(table, mid, "Chain Prison", target_id=RIGHT)["status"] == "COMMITTED"
    prison, = [o for o in cold(tmp_path, mid).state.objects.values() if o.object_kind == "BOUND_CHAIN"]
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)  # the prisoner's end-of-turn Strength save succeeds
    turn(table, mid, RIGHT)  # the temporary Bound state expires
    engine = cold(tmp_path, mid)
    assert not any(c.condition_id in ("condition:typed.restrained", "condition:typed.bound")
                   for c in engine.state.actors[RIGHT].conditions.values())
    assert not engine.state.objects[prison.object_id].destroyed
    before = len([e for e in engine.events if e.source_definition_id == bell])
    assert act(table, mid, "Cause", target_id=prison.object_id)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    assert engine.state.objects[prison.object_id].destroyed
    assert not any(c.condition_id == SPATIAL for c in engine.state.actors[RIGHT].conditions.values())
    assert len([e for e in engine.events if e.source_definition_id == bell]) == before + 1


@pytest.mark.parametrize("dc", [0, 100])
def test_heavenly_anchor_teleport_prohibition_and_expiry_reload(tmp_path, dc):
    talent = "tianxia.talent.chains.heavenly_anchor"
    combat, table, mid = fight(tmp_path, [talent], left_save_dc=dc, cause=[
        {"type": "teleport", "applies_to": "self", "distance_ft": 15},
    ], cause_target="SELF")
    assert act(table, mid, "Heavenly Anchor", target_id=RIGHT)["status"] == "COMMITTED"
    from combat.typed_executor import condition_rules
    engine = cold(tmp_path, mid)
    assert any(row.get("no_teleport") for row in condition_rules(engine.state.actors[RIGHT]))
    turn(table, mid, RIGHT)
    engine = cold(tmp_path, mid)
    if dc == 0:
        assert not any(row.get("no_teleport") for row in condition_rules(engine.state.actors[RIGHT]))
        return
    before = engine.state.actors[RIGHT].position
    assert act(table, mid, "Cause")["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].position == before
    saves = len([e for e in engine.events if e.event_type == "SAVE_ROLLED"])
    turn(table, mid, LEFT)
    engine = cold(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == saves + 1
    assert any(row.get("no_teleport") for row in condition_rules(engine.state.actors[RIGHT]))


@pytest.mark.parametrize("dc,condition", [(0, "bound"), (100, "restrained")])
@pytest.mark.parametrize("cl,count", [(15, 3), (25, 4)])
def test_chain_web_full_effects_through_table_reload(tmp_path, dc, condition, cl, count):
    from combat import zones
    combat, table, mid = fight(tmp_path, ["tianxia.talent.chains.chain_web"],
                              left_save_dc=dc, cl=cl)
    from tests.auto_worker1_support import cell_send
    assert cell_send(table, mid, "Chain Web", (4, 6))([])["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    zone, = [z for z in engine.state.zones.values() if z.active and z.owner_id == LEFT]
    assert zone.trigger_profile["difficult"] == "all"
    assert zones.zone_is_difficult(engine, zone, engine.state.actors[LEFT])
    assert zones.zone_is_difficult(engine, zone, engine.state.actors[RIGHT])
    action = engine.action_catalog[zone.source_definition_id]
    assert not action.parameters["typed"]["riders"]
    turn(table, mid, RIGHT)
    engine = cold(tmp_path, mid)
    held, = [c for c in engine.state.actors[RIGHT].conditions.values()
             if c.condition_id == "condition:typed." + condition]
    assert held.expires_on.startswith("START_OF_TURN_AT:")
    damage = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
              and e.target_ids == (RIGHT,)]
    assert len(damage) == 1
    assert damage[0].payload["expression"].startswith(f"{count}d8")
    # The victim's next turn is later than the source's next turn.
    turn(table, mid, LEFT)
    assert held.instance_id in cold(tmp_path, mid).state.actors[RIGHT].conditions
