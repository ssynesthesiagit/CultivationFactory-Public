"""Shield-Hacking Rhythm (MGR-T17-rw007): the Shield half is a real STR save and a paid Edge Momentum rider.

The printed talent is optional: on a qualifying hit the saber user may spend 1 Edge Momentum, the target makes a
Strength saving throw, and on a failure it loses the next shield, parry, guard, or temporary AC bonus it would apply
before the start of the user's next turn. The engine keeps each Armor Class modifier with its source, so the denial
takes the Shield Bonus or the next positive AC modifier, whichever the target is still applying.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from combat import armour, ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.ext import afflictions

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = importlib.import_module("test_review_sw-athletics")

ROOT = Path(__file__).resolve().parents[1]
ME = t.ME
TALENT = "tianxia.talent.sabers.shield_hacking_rhythm"
FORWARD = "tianxia.talent.sabers.forward_cut"
RHYTHM = "Forward Cut + Shield-Hacking Rhythm"
EDGE = "resource:named.edge_momentum"
CONDITION = "condition:typed.shield_hacking_rhythm"
DAO_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}
SHIELD_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}


def _saber_bundle():
    """A Sabers fighter whose own technique save DC is 50, so the foe always fails the printed save."""
    sheet = t._sheet("tianxia.sphere.sabers", [FORWARD, TALENT], DAO_KIT, dc=50)
    # Leave Saber-Line Pressure out: its once-a-turn Edge Momentum gain would hide the rider's own spend.
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
    return compile_character(sheet, actor_id=ME)


def _foe_bundle(*, shield: bool):
    sheet = t._sheet("", (), SHIELD_KIT if shield else {"starting_kit": {"items": []}}, dc=16)
    if shield:
        sheet["proficiencies"] = {"armor": ["Shield"]}  # the starting-kit Shield is worn, so it earns its +2
    return compile_character(sheet, actor_id=AN)


def _fight(*, shield: bool, edge: int = 1):
    engine = Gate4ControllerEngine(
        ROOT, match_seed="MGR17-SHIELDHACK", typed_bundles=(_saber_bundle(), _foe_bundle(shield=shield)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.resources[EDGE] = edge
    foe.armor_class = -50  # every attack roll hits; the Shield Bonus is read through the ac hook, not the d20
    return engine, me, foe


def _ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return me


def _names(engine):
    return [candidate.display_name for candidate in engine.legal_candidates()]


def _use(engine, name):
    candidate = next(candidate for candidate in engine.legal_candidates() if candidate.display_name == name)
    engine.execute_intent(ActionIntent(
        intent_id=f"intent:{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME,
        target_ids=candidate.target_ids or (AN,)))
    return candidate


def _hit_with(engine, name):
    """Run the action until it hits (a natural 1 can miss even against the forced AC); a miss pays nothing."""
    for _attempt in range(8):
        _ready(engine)
        before = len([e for e in engine.events if e.event_type == "ATTACK_ROLLED"])
        _use(engine, name)
        hit = next((e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME), None)
        if hit is not None:
            return hit
    raise AssertionError(f"{name} never hit")


def _ac_penalty(engine, foe):
    return sum(value for value in ext.run("ac", engine, foe) if isinstance(value, int))


def test_failed_save_denies_the_next_shield_bonus_then_it_returns():
    engine, me, foe = _fight(shield=True)
    assert armour.shield_bonus_earning(engine, foe) == 2
    assert _ac_penalty(engine, foe) == 0

    _hit_with(engine, RHYTHM)

    assert me.resources[EDGE] == 0
    save = next(event for event in reversed(engine.events) if event.event_type == "SAVE_ROLLED")
    assert save.payload["dc"] == 50
    assert save.payload["success"] is False
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    assert _ac_penalty(engine, foe) == -2  # the next incoming attack sees the Shield Bonus taken away

    # The next attack against the foe uses the denial up, even when it is an ordinary attack.
    _hit_with(engine, "Forward Cut")
    assert not [held for held in foe.conditions.values() if held.condition_id == CONDITION]
    assert _ac_penalty(engine, foe) == 0
    assert armour.shield_bonus_earning(engine, foe) == 2  # the Shield itself is not destroyed


def test_declining_the_edge_momentum_spend_leaves_pool_and_shield_alone():
    engine, me, foe = _fight(shield=True, edge=0)
    assert RHYTHM not in _names(engine)  # the paid rider is not offered with no Edge Momentum to spend
    me.resources[EDGE] = 1
    assert RHYTHM in _names(engine)

    _hit_with(engine, "Forward Cut")  # the printed "may" is declined by using the ordinary attack

    assert me.resources[EDGE] == 1
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0
    assert armour.shield_bonus_earning(engine, foe) == 2


def test_no_shield_target_is_not_offered_the_rider_and_is_unchanged():
    engine, me, foe = _fight(shield=False)
    assert armour.shield_bonus_earning(engine, foe) == 0
    assert RHYTHM not in _names(engine)

    _hit_with(engine, "Forward Cut")

    assert me.resources[EDGE] == 1
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0


def _add_defence(engine, foe, value, *, source="tianxia.test.guard_stance"):
    """A per-source Armor Class ADD modifier on the foe: a parry, a guard stance, or a temporary AC bonus."""
    engine._add_modifier(foe, source, "armor_class", "ADD", value, "SELF", expires_on="START_OF_SELF_NEXT_TURN")


def test_failed_save_takes_a_parry_or_guard_bonus_then_it_returns():
    """The parry/guard/temporary-AC half is automated: a foe with no Shield loses its next such bonus."""
    engine, me, foe = _fight(shield=False)
    _add_defence(engine, foe, 2)
    assert armour.shield_bonus_earning(engine, foe) == 0
    assert _ac_penalty(engine, foe) == 0
    assert RHYTHM in _names(engine)  # a parry is a bonus the denial can take, so the paid rider is offered

    _hit_with(engine, RHYTHM)

    assert me.resources[EDGE] == 0
    save = next(event for event in reversed(engine.events) if event.event_type == "SAVE_ROLLED")
    assert save.payload["success"] is False
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    assert _ac_penalty(engine, foe) == -2  # the next incoming attack loses the parry's +2

    _hit_with(engine, "Forward Cut")
    assert not [held for held in foe.conditions.values() if held.condition_id == CONDITION]
    assert _ac_penalty(engine, foe) == 0
    assert sum(m.value for m in foe.modifiers.values() if m.target_field == "armor_class") == 2  # the parry itself is kept


def test_consuming_attack_is_scored_against_the_denied_ac():
    """The attack that uses the denial rolls with the bonus taken away; the attack after it gets the bonus back."""
    engine, me, foe = _fight(shield=True)
    _hit_with(engine, RHYTHM)
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    start = len([e for e in engine.events if e.event_type == "ATTACK_ROLLED"])
    _hit_with(engine, "Forward Cut")
    _hit_with(engine, "Forward Cut")
    rolls = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME][start:]
    consuming, following = rolls[0], rolls[-1]
    assert consuming.payload["cover_bonus"] == 0 and following.payload["cover_bonus"] == 0
    assert int(following.payload["target_ac"]) == int(foe.armor_class) + int(engine._ac_modifier(foe))
    assert int(following.payload["target_ac"]) - int(consuming.payload["target_ac"]) == 2


def test_penalty_only_target_is_not_offered_and_pool_is_unchanged():
    """A target with no defensive bonus at all (only an AC penalty) gives the variant nothing to take: no Edge spent."""
    engine, me, foe = _fight(shield=False)
    _add_defence(engine, foe, -2, source="tianxia.test.exposed")
    assert RHYTHM not in _names(engine)

    _hit_with(engine, "Forward Cut")

    assert me.resources[EDGE] == 1
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0


def test_second_use_while_the_denial_is_held_is_not_offered_and_spends_nothing():
    """Finding 2: a creature already bearing the denial cannot take more, so the variant must not charge Edge for it."""
    engine, me, foe = _fight(shield=True, edge=2)
    _hit_with(engine, RHYTHM)
    assert me.resources[EDGE] == 1
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]

    _ready(engine)
    assert RHYTHM not in _names(engine)
    assert me.resources[EDGE] == 1


def test_private_workspace_report_is_not_committed_to_the_repository():
    """Review finding 1: a lane's private workspace report (local paths, queue receipts) must not live in the repo."""
    repo = Path(__file__).resolve().parents[2]
    assert not (repo / "fix" / "MGR-T17-rw007-shieldhack-1.report.md").exists()


