"""Stars Insights through sealed CombatService fights, table commits and reload.

The setup action is sealed before the fight; no running engine is patched.
TabletopService.act uses session.mechanical.execute_intent and its journal.
"""
import json
from pathlib import Path

import pytest

from combat.ext import stars_insights as si
from tests.auto_worker1_support import LEFT, RIGHT, act, fight as service_fight, reload, resolve, turn, cell_send

BOLT = "STARS_BASE_STARBOLT"
PATH = "tianxia.talent.stars.starpath_step"
SEVEN = "tianxia.talent.stars.seven_star_step"
MARK = {"type": "mark", "mark": "Stellar Mark", "applies_to": "target", "duration": {"kind": "until_removed"}}


def fight(tmp_path, talents, **kwargs):
    def insight_fields(doc, aid):
        fields = doc["spheres_and_talents"]
        ids = fields.get("learned_talent_record_ids", [])
        fields["cultivation_insight_record_ids"] = [mid for mid in ids if mid.startswith("insight.")]
        fields["learned_talent_record_ids"] = [mid for mid in ids if not mid.startswith("insight.")]
    return service_fight(tmp_path, talents, sheet_edit=insight_fields, **kwargs)


def setup_bundle(bundle):
    # A second Stars attack with no economy cost lets a test exercise one turn's
    # allowance twice. Its spec is sealed into the same normal match bundle.
    for action in bundle["action_catalog"]:
        if action["display_name"] == "Prepare":
            action["parameters"]["typed"].update(source=BOLT, sphere="tianxia.sphere.stars")


def packets(engine):
    return [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]


def bonus_rolls(engine):
    return [r for r in engine.rolls if str(r.reason).startswith("DAMAGE:")]


def test_comet_adds_one_roll_bonus_and_asks_marked_push_after_damage(tmp_path):
    combat, table, mid = fight(tmp_path, [si.COMET, BOLT], prepare=[MARK], left_attack_bonus=100,
                              positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}})
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    before = reload(combat, mid).state.actors[RIGHT].position
    _, prompts = resolve(lambda a: act(table, mid, "Starbolt", a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert engine.grid.distance_ft(before, engine.state.actors[RIGHT].position) == 5
    assert engine.state.actors[LEFT].turn_flags[si.COMET_USED] == si.turn(engine)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.stars_comet" for p in prompts)
    assert bonus_rolls(engine)[-1].modifier == 6  # key ability +2 and PB +4


def test_comet_bonus_is_not_spent_by_a_miss_and_push_can_be_declined(tmp_path):
    combat, table, mid = fight(tmp_path, [si.COMET, BOLT], prepare=[MARK], left_attack_bonus=-100)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    resolve(lambda a: act(table, mid, "Starbolt", a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert si.COMET_USED not in engine.state.actors[LEFT].turn_flags
    assert not packets(engine)


def test_comet_bonus_once_per_turn_across_two_real_damage_rolls(tmp_path):
    damage = {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["cold"]}
    combat, table, mid = fight(tmp_path, [si.COMET, BOLT], prepare=[damage], bundle_edit=setup_bundle,
                              left_attack_bonus=100)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    engine = reload(combat, mid)
    rolls = bonus_rolls(engine)
    assert [r.modifier for r in rolls] == [4, 0]
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    assert bonus_rolls(reload(combat, mid))[-1].modifier == 4


@pytest.mark.parametrize("decline,immune", [(False, False), (True, False), (False, True)])
def test_cold_heart_packet_choice_and_immunity(tmp_path, decline, immune):
    defend = {"type": "immunity" if immune else "resistance", "damage_types": ["cold"],
              "applies_to": "self", "duration": {"kind": "until_removed"}}
    damage = {"type": "damage", "flat": 20, "damage_types": ["cold"]}
    combat, table, mid = fight(tmp_path, [si.COLD], prepare=[damage], cause=[defend], cause_target="SELF",
                              bundle_edit=setup_bundle)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, "Cause", a))
    turn(table, mid, LEFT)
    picks = {"choice:needle.stars_cold_heart": []} if decline else None
    _, prompts = resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT), picks)
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == 1000 - (0 if immune else 10 if decline else 20)
    assert bool([p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.stars_cold_heart"]) == (not immune)
    assert (si.COLD_USED in engine.state.actors[LEFT].turn_flags) == (not immune and not decline)
    if not immune and not decline:
        resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
        assert reload(combat, mid).state.actors[RIGHT].current_hp == 970


@pytest.mark.parametrize("step", [PATH, SEVEN])
def test_battle_rhythm_next_attack_and_marked_step(tmp_path, step):
    from combat.gate2_runtime_models import Position

    combat, table, mid = fight(tmp_path, [si.RHYTHM, step, BOLT], prepare=[MARK], left_attack_bonus=100,
                              positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}})
    def walk(answers, x, y):
        state = table.state(mid)
        menu = state["menu"]
        move = next(m for m in menu["moves"] if m["destination"]["x"] == x
                    and m["destination"]["y"] == y and not m["destination"].get("z"))
        return table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], answers)

    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    resolve(lambda a: act(table, mid, "Starpath Step" if step == PATH else "Seven-Star Step", a))
    # Spend the Step's separate movement/OA-free grant on an out-and-back walk.
    # Its protection must be exhausted before testing Battle Rhythm's own step.
    away_y = 4 if step == PATH else 3
    resolve(lambda a: walk(a, 3, away_y), {"choice:needle.stars_seven_star": []})
    resolve(lambda a: walk(a, 3, 6), {"choice:needle.stars_seven_star": []})
    engine = reload(combat, mid)
    assert any(c.condition_id == si.READY for c in engine.state.actors[LEFT].conditions.values())
    before = engine.state.actors[LEFT]
    destination = Position(x=2, y=before.position.y)
    assert engine._distance_actor_to_actor(before, engine.state.actors[RIGHT]) == 5
    assert engine.state.actors[RIGHT].reaction_available
    assert not before.turn_flags.get("oa_free_ft") and not before.turn_flags.get("disengaged")
    movement, hp = before.movement_remaining_ft, before.current_hp
    _, prompts = resolve(lambda a: act(table, mid, "Starbolt", a, target_id=RIGHT), {
        "choice:needle.rider_step": [f"cell:2,{destination.y}"],
        "choice:needle.stars_seven_star": [],
    })
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].position == destination
    assert engine.state.actors[LEFT].movement_remaining_ft == movement
    assert engine.state.actors[LEFT].current_hp == hp
    assert engine.state.actors[RIGHT].reaction_available
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == RIGHT for e in engine.events)
    assert not any(c.condition_id == si.READY for c in engine.state.actors[LEFT].conditions.values())
    assert any("Seven-Star Battle Rhythm" in str(p) and "opportunity" in str(p).lower() for p in prompts)
    roll = next(e for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED")
    assert roll.payload["modifier"] == 101
    # Positive control: the same armed enemy can spend its ordinary Reaction
    # when we walk back into its reach and then walk out, without the grant.
    resolve(lambda a: walk(a, 3, destination.y), {"choice:needle.stars_seven_star": []})
    resolve(lambda a: walk(a, 2, destination.y), {"choice:needle.stars_seven_star": []})
    engine = reload(combat, mid)
    assert not engine.state.actors[RIGHT].reaction_available
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == RIGHT for e in engine.events)


