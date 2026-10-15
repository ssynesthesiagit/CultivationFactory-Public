"""Lane A2R09 (automation pass, 2026-10-13): the cultivation path and subpath
residual 1 -- the Sky-Treading Tendon School, Hundred-Beast Scripture and Qi
Cultivation features whose printed combat effects were still GM riders. Every
test compiles a real character owning the feature and runs the engine; each
fails on the typing the authority carried before this lane.

Plug-ins: combat/ext/sky_treading.py (Thousand-Mile Legs jumps, Heaven-Kicking
Leg vertical kicks, Pursuit Without Horizon's teleport/cumulative triggers and
free Tread), combat/ext/beast_aspects.py (Crane jumps and falling damage,
Falcon's attack-draw, Beast King Falcon vertical moves, Sovereign's become
Large, Chimera's default Aspects), combat/ext/flight.py and combat/ext/rider_movement.py
(the general jump and 3D forced-route seams), combat/ext/equipment_hands.py
(the attack_auto_draw seam), combat/ext/qi_sensing.py (Analyze Qi), and the
existing typed blocks for Qi Technique Potency, Cultivated Response and
Meridian Regulation.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import pytest

import combat.factory_compiler as factory_compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from combat.tabletop import normalize_map, to_battlefield
from tests.h1_support import script

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("A2R09_OLD_AUTHORITY"):  # proof runs only: compile against the authority before this lane
    factory_compiler.TYPED_AUTHORITY = Path(os.environ["A2R09_OLD_AUTHORITY"])
ME = "actor:factory.a2r09"
FOE = "actor:factory.a2r09foe"
IRON_FIST = {"sphere_record_ids": ["tianxia.sphere.iron_fist"], "automatic_sphere_component_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING"]}
STAMINA = "resource:core.stamina"
SKY = "tianxia.subpath.body.sky_treading_tendon_school.feature."
BEAST = "tianxia.subpath.body.hundred_beast_scripture.feature."
QI = "tianxia.path.qi_cultivation.feature."
NINPO = "tianxia.subpath.qi.ninpo_adept.feature."


# ------------------------------------------------------------------------------------------------------------ harness
@lru_cache(maxsize=2)
def _authority(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def mechanics():
    return _authority(str(factory_compiler.TYPED_AUTHORITY))


def riders(feature_id):
    return mechanics().get(feature_id, {}).get("riders") or []


def sheet(ids=(), *, cl=18, dc=50, mods=None, items=(), spheres=None, stamina=60, name="A2R09 Cultivator", path="Body Refining"):
    scores = {a: 2 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    scores.update(mods or {})
    return {
        "identity": {"display_name": name, "proficiency_bonus": 6 if cl >= 17 else 5 if cl >= 13 else 4 if cl >= 9 else 3 if cl >= 5 else 2,
                     "cultivation_level": cl, "path": path, "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 10 + 2 * v, "modifier": v} for a, v in scores.items()],
            "primary_resource": {"name": "Stamina", "maximum": stamina}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 120}, "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "path_and_subpath": {"path_feature_record_ids": list(ids)},
        "spheres_and_talents": copy.deepcopy(spheres) if spheres is not None else dict(IRON_FIST),
        "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}],
    }


import copy  # noqa: E402  (the sheet helper above deep-copies the sphere kit)


def bundle(ids=(), actor_id=ME, **kw):
    return compile_character(sheet(ids, **kw), actor_id=actor_id)


def fight(me, *, foe=None, me_at=(3, 6), foe_at=(4, 6), objects=(), seed="A2R09", width=20, height=14):
    from combat.gate2_runtime_content import AN

    foe_id = foe["actor_id"] if foe else AN
    document = normalize_map({"display_name": "A2R09 yard", "width_squares": width, "height_squares": height, "objects": list(objects),
                              "starts": {"team1": [list(me_at)], "team2": [list(foe_at)]}})
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(me, *([foe] if foe else [])), battlefield=to_battlefield(document),
                                   roster_setup={"primary_actor_ids": [ME, foe_id], "team_by_actor": {ME: "team:a", foe_id: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, foe_id: {"x": foe_at[0], "y": foe_at[1]}}})
    turn(engine, ME)
    other = engine.state.actors[foe_id]
    other.maximum_hp = other.current_hp = 1000
    return engine


def turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    return actor


def legal(engine):
    return {c.display_name.split(" — Hits allies too:")[0].split(" at ")[0] for c in engine.legal_candidates()}


def use(engine, name, *, target=None, at=None, actor_id=ME):
    matches = [c for c in engine.legal_candidates() if (c.display_name.split(" — Hits allies too:")[0] == name
                                                          or c.display_name.startswith(name + " at ")
                                                          or c.display_name.startswith(name + " to ")) and c.actor_id == actor_id
               and (target is None or target in (c.target_ids or ()))
               and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == tuple(at)))]
    assert matches, f"{name!r} (target={target}, at={at}) is not legal; legal: {sorted(legal(engine))}"
    candidate = matches[0]
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"a2r09-{start}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[start:]


def unarmed(engine, actor_id=ME):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id == actor_id and a.economy.value == "ACTION"
                and any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                        for e in (a.parameters.get("typed") or {}).get("effects") or [] if isinstance(e, dict)))


def answers(engine, selections=None):
    """Answer every extension choice: the listed option ids for a reaction source ending with a key, else the first ones."""
    selections = selections or {}

    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        chosen = next((value for suffix, value in selections.items() if request["reaction_source_id"].endswith(suffix)),
                      spec["option_ids"][:max(1, spec["minimum_selections"])])
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        if chosen is None:
            return ReactionDecision(**base, selection="DECLINE", option_ids=()), None
        # only offer options the question actually offers: a pick for an
        # aspect the creature does not yet know is not one of its options,
        # so fall back to the first offered options until it is recorded
        offered = [option for option in chosen if option in spec["option_ids"]] \
            or list(spec["option_ids"][:max(1, spec["minimum_selections"])])
        return ReactionDecision(**base, selection="USE", option_ids=tuple(offered)), None
    engine.set_reaction_provider(provider)


def _typed_foe():
    return bundle([], actor_id=FOE, name="A2R09 Foe")


def _sky(ids, *, picks=None, me_at=(3, 6), foe_at=(8, 6), objects=()):
    engine = fight(bundle([k if k.startswith("tianxia.") else SKY + k for k in ids]), foe=_typed_foe(), me_at=me_at, foe_at=foe_at, objects=objects)
    answers(engine, picks or {})
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.armor_class = -50
    return engine, me, foe


def _answer_turn_start(engine):
    """Re-run the owner's turn so the table answers this turn's start-of-turn
    question (the Beast Scripture Aspect pick). The turn-start ask needs an
    active intent to reach the table's provider -- the real table stands one
    in for the pause it makes, so the test does the same."""
    engine._active_intent = ActionIntent(intent_id="i-turn-start", decision_id="d-turn-start",
                                                candidate_id="c-turn-start", state_version=0, actor_id=ME)
    try:
        turn(engine, ME)
    finally:
        engine._active_intent = None


def _beasts(ids, *, picks=None, foe_at=(4, 6), items=(), cl=18):
    engine = fight(bundle([BEAST + k for k in ids], items=items, cl=cl), foe=_typed_foe(), foe_at=foe_at)
    answers(engine, picks or {})
    if picks:  # the table answers this turn's start-of-turn question now that it holds the provider
        _answer_turn_start(engine)
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _qi(ids, *, picks=None, cl=18, mods=None, dc=None, foe=None):
    engine = fight(bundle([k if k.startswith("tianxia.") else QI + k for k in ids],
                             cl=cl, mods=mods, dc=dc or 50, path="Qi Cultivation"),
                   foe=foe or _typed_foe())
    answers(engine, picks or {})
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def end_turns_until(engine, actor_id):
    while engine.state.current_actor_id != actor_id:
        turn(engine, engine.state.initiative_order[(engine.state.initiative_order.index(engine.state.current_actor_id) + 1) % len(engine.state.initiative_order)])


# ------------------------------------------------------------------------------------------------ Sky-Treading Tendon School
def test_thousand_mile_legs_triples_jump_distance_without_a_running_start():
    from combat import flight

    engine, me, foe = _sky(["thousand_mile_legs"])
    start = (Position(x=3, y=6),)
    run_up = tuple(Position(x=3 + i, y=6) for i in range(3))
    assert flight.jump_steps(engine, me, start) == 3  # STR 14: standing 1 x 3 (no running start needed)
    assert flight.jump_steps(engine, me, run_up) == 3  # the run-up buys nothing extra once tripled
    plain, me2, _ = _sky([])
    assert flight.jump_steps(plain, me2, start) == 0  # without the feature a standing STR-14 jump buys no step
    assert flight.jump_steps(plain, me2, run_up) == 1  # and a running start buys one


def test_jump_multiplier_applies_to_feet_before_grid_rounding(monkeypatch):
    from combat import flight

    engine, me, _ = _sky(["thousand_mile_legs"])
    monkeypatch.setattr(flight, "jump_score", lambda *_: (12, 0))  # 4-foot base high jump
    assert flight.jump_steps(engine, me, (Position(x=3, y=6),)) == 2  # 12 feet permits two 5-foot steps


def test_thousand_mile_legs_keeps_no_gm_jump_line():
    assert riders(SKY + "thousand_mile_legs") == ["The engine cannot automatically resolve crossing liquids or vertical surfaces during Stomping Step; ask the GM to determine whether you can cross them and how much movement they cost."]


def test_heaven_kicking_leg_kicks_upward_and_it_falls_if_unsupported():
    engine, me, foe = _sky(["heaven_kicking_leg"], foe_at=(6, 6),
                           picks={"heaven_kicking_leg": ["use"], "heaven_kick_destination": ["cell:6,6,3"]})
    use(engine, "Move to 5,6")  # 10 feet
    events = use(engine, unarmed(engine), target=FOE)
    assert (foe.position.x, foe.position.y, foe.position.z) == (6, 6, 0)  # kicked 15 feet straight up, then fell
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == FOE for e in events)  # the fall's damage
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FOE
               and (e.payload or {}).get("forced") for e in events)  # forced movement, not a teleport


def test_heaven_kicking_leg_kicks_diagonally():
    engine, me, foe = _sky(["heaven_kicking_leg"], foe_at=(6, 6),
                           picks={"heaven_kicking_leg": ["use"], "heaven_kick_destination": ["cell:7,7,1"]})
    use(engine, "Move to 5,6")
    events = use(engine, unarmed(engine), target=FOE)
    assert (foe.position.x, foe.position.y, foe.position.z) == (7, 7, 0)  # one square over and one up, then fell
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == FOE for e in events)  # the rise's fall damage


def test_heaven_kicking_leg_keeps_no_gm_line():
    assert riders(SKY + "heaven_kicking_leg") == []


def test_pursuit_without_horizon_counts_cumulative_willing_segments():
    engine, me, foe = _sky(["pursuit_without_horizon"], foe_at=(8, 6), picks={"pursuit_without_horizon": ["cell:9,6"]})
    end_turns_until(engine, FOE)
    use(engine, "Move to 9,6", actor_id=FOE)  # five feet: not yet
    assert me.resources[STAMINA] == 60
    use(engine, "Move to 10,6", actor_id=FOE)  # five more: the cumulative ten feet qualify
    assert me.resources[STAMINA] == 58  # the Reaction answered and paid its two Stamina


def test_pursuit_without_horizon_answers_the_hostiles_own_feature_teleport():
    from combat.canonical import canonical_sha256

    foe = _typed_foe()
    row = {"source_definition_id": "action:test.a2r09.foe_teleport", "display_name": "Foe Blink",
           "owner_id": FOE, "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "SELF",
           "parameters": {"typed": {"source": "test:blink", "effects": [{"type": "teleport", "applies_to": "self", "distance_ft": 30}],
                                 "numbers": {}, "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0}}
    foe["action_catalog"].append(row)
    foe["actor_template"]["action_ids"].append(row["source_definition_id"])
    foe.pop("bundle_sha256", None)
    foe["bundle_sha256"] = canonical_sha256(foe)
    engine = fight(bundle([SKY + "pursuit_without_horizon"]), foe=foe, foe_at=(8, 6))
    answers(engine, {"pursuit_without_horizon": ["cell:9,6"]})
    me = engine.state.actors[ME]
    end_turns_until(engine, FOE)
    use(engine, "Foe Blink", actor_id=FOE)
    assert me.resources[STAMINA] == 58  # the teleport by its own feature triggered the Reaction


def test_pursuit_without_horizon_activates_tread_for_free_while_airborne():
    from combat.ext.sky_treading import TREAD_HOLD

    engine, me, foe = _sky(["pursuit_without_horizon", "tread_the_empty_sky"], foe_at=(8, 6),
                           picks={"pursuit_without_horizon": ["cell:9,6"]})
    end_turns_until(engine, FOE)
    engine._apply_condition(me, TREAD_HOLD, SKY + "tread_the_empty_sky", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"turn": 0, "round": 0, "label": "Tread the Empty Sky: flight this turn; suspended until your next turn ends"})
    me.position = Position(x=3, y=6, z=2)  # suspended in the air
    use(engine, "Move to 10,6", actor_id=FOE)
    assert me.resources[STAMINA] == 58  # the Reaction's two Stamina only: Tread was free
    from combat.ext.sky_treading import _stamp

    assert any(c.condition_id == TREAD_HOLD and c.data.get("turn") == _stamp(engine)
               for c in me.conditions.values())  # renewed flight for this turn


def test_pursuit_without_horizon_keeps_no_gm_line():
    assert riders(SKY + "pursuit_without_horizon") == []


# ------------------------------------------------------------------------------------------------ Hundred-Beast Scripture
def _aspects(engine, actor_id=ME):
    from combat.ext.beast_aspects import active

    return active(engine, engine.state.actors[actor_id])


def _record_aspects(engine, aspects):
    """Record the owner's known Beast Aspects (the "Choose Beast Aspects"
    record buttons), then answer this turn's start-of-turn question so the
    table's provider picks which of them is active."""
    from combat.ext import menus
    from combat.ext.beast_aspects import MENU_ID

    owner = engine.state.actors[ME]
    for aspect in aspects:
        menus.pick(engine, owner, MENU_ID, aspect, "test:record")
    _answer_turn_start(engine)


