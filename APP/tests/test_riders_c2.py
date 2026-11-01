"""Rider lane C2 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones left"):
printed lines of the Gravity, Stars, Pressure Points, Wrestling, Verdant Growth, Guardian and Berserker abilities that were only
shown to the GM as riders.  Every ability is compiled on a real character and run through the engine.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c2.json (+ in-place edits of entries other files already reviewed);
feature rows: combat/rules/feature_blocks.d/riders_c2.json; plug-ins: combat/ext/gravity.py.
Each test fails on the typing the authority carried before this lane: run with C2_OLD=<old authority JSON> to compile the
characters against it (tests marked ``plugin_only`` need no typing change and are skipped there).
"""

import json
import os
from functools import lru_cache
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_auto_lane1 as L1

ROOT = Path(__file__).resolve().parents[1]
ME, ATK, ALLY = "actor:factory.c2", "actor:factory.c2_attacker", "actor:factory.c2_ally"
OLD = os.environ.get("C2_OLD")


@lru_cache(maxsize=2)
def _authority():
    return json.loads(Path(OLD).read_bytes()) if OLD else None


if OLD:  # Touch the Point reads Point/Seal effects from the authority file itself (combat/ext/shi_pressure_points._mechanics)
    from combat.ext import shi_pressure_points as _shi

    _shi._MECHANICS_CACHE = json.loads(Path(OLD).read_bytes())["mechanics"]


def _sheet(mids, *, cl=10, dc=16, weapon="tianxia.mortal.weapon.fu", key_score=14):
    sheet = L1._sheet(mids[0], cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(mids)
    sheet["path_and_subpath"] = {"path_record_ids": ["tianxia.path.body_refining"]}
    sheet["identity"]["path"] = "Body Refining"
    sheet["ability_scores_and_statistics"]["primary_resource"] = {"name": "Stamina", "maximum": 30}
    if weapon:
        sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon, "name": weapon, "quantity": 1}]}}]
    if key_score != 14:
        stats = sheet["ability_scores_and_statistics"]
        stats["abilities"] = [row if row["ability"] != "CON" else {"ability": "CON", "score": key_score, "modifier": (key_score - 10) // 2}
                              for row in stats["abilities"]]
    return sheet


def _bundle(mids, actor_id=ME, **kw):
    return compile_character(_sheet(mids, **kw), actor_id=actor_id, typed_authority=_authority())


def _attacker_bundle():
    sheet = _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], weapon="tianxia.mortal.weapon.dao")
    return compile_character(sheet, actor_id=ATK)


def _fight(bundle, *, allies=(), attacker=False, me_at=(3, 6), foe_at=(4, 6), both=False):
    """ME (team a, with ``allies``) against the sample foe An Eui, or against a compiled Factory attacker (typed attacks); ``both``: An
    Eui and the attacker (so one of them can fall without ending the fight)."""
    foe = ATK if attacker else L1.AN
    bundles = (bundle, *allies, *((_attacker_bundle(),) if attacker or both else ()))
    ids = [ME, *(b["actor_id"] for b in allies), foe, *([ATK] if both else [])]
    positions = {ME: {"x": me_at[0], "y": me_at[1]}, foe: {"x": foe_at[0], "y": foe_at[1]}, **({ATK: {"x": 12, "y": 2}} if both else {})}
    for index, ally in enumerate(allies):
        positions[ally["actor_id"]] = {"x": me_at[0], "y": me_at[1] + 1 + index}
    engine = Gate4ControllerEngine(ROOT, match_seed="C2", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": ids,
                                                 "team_by_actor": {ME: "team:a", **{b["actor_id"]: "team:a" for b in allies}, foe: "team:b",
                                                                   **({ATK: "team:b"} if both else {})},
                                                 "starting_positions": positions})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 500
    engine.state.actors[foe].armor_class = -50
    _ready(engine, ME)
    return engine


def _ready(engine, actor_id=ME):
    actor = engine.state.actors[actor_id]
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    return actor


def _names(engine):
    return {c.display_name for c in engine.legal_candidates()}


def _act(engine, name, target=None, actor_id=ME, destination=None):
    matches = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id
               and (target is None or target in (c.target_ids or ()))]
    assert matches, f"{name!r} is not legal for {actor_id}; legal: {sorted(n for n in _names(engine) if not n.startswith('Move to'))}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{before}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=(target,) if target else (candidate.target_ids or ()),
                                       destination=destination or candidate.destination))
    return engine.events[before:]


def _move(engine, x, y, actor_id=ME):
    return _act(engine, f"Move to {x},{y}", actor_id=actor_id)


def _answers(engine, picks):
    """A table that answers each extension choice whose id contains a key of ``picks`` with that selection (a list, or None to
    decline); every other question is declined.  Returns the questions asked."""
    asked = []

    def provider(request):
        asked.append(request)
        options = list(request.get("legal_option_ids") or ())
        for key, pick in picks.items():
            if key in request["reaction_source_id"]:
                chosen = pick(options) if callable(pick) else pick
                if chosen is None:
                    break
                return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                        reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=tuple(chosen)), None
        spec = request.get("extension_choice") or {}
        if spec and not spec.get("allow_decline", True):  # a choice that must be made: its preferred (the AI's) pick
            count = max(1, int(spec.get("minimum_selections") or 1))
            chosen = list(spec.get("preferred_option_ids") or options)[:count]
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=tuple(chosen)), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None

    engine.set_reaction_provider(provider)
    return asked


def _of(events, event_type):
    return [e.payload or {} for e in events if e.event_type == event_type]