def test_battle_rhythm_expires_at_end_of_turn(tmp_path):
    combat, table, mid = fight(tmp_path, [si.RHYTHM, SEVEN])
    resolve(lambda a: act(table, mid, "Seven-Star Step", a))
    resolve(lambda a: act(table, mid, "end", a))
    assert not any(c.condition_id == si.READY for c in reload(combat, mid).state.actors[LEFT].conditions.values())


def test_unowned_control_has_no_insight_rows_or_damage_bonus(tmp_path):
    damage = {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["cold"]}
    combat, table, mid = fight(tmp_path, [], prepare=[damage], bundle_edit=setup_bundle)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert not any(r.get("block") == si.BLOCK for r in engine.typed_passive_rows.get(LEFT, []))
    assert bonus_rolls(engine)[-1].modifier == 0


@pytest.mark.parametrize("auto", [False, True])
def test_star_shadow_appears_at_exact_chosen_visible_cell(tmp_path, auto):
    from combat.gate2_runtime_models import ActionIntent, Position
    from combat.gate4_context import build_decision_context

    shadow_id = "tianxia.talent.stars.star_shadow"
    combat, table, mid = fight(tmp_path, [shadow_id],
                              positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}})
    session = combat._load_session(mid)
    engine = session.engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == "Star Shadow")
    choices = [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    assert len(choices) > 1 and all(c.metadata.get("cell_placement") for c in choices)
    assert all(engine._effect_distance_to_cell(engine.state.actors[LEFT], c.destination) <= 30 for c in choices)
    assert not any(c.destination == engine.state.actors[RIGHT].position for c in choices)
    if auto:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
        policy, _ = combat.policies.for_actor(LEFT)
        choice = combat.controller.choose_primary_action(build_decision_context(engine, policy, for_ai=True))
        selected = next(c for c in choices if c.candidate_id == choice.intent.candidate_id)
        state = table.state(mid)
        result = table.auto_step(mid, state["last_sequence"], [])
        assert result["status"] == "COMMITTED", result
    else:
        selected = next(c for c in choices if c.destination == Position(x=3, y=5))
        # Explicitly exercise the service session's journal, never the bare engine.
        session.mechanical.execute_intent(ActionIntent(intent_id="intent:a2-stars-shadow", actor_id=LEFT,
            candidate_id=selected.candidate_id, decision_id=selected.decision_id,
            state_version=selected.state_version, target_ids=selected.target_ids, destination=selected.destination))
    engine = reload(combat, mid)
    appeared = next(e for e in engine.events if e.event_type == "SUMMON_APPEARED")
    shadow = engine.state.actors[appeared.target_ids[0]]
    assert shadow.position == selected.destination
    assert shadow.maximum_hp == 75 and shadow.armor_class == 17
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 95
    assert engine.state.actors[LEFT].concentration is not None


def test_new_insights_have_no_gm_riders_in_generated_authority():
    mechanics = json.loads((Path(__file__).parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    for feature in (si.COLD, si.COMET, si.RHYTHM):
        assert mechanics[feature]["coverage"] == "FULL"
        assert mechanics[feature]["riders"] == []