def test_crane_aspect_triples_jumps_without_a_running_start():
    from combat import flight

    engine, me, foe = _beasts(["beast_scripture_initiate"], picks={"beast_aspects": ["Crane"]})
    assert set(_aspects(engine)) == {"Crane"}
    start = (Position(x=3, y=6),)
    assert flight.jump_steps(engine, me, start) == 3  # standing STR-14 jump tripled with no running start
    plain, me2, _ = _beasts([])
    assert flight.jump_steps(plain, me2, start) == 0


def test_crane_aspect_reduces_one_falling_damage_event():
    from combat import falling

    engine, me, foe = _beasts(["beast_scripture_initiate"], cl=1, picks={"beast_aspects": ["Crane"]})
    assert set(_aspects(engine)) == {"Crane"}
    me.position = Position(x=3, y=6, z=2)  # a twenty-foot fall: 2d6
    before = len(engine.rolls)
    falling.settle(engine, "test:crane_fall", None)
    rolled = [r for r in engine.rolls[before:] if r.reason == "FALLING_DAMAGE"]
    assert rolled
    committed = next(e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME)
    assert committed.payload["hp_damage"] == max(0, rolled[0].total - 5)  # 5 x CL 1 off one event
    assert me.position.z == 0


def test_falcon_aspect_draws_its_thrown_weapon_with_the_attack():
    from combat.ext import equipment_hands
    from combat.ext.hand_occupancy import weapon_grips

    engine, me, foe = _beasts(["beast_scripture_initiate"], picks={"beast_aspects": ["Falcon"]},
                              items=("tianxia.mortal.weapon.bi_shou",))
    _record_aspects(engine, ["Falcon", "Wolf", "Serpent"])
    assert set(_aspects(engine)) == {"Falcon"}
    use(engine, "Stow Bi Shou (Dagger) (frees 1 hand; no Action)")  # the thrown weapon, put away
    assert not weapon_grips(engine, me)
    thrown = next(c for c in engine.legal_candidates()
                  if c.display_name == "Bi Shou (Dagger) thrown" and c.actor_id == ME)
    assert equipment_hands.require_free_hands(engine, me, thrown,
                                            engine.action_catalog[thrown.source_definition_id]) is not False
    assert not weapon_grips(engine, me)  # opening/filtering the menu must be a pure query
    events = use(engine, "Bi Shou (Dagger) thrown", target=FOE)
    # Drawing is part of execution, then the physical dagger leaves the hand
    # on the throw. A final held grip would contradict thrown-weapon release.
    from combat import carry
    from combat.ext.hand_occupancy import GRIP, weapon_requirement

    weapon = weapon_requirement(engine, engine.action_catalog[thrown.source_definition_id])[0]
    draw = next(e for e in events if e.event_type == "CONDITION_APPLIED"
                and e.source_definition_id == "action:typed.attack_auto_draw"
                and e.target_ids == (ME,) and e.payload["condition_id"] == GRIP)
    attack = next(e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME)
    release = next(e for e in events if e.event_type == "CONDITION_APPLIED"
                   and e.target_ids == (ME,) and e.payload["condition_id"] == carry.DROPPED)
    assert events.index(draw) < events.index(attack) < events.index(release)
    assert not weapon_grips(engine, me)
    assert any(c.condition_id == carry.DROPPED and c.data.get("disables_action") == weapon
               and c.data.get("dropped_at") == foe.position.model_dump(mode="json")
               for c in me.conditions.values())


