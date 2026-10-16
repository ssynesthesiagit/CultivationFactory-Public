"""Forged Techniques' expiry names (hunt 2, bugs 1 and 2, 2026-09-28).

Bug 1: the Severe Hindrance Augment ("a severe condition until the end of its next turn, repeating the save at the end of each
of its turns") copied the bare name END_OF_TARGET_NEXT_TURN out of combat/rules/forged_techniques.json. Nothing in the engine or
combat/ext/effect_durations.py removes that name, so Stunned / Paralyzed / Incapacitated lasted until the target's repeat save
succeeded: a stun-lock. It now states the duration in the words the executor reads (``until_end_of_next_turn``: the end of the
affected creature's next turn).

Bug 2: the Ignore Resistance Augment ("the damage ignores Resistance") became a ``suppress_resistance`` modifier on the target
that expired with the unknown name END_OF_SOURCE_TURN: permanent, so every later hit of that damage type by anyone ignored the
Resistance. It is now the ``ignore_resistance`` effect the executor reads from the action's own typed effects (Targeted
Assault's shape): that technique's damage only, and nothing is left on the target.
"""

import pytest

from combat import forged, typed_executor
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition
from tests.test_auto_docket import ME
from tests.test_damage_defenses import _committed
from tests.test_effect_durations import _conditions, _ctx, _end_turn, _fight, _modifiers

PRIMARY_ID = "talent:fake.fire"


def _attack_primary():
    return {"mechanic_id": PRIMARY_ID, "name": "Fake Bolt", "sphere_id": "tianxia.sphere.fake",
            "activation": {"economy": "action", "trigger": None},
            "effects": [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                         "on_hit": [{"type": "damage", "dice": {"count": 2, "sides": 8}, "damage_types": ["fire"]}]}],
            "duration": {"kind": "instant"}, "range": {"kind": "feet", "feet": 60}}


def _save_primary():
    return {"mechanic_id": PRIMARY_ID, "name": "Fake Wave", "sphere_id": "tianxia.sphere.fake",
            "activation": {"economy": "action", "trigger": None},
            "effects": [{"type": "save", "ability": "DEX", "dc": "technique_save_dc",
                         "on_fail": [{"type": "damage", "dice": {"count": 2, "sides": 8}, "damage_types": ["fire"]},
                                     {"type": "condition", "condition": "prone", "applies_to": "target"}],
                         "on_success": [{"type": "half_damage", "applies_to": "target"}]}],
            "duration": {"kind": "instant"}, "range": {"kind": "feet", "feet": 60}}


def _walk(effects):
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for key in ("on_hit", "on_fail", "on_success", "effects"):
                yield from _walk(effect.get(key))


def _technique(form, *augments, **choices):
    return {"technique_id": "forged:test.expiry", "name": "Test Expiry", "primary_sphere_effect": {"talent_id": PRIMARY_ID},
            "base_form": {"form_id": form}, "drawbacks": [], "augments": [{"augment_id": name} for name in augments],
            "table_choices": choices, "cp_cost": {"final": 3}, "action_type": "action"}


# ------------------------------------------------------------------ bug 1: Severe Hindrance
@pytest.mark.parametrize("condition", ["stunned", "paralyzed", "incapacitated"])
def test_a_severe_hindrance_ends_with_the_end_of_the_targets_next_turn(condition):
    engine, me, foe = _fight("FORGED-SEVERE")
    foe.saving_throws.update({"CON": -100, "WIS": -100})  # fails the technique's save, and the repeat at the end of its turn
    mechanic = forged.mechanic_for(_technique("projection", "severe_hindrance", severe_hindrance=condition), {PRIMARY_ID: _attack_primary()})
    typed_executor.run_effects(_ctx(engine, me, foe), mechanic["augment_effects"])
    held = _conditions(foe, condition)
    assert len(held) == 1 and held[0].data["repeat_save"]["when"] == "end"  # the repeated save stays part of it
    assert _end_turn(engine) == AN
    assert _conditions(foe, condition)  # through the whole of its next turn ...
    assert _end_turn(engine) == ME
    assert not _conditions(foe, condition), "the condition never ended: an expiry name nothing removes (stun-lock)"


