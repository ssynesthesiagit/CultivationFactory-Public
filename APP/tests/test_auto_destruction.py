"""Destruction sphere (w4-destruction, 2026-09-28/29 automation push): Destructive Blast's Blast Type is a sticky
free choice (combat/ext/destruction_blast.py); every Blast Shape (combat/ext/destruction_shapes.py) is its own
action whose damage/rider route through that choice instead of the old "the GM applies it" rider and the
combinatorial "Destructive Blast + every owned Blast Type/Shape" variant explosion.
"""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.ruin"

CRUSHING = "tianxia.talent.destruction.crushing_break"
FRACTURING = "tianxia.talent.destruction.fracturing_break"
SCOURING = "tianxia.talent.destruction.scouring_break"
HAMMER = "tianxia.talent.destruction.hammer_through_the_line"
BREAK_GUARD = "tianxia.talent.destruction.break_the_guard"
CALAMITY_FORM = "tianxia.talent.destruction.calamity_form"
CALAMITY_MANTLE = "tianxia.talent.destruction.calamity_mantle"


def _sheet(talents: list[str]) -> dict:
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 30, "technique_attack_bonus": 50,
        },
        "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.destruction"], "learned_talent_record_ids": talents,
                               "automatic_sphere_component_record_ids": ["TAL_DESTRUCTION_DESTRUCTIVE_BLAST"]},
    }


def _bundle(talents: list[str]) -> dict:
    return compile_character(_sheet(talents), actor_id=ME)