def test_beast_kings_falcon_moves_vertically_and_falls_afterward():
    # Beast King's Technique reads the active Aspect, so the wielder
    # needs the Beast Scripture Initiate to choose one (Falcon here).
    engine, me, foe = _beasts(["beast_scripture_initiate", "beast_king_s_technique"],
                                  picks={"beast_aspects": ["Falcon"],
                                         "beast_king": ["Falcon"],
                                         "beast_king_falcon": ["cell:3,6,4"]})
    _record_aspects(engine, ["Falcon", "Wolf", "Serpent"])
    use(engine, unarmed(engine), target=FOE)  # already within unarmed reach
    assert me.position.z == 0  # it rose four squares (20 feet) and, unsupported, fell back
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME
               and (e.payload or {}).get("destination", {}).get("z") == 4
               and not (e.payload or {}).get("forced") for e in engine.events)


def test_3d_forced_routes_offer_descent_and_combined_diagonal_destinations():
    from combat.ext.rider_movement import vertical_options

    engine, me, _ = _sky(["heaven_kicking_leg"])
    me.position = Position(x=3, y=6, z=2)
    options = vertical_options(engine, me, 15, viewer=me)
    assert "cell:4,6,1" in options
    assert "cell:4,6,3" in options


def test_sovereign_may_become_large_for_the_transformation():
    from combat import dynamic_size

    engine, me, foe = _beasts(["sovereign_of_ten_thousand_beasts"], picks={"sovereign_large": ["large"]})
    use(engine, "Sovereign of Ten Thousand Beasts")  # the Bonus Action transformation
    assert any(c.condition_id == "condition:typed.size_change" and c.data.get("growth_category") == "Large"
               for c in me.conditions.values())
    assert dynamic_size.current_category(engine, me) == "Large"