def _held(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _damage(events, kind=None):
    return [p for p in _of(events, "DAMAGE_COMMITTED") if kind is None or p.get("damage_type") == kind]


def _first(pattern):
    return lambda options: [next(o for o in options if o.startswith(pattern))]


def _mech():
    return (_authority() or {"mechanics": L1._mechanics()})["mechanics"]


# ============================================================================================================ Gravity
WS = "TAL_GRAVITY_WEIGHT_SHIFT_BASE"
STAFF = "tianxia.mortal.weapon.gun"  # Gun (Staff): simple, Two-Handed, Reach
LIGHT, HEAVY = "condition:typed.state.body_lightening", "condition:typed.state.body_heavying"


def test_weight_shift_mode_replaces_the_old_one_and_neutral_weight_is_free():
    """"Choose one mode ... You may change modes only once on each of your turns ... Neutral Weight: ... requires no action"."""
    engine = _fight(_bundle([WS]))
    me = engine.state.actors[ME]
    _act(engine, "Weight Shift: Body Lightening")
    assert _held(me, LIGHT) and sum(m.value for m in me.modifiers.values() if m.target_field == "speed_ft") == 10
    assert not {"Weight Shift: Body Heavying", "Weight Shift: Neutral Weight"} & _names(engine)  # one change this turn
    me.turn_flags.clear()
    _ready(engine)
    _act(engine, "Weight Shift: Body Heavying")
    assert _held(me, HEAVY) and not _held(me, LIGHT)
    assert sum(m.value for m in me.modifiers.values() if m.target_field == "speed_ft") == -5  # the Lightening +10 is gone
    me.turn_flags.clear()
    _ready(engine)
    me.bonus_action_available = me.action_available = False
    _act(engine, "Weight Shift: Neutral Weight")
    assert not _held(me, HEAVY) and not any(m.target_field == "speed_ft" for m in me.modifiers.values())


def test_incapacitated_returns_weight_shift_to_neutral():
    """"If you are Incapacitated, your Weight Shift becomes Neutral Weight": the mode and its benefits end."""
    engine = _fight(_bundle([WS]))
    me = engine.state.actors[ME]
    _act(engine, "Weight Shift: Body Heavying")
    assert _held(me, HEAVY) and any(m.target_field == "speed_ft" for m in me.modifiers.values())
    from combat import typed_executor
    foe = engine.state.actors[L1.AN]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4, "save_dc": 16}}, [me], me, {})
    typed_executor.run_effects(ctx, [{"type": "condition", "condition": "incapacitated", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"}])
    assert not _held(me, HEAVY) and not any(m.target_field == "speed_ft" for m in me.modifiers.values())


def test_body_heavying_first_melee_hit_adds_proficiency_bonus_damage_once():
    engine = _fight(_bundle([WS]))
    _answers(engine, {})
    _act(engine, "Weight Shift: Body Heavying")
    first = _act(engine, "Fu (Short Axe) attack", L1.AN)
    assert [p["hp_damage"] for p in _damage(first, "SLASHING")][1:] == [4]  # the weapon's own hit, then Proficiency Bonus 4
    _ready(engine)
    second = _act(engine, "Fu (Short Axe) attack", L1.AN)
    assert len(_damage(second)) == 1


def test_body_lightening_uses_the_gravity_key_ability_after_ten_feet():
    engine = _fight(_bundle([WS], key_score=20, weapon=STAFF), foe_at=(7, 6))
    _act(engine, "Weight Shift: Body Lightening")
    _move(engine, 5, 6)
    rolled = _of(_act(engine, "Gun (Staff) attack", L1.AN), "ATTACK_ROLLED")[0]
    standing = _fight(_bundle([WS], key_score=20, weapon=STAFF), foe_at=(5, 6))
    _act(standing, "Weight Shift: Body Lightening")
    still = _of(_act(standing, "Gun (Staff) attack", L1.AN), "ATTACK_ROLLED")[0]
    assert rolled["modifier"] == still["modifier"] + 3  # CON +5 in place of the axe's +2


def test_weighted_strike_heavying_blow_adds_force_dice_and_a_strength_save():
    engine = _fight(_bundle([WS], dc=50))
    asked = _answers(engine, {"gravity_weighted_strike": _first("heavying"), "gravity_heavying": ["prone"]})
    _act(engine, "Weight Shift: Body Heavying")
    events = _act(engine, "Fu (Short Axe) attack", L1.AN)
    force = [p for p in _of(events, "DAMAGE_ROLLED") if "Heavying" in str(p) or p.get("expression", "").startswith("2d6")]
    assert force and _damage(events, "FORCE")
    assert _held(engine.state.actors[L1.AN], "condition:typed.prone")
    assert any(r["reaction_source_id"].endswith("gravity_weighted_strike") for r in asked)
    assert engine.state.actors[ME].resources["resource:core.stamina"] == 29
    _ready(engine)
    again = _act(engine, "Fu (Short Axe) attack", L1.AN)
    assert not _damage(again, "FORCE")  # once per turn


@pytest.mark.parametrize("heavying,thrown", [(False, True), (True, True), (False, False), (True, False)])
def test_weighted_strike_needs_a_mode_and_a_melee_hit(heavying, thrown):
    # fix/hunt21 (round22 merge 23) intentionally releases a thrown weapon.
    # Each trigger combination needs its own held axe, not reuse after a throw.
    engine = _fight(_bundle([WS], dc=50), foe_at=(6, 6) if thrown else (4, 6))
    asked = _answers(engine, {"gravity_weighted_strike": _first("heavying")})
    if heavying:
        _act(engine, "Weight Shift: Body Heavying")
        _ready(engine)
    stamina = engine.state.actors[ME].resources["resource:core.stamina"]
    events = _act(engine, "Fu (Short Axe) thrown" if thrown else "Fu (Short Axe) attack", L1.AN)
    assert _of(events, "ATTACK_ROLLED") and _damage(events, "SLASHING")
    eligible = heavying and not thrown
    assert any("weighted_strike" in r["reaction_source_id"] for r in asked) == eligible
    assert bool(_damage(events, "FORCE")) == eligible
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina - int(eligible)
    if thrown:
        _ready(engine)
        assert "Fu (Short Axe) thrown" not in _names(engine)
        assert "Fu (Short Axe) attack" not in _names(engine)


def test_weighted_strike_lightening_blow_steps_without_the_targets_opportunity_attack():
    engine = _fight(_bundle([WS]))
    _answers(engine, {"gravity_weighted_strike": _first("lightening"), "rider_step": lambda options: [o for o in options if o == "cell:1,6"]})
    _act(engine, "Weight Shift: Body Lightening")
    events = _act(engine, "Fu (Short Axe) attack", L1.AN)
    assert _damage(events, "FORCE")
    me = engine.state.actors[ME]
    assert (me.position.x, me.position.y) == (1, 6)
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == L1.AN for e in events)


def test_heavy_weapon_body_and_gravitic_armor_raise_the_heavying_dice():
    engine = _fight(_bundle([WS, "tianxia.talent.gravity.heavy_weapon_body", "tianxia.talent.gravity.gravitic_armor"], weapon=STAFF))
    _answers(engine, {"gravity_weighted_strike": _first("heavying"), "gravity_heavying": ["push"]})
    _act(engine, "Weight Shift: Body Heavying")
    _ready(engine)
    _act(engine, "Gravitic Armor")
    _ready(engine)
    events = _act(engine, "Gun (Staff) attack", L1.AN)
    assert any(p.get("expression", "").startswith("2d10") for p in _of(events, "DAMAGE_ROLLED"))  # d6 -> d8 (two-handed) -> d10 (armor)


def test_anchor_stance_shortens_forced_movement_while_body_heavying():
    engine = _fight(_bundle([WS, "TAL_GRAVITY_ANCHOR_STANCE"]))
    me = engine.state.actors[ME]
    _act(engine, "Weight Shift: Body Heavying")
    L1._foe_forces_save  # noqa: B018 -- the helper module is shared; the push is made directly below
    from combat import typed_executor
    foe = engine.state.actors[L1.AN]
    action = next(iter(engine.action_catalog.values()))
    ctx = typed_executor.Context(engine, foe, action, None, {"numbers": {"pb": 4, "save_dc": 16}}, [me], me, {})
    start = me.position.x
    typed_executor.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away"}])
    assert me.position.x == start - 1  # 15 feet less 10


def test_orbiting_guard_steps_after_a_missed_melee_attack_and_gains_ac_at_cl5():
    engine = _fight(_bundle([WS, "tianxia.talent.gravity.orbiting_guard"]), attacker=True)
    me = engine.state.actors[ME]
    _act(engine, "Orbiting Guard")
    ac_guard = engine._effective_ac(me) if hasattr(engine, "_effective_ac") else None
    me.turn_flags.clear()
    _ready(engine)
    _act(engine, "Weight Shift: Body Heavying")
    if ac_guard is not None:
        assert engine._effective_ac(me) == ac_guard + 1
    asked = _answers(engine, {"rider_step": lambda options: [o for o in options if o == "cell:3,5"] or options[:1]})
    me.armor_class = 100
    _ready(engine, ATK)
    _act(engine, "Dao (Saber / Broadsword) attack", ME, actor_id=ATK)
    assert any("rider_step" in r["reaction_source_id"] and "Orbiting Guard" in str(r) for r in asked)
    assert (me.position.x, me.position.y) == (3, 5)


def test_orbit_breaking_guard_trips_the_attacker():
    engine = _fight(_bundle([WS, "tianxia.talent.gravity.orbiting_guard", "tianxia.talent.gravity.orbit_breaking_guard"], dc=50), attacker=True)
    me = engine.state.actors[ME]
    _act(engine, "Orbiting Guard")
    _answers(engine, {"gravity_orbit_breaking": ["trip"], "rider_step": None})
    me.armor_class = 100
    _ready(engine, ATK)
    _act(engine, "Dao (Saber / Broadsword) attack", ME, actor_id=ATK)
    assert _held(engine.state.actors[ATK], "condition:typed.prone") and not me.reaction_available


@pytest.mark.parametrize('extra_staff', [False, True])
def test_moon_falling_counter_strikes_back_after_a_miss_with_body_lightening(extra_staff):
    sheet = _sheet([WS, "tianxia.talent.gravity.moon_falling_counter"])
    if extra_staff:
        # The staff rests beside the axe but cannot attack in two hands while
        # the axe occupies one. The counter must use its legal readied attack.
        sheet['equipment'][0]['starting_kit']['items'].append({'item_id': 'tianxia.mortal.weapon.gun'})
    engine = _fight(compile_character(sheet, actor_id=ME, typed_authority=_authority()), attacker=True)
    me = engine.state.actors[ME]
    _act(engine, "Weight Shift: Body Lightening")
    _answers(engine, {"gravity_moon_falling_counter": lambda options: options[:1], "rider_step": None,
                      "gravity_weighted_strike": _first("lightening")})
    me.armor_class = 100
    engine.state.actors[ATK].armor_class = -50
    _ready(engine, ATK)
    events = _act(engine, "Dao (Saber / Broadsword) attack", ME, actor_id=ATK)
    mine = [p for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for p in [e.payload]]
    assert mine and not me.reaction_available
    assert me.resources["resource:core.stamina"] == 29  # the counter's 1; its Lightening Blow was free
    assert _damage(events, "FORCE")


def test_mountain_crushing_step_ignores_rough_ground_and_topples_the_first_creature_hit():
    engine = _fight(_bundle([WS, "tianxia.talent.gravity.mountain_crushing_step"], dc=50), foe_at=(6, 6))
    me = engine.state.actors[ME]
    _answers(engine, {"gravity_mountain_step": ["prone"]})
    _act(engine, "Weight Shift: Body Heavying")
    _act(engine, "Mountain-Crushing Step")
    assert _held(me, "condition:typed.ignore_difficult")
    _move(engine, 5, 6)
    assert "Mountain-Crushing Step" not in _names(engine)
    _act(engine, "Fu (Short Axe) attack", L1.AN)
    assert _held(engine.state.actors[L1.AN], "condition:typed.prone")


def test_ten_thousand_weight_body_bought_at_turn_start():
    """"When Body Heavying is active, you may spend 5 CP or Stamina at the start of your turn" -- asked as the turn starts, although
    the Body Heavying taken last turn lasts only until then."""
    engine = _fight(_bundle([WS, "tianxia.talent.gravity.mountain_body", "tianxia.talent.gravity.ten_thousand_weight_body"]), attacker=True)
    me = engine.state.actors[ME]
    _act(engine, "Weight Shift: Body Heavying")
    asked = _answers(engine, {"gravity_ten_thousand": lambda options: options[:1]})
    _act(engine, "End turn")
    assert engine.state.current_actor_id == ATK
    _act(engine, "End turn", actor_id=ATK)
    assert engine.state.current_actor_id == ME and any("gravity_ten_thousand" in r["reaction_source_id"] for r in asked)
    assert _held(me, "condition:typed.state.ten_thousand_weight") and me.resources["resource:core.stamina"] == 25
    me.armor_class = -50
    _ready(engine, ATK)
    events = _act(engine, "Dao (Saber / Broadsword) attack", ME, actor_id=ATK)
    assert any(p["damage_type"] == "FORCE" and p["hp_damage"] == 4 for p in _damage(events))  # the attacker takes PB Force
    _ready(engine, ME)
    from combat import typed_executor
    foe = engine.state.actors[ATK]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4, "save_dc": 16}}, [me], me, {})
    start = (me.position.x, me.position.y)
    typed_executor.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away"}])
    assert (me.position.x, me.position.y) == start  # a known CL 10 creature cannot move it