# ------------------------------------------------------------- review F2R2 fixes

def _split_the_shield_wall(engine, foe):
    """Split the Shield Wall's denial (break_guard, shield, next attack by anyone): the foe loses its Shield AC to the next attack."""
    from combat.ext import guard_broken

    engine._apply_condition(foe, guard_broken.CONDITION, "system:test", ME, expires_on="UNTIL_REMOVED",
                            data={"shield": True, "cover": False, "next": True, "axe": False, "by": "anyone", "label": "test"})


def _attack_on(engine, foe):
    """The attack from ME against the foe is being resolved now (as guard_broken reads it from before_attack)."""
    from combat.ext import guard_broken

    engine.__dict__[guard_broken.CURRENT] = {"attacker": ME, "target": foe.entity_id, "ranged": False, "axe": False}


def test_shield_already_denied_by_split_the_shield_wall_is_not_taken_again():
    """Review B1: guard_broken and Shield-Hacking Rhythm both read the same +2 Shield Bonus. One attack loses it once (-2, not -4)."""
    engine, me, foe = _fight(shield=True)
    _split_the_shield_wall(engine, foe)
    engine._apply_condition(foe, CONDITION, "system:test", ME, expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "test"})
    _attack_on(engine, foe)
    assert _ac_penalty(engine, foe) == -2

    # That attack uses up Split the Shield Wall's denial only. Shield-Hacking Rhythm had nothing it could take on this attack
    # beyond the Shield Bonus already gone, so it is still held and takes the Shield Bonus on the next attack.
    ext.run("event", engine, "ATTACK_ROLLED", {"target_ids": (AN,), "actor_id": ME})
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    assert _ac_penalty(engine, foe) == -2