def test_chimera_starts_with_tiger_crane_serpent_before_the_first_turn():
    engine, me, foe = _beasts(["chimera_meridian_network"])
    assert set(_aspects(engine)) == {"Tiger", "Crane", "Serpent"}  # the printed default before the first answer


def test_beast_scripture_initiate_keeps_only_the_non_combat_gm_lines():
    assert riders(BEAST + "beast_scripture_initiate") == ["Ape's Climb Speed and its Strength checks to climb, lift or hold, and Ox's carrying and lifting, are the GM's (the engine has no climbing mode; carrying and lifting are not combat effects)."]


def test_beast_kings_technique_and_sovereign_keep_no_gm_lines():
    assert riders(BEAST + "beast_king_s_technique") == []
    assert riders(BEAST + "sovereign_of_ten_thousand_beasts") == ["Carrying, lifting, pushing and dragging as two sizes larger and the Climb Speed are the GM's (not combat effects; the engine has no climbing mode). The engine does not yet grant this transformation's Fly Speed with Hover; ask the GM to resolve flight at your current Speed for the one-minute transformation."]


# ------------------------------------------------------------------------------------------------ Qi Cultivation Path
def test_qi_technique_potency_adds_the_key_modifier_to_one_damage_roll_per_activation():
    engine, me, foe = _qi(["qi_technique_potency", "meridian_regulation"], mods={"CON": 4}, dc=50)
    strike = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.economy.value == "ACTION"
                  and any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                          for e in (a.parameters.get("typed") or {}).get("effects") or [] if isinstance(e, dict)))
    events = use(engine, strike.display_name, target=FOE)
    packets = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike.source_definition_id]
    assert packets and packets[0]["hp_damage"] >= 5  # the unarmed 1d3 (STR +2) plus the CON +4 potency bonus
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == strike.source_definition_id]) >= 1