def test_gravity_well_knocks_down_a_creature_pulled_into_the_center():
    engine = _fight(_bundle(["TAL_GRAVITY_GRAVITY_WELL"], dc=50), foe_at=(7, 6))
    names = sorted(n for n in _names(engine) if n.startswith("Gravity Well"))
    pick = next((n for n in names if n.endswith("at 8,6")), names[0])
    _act(engine, pick)
    foe = engine.state.actors[L1.AN]
    assert (foe.position.x, foe.position.y) == (8, 6)
    assert _held(foe, "condition:typed.prone")


def test_singularity_seed_pulls_a_failing_creature_to_the_center():
    engine = _fight(_bundle(["tianxia.talent.gravity.singularity_seed"], dc=50), foe_at=(7, 6))
    names = sorted(n for n in _names(engine) if n.startswith("Singularity Seed"))
    pick = next((n for n in names if n.endswith("at 9,6")), names[0])
    _act(engine, pick)
    foe = engine.state.actors[L1.AN]
    assert (foe.position.x, foe.position.y) == (9, 6)


def test_heavens_weight_burns_each_turn_start_and_blocks_teleport():
    engine = _fight(_bundle(["tianxia.talent.gravity.heaven_s_weight"], cl=17, dc=50))
    _act(engine, "Heaven’s Weight", L1.AN)
    foe = engine.state.actors[L1.AN]
    held = _held(foe, "condition:typed.restrained")
    assert held and held[0].data["rule"].get("no_teleport") and held[0].data["repeat_save"]["ability"] == "STR"
    from combat import ext
    before = len(engine.events)
    ext.run("turn_start", engine, foe)
    assert _damage(engine.events[before:], "FORCE")


def test_gravitic_push_stops_at_the_printed_size():
    mech = _mech()["tianxia.talent.gravity.gravitic_push"]
    saves = [row for row in mech["effects"] if row.get("type") == "save"]
    assert [row.get("max_size_cells") for row in saves] == [2, 3]  # Large below CL 5, Huge from CL 5


def test_feather_body_and_gravitic_armor_add_to_body_lightening_speed():
    engine = _fight(_bundle([WS, "tianxia.talent.gravity.feather_body", "tianxia.talent.gravity.gravitic_armor"]))
    me = engine.state.actors[ME]
    base = engine._effective_speed(me)
    _act(engine, "Weight Shift: Body Lightening")
    _ready(engine)
    _act(engine, "Gravitic Armor")
    assert engine._effective_speed(me) == base + 10 + 5 + 10


def test_light_body_rush_dash_needs_body_lightening():
    engine = _fight(_bundle([WS, "tianxia.talent.gravity.feather_body", "tianxia.talent.gravity.light_body_rush"]))
    assert not any(n.startswith("Light Body Rush") for n in _names(engine))
    _act(engine, "Weight Shift: Body Lightening")
    engine.state.actors[ME].bonus_action_available = True
    name = next(n for n in _names(engine) if n.startswith("Light Body Rush: Dash"))
    before = engine.state.actors[ME].movement_remaining_ft
    _act(engine, name)
    assert engine.state.actors[ME].movement_remaining_ft > before


def test_gravity_modes_and_weighted_strike_survive_table_commit_and_reload(tmp_path):
    """Body Heavying (a state, a singleton marker, integer turn flags) is saved with the fight and still drives Weighted Strike and the
    first-hit bonus after the table reloads it."""
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C2-GRAVITY-SAVE", typed_bundles=(_bundle([WS], dc=50),),
                                       roster_setup={"primary_actor_ids": [ME, L1.AN], "team_by_actor": {ME: "team:a", L1.AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, L1.AN: {"x": 4, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.submit_intent(ActionIntent(
            intent_id=f"c2-save-{candidate.state_version}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=(target,) if target else candidate.target_ids,
            destination=candidate.destination), primary_decision_record=None, reaction_provider=None)

    for _ in session.engine.state.initiative_order:
        if session.engine.state.current_actor_id == ME:
            break
        commit("End turn")
    assert session.engine.state.current_actor_id == ME, "The controller session must advance with the committed turn"
    commit("Weight Shift: Body Heavying")
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    engine = reloaded.engine
    me = engine.state.actors[ME]
    assert _held(me, HEAVY) and me.turn_flags.get("gravity_mode_changed") == 1
    assert "Weight Shift: Body Lightening" not in _names(engine)
    engine.state.actors[L1.AN].armor_class = -50
    engine.state.actors[L1.AN].maximum_hp = 500
    engine.state.actors[L1.AN].current_hp = 500
    _answers(engine, {"gravity_weighted_strike": _first("heavying"), "gravity_heavying": ["push"]})
    events = _act(engine, "Fu (Short Axe) attack", L1.AN)
    assert _damage(events, "FORCE") and any(p["hp_damage"] == 4 and p["damage_type"] == "SLASHING" for p in _damage(events)[1:])


def test_black_star_grip_crushes_its_grappled_target_each_turn_start():
    engine = _fight(_bundle(["tianxia.talent.gravity.black_star_grip"], dc=50))
    _act(engine, "Black-Star Grip", L1.AN)
    foe = engine.state.actors[L1.AN]
    [grip] = _held(foe, "condition:typed.grappled")
    assert grip.data["escape_dc"] == 50 and grip.data["reach_ft"] > 1000  # not ended by moving away
    from combat import ext
    before = len(engine.events)
    ext.run("turn_start", engine, foe)
    assert [p["hp_damage"] for p in _damage(engine.events[before:], "FORCE")] == [4]


def test_event_horizon_prison_teleport_out_needs_an_opposed_cultivation_check():
    engine = _fight(_bundle(["tianxia.talent.gravity.event_horizon_prison"], cl=17), foe_at=(8, 6))
    names = sorted(n for n in _names(engine) if n.startswith("Event Horizon Prison"))
    _act(engine, next((n for n in names if n.endswith("at 8,6")), names[0]))
    from combat import ext, typed_executor
    from combat.gate2_runtime_models import Position
    foe = engine.state.actors[L1.AN]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 0, "key_mod": -30}}, [foe], foe, {})
    before = len(engine.events)
    verdicts = ext.run("teleport_gate", ctx, foe.position, Position(x=15, y=6))
    checks = _of(engine.events[before:], "CHECK_ROLLED")
    assert False in verdicts and checks and checks[0]["check"] == "Cultivation Check (opposed)"
    inside = ext.run("teleport_gate", ctx, foe.position, Position(x=9, y=6))
    assert False not in inside  # a teleport that stays inside is not checked


