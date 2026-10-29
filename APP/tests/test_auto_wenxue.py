"""Wen Xue's Sabers core and Empty Bowl Mark generation (owner 2026-09-28, "automate every aspect before another
playtest"): Edge Momentum/Guard Pressured, Saber-Line Pressure's once-a-turn choice, Hard Draw Cut's next-hit
bonus, Saber Scare, and Gather Empty Bowl Mark. combat/ext/wenxue_sabers.py, combat/ext/wenxue_foundation.py,
authority/typed_mechanics/reviewed_final.d/wenxue.json."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.wenxue_test"
DAO_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}

BASE_SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Spirit Awakening", "key_ability": "WIS"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Resonance", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 16, "technique_attack_bonus": 8,
    },
    "equipment": [DAO_KIT],
}
SABERS_TALENTS = ["tianxia.talent.sabers.forward_cut", "tianxia.talent.sabers.circle_cleaving_saber",
                  "tianxia.talent.sabers.hard_draw_cut", "tianxia.talent.sabers.saber_scare",
                  "tianxia.talent.sabers.banner_cleaving_advance",  # mentions "Edge Momentum" so the pool is created
                  "SABERS_BASE_SABER_LINE_METHOD", "SABERS_BASE_SABER_LINE_PRESSURE"]
FOUNDATION = {"foundation_id": "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR", "stage": "Awakened",
              "resource": {"name": "Empty Bowl Mark", "resource_id": "foundation.resource.FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR", "maximum": 1}}
EMPTY_BOWL_MARK = "resource:foundation.empty_bowl_mark"
EDGE_MOMENTUM = "resource:named.edge_momentum"


def _bundle(talents=SABERS_TALENTS, foundation=None, extra_music=()):
    sheet = {**BASE_SHEET,
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.sabers", "tianxia.sphere.music"],
                                     "learned_talent_record_ids": [*talents, *extra_music]}}
    if foundation:
        sheet["foundation"] = foundation
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="WENXUE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _use(engine, name, *, target=None):
    """Execute the named action (its own weapon reach/range), against ``target`` (default: the sole foe)."""
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=f"i{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids or ((target,) if target else ())))
    return candidate


def _ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available = True, True


def test_forward_cut_deals_the_dao_s_own_damage_not_a_bare_1d4():
    bundle = _bundle()
    forward_cut = next(row for row in bundle["action_catalog"] if row["display_name"] == "Forward Cut")
    effects = forward_cut["parameters"]["typed"]["effects"]
    assert effects[0]["type"] == "attach_saber_weapon"  # runs before the attack effect resolves ctx.typed["weapon"]
    attack = next(e for e in effects if e["type"] == "attack")
    damage = next(e for e in attack["on_hit"] if e["type"] == "damage")
    assert damage["weapon_damage"] is True  # not the flat-PB-only, no-dice effect the authority originally typed


def test_forward_cut_hits_with_the_dao_s_slashing_dice():
    engine = _engine(_bundle())
    foe = engine.state.actors[AN]
    hp_before = foe.current_hp
    hit_event = None
    for attempt in range(8):
        _ready(engine)
        _use(engine, "Forward Cut")
        if foe.current_hp < hp_before:
            hit_event = next(e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME)
            break
        hp_before = foe.current_hp
    assert hit_event is not None
    assert hit_event.payload["damage_type"] == "SLASHING"  # the dao's own type, not the pre-fix bug's UNTYPED default


def test_circle_cleaving_saber_marks_its_target_guard_pressured():
    engine = _engine(_bundle())
    foe = engine.state.actors[AN]
    for attempt in range(8):
        _ready(engine)
        _use(engine, "Circle-Cleaving Saber")
        if bears_mark(foe, ME, "Guard Pressured"):
            break
    assert bears_mark(foe, ME, "Guard Pressured")


def test_saber_line_pressure_grants_edge_momentum_once_a_turn_on_a_saber_hit():
    bundle = _bundle()
    assert any(row["block"] == "saber_line_pressure" for row in bundle["typed_passives"])
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert me.resources[EDGE_MOMENTUM] == 0
    hits = 0
    for attempt in range(10):
        _ready(engine)
        before = foe.current_hp
        _use(engine, "Forward Cut")
        if foe.current_hp < before:
            hits += 1
            if hits == 1:
                assert me.resources[EDGE_MOMENTUM] == 1  # gained on the first saber hit this turn
            if hits == 2:
                break  # a second hit in a later turn must not grant a second Edge Momentum this same turn
    assert me.resources[EDGE_MOMENTUM] == 1  # capped at once per turn even across two separate hits/turns' worth of tries


def test_saber_line_pressure_toggle_guard_pressures_instead_of_gaining_edge_momentum():
    bundle = _bundle()
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    toggle = next(c for c in engine.legal_candidates() if c.display_name == "Saber-Line Pressure: prefer Guard Pressure")
    engine.execute_intent(ActionIntent(intent_id="toggle", decision_id=toggle.decision_id, candidate_id=toggle.candidate_id,
                                       state_version=toggle.state_version, actor_id=ME, target_ids=toggle.target_ids))
    for attempt in range(8):
        _ready(engine)
        before = foe.current_hp
        _use(engine, "Forward Cut")
        if foe.current_hp < before:
            break
    assert bears_mark(foe, ME, "Guard Pressured")
    assert me.resources[EDGE_MOMENTUM] == 0  # the toggle traded the default Edge Momentum gain for this instead


def test_hard_draw_cut_adds_proficiency_bonus_to_only_the_next_saber_hit():
    engine = _engine(_bundle())
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _use(engine, "Hard Draw Cut")
    assert any(c.condition_id == "condition:typed.wenxue.hard_draw_ready" for c in me.conditions.values())
    first_hit_damage = None
    for attempt in range(8):
        if first_hit_damage is None:
            _ready(engine)
        before = foe.current_hp
        _use(engine, "Forward Cut")
        if foe.current_hp < before:
            first_hit_damage = before - foe.current_hp
            break
        _ready(engine)
    assert first_hit_damage is not None
    assert not any(c.condition_id == "condition:typed.wenxue.hard_draw_ready" for c in me.conditions.values())  # consumed
    # A later hit (Circle-Cleaving Saber, once Hard Draw Cut is spent) must not add the bonus again.
    second_hit_damage = None
    for attempt in range(8):
        _ready(engine)
        before = foe.current_hp
        _use(engine, "Circle-Cleaving Saber")
        if foe.current_hp < before:
            second_hit_damage = before - foe.current_hp
            break
    assert second_hit_damage is not None
    bonus_commits = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id.endswith(".hard_draw_cut")]
    assert len(bonus_commits) == 1  # the +PB bonus fired exactly once (the first hit), never on the second


def test_saber_scare_makes_a_nearby_hostile_save_or_lose_reactions_on_a_kill():
    from combat.gate2_runtime_content import LING

    bundle = _bundle()
    assert any(row["block"] == "saber_scare" for row in bundle["typed_passives"])
    engine = Gate4ControllerEngine(ROOT, match_seed="SCARE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN, LING], "team_by_actor": {ME: "team:a", AN: "team:b", LING: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, LING: {"x": 5, "y": 6}}})
    foe, bystander = engine.state.actors[AN], engine.state.actors[LING]
    foe.current_hp = 1  # one hit away from 0
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    killed = False
    for attempt in range(10):
        _ready(engine)
        _use(engine, "Forward Cut")
        if not foe.active:
            killed = True
            break
    assert killed
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == bystander.entity_id for e in engine.events[-15:]) \
        or any(e.event_type == "CONDITION_APPLIED" and bystander.entity_id in (e.target_ids or ()) and "reaction_denied" in str((e.payload or {}).get("condition_id"))
              for e in engine.events[-15:])  # Saber Scare offered the WIS save (or it already failed and lost Reactions)


def test_gather_empty_bowl_mark_fires_after_healing_hymn_once_a_round():
    bundle = _bundle(talents=[], foundation=FOUNDATION, extra_music=["tianxia.talent.music.healing_hymn", "MUSIC_BASE_KEEP_THE_MEASURE"])
    assert any(row["block"] == "generate" and "wenxue_empty_bowl_support" in (row.get("on") or []) for row in bundle["typed_passives"])
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    assert me.resources[EMPTY_BOWL_MARK] == 0
    _use(engine, "Healing Hymn")
    assert me.resources[EMPTY_BOWL_MARK] == 1
    _ready(engine)
    engine._spend_resource(me, EMPTY_BOWL_MARK, 1, "test")
    _use(engine, "Healing Hymn")
    assert me.resources[EMPTY_BOWL_MARK] == 0  # once a round -- the same round's second use does not regenerate it


def test_guard_cutting_parry_press_the_guard_spends_a_resource_and_marks_the_attacker():
    from combat.factory_compiler import RESOURCE_IDS
    from combat.typed_executor import mark_condition_id

    bundle = _bundle(talents=["tianxia.talent.sabers.guard_cutting_parry", "SABERS_BASE_SABER_LINE_METHOD"])
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    resonance = RESOURCE_IDS["resonance"]
    me.resources[resonance] = 5
    # The base parry itself runs through the engine's own generic damage_reduction reaction block (not this
    # plug-in); simulate its REACTION_RESOLVED event directly rather than orchestrating a real incoming hit.
    engine._append_event("REACTION_RESOLVED", "tianxia.talent.sabers.guard_cutting_parry", actor_id=me.entity_id, target_ids=(foe.entity_id,),
                         payload={"checkpoint": "DAMAGE_APPLICATION", "reduction": 5, "pending_before": 10, "pending_after": 5, "reaction_depth": 0})
    assert me.resources[resonance] == 4  # spent the optional 1 CP/Stamina upgrade
    assert any(c.condition_id == mark_condition_id("Guard Pressured", me.entity_id) for c in foe.conditions.values())
