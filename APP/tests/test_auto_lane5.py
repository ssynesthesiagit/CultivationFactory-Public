"""Automation lane 5 (untyped passive abilities): each typed passive is compiled on a real character and run through the
engine.  Every test fails on the typing the authority carried before this lane (nothing typed: RIDERS_ONLY).

Overrides live in authority/typed_mechanics/reviewed_final.d/auto_lane5.json.  Saves are forced with the sheet's technique
DC (FAIL=50: the foe fails, PASS=-40: it succeeds) and attacks always hit (foe AC -50), as in test_review_sw-athletics.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent

_spec = importlib.util.spec_from_file_location("sweep_athletics_helpers", Path(__file__).with_name("test_review_sw-athletics.py"))
h = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(h)

BRUTE = "tianxia.sphere.brute"


def _hp_lost(engine):
    foe = h._foe(engine)
    return foe.maximum_hp - foe.current_hp


# ------------------------------------------------------------------------------------------------------------- Brute


def test_perpetual_motion_makes_a_second_shove_on_the_same_target():
    """"Immediately make one additional shove against the same target ... deals Brutal Shove damage normally, cannot trigger
    Perpetual Motion again": one Brutal Shove contest shoves once; the Perpetual Motion variant shoves twice (the first shove has
    already moved the target out of reach, which must not stop the second) and never a third time. Rider lane C16: Brutal Shove is
    the printed Athletics contest (it was an attack roll), so the distance is the printed margin's, not a fixed 10 feet."""
    plain = h._engine(h._bundle(BRUTE, [], h.AXE_KIT), foe_hp=200)
    plain.grid.qi_hazard = set()  # isolate shove packets from native forced-movement hazards
    h._foe(plain).skills = {"Athletics": -100, "Acrobatics": -100}
    events = h._use(plain, "Brutal Shove")
    assert [e.event_type for e in events].count("CHECK_ROLLED") == 1

    engine = h._engine(h._bundle(BRUTE, ["TAL_BRUTE_PERPETUAL_MOTION"], h.AXE_KIT), foe_hp=200)
    engine.grid.qi_hazard = set()
    h._foe(engine).skills = {"Athletics": -100, "Acrobatics": -100}
    names = h._legal(engine)
    assert "Brutal Shove + Perpetual Motion" in names, sorted(names)
    x0, hp = h._foe(engine).position.x, h._foe(engine).current_hp
    events = h._use(engine, "Brutal Shove + Perpetual Motion")
    kinds = [e.event_type for e in events]
    assert kinds.count("CHECK_ROLLED") == 2  # two shoves, never a third
    contests = [e for e in events if e.event_type == "CHECK_ROLLED"]
    assert all(e.payload["success"] and e.payload["contest"] == "shove" for e in contests)
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and h._foe(engine).entity_id in e.target_ids]
    assert [e.payload["rolled_or_pending_damage"] for e in packets] == [3, 3]  # each successful shove: Strength modifier
    assert [e.payload["hp_damage"] for e in packets] == [3, 3]
    assert hp - h._foe(engine).current_hp == 6
    assert h._foe(engine).position.x - x0 >= 2  # moved at least once beyond its first square
    assert not any("out of reach" in (e.payload or {}).get("rider", "") for e in events if e.event_type == "GM_RIDER")


def test_perpetual_motion_needs_the_first_shove_to_succeed():
    engine = h._engine(h._bundle(BRUTE, ["TAL_BRUTE_PERPETUAL_MOTION"], h.AXE_KIT), foe_hp=200, sure_hit=False)
    h._foe(engine).skills = {"Athletics": 100, "Acrobatics": 100}  # it wins the contest (rider lane C16: no attack roll)
    events = h._use(engine, "Brutal Shove + Perpetual Motion")
    assert [e.event_type for e in events].count("CHECK_ROLLED") == 1


# ------------------------------------------------------------------------------------------------------------- Dark

DARK = "tianxia.sphere.dark"