# ============================================================================================================ Stars
S = "tianxia.talent.stars."
STARBOLT = "STARS_BASE_STARBOLT"


def _stars(mids, **kw):
    return _bundle([STARBOLT, *mids], weapon=None, **kw)


def _mark(engine, holder_id, owner_id=ME, name="Stellar Mark"):
    from combat.typed_executor import mark_condition_id
    engine._apply_condition(engine.state.actors[holder_id], mark_condition_id(name, owner_id), "test:mark", owner_id, expires_on="UNTIL_REMOVED")


def test_starbolt_reaches_30_feet_farther_against_a_marked_creature():
    engine = _fight(_stars([]), me_at=(0, 6), foe_at=(19, 6))  # 95 feet away
    aligned = [n for n in _names(engine) if n.startswith("Starbolt (Aligned")]
    assert not aligned and "Starbolt" not in {n for n in _names(engine)}
    _mark(engine, L1.AN)
    aligned = [n for n in _names(engine) if n.startswith("Starbolt (Aligned")]
    assert aligned
    events = _act(engine, aligned[0], L1.AN)
    assert _of(events, "ATTACK_ROLLED")


def test_falling_spark_gives_one_marked_creature_disadvantage():
    engine = _fight(_stars(["STARS_TAL_FALLING_SPARK"]), foe_at=(8, 6))
    _mark(engine, L1.AN)
    names = sorted(n for n in _names(engine) if n.startswith("Falling Spark"))
    events = _act(engine, next((n for n in names if n.endswith("at 8,6")), names[0]))
    assert [p["mode"] for p in _of(events, "SAVE_ROLLED")] == ["DISADVANTAGE"]


def test_heaven_falling_star_marked_creatures_have_disadvantage():
    engine = _fight(_stars(["STARS_TAL_HEAVEN_FALLING_STAR"], cl=17), foe_at=(8, 6))
    _mark(engine, L1.AN)
    names = sorted(n for n in _names(engine) if n.startswith("Heaven-Falling Star"))
    # The intended centre retains the native allied-collateral warning suffix.
    events = _act(engine, next(n for n in names if n.split(" — ", 1)[0].endswith("at 8,6")))
    # Heaven-Falling Star affects every creature in the area. Friendly-fire
    # preserves the unmarked caster's normal save as well as the marked foe's.
    assert [e.payload["mode"] for e in events if e.event_type == "SAVE_ROLLED"
            and e.actor_id == L1.AN] == ["DISADVANTAGE"]
    assert [e.payload["mode"] for e in events if e.event_type == "SAVE_ROLLED"
            and e.actor_id != L1.AN] == ["NORMAL"]


def test_comet_spear_strips_half_cover_from_a_marked_target_for_its_attack():
    engine = _fight(_stars(["STARS_TAL_COMET_SPEAR"]), foe_at=(8, 6))
    _mark(engine, L1.AN)
    events = _act(engine, "Comet Spear", L1.AN)
    applied = [p for p in _of(events, "CONDITION_APPLIED") if p["condition_id"] == "condition:an_eui.break_guard.no_half_cover"]
    assert applied and not _held(engine.state.actors[L1.AN], "condition:an_eui.break_guard.no_half_cover")


def test_star_piercing_line_needs_a_marked_target_and_seals_teleport_invisibility_and_cover():
    engine = _fight(_stars(["STARS_TAL_STAR_PIERCING_LINE"], cl=17, dc=50), foe_at=(8, 6))
    assert "Star-Piercing Line" not in _names(engine)
    _mark(engine, L1.AN)
    _act(engine, "Star-Piercing Line", L1.AN)
    foe = engine.state.actors[L1.AN]
    assert _held(foe, "condition:typed.cannot_teleport") and _held(foe, "condition:an_eui.break_guard.no_half_cover")
    assert [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.exposed")]


def test_cold_star_mantle_adds_proficiency_bonus_to_one_star_damage_roll_a_turn():
    engine = _fight(_stars([S + "cold_star_mantle"]), foe_at=(8, 6))
    _answers(engine, {"willing": lambda options: options[:1], "stars_cold_mantle": lambda options: options[:1]})
    _act(engine, "Cold Star Mantle")
    assert _held(engine.state.actors[ME], "condition:typed.stars_cold_mantle")
    _ready(engine)
    first = _act(engine, "Starbolt", L1.AN)
    rolled = [p for p in _of(first, "DAMAGE_ROLLED")]
    assert rolled and rolled[0]["modifier"] >= 4
    _ready(engine)
    second = _act(engine, "Starbolt", L1.AN)
    assert all(p["modifier"] < 4 for p in _of(second, "DAMAGE_ROLLED"))  # once per turn


def test_constellation_guard_ac_lasts_while_a_star_burns():
    engine = _fight(_stars([S + "constellation_guard"]), attacker=True)
    me = engine.state.actors[ME]
    before = engine._effective_ac(me) if hasattr(engine, "_effective_ac") else None
    _act(engine, "Constellation Guard")
    from combat import ext
    assert sum(ext.run("ac", engine, me)) >= 2
    for _ in range(7):
        engine._commit_damage(me, 3, "SLASHING", "test:hit", ATK, None, reaction_depth=0)
    assert 2 not in ext.run("ac", engine, me)


def test_guiding_star_gives_an_ally_a_d4_against_the_marked_creature():
    ally = _bundle(["TAL_ALCHEMY_CALMING_HEART_PILL"], actor_id=ALLY, weapon="tianxia.mortal.weapon.dao")
    engine = _fight(_stars([S + "guiding_star"], dc=50), allies=(ally,))
    _act(engine, "Guiding Star", L1.AN)
    assert _held(engine.state.actors[L1.AN], "condition:typed.mark.stellar_mark." + ME)
    _ready(engine, ALLY)
    engine.state.actors[ALLY].position = engine.state.actors[L1.AN].position.model_copy(update={"y": 5})
    events = _act(engine, "Dao (Saber / Broadsword) attack", L1.AN, actor_id=ALLY)
    assert any("GUIDING_STAR" in str(p.get("reason")) for p in _of(events, "DAMAGE_ROLLED")) or \
        any("Guiding Star" in str(p.get("log")) for p in _of(events, "PASSIVE_TRIGGERED"))


def test_night_sight_meridian_grants_darkvision():
    engine = _fight(_stars([S + "night_sight_meridian"]))
    from combat import senses
    before = dict(senses.of(engine, engine.state.actors[ME])) if hasattr(senses, "of") else {}
    _act(engine, "Night-Sight Meridian")
    after = senses.of(engine, engine.state.actors[ME])
    assert "darkvision" in json.dumps(after, default=str).lower() and after != before


def test_star_name_seal_needs_the_mark_and_holds_teleport():
    engine = _fight(_stars([S + "star_name_seal"], cl=17, dc=50), foe_at=(8, 6))
    assert "Star Name Seal" not in _names(engine)
    _mark(engine, L1.AN)
    _act(engine, "Star Name Seal", L1.AN)
    [seal] = _held(engine.state.actors[L1.AN], "condition:typed.star_name_seal")
    assert seal.data["rule"]["no_teleport"] and seal.data["repeat_save"]["ability"] == "CHA"


def test_marked_creature_cannot_hide_behind_invisibility_from_the_marker():
    engine = _fight(_stars([]), foe_at=(8, 6))
    foe, me = engine.state.actors[L1.AN], engine.state.actors[ME]
    engine._apply_condition(foe, "condition:typed.invisible", "test:inv", L1.AN, expires_on="UNTIL_REMOVED")
    from combat import ext
    assert not any(ext.run("masked_conditions", engine, me, foe))
    _mark(engine, L1.AN)
    masked = [m for m in ext.run("masked_conditions", engine, me, foe) if L1.AN in m]
    assert masked


def test_starpath_step_moves_without_opportunity_attacks_over_rough_ground():
    engine = _fight(_stars([S + "starpath_step"]))
    me = engine.state.actors[ME]
    _act(engine, "Starpath Step")
    assert int(me.turn_flags.get("oa_free_ft") or 0) >= 20 and _held(me, "condition:typed.ignore_difficult")


def test_stars_domain_compass_pulse_is_one_chosen_effect():
    """"Compass Pulse. When an enemy starts its turn inside the Domain ... Failed Save: Choose one effect" (it applied all five)."""
    engine = _fight(_stars([S + "stars_domain"], cl=17, dc=50), foe_at=(5, 6))
    asked = _answers(engine, {"stars_compass_pulse": ["reactions"]})
    _act(engine, "Stars Domain")
    foe = engine.state.actors[L1.AN]
    foe.saving_throws["CHA"] = -40
    before = len(engine.events)
    _act(engine, "End turn")
    assert engine.state.current_actor_id == L1.AN
    assert _held(foe, "condition:typed.reaction_denied") and not _damage(engine.events[before:])
    assert not [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.mark.stellar_mark")]
    assert any("stars_compass_pulse" in r["reaction_source_id"] for r in asked)


def test_world_beneath_the_constellations_saves_before_teleporting():
    engine = _fight(_stars([S + "world_beneath_the_constellations"], cl=17, dc=50), foe_at=(8, 6))
    names = sorted(n for n in _names(engine) if n.startswith("World Beneath"))
    _act(engine, next((n for n in names if n.endswith("at 8,6")), names[0]))
    from combat import ext, typed_executor
    from combat.gate2_runtime_models import Position
    foe = engine.state.actors[L1.AN]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 2}}, [foe], foe, {})
    assert False in ext.run("teleport_gate", ctx, foe.position, Position(x=0, y=0))