def _engine(bundle: dict, foe_at=(6, 6)) -> Gate4ControllerEngine:
    engine = Gate4ControllerEngine(ROOT, match_seed="DESTRUCTION", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _renew_turn(engine: Gate4ControllerEngine) -> None:
    """Start a fresh turn for the same actor: Destructive Blast spends its Action, so a second
    release needs the next turn (mirrors how _engine opens the fight)."""
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()


def _use(engine: Gate4ControllerEngine, name: str, *, target_id: str | None = None, at: Position | None = None) -> None:
    def matches(candidate) -> bool:
        if at is not None:
            # A CELL-targeted candidate's display name bakes in its aim point ("Calamity Form: Sphere at 9,6").
            return candidate.display_name.startswith(name) and candidate.destination is not None \
                and (candidate.destination.x, candidate.destination.y) == (at.x, at.y)
        if candidate.display_name != name:
            return False
        if target_id is not None:
            return target_id in (candidate.target_ids or ())
        return True

    candidate = next(c for c in engine.legal_candidates() if matches(c))
    engine.execute_intent(ActionIntent(intent_id=f"use-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _last_damage(engine: Gate4ControllerEngine) -> dict:
    return next(e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED").payload


def test_unshaped_destructive_blast_deals_force_damage_by_default():
    engine = _engine(_bundle([]))
    _use(engine, "Destructive Blast", target_id=AN)
    assert _last_damage(engine)["damage_type"] == "FORCE"


def test_blast_type_choice_is_sticky_and_changes_the_next_release_damage_type_and_rider():
    engine = _engine(_bundle([CRUSHING]))
    _use(engine, "Blast Type: Crushing Break")
    foe = engine.state.actors[AN]
    start_x = foe.position.x
    _use(engine, "Destructive Blast", target_id=AN)
    assert _last_damage(engine)["damage_type"] == "BLUDGEONING"
    # Crushing Break's own rider: a Strength save (DC 30, always failed here) pushes the target 10 feet away.
    assert foe.position.x > start_x
    # The choice persists: a second release (after refreshing the actor's action) still uses Crushing Break.
    engine.state.current_actor_id = ME
    me = engine.state.actors[ME]
    me.action_available = True
    _use(engine, "Destructive Blast", target_id=AN)
    assert _last_damage(engine)["damage_type"] == "BLUDGEONING"


def test_hammer_through_the_line_adds_damage_and_prone_on_a_collision():
    # The foe stands one square from the west edge of the map: Crushing Break's 10-foot push runs it straight into
    # the boundary, giving typed_executor._push's "collision" hook something to fire on.
    engine = _engine(_bundle([CRUSHING, HAMMER]), foe_at=(1, 6))
    _use(engine, "Blast Type: Crushing Break")
    foe = engine.state.actors[AN]
    hp_before = foe.current_hp
    _use(engine, "Destructive Blast", target_id=AN)
    # Two damage events land: Crushing Break's own blast damage, then Hammer Through the Line's extra Destruction Die.
    damages = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and AN in (e.target_ids or ())]
    assert len(damages) >= 2 and all(row.payload["damage_type"] == "BLUDGEONING" for row in damages)
    assert foe.current_hp < hp_before
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())


def test_break_the_guard_reduce_ac_applies_after_a_failed_save_against_fracturing_break():
    engine = _engine(_bundle([FRACTURING, BREAK_GUARD]))
    _use(engine, "Blast Type: Fracturing Break")
    _use(engine, "Break the Guard: Reduce AC")
    foe = engine.state.actors[AN]
    _use(engine, "Destructive Blast", target_id=AN)
    assert _last_damage(engine)["damage_type"] == "FORCE"
    penalty = [m for m in foe.modifiers.values() if m.target_field == "armor_class" and m.value == -1]
    assert penalty, f"expected an AC -1 modifier from Break the Guard, got {[(m.target_field, m.value) for m in foe.modifiers.values()]}"


TETHER = "tianxia.talent.destruction.ruin_binding_tether"


def _bound_tether_fight(talents: list[str], blast_type: str):
    """A real fight with a Tether already cast, so a second release (the Bonus Action Pulse) can
    land in the same turn as the Action blast -- the only way the table offers two Blast Type
    releases while the first option is still active. The Blast Type is chosen before the Tether,
    because the Tether locks the type that was selected when it was created."""
    engine = _engine(_bundle([*talents, TETHER]), foe_at=(4, 6))
    _use(engine, f"Blast Type: {blast_type}")
    _use(engine, "Ruin-Binding Tether", target_id=AN)
    _renew_turn(engine)
    return engine


def test_break_the_guard_gives_a_creature_only_one_option_at_a_time():
    # "A creature can suffer only one option from Break the Guard at a time: if the chosen option changes while an
    # earlier one is still on it, the GM removes one." The Action blast puts Advantage on the creature and the
    # Bonus Action Pulse, with a different option chosen between them, used to leave both Advantage and AC -1 up.
    engine = _bound_tether_fight([SCOURING, BREAK_GUARD], "Scouring Break")
    foe = engine.state.actors[AN]
    _use(engine, "Break the Guard: Attack Advantage")
    _use(engine, "Destructive Blast", target_id=AN)
    advantage = [m for m in foe.modifiers.values() if m.target_field == "incoming_attack_mode"]
    assert advantage, f"the first option (Advantage) should be on the creature, got {[(m.target_field, m.value) for m in foe.modifiers.values()]}"

    _use(engine, "Break the Guard: Reduce AC")
    _use(engine, "Ruin-Binding Tether: Pulse")
    assert not [m for m in foe.modifiers.values() if m.target_field == "incoming_attack_mode"], \
        "only one Break the Guard option may apply; the old Advantage survived the change"
    penalty = [m for m in foe.modifiers.values() if m.target_field == "armor_class" and m.value == -1]
    assert len(penalty) == 1, f"the new option (AC -1) should be on the creature exactly once, got {[(m.target_field, m.value) for m in foe.modifiers.values()]}"


def test_break_the_guard_keeps_the_blast_types_own_advantage_when_the_option_changes():
    # Fracturing Break grants its own Advantage from the same release that carries Break the Guard's
    # Advantage, and the engine keeps the two as separate modifiers with the same source. The option change
    # must never take the Blast Type's printed Advantage with it, so while Fracturing Break is the active type
    # the earlier Advantage is deliberately left in place rather than risk removing the type's own benefit.
    engine = _bound_tether_fight([FRACTURING, BREAK_GUARD], "Fracturing Break")
    foe = engine.state.actors[AN]
    _use(engine, "Break the Guard: Attack Advantage")
    _use(engine, "Destructive Blast", target_id=AN)
    assert len([m for m in foe.modifiers.values() if m.target_field == "incoming_attack_mode"]) == 2, \
        "Fracturing Break's own Advantage and Break the Guard's should both be on the creature"

    _use(engine, "Break the Guard: Reduce AC")
    _use(engine, "Ruin-Binding Tether: Pulse")
    assert [m for m in foe.modifiers.values() if m.target_field == "incoming_attack_mode"], \
        "Fracturing Break grants its own Advantage; it must survive the Break the Guard option changing"
    assert [m for m in foe.modifiers.values() if m.target_field == "armor_class" and m.value == -1], "AC -1 should be on the creature"


def test_calamity_form_sphere_hits_the_area_around_the_aim_point():
    engine = _engine(_bundle([CALAMITY_FORM]), foe_at=(9, 6))
    hp_before = engine.state.actors[AN].current_hp
    _use(engine, "Calamity Form: Sphere", at=Position(x=9, y=6))
    assert engine.state.actors[AN].current_hp < hp_before
    assert _last_damage(engine)["damage_type"] == "FORCE"


def test_calamity_mantle_locks_its_blast_type_at_activation_not_at_the_pulse():
    # "The Blast Type ... [is] selected when you activate the Calamity Mantle and cannot be changed while it
    # remains active": switching Blast Type after activating must not change what the Pulse deals.
    engine = _engine(_bundle([CRUSHING, CALAMITY_MANTLE]), foe_at=(4, 6))
    _use(engine, "Blast Type: Crushing Break")
    _use(engine, "Calamity Mantle")
    _use(engine, "Blast Type: Unshaped Ruin (Force)")
    _use(engine, "Calamity Mantle: Pulse")
    assert _last_damage(engine)["damage_type"] == "BLUDGEONING"