def _foe_menu_after_darkness(talents, at="4,6"):
    """The foe's menu once the caster has laid its Darkness at ``at`` (the foe stands at 4,6)."""
    engine = h._engine(h._bundle(DARK, talents, h.AXE_KIT), foe_hp=200)
    h._use(engine, f"Darkness at {at}", target=None)
    engine.state.current_actor_id = h.AN
    h._foe(engine).action_available = True
    return h._foe(engine), {c.display_name for c in engine.legal_candidates()}


def test_thick_darkness_takes_dash_and_disengage_from_creatures_inside():
    """"Creatures inside move at half Speed and cannot take the Dash or Disengage actions": inside a Thick Darkness the foe's
    menu has neither; in a plain Darkness, or outside a Thick one, it has both."""
    foe, menu = _foe_menu_after_darkness(["TAL_DARK_THICK_DARKNESS"])
    assert "typed.zone_effect" in h._conditions(foe)
    assert "Dash" not in menu and "Disengage" not in menu
    assert "Dodge" in menu  # only the two actions the text names

    _, plain = _foe_menu_after_darkness([])
    assert "Dash" in plain and "Disengage" in plain

    _, outside = _foe_menu_after_darkness(["TAL_DARK_THICK_DARKNESS"], at="0,13")
    assert "Dash" in outside and "Disengage" in outside


# ------------------------------------------------------------------------------------------------------- Berserker

BERSERKER = "tianxia.sphere.berserker"


def _juggernaut(*, adrenaline=True):
    engine = h._engine(h._bundle(BERSERKER, ["TAL_BERSERKER_JUGGERNAUT"], h.AXE_KIT), foe_hp=200)
    if adrenaline:
        h._use(engine, "Adrenaline: Juggernaut", target=None)
    return engine


def _slow(engine, **effect):
    """The foe puts a Speed effect on the Berserker (a typed effect, as any technique's failed save would)."""
    from combat import typed_executor

    me, foe = h._me(engine), h._foe(engine)
    action = next(row for row in engine.action_catalog.values() if row.owner_id == h.ME)
    ctx = typed_executor.Context(engine, foe, action, None, {"effects": [], "numbers": {}}, [me], me, {})
    typed_executor.run_effects(ctx, [{"type": "speed", "applies_to": "target", **effect}])
    return engine._effective_speed(me)


def test_juggernaut_speed_cannot_be_cut_by_ordinary_effects_while_adrenaline_is_on():
    """"Your Speed cannot be reduced below its normal value by ordinary effects; effects that reduce Speed to 0 still function":
    a Speed penalty and a halving do nothing to it, a Speed of 0 does; without Juggernaut's Adrenaline it is slowed as usual."""
    off = _juggernaut(adrenaline=False)
    normal = off._effective_speed(h._me(off))
    assert _slow(off, flat=-10) == normal - 10  # no Adrenaline: an ordinary penalty lands
    assert _slow(_juggernaut(adrenaline=False), halved=True) == normal // 2

    on = _juggernaut()
    assert _slow(on, flat=-10) == normal
    assert _slow(_juggernaut(), halved=True) == normal
    assert _slow(_juggernaut(), becomes=10) == normal  # "its Speed becomes 10 feet" is a reduction too
    assert _slow(_juggernaut(), becomes=0) == 0  # an effect that reduces Speed to 0 still works


def _difficult_ground(engine, cells):
    """An area of difficult ground made by the foe's ability (a zone, not the map's own terrain)."""
    from combat import zones
    from combat.gate2_runtime_models import Position, ZoneState

    engine.state.zones["zone:typed:test:1"] = ZoneState(
        zone_id="zone:typed:test:1", source_definition_id="test:ground", owner_id=h.AN, center=Position(x=cells[0][0], y=cells[0][1]),
        radius_cells=0, affected_cells=tuple(Position(x=x, y=y) for x, y in cells), concentration_link=False, duration_rounds=None,
        created_round=1, trigger_profile={"kind": zones.KIND, "name": "Rough ground", "difficult": "all", "triggers": [], "visual": {"material": "rubble"}})