def test_star_shadow_is_summoned_and_its_hit_marks():
    """Star Shadow: AC 13 + PB, a Star Strike, and "Guiding Light. When the shadow hits a creature, apply Stellar Mark"."""
    engine = _fight(_stars([S + "star_shadow"]), foe_at=(5, 6))
    _act(engine, "Star Shadow")
    [shadow] = [a for a in engine.state.actors.values() if (a.summon or {}).get("source") == S + "star_shadow" and a.active]
    assert shadow.armor_class == 13 + 4
    _ready(engine, shadow.entity_id)
    shadow.position = engine.state.actors[L1.AN].position.model_copy(update={"y": 5})
    _act(engine, "Star Strike", L1.AN, actor_id=shadow.entity_id)
    assert _held(engine.state.actors[L1.AN], "condition:typed.mark.stellar_mark." + ME)


def test_star_sovereign_starbolt_deals_six_d10_and_starpath_is_free_once():
    engine = _fight(_stars([S + "star_sovereign_incarnation", S + "starpath_step"], cl=17), foe_at=(8, 6))
    _act(engine, "Star-Sovereign Incarnation")
    _ready(engine)
    events = _act(engine, "Starbolt", L1.AN)
    assert any(p["expression"].startswith("6d10") for p in _of(events, "DAMAGE_ROLLED"))
    free = "Starpath Step (Star-Sovereign: 60 feet, no cost)"
    assert free in _names(engine)
    _act(engine, free)
    assert free not in _names(engine)


def test_star_needle_aim_adds_one_to_an_unmarked_target():
    plain = _fight(_stars([S + "star_needle_aim"]), foe_at=(8, 6))
    base = _of(_act(plain, "Starbolt", L1.AN), "ATTACK_ROLLED")[0]["modifier"]
    engine = _fight(_stars([S + "star_needle_aim"]), foe_at=(8, 6))
    _act(engine, "Star-Needle Aim")
    aimed = _of(_act(engine, "Starbolt", L1.AN), "ATTACK_ROLLED")[0]["modifier"]
    assert aimed == base + 1
    _ready(engine)
    _act(engine, "Star-Needle Aim")  # now against the creature Starbolt marked: no Half Cover for that attack only
    events = _act(engine, "Starbolt", L1.AN)
    assert any(p["condition_id"] == "condition:an_eui.break_guard.no_half_cover" for p in _of(events, "CONDITION_APPLIED"))
    assert not _held(engine.state.actors[L1.AN], "condition:an_eui.break_guard.no_half_cover")


# ============================================================================================================ Pressure Points
PP = "tianxia.talent.pressure_points."
PP_MARK = "condition:typed.mark.pressure_point." + ME


def _pp(mids, **kw):
    return _bundle(list(mids), **kw)


def _pick(engine, label):
    _act(engine, f"Touch the Point: {label}")


def _press(engine, target=None):
    _ready(engine)
    return _act(engine, "Fu (Short Axe) attack", target or L1.AN)


def test_eye_watering_point_blurs_the_next_far_attack():
    engine = _fight(_pp([PP + "eye_watering_point"]))
    _pick(engine, "Eye-Watering Point")
    _press(engine)
    foe = engine.state.actors[L1.AN]
    assert _held(foe, "condition:typed.pp_eye_watering") and _held(foe, PP_MARK)
    from combat import ext, typed_executor
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {}, "range_ft": 60}, [engine.state.actors[ME]],
                                 engine.state.actors[ME], {})
    assert "DISADVANTAGE" in ext.run("attack_mode", ctx, engine.state.actors[ME])
    assert not _held(foe, "condition:typed.pp_eye_watering")  # "the next" attack roll


def test_stance_breaking_point_failed_save_is_one_chosen_effect():
    engine = _fight(_pp([PP + "stance_breaking_point"], dc=50))
    _answers(engine, {"pp_stance_breaking": ["stop"]})
    _pick(engine, "Stance-Breaking Point")
    foe = engine.state.actors[L1.AN]
    foe.saving_throws.update({"STR": -40, "DEX": -40})  # Touch the Point saves use the attack's own Cultivation Save DC
    _press(engine)
    assert engine._effective_speed(foe) == 0 and not _held(foe, "condition:typed.prone")


def test_stolen_pulse_step_steps_away_without_the_targets_opportunity_attack():
    engine = _fight(_pp([PP + "stolen_pulse_step"]))
    asked = _answers(engine, {"rider_step": lambda options: [o for o in options if o == "cell:1,6"]})
    _pick(engine, "Stolen Pulse Step")
    _press(engine)
    me = engine.state.actors[ME]
    assert (me.position.x, me.position.y) == (1, 6) and any("Stolen Pulse Step" in str(r) for r in asked)


def test_weak_pulse_point_shrinks_the_next_healing():
    engine = _fight(_pp([PP + "weak_pulse_point"]))
    _pick(engine, "Weak Pulse Point")
    _press(engine)
    foe = engine.state.actors[L1.AN]
    foe.current_hp = 100
    from combat import typed_executor
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 2}}, [foe], foe, {})
    typed_executor.run_effects(ctx, [{"type": "healing", "applies_to": "target", "flat": 10, "formula": "none"}])
    assert foe.current_hp == 100 + 10 - 4


def test_falling_gate_seal_knocks_the_marked_creature_prone():
    engine = _fight(_pp([PP + "falling_gate_seal"]))
    engine.state.actors[L1.AN].saving_throws["DEX"] = 40
    _pick(engine, "Falling Gate Seal")
    _mark(engine, L1.AN, name="Pressure Point")
    _press(engine)
    foe = engine.state.actors[L1.AN]
    assert _held(foe, "condition:typed.prone") and not _held(foe, PP_MARK)