def test_cultivated_response_rescues_a_failed_save_with_proficiency(tmp_path):
    from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, FOE as WFOE

    def saves_fixture(bundles):
        bundle = bundles[2]
        # The disciplines cover Dexterity, Intelligence and Charisma (the
        # compiled stand-in keeps the numerically weakest, here Dexterity),
        # so the forced save is the one the Response can rescue.
        effects = [{"type": "save", "ability": "dex", "applies_to": "target",
                    "on_fail": [{"type": "condition", "condition": "frightened", "applies_to": "target", "expires_on": "END_OF_CURRENT_TURN"}],
                    "on_success": []}]
        row = {"source_definition_id": "action:test.a2r09.save", "display_name": "Cultivation test save",
               "owner_id": WFOE, "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
               "parameters": {"free_primary": True, "typed": {"source": "test:frightened", "effects": effects, "numbers": {"save_dc": 18},
                                        "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0}}
        bundle["action_catalog"].append(row)
        bundle["actor_template"]["action_ids"].append(row["source_definition_id"])
        from combat.canonical import canonical_sha256

        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [], owner_features=[QI + "cultivated_response"],
                                    seed="A2R09-CULTIVATED", bundle_transform=saves_fixture)
    engine = combat._load_session(mid).engine
    row = next(r for r in engine.typed_reaction_rows.get(OWNER, []) if r.get("block") == "save_rescue")
    bonus = int(row["bonus"])
    rescue = f"reaction:typed.{row['feature_id']}"  # the Reaction itself, which the table must USE
    turn(table, mid, WFOE)
    rescued = []
    for _ in range(40):
        c = candidate(combat, mid, "Cultivation test save", target=OWNER)
        settle(table, mid, c.candidate_id, picks={rescue: "use"})
        engine = reload(tmp_path, mid)
        rolls = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == OWNER]
        rescued = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and "cultivated_response" in e.source_definition_id]
        if rescued:
            break
        if not rolls or not (18 - bonus <= rolls[-1].payload["total"] < 18):
            continue  # a success, or a failure too deep for the Proficiency Bonus to flip
    else:
        pytest.fail("seed never reached a rescuable failed save")
    assert rescued and rescued[0].payload["bonus"] >= 1  # the Discipline added the Proficiency Bonus to the failed save


