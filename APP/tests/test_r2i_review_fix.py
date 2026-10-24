"""Composed table transactions for the three R2 pre-merge findings."""
import importlib

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

R = importlib.import_module("tests.test_riders_lane2")
SOVEREIGN = "TAL_IRON_FIST_SOVEREIGN_IRON_BODY_INCARNATION"
COUNTER = "TAL_IRON_FIST_COUNTER_PALM"
CRANE = "TAL_IRON_FIST_TIGER_CRANE_ALTERNATION"
DIAGNOSIS = "TAL_IRON_FIST_EIGHT_GATE_DIAGNOSIS"
TAP = "tianxia.talent.pressure_points.intercepting_tap"


def fixture(tmp_path, talents, *, strike_hits=True, bell=False, foe_sphere=None, foe_talents=(), third=False, boon=False):
    bundles = []
    for aid in ((R.ME, R.FOE, "visible") if third else (R.ME, R.FOE)):
        sheet = R.A._sheet(R.IRON_FIST if aid == R.ME else None,
                           talents if aid == R.ME else [], R.KIT, dc=-40)
        if aid == R.FOE and foe_sphere:
            sheet = R.A._sheet(foe_sphere, foe_talents, R.KIT, dc=-40)
            if foe_sphere == "tianxia.sphere.sabers":
                sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "quantity": 1}]}}]
        if aid == "visible":
            sheet = R.A._sheet(None, [], R.KIT, dc=-40)
        if bell and aid == R.ME:
            points = R.A._sheet("tianxia.sphere.pressure_points", [], R.KIT)["spheres_and_talents"]
            for key in ("sphere_record_ids", "automatic_sphere_component_record_ids"):
                sheet["spheres_and_talents"][key] += points[key]
        bundle = compile_character(sheet, actor_id=aid, reaction_plan={"ask": True})
        bundle["actor_template"].update(
            armor_class=0 if bell or (aid != R.ME and strike_hits) else 1000,
            maximum_hp=2000, speed_ft=30 if aid == R.ME else 0,
            initiative_bonus=100 if aid == R.ME else -100 if aid == R.FOE else -200)
        if aid == R.FOE:
            bundle["actor_template"]["speed_ft"] = 30 if foe_sphere else 0
        # Fixture resource capacity keeps activation and Counter Palm composable;
        # all spending still occurs through real table actions/reactions.
        for resource in bundle["actor_template"]["resources"]:
            if resource["resource_id"] == "resource:core.martial_focus":
                resource.update(initial=2, maximum=2)
        for action in bundle["action_catalog"]:
            typed = action["parameters"].get("typed")
            if typed:
                if typed.get("zone_spec"):
                    # A single opaque smoke cell isolates the obscured target.
                    typed["zone_spec"].update(size_ft=5, obscured="heavy")
                typed["numbers"]["attack_bonus"] = 100
                if aid == R.FOE and action["display_name"] == "Forward Cut":
                    typed["numbers"]["attack_bonus"] = 2000
                for row in typed.get("effects") or []:
                    if row.get("type") == "attack":
                        row["count"] = 2 if bell and aid == R.FOE else 1
                if typed.get("weapon"):
                    typed["weapon"]["fixed_damage"] = 40
        bundle.pop("bundle_sha256", None)
        if boon and aid == R.ME:
            # A fixture next-roll boon delivered after Counter Palm's roll is
            # pre-existing when the independent Sovereign strike is prepared.
            for row in bundle["typed_reactions"]:
                if row.get("feature_id") == COUNTER:
                    row["effects"].append({"type": "advantage", "applies_to": "self", "on": "your next attack roll", "expires_on": "CONSUMED"})
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(R.ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="R2I-REVIEW", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": [R.ME, R.FOE, "visible"] if third else [R.ME, R.FOE],
                      "team_by_actor": {R.ME: "team:a", R.FOE: "team:b", "visible": "team:b"},
                      "starting_positions": {R.ME: {"x": 4, "y": 6}, R.FOE: {"x": 5, "y": 6}, "visible": {"x": 0, "y": 6}}})
    return combat, TabletopService(combat, tmp_path), session.match_id


def take(combat, table, mid, name, target=None, *, choices=(), destination=None, declines=()):
    menu = table.state(mid)["menu"]
    candidate_id = menu["end_turn"] if name == "End Turn" else next(
        c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
        if c["display_name"] == name and (target is None or target in c["target_ids"])
        and (destination is None or c.get("destination") == destination))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(20):
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        preferred = [v for v in choices if v in options]
        if "Bloodied" in options:
            preferred = ["Bloodied", "Weakest physical save"]
        if "Tiger" in options:
            preferred = ["Crane"]
        answer = {**prompt["context"], "selection": "USE",
                  "option_ids": preferred or options[:1]}
        if any(v.startswith("TAL_IRON_FIST_") for v in options):
            answer.update(selection="DECLINE", option_ids=[])
        if any(v in prompt["context"]["reaction_source_id"] for v in declines):
            answer.update(selection="DECLINE", option_ids=[])
        answers.append(answer)
    assert result["status"] == "COMMITTED"
    loaded = combat._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return prompts


def reload(tmp_path, combat, mid):
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