def test_shield_denied_elsewhere_leaves_the_parry_for_shield_hacking():
    """With a parry also held, the attack loses the Shield Bonus once (guard_broken) and the parry once (the rider)."""
    engine, me, foe = _fight(shield=True)
    _add_defence(engine, foe, 2)
    _split_the_shield_wall(engine, foe)
    engine._apply_condition(foe, CONDITION, "system:test", ME, expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "test"})
    _attack_on(engine, foe)
    assert _ac_penalty(engine, foe) == -4


def test_unused_denial_expires_at_the_casters_next_turn():
    engine, me, foe = _fight(shield=True)
    _hit_with(engine, RHYTHM)
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    engine._expire_typed_for_checkpoint("START_OF_TURN", ME)
    assert not foe.conditions
    assert _ac_penalty(engine, foe) == 0


def test_condition_backed_temporary_ac_bonus_is_a_qualifying_defence():
    """A real condition-backed AC provider qualifies even without a shield or modifier row."""
    from combat.ext.bojutsu import BARRIER_AC

    engine, me, foe = _fight(shield=False)
    engine._apply_condition(foe, BARRIER_AC, "system:test", AN, expires_on="START_OF_SELF_NEXT_TURN",
                            data={"label": "test barrier"})
    assert RHYTHM in _names(engine)
    _hit_with(engine, RHYTHM)
    assert me.resources[EDGE] == 0
    assert {held.condition_id for held in foe.conditions.values()} == {CONDITION, BARRIER_AC}
    _attack_on(engine, foe)
    ext.run("event", engine, "ATTACK_ROLLED", {"target_ids": (AN,), "actor_id": ME})
    assert not [held for held in foe.conditions.values() if held.condition_id == CONDITION]
    assert [held.condition_id for held in foe.conditions.values()] == [BARRIER_AC]
    assert _ac_penalty(engine, foe) == 1  # temporary barrier remains after its +1 was denied once