def test_a_severe_hindrance_lands_from_a_reaction_on_the_targets_own_turn_too():
    engine, me, foe = _fight("FORGED-SEVERE-REACTION")
    foe.saving_throws.update({"CON": -100, "WIS": -100})
    mechanic = forged.mechanic_for(_technique("projection", "severe_hindrance"), {PRIMARY_ID: _attack_primary()})
    assert _end_turn(engine) == AN  # a Counter answers on the target's own turn: "its next turn" is the one after this
    typed_executor.run_effects(_ctx(engine, me, foe), mechanic["augment_effects"])
    assert _conditions(foe, "stunned")
    assert _end_turn(engine) == ME
    assert _conditions(foe, "stunned")  # this turn ending is not the end of its next turn
    assert _end_turn(engine) == AN
    assert _conditions(foe, "stunned")
    assert _end_turn(engine) == ME
    assert not _conditions(foe, "stunned")


# ------------------------------------------------------------------ bug 2: Ignore Resistance
_IGNORE_SHAPES = [("projection", _attack_primary), ("strike", _save_primary), ("burst", _save_primary)]


def _resisting_fight(seed, form, primary):
    """Use full action records for the reviewed hunt32 turn-start subscriber.

    fix/hunt32 (8ee9c696, approved FIX32r2.review.md, merged 3e7cbf31)
    legitimately reads catalog ownership; resistance/later-hit checks are intact.
    """
    engine, me, foe = _fight(seed)
    mechanic = forged.mechanic_for(_technique(form, "ignore_resistance"), {PRIMARY_ID: primary()})
    # fix/hunt32 (8ee9c696; approved FIX32r2.review.md, merged 3e7cbf31)
    # queries owned catalog actions at turn start. Use the native catalog schema,
    # rather than incomplete stubs that crash before the later-hit assertion.
    for source, effects in (("src.forged", mechanic["effects"]),
                            ("src.palm", [{"type": "attack", "attack_kind": "unarmed"}])):
        engine.action_catalog[source] = ActionDefinition(
            source_definition_id=source, display_name=source, owner_id=ME,
            economy="ACTION", resolution_kind="TYPED", target_kind="CREATURE",
            parameters={"typed": {"effects": effects, "numbers": {"cl": 5}}})
    engine.typed_actor_ids.add(AN)  # the engine applies typed Resistance to typed fighters only
    engine.typed_passive_rows[AN] = [{"feature_id": "f.crown", "block": "defense", "kind": "resistance", "damage_types": ["FIRE"]}]
    return engine, me, foe, mechanic


@pytest.mark.parametrize("form, primary", _IGNORE_SHAPES)
def test_ignore_resistance_is_the_techniques_own_damage(form, primary):
    engine, _, foe, _ = _resisting_fight("FORGED-IGNORE", form, primary)
    assert _committed(engine, foe, 20, "FIRE", "src.palm", ME) == 10  # the Resistance is real
    assert _committed(engine, foe, 20, "FIRE", "src.forged", ME) == 20  # "the damage ignores Resistance" -- this technique's


@pytest.mark.parametrize("form, primary", _IGNORE_SHAPES)
def test_ignore_resistance_leaves_nothing_on_the_target(form, primary):
    engine, me, foe, mechanic = _resisting_fight("FORGED-IGNORE-KEPT", form, primary)
    # Resolve every resistance effect the technique carries, as it would on a hit: nothing may stay on the target ...
    carried = [row for row in _walk(mechanic["effects"]) if "resistance" in str(row.get("type"))]
    assert carried
    typed_executor.run_effects(_ctx(engine, me, foe), carried)
    assert not _modifiers(foe, "resistance_suppressed")
    # ... so a later hit of the same type from anything else is still resisted, this turn and after.
    assert _committed(engine, foe, 20, "FIRE", "src.palm", ME) == 10
    _end_turn(engine)
    _end_turn(engine)
    assert _committed(engine, foe, 20, "FIRE", "src.palm", ME) == 10