@pytest.mark.parametrize("destination,expected", [("1,6", False), ("3,6", True)])
def test_sovereign_after_counter_palm_crane_respects_real_reach(tmp_path, destination, expected):
    combat, table, mid = fixture(tmp_path, [COUNTER, CRANE, SOVEREIGN])
    take(combat, table, mid, "Sovereign Iron-Body Incarnation", R.ME)
    take(combat, table, mid, "End Turn")
    start = len(combat._load_session(mid).engine.events)
    prompts = take(combat, table, mid, "Fu (Short Axe) attack", R.ME, choices=["cell:" + destination])
    engine = reload(tmp_path, combat, mid)
    events = engine.events[start:]
    assert any(e.event_type == "ATTACK_ROLLED" and e.source_definition_id == COUNTER for e in events)
    assert any("cell:" + destination in [o["id"] for o in p.get("choice", {}).get("options", [])] for p in prompts), [
        (p["context"]["reaction_source_id"], [o["id"] for o in p.get("choice", {}).get("options", [])]) for p in prompts]
    assert (engine.state.actors[R.ME].position.x, engine.state.actors[R.ME].position.y) == tuple(map(int, destination.split(",")))
    strikes = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.source_definition_id.endswith(".sovereign_counterstrike")]
    assert bool(strikes) == expected
    assert bool([e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith(".sovereign_counterstrike")]) == expected
    if expected:
        action = next(a for a in engine.action_catalog.values() if a.owner_id == R.ME and a.display_name == R.STRIKE)
        assert engine._distance_actor_to_actor(engine.state.actors[R.ME], engine.state.actors[R.FOE]) <= int(action.reach_ft or action.range_ft or 5) + 10


@pytest.mark.parametrize("reaction", [COUNTER, SOVEREIGN, "both"])
@pytest.mark.parametrize("strike_hits", [False, True])
def test_diagnosis_first_reaction_unarmed_roll_consumes_window(tmp_path, reaction, strike_hits):
    talents = [DIAGNOSIS, COUNTER, SOVEREIGN] if reaction == "both" else [DIAGNOSIS, reaction]
    combat, table, mid = fixture(tmp_path, talents, strike_hits=strike_hits)
    if reaction in (SOVEREIGN, "both"):
        take(combat, table, mid, "Sovereign Iron-Body Incarnation", R.ME)
    take(combat, table, mid, "Eight-Gate Diagnosis", R.ME, choices=[R.FOE, "Wisdom (Medicine)"])
    engine = reload(tmp_path, combat, mid)
    assert any(c.condition_id.endswith(R.FOE) and "iron_diagnosis" in c.condition_id for c in engine.state.actors[R.ME].conditions.values())
    take(combat, table, mid, "End Turn")
    start = len(combat._load_session(mid).engine.events)
    take(combat, table, mid, "Fu (Short Axe) attack", R.ME)
    engine = reload(tmp_path, combat, mid)
    strikes = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == R.ME]
    assert len(strikes) == (2 if reaction == "both" else 1) and strikes[0].payload["mode"] == "ADVANTAGE"
    assert all(e.payload["mode"] == "NORMAL" for e in strikes[1:])
    assert strikes[0].payload["provisional_hit"] == strike_hits
    assert not any("iron_diagnosis" in c.condition_id for c in engine.state.actors[R.ME].conditions.values())
    take(combat, table, mid, "End Turn")
    start = len(combat._load_session(mid).engine.events)
    take(combat, table, mid, R.STRIKE, R.FOE)
    engine = reload(tmp_path, combat, mid)
    ordinary = [e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == R.ME]
    assert ordinary and all(e.payload["mode"] == "NORMAL" for e in ordinary)


def test_bell_binds_original_hit_across_nested_intercepting_tap_and_reload(tmp_path):
    results = []
    for softened in (False, True):
        path = tmp_path / ("softened" if softened else "control")
        combat, table, mid = fixture(path, [R.BELL, TAP], bell=True)
        # Open via a real strike, then on the next turn apply Bell to that mark.
        take(combat, table, mid, R.STRIKE, R.FOE)
        take(combat, table, mid, "End Turn")
        take(combat, table, mid, "End Turn")
        take(combat, table, mid, "Choose Bell-Ringing Body Shot: " + ("Softened blows" if softened else "No Dash"))
        take(combat, table, mid, R.STRIKE, R.FOE)
        engine = reload(path, combat, mid)
        held = [c for c in engine.state.actors[R.FOE].conditions.values() if c.condition_id.endswith("next_attack_damage")]
        assert bool(held) == softened
        cut = int(held[0].data["amount"]) if held else 0
        take(combat, table, mid, "End Turn")
        start = len(combat._load_session(mid).engine.events)
        prompts = take(combat, table, mid, "Fu (Short Axe) attack", R.ME)
        engine = reload(path, combat, mid)
        events = engine.events[start:]
        rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
        assert [e.actor_id for e in rolls] == [R.FOE, R.ME, R.FOE]
        assert rolls[1].source_definition_id == TAP
        assert any(TAP in p["context"]["reaction_source_id"] for p in prompts)
        damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == R.FOE and R.ME in e.target_ids]
        assert len(damage) == 2
        assert rolls[0].sequence < rolls[1].sequence < damage[0].sequence < rolls[2].sequence
        assert not any(c.condition_id.endswith("next_attack_damage") for c in engine.state.actors[R.FOE].conditions.values())
        results.append(([e.payload["hp_damage"] for e in damage], cut))
    assert results[1][0][0] == results[0][0][0] - results[1][1]
    assert results[1][0][1] == results[0][0][1]