def test_shut_the_heaven_gate_dazes_on_a_success_and_stuns_on_a_failure():
    for save, stunned in ((40, False), (-40, True)):
        engine = _fight(_pp([PP + "shut_the_heaven_gate"], cl=17), attacker=True)
        _pick(engine, "Shut the Heaven Gate")
        _mark(engine, ATK, name="Pressure Point")
        engine.state.actors[ATK].saving_throws["CON"] = save
        engine.state.actors[ATK].armor_class = -50
        _press(engine, ATK)
        atk = engine.state.actors[ATK]
        assert bool(_held(atk, "condition:typed.stunned")) is stunned
        if not stunned:
            assert _held(atk, "condition:typed.pp_dazed")
            _ready(engine, ATK)
            _act(engine, "Calming Heart Pill", actor_id=ATK) if "Calming Heart Pill" in _names(engine) else _act(engine, "Dodge", actor_id=ATK)
            assert not any(c.display_name != "End turn" and engine.action_catalog.get(c.source_definition_id) is not None
                           and str(engine.action_catalog[c.source_definition_id].economy).endswith("BONUS_ACTION")
                           for c in engine.legal_candidates() if c.actor_id == ATK)


def test_soft_paralysis_tap_does_not_restrain_on_a_success():
    engine = _fight(_pp([PP + "soft_paralysis_tap"], cl=10))
    engine.state.actors[L1.AN].saving_throws["CON"] = 40
    _pick(engine, "Soft Paralysis Tap")
    _mark(engine, L1.AN, name="Pressure Point")
    _press(engine)
    assert not _held(engine.state.actors[L1.AN], "condition:typed.restrained")


def test_joint_seal_disables_the_chosen_leg():
    engine = _fight(_pp([PP + "joint_seal"], dc=50))
    _answers(engine, {"pp_joint_seal": ["leg"]})
    _pick(engine, "Joint Seal")
    _mark(engine, L1.AN, name="Pressure Point")
    foe = engine.state.actors[L1.AN]
    foe.saving_throws["STR"] = -40
    full = engine._effective_speed(foe)
    _press(engine)
    assert engine._effective_speed(foe) == full // 2


def test_retaliatory_nerve_answers_a_miss_with_a_strike_that_applies_a_point():
    engine = _fight(_pp([PP + "retaliatory_nerve", PP + "eye_watering_point"]), attacker=True)
    _pick(engine, "Eye-Watering Point")
    me = engine.state.actors[ME]
    me.armor_class = 100
    engine.state.actors[ATK].armor_class = -50
    _answers(engine, {"retaliatory": ["use"], "Retaliatory": ["use"]})
    _ready(engine, ATK)
    events = _act(engine, "Dao (Saber / Broadsword) attack", ME, actor_id=ATK)
    atk = engine.state.actors[ATK]
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in events)
    assert _held(atk, "condition:typed.mark.pressure_point." + ME) and _held(atk, "condition:typed.pp_eye_watering")


def test_needle_meets_blade_applies_a_point_when_it_stops_the_hit():
    engine = _fight(_pp([PP + "needle_meets_blade", PP + "eye_watering_point"], cl=11), attacker=True)
    _pick(engine, "Eye-Watering Point")
    from combat import ext
    ext.run("hit_absorbed", engine, engine.state.actors[ME], engine.state.actors[ATK], (PP + "needle_meets_blade",))
    assert _held(engine.state.actors[ATK], "condition:typed.mark.pressure_point." + ME)
    mech = _mech()[PP + "needle_meets_blade"]
    assert any(r.get("dice_by_cl") for r in mech["effects"])


def test_meridian_stillness_field_slows_marked_foes_and_taxes_their_techniques():
    engine = _fight(_pp([PP + "meridian_stillness_field"], cl=17, dc=50), attacker=True, foe_at=(8, 6))
    names = sorted(n for n in _names(engine) if n.startswith("Meridian Stillness Field"))
    _act(engine, next((n for n in names if n.endswith("at 8,6")), names[0]))
    atk = engine.state.actors[ATK]
    free = engine._effective_speed(atk)
    _mark(engine, ATK, name="Pressure Point")
    assert engine._effective_speed(atk) == free - 10
    from combat import ext
    assert False in ext.run("opportunity_allowed", engine, atk, engine.state.actors[ME])
    _ready(engine, ATK)
    events = _act(engine, "Calming Heart Pill", actor_id=ATK)
    assert any("meridian_stillness_field" in str(p.get("reason")) for p in _of(events, "SAVE_ROLLED"))


# ============================================================================================================ Wrestling
W = "TAL_WRESTLING_"
GRAPPLED = "condition:typed.grappled"