def test_meridian_regulation_applies_the_chosen_regulation():
    # Meridian Regulation's own automation is pre-existing (combat/ext/qi_path.py,
    # reviewed by lane AUTO2 in tests/test_auto2_paths_b.py, which drives both
    # printed branches against real printed effects). This lane only confirms the
    # printed "choose one" is still offered with every eligible effect in one question.
    from tests.test_auto2_paths_b import _meridian_fixture, _use_meridian

    engine, victim, repeating, plain = _meridian_fixture()
    events, asker = _use_meridian(engine, victim.entity_id)
    request = asker.meridian()
    assert request, "the printed Meridian Regulation choice was never asked"
    options = [str(option) for option in request["extension_choice"]["option_ids"]]
    assert len(options) >= 2, options  # both printed branches' effects in one question
    assert request["extension_choice"]["allow_decline"] is False  # a printed "choose one"


def test_qi_sensing_analyze_reveals_the_engine_known_facts():
    from combat.ext.qi_sensing import analyze_qi_ai_candidate
    from types import SimpleNamespace

    engine, me, foe = _qi(["qi_sensing"])
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Analyze Qi")
    assert action.parameters.get("player_only") is not True
    assert analyze_qi_ai_candidate(engine, me, SimpleNamespace(target_ids=(FOE,)), action) is True
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == FOE and a.parameters.get("typed"))
    engine._apply_condition(foe, "condition:typed.speed_bonus", source, FOE,
                            expires_on="UNTIL_REMOVED", data={"label": "Qi Ward"})
    engine._apply_condition(foe, "condition:typed.fatigue", "system:mundane", FOE,
                            expires_on="UNTIL_REMOVED", data={"label": "Mundane fatigue"})
    events = use(engine, "Analyze Qi", target=FOE)
    rider = next((e.payload.get("rider", "") for e in events
                    if e.event_type == "GM_RIDER" and e.source_definition_id == action.source_definition_id), "")
    assert "Analyze Qi" in rider and engine.state.actors[FOE].display_name in rider
    assert "supernatural effects are active (Qi Ward)" in rider
    assert "one active supernatural tag: Qi Ward" in rider
    assert "Mundane fatigue" not in rider