def test_juggernaut_ignores_difficult_terrain_while_adrenaline_is_on():
    """"While active: ignore difficult terrain" -- the map's and an ability's ground alike (the text says no "nonmagical")."""
    cells = [(5, 6), (6, 6)]
    off = _juggernaut(adrenaline=False)
    _difficult_ground(off, cells)
    assert set(cells) <= off._hostile_difficult_cells(h._me(off))
    on = _juggernaut()
    _difficult_ground(on, cells)
    assert not on._hostile_difficult_cells(h._me(on))


# ---------------------------------------------------------------------------------------------------------- Equipment

def _lethal_hit(engine, me):
    """A hit that would take the fighter to 0 HP, run as block_damage does: offer the DAMAGE_APPLICATION reactions first, then
    commit whatever amount survives them."""
    from combat import typed_reactions

    pending = typed_reactions.on_damage(engine, me, 999, 0, source_actor_id=AN)
    engine._commit_damage(me, pending, "FORCE", "reaction:test.lethal_hit", AN, None, reaction_depth=0)


def test_soul_sealed_armor_holds_a_lethal_hit_at_1_hp_once_per_fight():
    """"Once per long rest, when damage would reduce you to 0 HP but not kill you outright, you may instead drop to 1 HP": the
    first lethal hit leaves 1 HP, the second (the same fight) drops to 0; without the talent the first one drops to 0."""
    engine = h._engine(h._bundle("tianxia.sphere.equipment", ["tianxia.talent.equipment.soul_sealed_armor"], h.AXE_KIT), foe_hp=200)
    me = h._me(engine)
    me.current_hp = 20
    _lethal_hit(engine, me)
    assert me.current_hp == 1
    me.current_hp = 20
    _lethal_hit(engine, me)
    assert me.current_hp == 0

    plain = h._engine(h._bundle("tianxia.sphere.equipment", [], h.AXE_KIT), foe_hp=200)
    plain_me = h._me(plain)
    plain_me.current_hp = 20
    _lethal_hit(plain, plain_me)
    assert plain_me.current_hp == 0


# ------------------------------------------------------------------------------------------------------------------ Poison


def _damage_types(events):
    return [(e.payload or {}).get("damage_type") for e in events if e.event_type == "DAMAGE_COMMITTED"]


def test_soul_venom_method_offers_the_spiritual_poison_as_psychic_or_necrotic():
    """"You may choose to make the poison spiritual ... you may deal Psychic or Necrotic damage instead of Poison or Acid damage":
    Deliver the Dose keeps its Poison/Acid dose, and a "+ Soul Venom Method" variant is offered that deals Psychic or Necrotic."""
    talents = ["tianxia.talent.poison.soul_venom_method"]
    names = h._legal(h._engine(h._bundle("tianxia.sphere.poison", talents, h.AXE_KIT), foe_hp=200))
    assert "Deliver the Dose" in names and "Deliver the Dose + Soul Venom Method" in names, sorted(names)
    plain = h._engine(h._bundle("tianxia.sphere.poison", talents, h.AXE_KIT), foe_hp=200)
    assert set(_damage_types(h._use(plain, "Deliver the Dose"))) <= {"POISON", "ACID"}
    spiritual = h._engine(h._bundle("tianxia.sphere.poison", talents, h.AXE_KIT), foe_hp=200)
    kinds = set(_damage_types(h._use(spiritual, "Deliver the Dose + Soul Venom Method")))
    assert kinds and kinds <= {"PSYCHIC", "NECROTIC"}, kinds

    without = h._legal(h._engine(h._bundle("tianxia.sphere.poison", [], h.AXE_KIT), foe_hp=200))
    assert "Deliver the Dose + Soul Venom Method" not in without


# ------------------------------------------------------------------------------------------------------------ Blacksmith