def _grab(engine, holder_id=L1.AN, by=ME):
    """The creature is Grappled by ``by`` (the ordinary typed grapple data: escape DC and reach)."""
    engine._apply_condition(engine.state.actors[holder_id], GRAPPLED, "test:grapple", by, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": 14, "reach_ft": 5})


def _slam(engine, name, target=L1.AN):
    _ready(engine)
    return _act(engine, f"Apply a Slam: {name}", target)


def test_hammerlock_is_a_slam_that_makes_escape_checks_harder():
    engine = _fight(_bundle([W + "HAMMERLOCK"]))
    assert "Apply a Slam: Hammerlock" not in _names(engine)  # only against a creature you Grapple
    _grab(engine)
    _slam(engine, "Hammerlock")
    foe = engine.state.actors[L1.AN]
    from combat import ext
    grips = {c.instance_id: c for c in foe.conditions.values() if c.condition_id == GRAPPLED}
    assert "DISADVANTAGE" in ext.run("escape_mode", engine, foe, grips)


def test_hard_whip_ends_this_grapple_and_throws_ten_feet():
    engine = _fight(_bundle([W + "HARD_WHIP"]))
    _grab(engine)
    foe = engine.state.actors[L1.AN]
    start = foe.position.x
    _slam(engine, "Hard Whip")
    assert not _held(foe, GRAPPLED) and foe.position.x == start + 2


def test_heel_tactics_spends_martial_focus_and_blinds():
    engine = _fight(_bundle([W + "HEEL_TACTICS"]))
    _grab(engine)
    foe, me = engine.state.actors[L1.AN], engine.state.actors[ME]
    foe.saving_throws["DEX"] = -40
    _slam(engine, "Heel Tactics")
    assert _held(foe, "condition:typed.blinded") and me.resources["resource:core.martial_focus"] == 0


def test_joint_locking_scripture_failed_save_is_one_chosen_lock():
    engine = _fight(_bundle([W + "JOINT_LOCKING_SCRIPTURE"]), attacker=True)
    _answers(engine, {"wrestling_joint_lock": ["weapon"]})
    _grab(engine, ATK)
    atk = engine.state.actors[ATK]
    atk.saving_throws["CON"] = -40
    _slam(engine, "Joint-Locking Scripture", ATK)
    assert not _held(atk, "condition:typed.reaction_denied")
    _ready(engine, ATK)
    events = _act(engine, "Dao (Saber / Broadsword) attack", ME, actor_id=ATK)
    assert _of(events, "ATTACK_ROLLED")[0]["mode"] == "DISADVANTAGE"


def test_meridian_crushing_clinch_takes_two_and_can_bar_bonus_actions():
    engine = _fight(_bundle([W + "MERIDIAN_CRUSHING_CLINCH"], cl=10), attacker=True)
    _answers(engine, {"wrestling_meridian_crush": ["bonus", "reactions"]})
    _grab(engine, ATK)
    atk = engine.state.actors[ATK]
    atk.saving_throws["CON"] = -40
    _slam(engine, "Meridian-Crushing Clinch", ATK)
    assert _held(atk, "condition:typed.reaction_denied") and _held(atk, "condition:typed.wrestling_hold")
    _ready(engine, ATK)
    assert not any(str(engine.action_catalog[c.source_definition_id].economy).endswith("BONUS_ACTION")
                   for c in engine.legal_candidates() if c.actor_id == ATK and c.source_definition_id in engine.action_catalog)


def test_meridian_wrenching_lock_needs_your_pin():
    engine = _fight(_bundle([W + "MERIDIAN_WRENCHING_LOCK", W + "PIN_2"], cl=10))
    _answers(engine, {"wrestling_wrench": ["leg"]})
    _grab(engine)
    foe = engine.state.actors[L1.AN]
    foe.saving_throws.update({"STR": -40, "DEX": -40})
    full = engine._effective_speed(foe)
    focus = dict(engine.state.actors[ME].resources)
    assert "Apply a Slam: Meridian-Wrenching Lock" not in _names(engine)
    assert engine._effective_speed(foe) == full  # not Restrained through your Pin: no paid, ineffective button
    assert engine.state.actors[ME].resources == focus
    _ready(engine)
    _act(engine, "Pin", L1.AN)
    assert _held(foe, "condition:typed.restrained")
    _slam(engine, "Meridian-Wrenching Lock")
    assert _held(foe, "condition:typed.wrenched_leg")


def test_iron_clinch_adds_one_ac_against_the_grappled_creature():
    engine = _fight(_bundle([W + "IRON_CLINCH"]), attacker=True)
    from combat import ext
    me, atk = engine.state.actors[ME], engine.state.actors[ATK]
    assert not ext.run("hit_response", engine, atk, me, {}, 15, 10, 15)
    _grab(engine, ATK)
    assert ext.run("hit_response", engine, atk, me, {}, 15, 10, 15) == [(16, False)]
    assert not ext.run("hit_response", engine, atk, me, {}, 16, 10, 15)


def test_court_of_the_closed_distance_regains_focus_when_a_grapple_save_fails():
    engine = _fight(_bundle([W + "COURT_OF_THE_CLOSED_DISTANCE"], cl=12))
    me = engine.state.actors[ME]
    _act(engine, "Court of the Closed Distance")
    assert _held(me, "condition:typed.state.court_of_the_closed_distance") and me.resources["resource:core.martial_focus"] == 0
    engine.state.actors[L1.AN].saving_throws.update({"STR": -40, "DEX": -40})
    _ready(engine)
    _act(engine, "Grapple", L1.AN)
    assert _held(engine.state.actors[L1.AN], GRAPPLED) and me.resources["resource:core.martial_focus"] == 1


def test_slip_and_strike_strikes_the_creature_you_let_go():
    engine = _fight(_bundle([W + "SLIP_AND_STRIKE"]))
    strike = [n for n in _names(engine) if n.startswith("Slip and Strike")]
    assert not strike
    _grab(engine)
    _act(engine, "Release grapple")
    strike = [n for n in _names(engine) if n.startswith("Slip and Strike")]
    assert strike
    events = _act(engine, strike[0], L1.AN)
    assert _of(events, "ATTACK_ROLLED") and not [n for n in _names(engine) if n.startswith("Slip and Strike")]


def test_choke_hold_silences_and_consecutive_rounds_choke():
    engine = _fight(_bundle([W + "CHOKE_HOLD"]))
    _grab(engine)
    foe = engine.state.actors[L1.AN]
    _slam(engine, "Choke Hold")
    assert _held(foe, "condition:typed.silenced") and not _held(foe, "condition:typed.choking")
    _slam(engine, "Choke Hold")
    assert not _held(foe, "condition:typed.choking")  # twice in one round is not consecutive rounds
    _act(engine, "End turn")
    while engine.state.current_actor_id != ME:
        _act(engine, "End turn", actor_id=engine.state.current_actor_id)
    _slam(engine, "Choke Hold")
    assert _held(foe, "condition:typed.choking")
    _act(engine, "End turn")
    while engine.state.current_actor_id != ME:
        _act(engine, "End turn", actor_id=engine.state.current_actor_id)
    from combat.ext import forged_exhaustion
    assert forged_exhaustion.level(foe) == 1


def test_opening_strike_grapples_on_a_failed_save():
    mech = _mech()[W + "OPENING_STRIKE"]
    save = mech["effects"][0]
    assert save["ability"].upper() == "STR_OR_DEX" and save["on_fail"][0]["condition"] == "grappled"


# ============================================================================================================ Verdant Growth
def test_thousand_root_prison_tears_away_when_its_prisoner_teleports():
    engine = _fight(_bundle(["TAL_VERDANT_GROWTH_THOUSAND_ROOT_PRISON"], cl=17, dc=50), foe_at=(8, 6))
    from combat.ext import verdant_chassis

    # "Target: One creature with at least 3 of your Growth Marks" (rider lane C16: the table counts them now).
    verdant_chassis.place(engine, engine.state.actors[ME], engine.state.actors[L1.AN], 3, "test")
    _act(engine, "Thousand-Root Prison", L1.AN)
    foe = engine.state.actors[L1.AN]
    assert _held(foe, "condition:typed.restrained")
    from combat import ext, typed_executor
    from combat.gate2_runtime_models import Position
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {}}, [foe], foe, {})
    before = len(engine.events)
    typed_executor._teleport(ctx, Position(x=12, y=6))
    assert foe.position == Position(x=12, y=6) and not _held(foe, "condition:typed.restrained")
    assert any(p["expression"].startswith("4d10") for p in _of(engine.events[before:], "DAMAGE_ROLLED"))


def test_seed_thorn_strike_scaling_line_is_typed_not_a_gm_line():
    # Merge 5c892c64 (owner MOD1) must retain C2's typed scaling, not restore its GM rider.
    mech = _mech()["TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"]
    assert not any(r.startswith("The damage increases") for r in mech["riders"])
    damage = [row for row in mech["effects"][0]["on_hit"] if row.get("type") == "damage"]
    assert len(damage) == 1
    assert damage[0]["dice_by_cl"] == [[1, 4, 1, 6], [5, 10, 2, 6], [11, 16, 3, 6], [17, 20, 4, 6]]
    assert damage[0]["formula"] == "key_ability_modifier"


# ============================================================================================================ Guardian
CH = "GUARDIAN_BASE_CHALLENGE_PRACTICE"
G = "TAL_GUARDIAN_"


def _guardian(mids=(), **kw):
    return _bundle([CH, *mids], **kw)


def test_challenge_makes_the_foe_attack_you_or_suffer():
    ally = _bundle(["TAL_ALCHEMY_CALMING_HEART_PILL"], actor_id=ALLY, weapon="tianxia.mortal.weapon.dao")
    engine = _fight(_guardian(dc=50), attacker=True, allies=(ally,))
    atk = engine.state.actors[ATK]
    atk.saving_throws["CHA"] = -40
    _act(engine, "Challenge Practice", ATK)
    assert _held(atk, "condition:typed.challenged")
    engine.state.actors[ALLY].position = atk.position.model_copy(update={"y": atk.position.y + 1})
    _ready(engine, ATK)
    at_ally = _of(_act(engine, "Dao (Saber / Broadsword) attack", ALLY, actor_id=ATK), "ATTACK_ROLLED")
    _ready(engine, ATK)
    at_me = _of(_act(engine, "Dao (Saber / Broadsword) attack", ME, actor_id=ATK), "ATTACK_ROLLED")
    assert at_ally[0]["mode"] == "DISADVANTAGE" and at_me[0]["mode"] == "ADVANTAGE"


def test_a_new_challenge_ends_the_old_one():
    engine = _fight(_guardian(dc=50), attacker=True)
    atk, foe = engine.state.actors[ATK], engine.state.actors[L1.AN] if L1.AN in engine.state.actors else None
    atk.saving_throws["CHA"] = -40
    _act(engine, "Challenge Practice", ATK)
    from combat import typed_executor
    from combat.ext import guardian
    me = engine.state.actors[ME]
    ctx = typed_executor.Context(engine, me, next(a for a in engine.action_catalog.values() if a.display_name == "Challenge Practice"), None,
                                 {"numbers": {}, "duration": {"kind": "minutes", "amount": 1}}, [me], me, {})
    guardian.challenge(ctx, {})  # (a creature of its own side stands in for a second foe)
    assert not _held(atk, "condition:typed.challenged") and _held(me, "condition:typed.challenged")