def test_qi_sensing_is_checked_against_concealment_and_is_not_retried():
    engine, me, foe = _qi(["qi_sensing"], foe=bundle([], actor_id=FOE, dc=100))
    foe.position = Position(x=4, y=6)
    from combat import stealth

    assert stealth.sees(engine, me, foe)  # the fixture foe is visible until it is concealed
    engine._apply_condition(foe, "condition:typed.concealed", "test:conceal", FOE, expires_on="UNTIL_REMOVED",
                            data={"label": "Qi concealment"})
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Analyze Qi")
    from combat.ext.qi_sensing import analyze_qi_ai_candidate
    from types import SimpleNamespace
    # Qi concealment can hide its supernatural nature while its body stays visible.
    assert analyze_qi_ai_candidate(engine, me, SimpleNamespace(target_ids=(FOE,)), action) is True
    events = use(engine, "Analyze Qi", target=FOE)
    assert any(e.event_type == "CHECK_ROLLED" for e in events)
    rider = next((e.payload.get("rider", "") for e in events
                    if e.event_type == "GM_RIDER" and e.source_definition_id == action.source_definition_id), "")
    assert "present" in rider  # failure: presence only, no details
    me = engine.state.actors[ME]
    me.action_available = True  # economy must not mask a broken retry guard
    assert not any(c.source_definition_id == action.source_definition_id and FOE in (c.target_ids or ())
                   for c in engine.legal_candidates())  # the same concealment cannot be retried
    from types import SimpleNamespace
    from combat.ext.qi_sensing import analyze_qi_candidate
    engine._remove_condition(foe, "condition:typed.concealed", "test:conceal")
    engine._apply_condition(foe, "condition:typed.concealed", "test:new-concealment", FOE,
                            expires_on="UNTIL_REMOVED", data={"label": "A changed Qi concealment"})
    before = me.model_dump(mode="json")
    assert analyze_qi_candidate(engine, me, SimpleNamespace(target_ids=(FOE,)), action) is True
    assert me.model_dump(mode="json") == before  # a menu query never removes receipts


# ------------------------------------------------------------------------------------------------ authority riders
def test_the_lanes_automated_rows_carry_no_gm_resolution_lines():
    # Thousand-Mile Legs keeps exactly its one documented rider: crossing
    # liquids and vertical surfaces has no engine terrain rule (the rest of
    # the lane's automated rows carry no GM resolution text at all).
    assert riders(SKY + "thousand_mile_legs") == ["The engine cannot automatically resolve crossing liquids or vertical surfaces during Stomping Step; ask the GM to determine whether you can cross them and how much movement they cost."]
    for feature in (SKY + "heaven_kicking_leg", SKY + "pursuit_without_horizon",
                    BEAST + "beast_king_s_technique", BEAST + "chimera_meridian_network",
                    QI + "qi_technique_potency"):
        assert riders(feature) == [], feature


# --------------------------------------------------- service-level table coverage
# Each group's flagship ability runs through CombatService's session
# (table.act submits the session's execute_intent) and survives a cold
# reload whose mechanical replay still passes, beside the engine-level
# per-ability tests above.
def _low_ac_foe():
    from tests.h1_support import sheet

    document = sheet([], cl=18)
    document["ability_scores_and_statistics"]["armor_class"]["base_value"] = 0  # always hit
    return document


def test_shadow_clone_array_commits_and_cold_reloads_through_the_table(tmp_path):
    from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER

    combat, table, mid = fixture(tmp_path, [], primary="Qi", seed="A2R09-NINPO",
                                    owner_path="Qi Cultivation",
                                    owner_features=[NINPO + "shadow_clone_array"])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Shadow Clone Array").candidate_id)
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.shadow_clone_array"
               and c.data["clones"] == 2 and c.expires_on and c.expires_on.startswith("START_OF_SLOT_AT:")
               for c in engine.state.actors[OWNER].conditions.values())
    engine = reload(tmp_path, mid)  # cold reload: the array's two Clones survive
    assert any(c.condition_id == "condition:typed.shadow_clone_array"
               and c.data["clones"] == 2 for c in engine.state.actors[OWNER].conditions.values())