def _smith(with_talent: bool):
    from combat.factory_compiler import compile_character
    from tests import test_auto_ironclad as ironclad
    from tests.test_carry import KIT

    talents = [*ironclad.BLACKSMITH_TALENTS, *(["tianxia.talent.blacksmith.edge_before_blood"] if with_talent else [])]
    sheet = {**ironclad.SHEET, "equipment": [{"starting_kit": KIT}], "identity": {**ironclad.SHEET["identity"], "cultivation_level": 10},
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.blacksmith"], "learned_talent_record_ids": talents}}
    return ironclad, ironclad._engine(compile_character(sheet, actor_id=ironclad.ME))


def _set_edge_then_hit(with_talent: bool):
    """A Blacksmith with a Forge Mark uses Set Edge, then lands a guaranteed weapon hit.  Returns (engine, marks after Set Edge,
    marks after the hit)."""
    from combat.typed_executor import bears_mark, mark_condition_id

    ironclad, engine = _smith(with_talent)
    me = engine.state.actors[ironclad.ME]
    engine._apply_condition(me, mark_condition_id("Forge Mark", ironclad.ME), "test", ironclad.ME, expires_on="UNTIL_REMOVED")
    edge = next(c for c in engine.legal_candidates() if c.display_name == "Set Edge")
    engine.execute_intent(ActionIntent(intent_id="edge", decision_id=edge.decision_id, candidate_id=edge.candidate_id,
                                       state_version=edge.state_version, actor_id=ironclad.ME, target_ids=edge.target_ids))
    names = ("Set Edge Ready", "Edge Before Blood")
    during = {name: bears_mark(me, ironclad.ME, name) for name in names}
    attack = next(c for c in engine.legal_candidates() if c.display_name.endswith(" attack") and ".weapon." in c.source_definition_id)
    ironclad._guaranteed_hit(engine, attack)
    engine.execute_intent(ActionIntent(intent_id="wpn", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                       state_version=attack.state_version, actor_id=ironclad.ME, target_ids=attack.target_ids))
    return engine, during, {name: bears_mark(me, ironclad.ME, name) for name in names}


def test_edge_before_blood_marks_the_smith_at_set_edge_and_the_first_weapon_hit_spends_it():
    _, during, after = _set_edge_then_hit(True)
    assert during == {"Set Edge Ready": True, "Edge Before Blood": True}
    assert after == {"Set Edge Ready": False, "Edge Before Blood": False}
    _, during, _ = _set_edge_then_hit(False)
    assert during == {"Set Edge Ready": True, "Edge Before Blood": False}


def test_edge_before_blood_lets_the_marked_weapon_hit_through_resistance_but_not_immunity():
    """"Resistance becomes normal damage; immunity is unaffected": while the mark stands, a weapon hit deals full damage of the
    weapon's own type to a target that resists it, nothing more to one immune, and the mark does not help other damage types or a
    strike that is not a weapon attack; without the mark the resistance halves it."""
    from types import SimpleNamespace

    from combat.typed_executor import mark_condition_id
    from tests.test_damage_defenses import _committed
    from tests.test_typed_executor import _reactor

    engine, attacker, target = _reactor("EDGE", [])
    engine.action_catalog["src.blade"] = SimpleNamespace(parameters={"typed": {
        "effects": [{"type": "attack", "attack_kind": "weapon"}],
        "weapon": {"damage": {"count": 1, "sides": 4, "modifier": 2}, "damage_type": "PIERCING", "damage_types": ["PIERCING", "SLASHING"]}}})
    engine.action_catalog["src.fist"] = SimpleNamespace(parameters={"typed": {"effects": [{"type": "attack", "attack_kind": "unarmed"}]}})
    engine.typed_passive_rows[target.entity_id] = [
        {"feature_id": "f.hide", "block": "defense", "kind": "resistance", "damage_types": ["PIERCING", "SLASHING", "FIRE"]},
        {"feature_id": "f.bone", "block": "defense", "kind": "immunity", "damage_types": ["COLD"]}]
    hit = lambda kind, source="src.blade": _committed(engine, target, 20, kind, source, attacker.entity_id)  # noqa: E731
    assert hit("PIERCING") == 10  # no mark: resisted
    engine._apply_condition(attacker, mark_condition_id("Edge Before Blood", attacker.entity_id), "test", attacker.entity_id, expires_on="UNTIL_REMOVED")
    assert hit("PIERCING") == 20 and hit("SLASHING") == 20
    assert hit("FIRE") == 10  # not a type the weapon deals
    assert hit("COLD") == 0  # immunity is unaffected
    assert hit("PIERCING", "src.fist") == 10  # not a weapon hit


# ---------------------------------------------------------------- Rapid Analysis, Part-Breaker (Hidden Eye)
RAPID, PART = "TAL_THE_HIDDEN_EYE_RAPID_ANALYSIS", "TAL_THE_HIDDEN_EYE_PART_BREAKER"


def test_rapid_analysis_makes_analyze_a_bonus_action():
    from tests import test_auto_eye as eye

    def economy(talents):
        engine = eye._engine(talents)
        return next(action.economy.name for action in engine.action_catalog.values() if action.display_name == "Analyze")

    assert economy([]) == "ACTION"
    assert economy([RAPID]) == "BONUS_ACTION"


def _initiative_analyze(talents):
    """The Eye's own free Analyze as the fight begins: (its rolls, whether the foe is Analyzed, Martial Focus left)."""
    from combat.gate2_runtime_content import AN
    from tests import test_auto_eye as eye

    engine = eye._engine(talents)
    if engine.state.setup_tasks:
        from combat.gate2_runtime_models import ActionIntent
        candidate = engine.legal_candidates()[0]
        engine.execute_intent(ActionIntent(intent_id="initiative-setup", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=candidate.actor_id))
    me, foe = engine.state.actors[eye.ME], engine.state.actors[AN]
    rolls = [event for event in engine.events if event.event_type == "CHECK_ROLLED" and event.actor_id == eye.ME
             and ("rapid_analysis" in event.source_definition_id or event.source_definition_id == RAPID)]
    analyzed = any(c.condition_id == eye.ANALYZED and c.source_actor_id == eye.ME for c in foe.conditions.values())
    return rolls, analyzed, me.resources.get(eye.FOCUS)


def test_rapid_analysis_analyzes_a_visible_foe_when_the_fight_begins_for_free():
    rolls, analyzed, focus = _initiative_analyze([RAPID])
    assert len(rolls) == 1 and rolls[0].payload["success"] == analyzed
    assert focus == 1  # no Martial Focus expended
    none, analyzed_without, _ = _initiative_analyze([])
    assert none == [] and analyzed_without is False


def test_part_breaker_declaration_costs_focus_and_a_hit_analyzes_with_no_check():
    from tests import test_auto_eye as eye

    from combat.gate2_runtime_content import AN

    engine = eye._engine([PART])
    me, foe = engine.state.actors[eye.ME], engine.state.actors[AN]
    assert me.resources[eye.FOCUS] == 1
    # without the declaration a hit teaches nothing
    assert eye._attack_until_hit(engine, foe)
    assert not any(c.condition_id == eye.ANALYZED for c in foe.conditions.values())
    me.action_available = True
    declare = next(c for c in engine.legal_candidates() if c.display_name == "Part-Breaker")
    eye._do(engine, declare)
    assert me.resources[eye.FOCUS] == 0
    assert any(c.condition_id == "condition:typed.part_breaker_declared" for c in me.conditions.values())
    checks = len([event for event in engine.events if event.event_type == "CHECK_ROLLED"])
    assert eye._attack_until_hit(engine, foe)
    assert any(c.condition_id == eye.ANALYZED and c.source_actor_id == eye.ME for c in foe.conditions.values())
    assert len([event for event in engine.events if event.event_type == "CHECK_ROLLED"]) == checks  # no ability check
    assert not any(c.condition_id == "condition:typed.part_breaker_declared" for c in me.conditions.values())  # spent by the attack
    assert not any(c.display_name == "Part-Breaker" for c in engine.legal_candidates())  # no Martial Focus left to declare again


def test_part_breaker_declaration_is_spent_by_a_miss_and_teaches_nothing():
    from combat.gate2_runtime_content import AN
    from tests import test_auto_eye as eye

    engine = eye._engine([PART])
    me, foe = engine.state.actors[eye.ME], engine.state.actors[AN]
    eye._do(engine, next(c for c in engine.legal_candidates() if c.display_name == "Part-Breaker"))
    attack = eye._weapon_attack(engine, foe.entity_id)
    typed = engine.action_catalog[attack.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": -40}
    before = len(engine.events)
    eye._do(engine, attack)
    assert not any(event.event_type == "DAMAGE_COMMITTED" and foe.entity_id in (event.target_ids or ()) for event in engine.events[before:]), \
        "this seed rolled a natural 20 against a -40 attack bonus; pick another seed"
    assert not any(c.condition_id == eye.ANALYZED for c in foe.conditions.values())
    assert not any(c.condition_id == "condition:typed.part_breaker_declared" for c in me.conditions.values())


# --------------------------------------------------------------------------------------------------------- Lightning

LIGHTNING = "tianxia.sphere.lightning"
GROUNDING = "TAL_LIGHTNING_GROUNDING_BREATH"
SAVE_DC = 15


def _shocked(with_talent: bool):
    """The lightning sphere character (the foe attacks it), with or without Grounding Breath."""
    return h._engine(h._bundle(LIGHTNING, [GROUNDING] if with_talent else [], h.AXE_KIT), foe_hp=200)


def _foe_save(engine, on_fail, *, ability="dex", typed_effects=None):
    """The foe's technique forces ``me`` to make a save; returns the save's target DC (the DC minus what its roller added)."""
    from combat import typed_executor

    me, foe = engine.state.actors[h.ME], h._foe(engine)
    action = next(iter(engine.action_catalog.values()))
    effect = {"type": "save", "ability": ability, "on_fail": on_fail, "on_success": []}
    typed = {"numbers": {"pb": 4, "save_dc": SAVE_DC}, "effects": typed_effects if typed_effects is not None else [effect]}
    before = len(engine.events)
    typed_executor.block_save(typed_executor.Context(engine, foe, action, None, typed, [me], me, {}), effect)
    return next(e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED").payload["dc"]


def _bolt(damage_type="lightning", **row):
    return {"type": "damage", "applies_to": "target", "damage_types": [damage_type], "dice": {"count": 1, "sides": 6}, "flat": 0, **row}


def test_grounding_breath_adds_pb_to_a_save_against_lightning_damage_once_until_the_next_turn():
    """"add your Proficiency Bonus ... Once you use this benefit, you cannot use it again until the start of your next turn":
    the first save against lightning damage is easier by PB, the second in the same turn is not; the creature's own turn
    start gives it back.  Without the talent nothing is added."""
    plain = _shocked(False)
    assert _foe_save(plain, [_bolt()]) == SAVE_DC

    engine = _shocked(True)
    me = engine.state.actors[h.ME]
    assert _foe_save(engine, [_bolt()]) == SAVE_DC - me.proficiency_bonus
    assert any(e.event_type == "PASSIVE_TRIGGERED" and "Grounding Breath" in (e.payload or {}).get("trigger", "") for e in engine.events)
    assert _foe_save(engine, [_bolt("thunder")]) == SAVE_DC  # used up
    engine.state.current_actor_id = h.ME
    engine._system_start_turn()
    assert _foe_save(engine, [_bolt("thunder")]) == SAVE_DC - me.proficiency_bonus  # thunder counts too, and it is back


def test_grounding_breath_covers_paralysis_and_being_knocked_prone_but_not_other_damage():
    engine = _shocked(True)
    pb = engine.state.actors[h.ME].proficiency_bonus
    assert _foe_save(engine, [_bolt("fire")]) == SAVE_DC  # fire damage is none of the listed things
    assert _foe_save(engine, [{"type": "condition", "condition": "prone", "applies_to": "target"}]) == SAVE_DC - pb
    engine.state.actors[h.ME].turn_flags.clear()
    assert _foe_save(engine, [{"type": "condition", "condition": "paralyzed", "applies_to": "target"}]) == SAVE_DC - pb
    engine.state.actors[h.ME].turn_flags.clear()
    assert _foe_save(engine, [{"type": "condition", "condition": "frightened", "applies_to": "target"}], ability="wis") == SAVE_DC


def test_grounding_breath_covers_forced_movement_only_by_a_lightning_or_thunder_effect():
    from combat.ext.lightning_grounding import FLAG, grounding_breath

    engine = _shocked(True)
    me, foe = engine.state.actors[h.ME], h._foe(engine)
    action = next(iter(engine.action_catalog.values()))

    def context(effects):
        from combat import typed_executor

        return typed_executor.Context(engine, foe, action, None, {"numbers": {}, "effects": effects}, [me], me, {})

    assert grounding_breath(context([_bolt("fire")]), me, "STR", {"forced_movement"}) is None
    assert not me.turn_flags.get(FLAG)  # (not spent: other plug-ins keep their own turn flags, e.g. the formations' Formation Step record)
    assert grounding_breath(context([_bolt("thunder")]), me, "STR", {"forced_movement"}) == {"bonus": me.proficiency_bonus, "modes": []}


# --------------------------------------------------------------------------------------------------------- Piercing Needle

PARRY = "TAL_FENCING_PARRY_AND_RIPOSTE"
NEEDLE_CATCHING = "TAL_FENCING_NEEDLE_CATCHING_REVERSAL"
FOCUS = "resource:core.martial_focus"


def _parried(talents, pending):
    """A foe's melee hit on a fencer with Parry and Riposte, run through the real hit/damage checkpoints; returns the fencer,
    its Martial Focus after, the damage left and the events."""
    from tests.test_auto_ironclad import ME, _bundle, _engine, _hit_then_damage

    engine = _engine(_bundle([PARRY, *talents], spheres=("tianxia.sphere.the_piercing_needle",)))
    me, foe = engine.state.actors[ME], engine.state.actors[h.AN]
    assert me.resources[FOCUS] == 1
    before = len(engine.events)
    left = _hit_then_damage(engine, foe, me, pending)
    return me, left, engine.events[before:]


def test_needle_catching_reversal_returns_the_martial_focus_when_parry_and_riposte_zeroes_the_damage():
    """"When Parry and Riposte reduces the triggering attack's damage to 0, regain Martial Focus": the parry spends the Focus,
    a 1-point hit is taken to 0 and the Focus comes back; without the talent it stays spent."""
    me, left, events = _parried([NEEDLE_CATCHING], pending=1)
    assert left == 0
    assert [e.event_type for e in events].count("RESOURCE_SPENT") == 1
    assert me.resources[FOCUS] == 1
    assert any(e.event_type == "PASSIVE_TRIGGERED" and "Needle-Catching Reversal" in (e.payload or {}).get("trigger", "") for e in events)

    me, left, _ = _parried([], pending=1)
    assert left == 0 and me.resources[FOCUS] == 0


def test_needle_catching_reversal_does_nothing_when_the_parry_leaves_damage():
    me, left, events = _parried([NEEDLE_CATCHING], pending=200)
    assert left > 0
    assert me.resources[FOCUS] == 0
    assert not any(e.event_type == "PASSIVE_TRIGGERED" and "Needle-Catching" in (e.payload or {}).get("trigger", "") for e in events)