def test_attack_qualified_temporary_ac_bonus_is_a_qualifying_defence():
    """A temporary ranged-only AC bonus remains a legal target for the optional rider."""
    engine, me, foe = _fight(shield=False)
    engine._add_modifier(foe, "tianxia.test.ranged_guard", "armor_class_vs_ranged", "ADD", 2, "SELF",
                         expires_on="START_OF_SELF_NEXT_TURN")
    assert RHYTHM in _names(engine)


def test_ranged_only_bonus_is_not_denied_or_consumed_by_a_melee_attack():
    engine, me, foe = _fight(shield=False)
    engine._add_modifier(foe, "tianxia.test.ranged_guard", "armor_class_vs_ranged", "ADD", 2, "SELF",
                         expires_on="START_OF_SELF_NEXT_TURN")
    engine._apply_condition(foe, CONDITION, "system:test", ME, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "test"})
    _attack_on(engine, foe)  # melee
    assert _ac_penalty(engine, foe) == 0
    ext.run("event", engine, "ATTACK_ROLLED", {"target_ids": (AN,), "actor_id": ME})
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
    from combat.ext.guard_broken import CURRENT as GUARD_ATTACK
    _attack_on(engine, foe)  # a second attack begins after the first attack's context has been cleared
    engine.__dict__[GUARD_ATTACK]["ranged"] = True
    assert _ac_penalty(engine, foe) == -2
    ext.run("event", engine, "ATTACK_ROLLED", {"target_ids": (AN,), "actor_id": ME})
    assert not [held for held in foe.conditions.values() if held.condition_id == CONDITION]


def test_permanent_armor_class_bonus_is_never_denied():
    """A non-expiring AC bonus is not a parry, guard stance or temporary bonus: the rider is not offered and takes nothing."""
    engine, me, foe = _fight(shield=False)
    engine._add_modifier(foe, "tianxia.test.permanent_ward", "armor_class", "ADD", 2, "SELF", expires_on="UNTIL_REMOVED")
    assert RHYTHM not in _names(engine)
    assert me.resources[EDGE] == 1


# ------------------------------------------------------------- review F3R1 fixes (temporary AC providers, configured route)

PROVIDERS = [  # (condition id, its own ac hook amount, record data) for each real temporary AC condition
    pytest.param("condition:typed.bojutsu_barrier_ac", 1, {"label": "Heavenly Staff Barrier"}, id="bojutsu-barrier"),
    pytest.param("condition:typed.bell_skin_discipline", 1, {"label": "Bell-Skin Discipline"}, id="bell-skin"),
    pytest.param("condition:typed.vessel_guarded", 2, {"label": "Guarding Vessel"}, id="vessel-guarded"),
    pytest.param("condition:typed.verdant_shelter_cover", 2, {"label": "Half Cover (+2 AC)"}, id="verdant-cover"),
    pytest.param("condition:typed.tempering_hardened", 1, {"label": "Tempering Hardened"}, id="tempering-hardened"),
    pytest.param(afflictions.condition_id(), 2, {"ac": 2, "label": "Affliction"}, id="affliction"),
]