def test_thousand_mile_legs_strike_rider_commits_and_cold_reloads_through_the_table(tmp_path):
    from tests.worker2_support import fixture, settle, reload, OWNER, FOE as WFOE

    combat, table, mid = fixture(tmp_path, ["TAL_IRON_FIST_IRON_FIST_TRAINING"],
                                    seed="A2R09-SKY", owner_path="Qi Cultivation",
                                    owner_features=[SKY + "thousand_mile_legs"],
                                    foe_sheet=_low_ac_foe())
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates()
                  if c.actor_id == OWNER and c.display_name == "Move to 7,6")
    settle(table, mid, move.candidate_id)  # 20 feet
    engine = combat._load_session(mid).engine
    strike = next(c for c in engine.legal_candidates()
                    if c.actor_id == OWNER and c.display_name.startswith("Unarmed Strike")
                    and WFOE in (c.target_ids or ()))
    before_strike = len(engine.events)
    prompts = settle(table, mid, strike.candidate_id,
                     picks={"choice:needle.thousand_mile_step": ["cell:8,6"]})
    engine = combat._load_session(mid).engine
    # the strike lands, the rider pays its extra damage as its own
    # packet (the Proficiency Bonus) and steps 5 feet without provoking
    damages = [e for e in engine.events
                   if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == OWNER]
    assert len(damages) >= 2  # the strike, then the rider's +PB packet
    assert any(p["context"]["reaction_source_id"] == "choice:needle.thousand_mile_step" for p in prompts)
    steps = [e for e in engine.events[before_strike:]
             if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER
             and e.source_definition_id == SKY + "thousand_mile_legs"]
    assert len(steps) == 1 and steps[0].payload["without_provoking"]
    hit = next(e for e in engine.events[before_strike:] if e.event_type == "DAMAGE_COMMITTED")
    assert steps[0].sequence > hit.sequence
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert (actor.position.x, actor.position.y, actor.position.z) == (8, 6, 0)


def test_sovereign_transformation_commits_and_cold_reloads_through_the_table(tmp_path, monkeypatch):
    import tests.worker2_support as worker2
    from tests.worker2_support import fixture, candidate, settle, reload, OWNER

    def drive(table, mid, actor):
        """Drive to ``actor``'s turn, answering the Beast Scripture
        turn-start Aspect pick with its full count (the Chimera
        Meridian Network maintains three)."""
        for _ in range(12):
            if table.state(mid)["menu"]["actor_id"] == actor:
                return
            worker2.settle(table, mid, table.state(mid)["menu"]["end_turn"],
                              picks={"choice:needle.beast_aspects": ["Tiger", "Crane", "Serpent"]})
        pytest.fail("the owner's turn never came")

    monkeypatch.setattr(worker2, "prompt_turn", drive)
    combat, table, mid = fixture(tmp_path, [], primary="Stamina", seed="A2R09-BEAST",
                                    owner_path="Body Refining",
                                    owner_features=[BEAST + "beast_scripture_initiate",
                                                     BEAST + "chimera_meridian_network",
                                                     BEAST + "sovereign_of_ten_thousand_beasts"])
    settle(table, mid, candidate(combat, mid, "Sovereign of Ten Thousand Beasts").candidate_id,
              picks={"choice:needle.sovereign_large": ["large"]})
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.size_change"
               and c.data.get("growth_category") == "Large"
               for c in engine.state.actors[OWNER].conditions.values())
    engine = reload(tmp_path, mid)  # cold reload: the transformation survives
    assert any(c.condition_id == "condition:typed.size_change"
               and c.data.get("growth_category") == "Large"
               for c in engine.state.actors[OWNER].conditions.values())


def test_analyze_qi_commits_and_cold_reloads_through_the_table(tmp_path):
    from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, FOE as WFOE

    combat, table, mid = fixture(tmp_path, [], primary="Qi", seed="A2R09-QI",
                                    owner_path="Qi Cultivation",
                                    owner_features=[QI + "qi_sensing"])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Analyze Qi", target=WFOE).candidate_id)
    engine = combat._load_session(mid).engine
    assert any(e.event_type == "GM_RIDER" and "Analyze Qi" in (e.payload or {}).get("rider", "")
               for e in engine.events)
    reload(tmp_path, mid)