def test_punishing_challenge_burns_a_foe_that_ignores_you():
    ally = _bundle(["TAL_ALCHEMY_CALMING_HEART_PILL"], actor_id=ALLY, weapon="tianxia.mortal.weapon.dao")
    engine = _fight(_guardian([G + "PUNISHING_CHALLENGE"], dc=50), attacker=True, allies=(ally,))
    atk = engine.state.actors[ATK]
    atk.saving_throws["CHA"] = -40
    _act(engine, "Challenge Practice", ATK)
    engine.state.actors[ALLY].position = atk.position.model_copy(update={"y": atk.position.y + 1})
    _ready(engine, ATK)
    events = _act(engine, "Dao (Saber / Broadsword) attack", ALLY, actor_id=ATK)
    assert any(p["hp_damage"] == 10 and p["damage_type"] in ("PSYCHIC", "RADIANT") for p in _damage(events))


def test_flush_of_victory_grants_temporary_hp_when_the_challenged_foe_drops():
    engine = _fight(_guardian([G + "FLUSH_OF_VICTORY"], dc=50), attacker=True)
    atk, me = engine.state.actors[ATK], engine.state.actors[ME]
    atk.saving_throws["CHA"] = -40
    _act(engine, "Challenge Practice", ATK)
    engine._commit_damage(atk, atk.current_hp, "SLASHING", "test:finish", ME, None, reaction_depth=0)
    assert me.temporary_hp == 10


def test_inescapable_challenge_saves_before_teleporting_away():
    engine = _fight(_guardian([G + "INESCAPABLE_CHALLENGE"], dc=50), attacker=True)
    atk = engine.state.actors[ATK]
    atk.saving_throws.update({"CHA": -40, "WIS": -40})
    _act(engine, "Challenge Practice", ATK)
    from combat import ext, typed_executor
    from combat.gate2_runtime_models import Position
    ctx = typed_executor.Context(engine, atk, next(iter(engine.action_catalog.values())), None, {"numbers": {}}, [atk], atk, {})
    assert False in ext.run("teleport_gate", ctx, atk.position, Position(x=15, y=6))
    assert False not in ext.run("teleport_gate", ctx, atk.position, Position(x=3, y=5))


def test_swift_guardian_challenges_without_the_bonus_action():
    engine = _fight(_guardian([G + "SWIFT_GUARDIAN"], dc=50), attacker=True)
    me = engine.state.actors[ME]
    engine.state.actors[ATK].saving_throws["CHA"] = -40
    name = "Challenge (Swift Guardian: no action; spend Martial Focus, your readiness point)"
    _act(engine, name, ATK)
    assert me.bonus_action_available and me.resources["resource:core.martial_focus"] == 0


# ============================================================================================================ Berserker
B = "TAL_BERSERKER_"


def _batter_twice(engine, name, target=L1.AN):
    _ready(engine)
    first = _act(engine, name, target)
    _ready(engine)
    engine.state.actors[ME].turn_flags.clear()
    second = _act(engine, name, target)
    return first, second


def test_heavy_swing_stuns_only_a_target_battered_before_the_attack():
    engine = _fight(_bundle([B + "HEAVY_SWING"], cl=10))
    foe = engine.state.actors[L1.AN]
    foe.saving_throws["CON"] = -40
    _ready(engine)
    _act(engine, "Batter: Fu (Short Axe) + Heavy Swing", L1.AN)
    assert _held(foe, "condition:typed.battered") and not _held(foe, "condition:typed.stunned")
    assert _held(foe, "condition:typed.wrestling_hold")  # cannot take Bonus Actions
    _ready(engine)
    engine.state.actors[ME].turn_flags.clear()
    _act(engine, "Batter: Fu (Short Axe) + Heavy Swing", L1.AN)
    assert _held(foe, "condition:typed.stunned")


def test_leg_smasher_topples_an_already_battered_target():
    engine = _fight(_bundle([B + "LEG_SMASHER"], cl=10))
    foe = engine.state.actors[L1.AN]
    foe.saving_throws["STR"] = -40
    first, second = _batter_twice(engine, "Batter: Fu (Short Axe) + Leg-Smasher")
    assert not any(p["condition_id"] == "condition:typed.prone" for p in _of(first, "CONDITION_APPLIED"))
    assert _held(foe, "condition:typed.prone")


def test_marauder_speed_follows_cultivation_level_while_it_is_the_adrenaline_talent():
    for cl, bonus in ((3, 5), (10, 10), (17, 20)):
        engine = _fight(_bundle([B + "MARAUDER"], cl=cl))
        me = engine.state.actors[ME]
        base = engine._effective_speed(me)
        _act(engine, "Adrenaline: Marauder")
        assert engine._effective_speed(me) == base + bonus


def test_unyielding_advance_resists_a_push_that_fails_a_strength_check():
    engine = _fight(_bundle([B + "UNYIELDING_ADVANCE"], cl=10, dc=50))
    me = engine.state.actors[ME]
    _act(engine, "Adrenaline: Unyielding Advance")
    from combat import typed_executor
    foe = engine.state.actors[L1.AN]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 2, "save_dc": 10}}, [me], me, {})
    start = me.position.x
    typed_executor.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away"}])
    assert me.position.x == start and any(e.event_type == "CHECK_ROLLED" for e in engine.events[-6:])


def test_war_god_incarnation_adds_batter_dice_and_counts_the_target_as_battered():
    engine = _fight(_bundle([B + "WAR_GOD_INCARNATION", B + "HEAVY_SWING"], cl=15))
    foe = engine.state.actors[L1.AN]
    foe.saving_throws["CON"] = -40
    _act(engine, "War-God Incarnation")
    _ready(engine)
    events = _act(engine, "Batter: Fu (Short Axe) + Heavy Swing", L1.AN)
    assert any(p["expression"].startswith("2d10") for p in _of(events, "DAMAGE_ROLLED"))
    assert _held(foe, "condition:typed.stunned")  # counts as already Battered


def test_sanguine_invigoration_grants_cl_temporary_hp_on_a_melee_kill():
    engine = _fight(_bundle([B + "SANGUINE_INVIGORATION"], cl=10), both=True)
    _answers(engine, {"berserker_sanguine_eligibility": ["eligible"]})  # the GM confirms printed CR eligibility
    foe, me = engine.state.actors[L1.AN], engine.state.actors[ME]
    foe.current_hp = 1
    _ready(engine)
    _act(engine, "Fu (Short Axe) attack", L1.AN)
    assert me.temporary_hp == 10


@pytest.mark.parametrize("hit,critical,con_save,disabled", [
    (True, True, -40, True),
    (True, True, 40, False),
    (True, False, -40, False),
    (False, False, -40, False),
])
def test_meridian_rending_blow_disables_a_leg_on_a_critical_hit(hit, critical, con_save, disabled):
    engine = _fight(_bundle([B + "MERIDIAN_RENDING_BLOW"], cl=10))
    asked = _answers(engine, {"berserker_meridian_rending": ["leg"]})
    foe, me = engine.state.actors[L1.AN], engine.state.actors[ME]
    foe.saving_throws["CON"] = con_save
    from combat import ext
    from combat.typed_executor import Context
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Fu (Short Axe) attack")
    candidate = next(c for c in engine.legal_candidates() if c.display_name == action.display_name)
    intent = ActionIntent(intent_id="meridian-probe", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=ME, target_ids=(foe.entity_id,))
    # Merge cf1c107f (C9 Intercession) consumes the documented attack_result
    # field. Use the real Context contract rather than an incomplete stand-in.
    ctx = Context(engine, me, action, intent, action.parameters["typed"], [foe], foe,
                  attack_effect={"attack_kind": "weapon"},
                  attack_result={"roll_id": "meridian-probe", "natural_result": 20 if critical else 10})
    before = len(engine.events)
    ext.run_strict("attack_result", ctx, foe, hit, critical)
    legs = _held(foe, "condition:typed.rended_leg")
    assert bool(legs) is disabled
    assert not _held(foe, "condition:typed.rended_arm")
    triggered = hit and critical
    assert me.resources["resource:core.martial_focus"] == (0 if triggered else 1)
    assert bool(asked) is triggered
    saves = _of(engine.events[before:], "SAVE_ROLLED")
    assert len(saves) == int(triggered)
    if saves:
        assert saves[0]["success"] is (not disabled)
    if legs:
        assert len(legs) == 1
        assert legs[0].expires_on == "UNTIL_REMOVED"