@pytest.mark.parametrize("condition_id, amount, data", PROVIDERS)
def test_real_temporary_ac_condition_is_taken_by_the_rider_after_a_reload(condition_id, amount, data):
    """Finding 1: an unshielded creature whose only defence is a condition-borne temporary AC bonus is offered the rider,
    the rider takes that bonus, and the bonus returns once the denial is used up."""
    engine, me, foe = _fight(shield=False)
    engine._apply_condition(foe, condition_id, "system:test.provider", ME, expires_on="START_OF_SOURCE_NEXT_TURN", data=data)
    assert _ac_penalty(engine, foe) == amount  # the provider's own ac hook supplies the bonus
    assert RHYTHM in _names(engine)

    _hit_with(engine, RHYTHM)

    assert me.resources[EDGE] == 0
    save = next(event for event in reversed(engine.events) if event.event_type == "SAVE_ROLLED")
    assert save.payload["success"] is False
    assert [held.condition_id for held in foe.conditions.values() if held.condition_id == CONDITION] == [CONDITION]
    consumable = condition_id in {"condition:typed.vessel_guarded", "condition:typed.verdant_shelter_cover"}
    if consumable:
        assert not any(held.condition_id == condition_id for held in foe.conditions.values())
        assert _ac_penalty(engine, foe) == 0
        _add_defence(engine, foe, amount)  # a new defence, not the consumed grant
    assert _ac_penalty(engine, foe) == (0 if not consumable else -amount)

    _hit_with(engine, "Forward Cut")
    assert not [held for held in foe.conditions.values() if held.condition_id == CONDITION]
    assert _ac_penalty(engine, foe) == (0 if consumable else amount)  # the new modifier or lasting hook remains


def test_denied_creature_is_not_offered_the_rider_again_while_it_holds_the_denial():
    """Finding 1 (second use): a creature already bearing the denial is not offered the rider a second time."""
    engine, me, foe = _fight(shield=False, edge=2)
    engine._apply_condition(foe, "condition:typed.bell_skin_discipline", "system:test.provider", ME,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Bell-Skin Discipline"})
    _hit_with(engine, RHYTHM)
    assert me.resources[EDGE] == 1
    assert [held.condition_id for held in foe.conditions.values() if held.condition_id == CONDITION] == [CONDITION]
    _ready(engine)
    assert RHYTHM not in _names(engine)


def _forward_cut(engine):
    return next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Forward Cut"
                and not (a.parameters.get("typed") or {}).get("variant_of"))


def _is_rider_row(row):
    return isinstance(row, dict) and row.get("source_modifier") == TALENT


def _shield_group(base):
    for group in base.parameters["typed"].get("attack_modifier_loadout") or []:
        for option in group["options"]:
            if any(_is_rider_row(row) for row in option["effects"]):
                return group, option
    raise AssertionError("Forward Cut has no configured Shield-Hacking option")


def _configure(engine, base, group, field, value):
    """Set one configured attack-modifier field through the same setting candidate the player uses."""
    _ready(engine)
    def is_setting(action):
        setting = action.parameters.get("attack_modifier_setting") or {}
        return (setting.get("family") == base.source_definition_id and setting.get("modifier") == group["id"]
                and setting.get("field") == field and setting.get("value") == value)
    action = next(a for a in engine.action_catalog.values() if is_setting(a))
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    engine.execute_intent(ActionIntent(
        intent_id=f"intent:configure:{field}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids or ()))


def _configure_shield_hacking(engine):
    base = _forward_cut(engine)
    group, option = _shield_group(base)
    _configure(engine, base, group, "on", "toggle")
    _configure(engine, base, group, "option", option["id"])
    _configure(engine, base, group, "payment", "0")


def test_configured_manual_loadout_spends_no_edge_on_an_ineligible_hit():
    """Finding 2: the configured route must refuse the Edge spend and the save before consent or payment when the hit is
    not qualifying (no shield, no temporary AC bonus to take)."""
    engine, me, foe = _fight(shield=False)
    _configure_shield_hacking(engine)

    _hit_with(engine, "Forward Cut")

    assert me.resources[EDGE] == 1
    assert not [event for event in engine.events if event.event_type == "SAVE_ROLLED"]
    assert not foe.conditions


def test_configured_manual_loadout_pays_on_a_qualifying_hit():
    """Positive control for finding 2: the same configured loadout still pays and denies on a shielded target."""
    engine, me, foe = _fight(shield=True)
    _configure_shield_hacking(engine)

    _hit_with(engine, "Forward Cut")

    assert me.resources[EDGE] == 0
    assert [event for event in engine.events if event.event_type == "SAVE_ROLLED"]
    assert [held.condition_id for held in foe.conditions.values()] == [CONDITION]
