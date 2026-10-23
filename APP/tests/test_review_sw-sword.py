"""Sword sphere printed-rule regressions (automation lane AUTO54).

The Sword sphere's own automation (combat/ext/sword_sphere.py plus the reviewed rows in
authority/typed_mechanics/reviewed_final.d/review_sw-spirit_companions.json) has to make the printed effects
happen at the table, not just compile. Each test drives the shipped ability through the real table service or
the live controller engine and checks the printed outcome; the table-level ones also reload the fight from disk,
so the printed state has to survive a save.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor as te
from combat.ext import sword_sphere
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.sword"
SWORD = "tianxia.sphere.sword"
AUTH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
BASES = [k for k, v in AUTH.items() if v.get("sphere_id") == SWORD and v.get("kind") == "base_ability"]
INFUSION = "TAL_SWORD_SWORD_QI_INFUSION"
DRAWING = "TAL_SWORD_SWORD_DRAWING_STANCE"
INCARNATION = "TAL_SWORD_SWORD_SOVEREIGN_INCARNATION"
IRON_BODY = "TAL_SWORD_IRON_SWORD_BODY"
STEP = "TAL_SWORD_SWORD_QI_STEP"
PRESSURE = "TAL_SWORD_SWORD_PRESSURE"
MYRIAD = "TAL_SWORD_MYRIAD_SWORD_PROCESSION"
MANIFESTATION = "TAL_SWORD_SWORD_INTENT_MANIFESTATION"
GUARD = "TAL_SWORD_SWORD_GUARD"
RAIN = "TAL_SWORD_SWORD_RAIN_DESCENT"
SWORD_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "name": "Jian", "quantity": 1}]}}
# The Sword sphere's own attack is the wielded Sword's weapon attack ("Replace one attack with one Sword weapon
# attack"), so the printed Sword Intent Strike is that action's display name.
STRIKE = "Jian (Straight Sword) attack: Sword in Hand"


def _sheet(talents, *, cl=18, dc=100, con=18, str_score=10, dex=10, primary="Qi", sword_kit=True, ability_choices=None):
    talents = list(talents)
    scores = {"STR": str_score, "DEX": dex, "CON": con, "INT": 10, "WIS": 10, "CHA": 10}
    out = {
        **SHEET,
        "identity": {**SHEET["identity"], "proficiency_bonus": 4, "cultivation_level": cl, "key_ability": "STR"},
        "ability_scores_and_statistics": {
            **SHEET["ability_scores_and_statistics"],
            "abilities": [{"ability": a, "score": s, "modifier": (s - 10) // 2} for a, s in scores.items()],
            "primary_resource": {"name": primary, "maximum": 60},
            "hit_points": {"maximum": 200},
        },
        "spheres_and_talents": {"sphere_record_ids": [SWORD],
                                "learned_talent_record_ids": list(dict.fromkeys([*BASES, *talents])),
                                "automatic_sphere_component_record_ids": BASES},
    }
    if sword_kit:
        out["equipment"] = [SWORD_KIT]
    if ability_choices:
        # A recorded combat ability choice is the sheet's own answer to "which ability does this weapon roll with"
        # (combat/ext/attack_abilities.py), so a Sword can roll with a modifier that is not the Path key ability's.
        # Given as pairs so the cached compile stays hashable.
        out["combat_ability_choices"] = dict(ability_choices)
    return out


@lru_cache(maxsize=None)
def _compiled(talents, cl=18, dc=100, con=18, str_score=10, dex=10, primary="Qi", sword_kit=True, ability_choices=None):
    return compile_character(_sheet(tuple(talents), cl=cl, dc=dc, con=con, str_score=str_score, dex=dex, primary=primary,
                                    sword_kit=sword_kit, ability_choices=ability_choices),
                             actor_id=ME, reaction_plan={"ask": True})


def _engine(bundle, *, me_at=(6, 6), foe_at=(7, 6), seed="AUTO54"):
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]},
                                                                        AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance"):
        if pool in me.resources:
            me.resources[pool] = 60
    me.resources["resource:core.martial_focus"] = 1
    return engine, me, foe


def _fight(talents, **kw):
    keys = {k: v for k, v in kw.items()
            if k in {"cl", "dc", "con", "str_score", "dex", "primary", "sword_kit", "ability_choices"}}
    return _engine(copy.deepcopy(_compiled(tuple(talents), **keys)), **{k: v for k, v in kw.items() if k not in keys})


def _second_sword_fighter(engine, me, *, team_id, entity_id, name="Second Sword fighter"):
    """A second Sword fighter in the same fight, so an ally's and a rival's printed rider can both be observed."""
    other = me.model_copy(deep=True)
    other.entity_id = entity_id
    other.display_name = name
    other.team_id = team_id
    other.resources = dict(me.resources)
    other.conditions = {}
    other.turn_flags = {}
    engine.state.actors[entity_id] = other
    return other


ALLY = "actor:factory.sword_ally"
# The service-level fights build their two fighters with tests/hunt12_support's own actor ids (the live-controller
# ``_fight`` above uses its own), so they are named here once and never guessed at a call site.
SVC_ME, SVC_FOE = "actor:factory.fix12", "actor:factory.fix12-foe"


def _team_fight(talents, ally_talents=("SWORD_BASE_SWORD_IN_HAND",), *, ally_at=(6, 7), seed="AUTO54"):
    """The caster, a second Sword fighter on its own team and the sparring foe, all compiled fighters of one fight."""
    bundles = (copy.deepcopy(_compiled(tuple(talents))),
               copy.deepcopy(compile_character(_sheet(tuple(ally_talents)), actor_id=ALLY)))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, ALLY, AN],
                                                 "team_by_actor": {ME: "team:a", ALLY: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 6, "y": 6},
                                                                        ALLY: {"x": ally_at[0], "y": ally_at[1]},
                                                                        AN: {"x": 7, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    for actor in (me, engine.state.actors[ALLY]):
        for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance"):
            if pool in actor.resources:
                actor.resources[pool] = 60
        actor.resources["resource:core.martial_focus"] = 1
    return engine, me, foe


def _turn_of(engine, actor_id):
    """Put ``actor_id``'s turn on the clock and start it (a creature that joined the fight takes its place in the order)."""
    order = engine.state.initiative_order
    if actor_id not in order:
        order.insert(min(engine.state.current_slot_index + 1, len(order)), actor_id)
    engine.state.current_slot_index = order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    return engine.state.actors[actor_id]


def _near(engine, prefix, *, actor=ME, contains=""):
    """The candidate whose aim point is closest to the sparring foe (an area ability is offered once per square)."""
    foe = engine.state.actors[AN]
    found = [c for c in engine.legal_candidates() if c.actor_id == actor
             and c.display_name.startswith(prefix) and contains in c.display_name and c.destination is not None]
    assert found, prefix
    return min(found, key=lambda c: abs(c.destination.x - foe.position.x) + abs(c.destination.y - foe.position.y))


def _do(engine, prefix, *, actor=ME, target=None, contains="", aim=False):
    if aim:
        candidate = _near(engine, prefix, actor=actor, contains=contains)
    else:
        every = [c for c in engine.legal_candidates() if c.actor_id == actor]
        found = [c for c in every
                 if prefix in c.display_name and contains in c.display_name and (target is None or target in c.target_ids)]
        assert found, (prefix, contains, [c.display_name for c in every][:50])
        candidate = min(found, key=lambda c: (len(c.display_name), c.display_name))
    engine.execute_intent(ActionIntent(intent_id="auto54", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return candidate


def _hit(engine, prefix, target_id, *, natural=18, flat=1, actor=ME):
    """Run one of this fighter's attacks with a scripted d20 so the printed hit rider fires."""
    from tests.h1_support import script

    original = Gate4ControllerEngine._resolve_attack_spec

    def resolve(engine_self, *args, **kwargs):
        script(engine_self, [natural] + [flat] * 80)
        return original(engine_self, *args, **kwargs)

    engine.__class__._resolve_attack_spec = resolve
    try:
        return _do(engine, prefix, target=target_id, actor=actor)
    finally:
        engine.__class__._resolve_attack_spec = original


def miss_dice(monkeypatch, *, natural=1):
    """Script the next attack so it genuinely misses, and make sure the target cannot be hit by luck.

    ``_fight`` gives the sparring foe an Armor Class of -50 so a scripted hit always lands; a "miss" test has
    to take that away, or a natural 1 still hits and the test proves nothing.
    """
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script

    original = Gate4ControllerEngine._resolve_attack_spec

    def resolve(engine_self, *args, **kwargs):
        script(engine_self, [natural] + [1] * 80)
        return original(engine_self, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)


def _rolls(engine, reason):
    return [r for r in engine.rolls if r.reason.startswith(reason)]


def _missed(engine, actor_id=ME):
    """The engine's own ATTACK_ROLLED record of an attack that did not hit (total below the target's Armor Class)."""
    return [event for event in engine.events
            if event.event_type == "ATTACK_ROLLED" and event.actor_id == actor_id
            and not (event.payload or {}).get("provisional_hit")
            and int((event.payload or {}).get("total") or 0) < int((event.payload or {}).get("target_ac") or 0)]


def _state(engine, actor, name):
    return sword_sphere._state(engine, actor, name)


def _ctx(engine, actor, typed=None):
    return type("Ctx", (), {"engine": engine, "actor": actor, "typed": typed if typed is not None else {"sphere": sword_sphere.SWORD_SPHERE}})()


def _marked(actor, owner, mark="Sword Intent"):
    return te.bears_mark(actor, owner if isinstance(owner, str) else owner.entity_id, mark)


# =========================================================== Sword-Qi Infusion, through the table service and a reload
@pytest.mark.parametrize("cl,count", [(10, 1), (12, 2), (18, 3)])
def test_sword_qi_infusion_adds_its_own_dice_once_per_turn_and_marks_the_target(tmp_path, monkeypatch, cl, count):
    from tests.hunt12_support import ME as ME2, FOE, candidate, fight, hit_dice, reload, send

    combat, table, mid = fight(tmp_path, [INFUSION], cl=cl, dc=100, kit=SWORD_KIT)
    hit_dice(monkeypatch)
    me = combat._load_session(mid).engine.state.actors[ME2]

    # Infuse (a Bonus Action), then attack with the wielded Sword: printed 1d6 / 2d6 / 3d6 Slashing or Force,
    # Sword Intent on the target, and only once per turn.
    send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == "Sword-Qi Infusion"))
    engine = reload(tmp_path, mid)
    me = engine.state.actors[ME2]
    assert _state(engine, me, sword_sphere.INFUSION_STATE) is not None
    assert any(c.condition_id == sword_sphere.MAGICAL for c in me.conditions.values())
    assert not _marked(engine.state.actors[FOE], ME2)

    hit_dice(monkeypatch)
    send(combat, table, mid, candidate(combat, mid, lambda c: "Sword in Hand" in c.display_name
                                       and FOE in c.target_ids and "#" not in c.source_definition_id))
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    bonus = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and f"{count}d6" in r.expression]
    assert len(bonus) == 1, [r.expression for r in engine.rolls if r.reason.startswith("DAMAGE:")]
    assert _marked(foe, ME2), "Sword-Qi Infusion: apply Sword Intent on a hit"


def test_sword_qi_infusion_does_nothing_to_a_character_without_it(tmp_path, monkeypatch):
    from tests.hunt12_support import ME as ME2, FOE, candidate, fight, hit_dice, reload, send

    combat, table, mid = fight(tmp_path, ["SWORD_BASE_SWORD_IN_HAND"], cl=18, dc=100, kit=SWORD_KIT)
    hit_dice(monkeypatch)
    send(combat, table, mid, candidate(combat, mid, lambda c: "Sword in Hand" in c.display_name
                                       and FOE in c.target_ids and "#" not in c.source_definition_id))
    engine = reload(tmp_path, mid)
    assert not any(f"{n}d6" in r.expression for n in (1, 2, 3)
                   for r in engine.rolls if r.reason.startswith("DAMAGE:"))
    assert not any(c.condition_id == sword_sphere.MAGICAL for c in engine.state.actors[ME2].conditions.values())


# ============================================================== Sword Drawing Stance (Advantage, mark, then it ends)
def test_sword_drawing_stance_grants_advantage_marks_the_target_and_then_ends():
    engine, me, foe = _fight([DRAWING])
    _do(engine, "Sword Drawing Stance")
    assert _state(engine, me, sword_sphere.DRAWING_STATE) is not None

    from combat import ext

    assert sword_sphere.drawing_stance_mode(_ctx(engine, me), foe) == "ADVANTAGE"
    _hit(engine, "Sword in Hand", foe.entity_id)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert _marked(foe, me), "Sword Drawing Stance: apply Sword Intent on a hit"
    assert _state(engine, me, sword_sphere.DRAWING_STATE) is None, "After the attack resolves, the stance ends."


def test_sword_drawing_stance_is_spent_by_an_attack_that_misses_too(monkeypatch):
    """"After the attack resolves, the stance ends." -- not "after the attack hits".

    A real miss is asserted first (ATTACK_ROLLED reports the miss), because the sparring foe's Armor Class of -50
    in ``_fight`` would let even a natural 1 through, and a stance that only vanished on a hit would look the
    same as this test if the attack had connected.
    """
    engine, me, foe = _fight([DRAWING])
    _do(engine, "Sword Drawing Stance")
    me = engine.state.actors[ME]
    assert _state(engine, me, sword_sphere.DRAWING_STATE) is not None
    foe = engine.state.actors[AN]
    foe.armor_class = 40

    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script

    original = Gate4ControllerEngine._resolve_attack_spec

    def resolve(engine_self, *args, **kwargs):
        script(engine_self, [1] + [1] * 80)
        return original(engine_self, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)
    _do(engine, "Sword in Hand", target=foe.entity_id)
    assert _missed(engine), "the attack really did miss"
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert not _marked(foe, me), "Sword Intent is applied on a hit, and this was a miss"
    assert _state(engine, me, sword_sphere.DRAWING_STATE) is None, \
        "After the attack resolves, the stance ends -- a miss spends it too"


def test_sword_qi_infusion_bonuses_only_the_wielded_sword_not_every_sword_qi_attack():
    """"Infuse one wielded Sword ... once per turn when **the Sword** hits".

    The bonus is the infused weapon's, so a Sword-Qi talent of the same fighter that carries no weapon of its own
    (Sword Beyond Hand) neither spends the once-per-turn bonus nor receives the extra dice.
    """
    engine, me, foe = _fight([INFUSION, "SWORD_BASE_SWORD_BEYOND_HAND"])
    _do(engine, "Sword-Qi Infusion")
    me = engine.state.actors[ME]
    assert _state(engine, me, sword_sphere.INFUSION_STATE) is not None

    # A Sword-Qi talent is not the wielded Sword: the once-per-turn bonus stays unspent.
    _hit(engine, "Sword Beyond Hand", foe.entity_id)
    me = engine.state.actors[ME]
    assert not me.turn_flags.get("sword_qi_infusion_hit"), \
        "Sword Beyond Hand is Sword-Qi, not the infused wielded Sword"
    assert not _marked(engine.state.actors[AN], ME), "and it applies no Sword Intent in place of the Sword's hit"

    # The wielded Sword is: the extra dice land and the once-per-turn bonus is spent. Both are Actions, so the
    # fighter takes a fresh turn between them.
    _next_turn(engine)
    _hit(engine, "Sword in Hand", engine.state.actors[AN].entity_id)
    me = engine.state.actors[ME]
    assert me.turn_flags.get("sword_qi_infusion_hit"), "the wielded Sword spends the printed once-per-turn bonus"
    assert _marked(engine.state.actors[AN], ME), "Sword-Qi Infusion: apply Sword Intent on the Sword's hit"


def test_sword_drawing_stance_is_inert_without_the_talent():
    engine, me, foe = _fight(["SWORD_BASE_SWORD_IN_HAND"])
    from combat import ext

    assert sword_sphere.drawing_stance_mode(_ctx(engine, me), foe) is None


# ================================================ Sword-Sovereign Incarnation (flight, mark length, Disarm, counter)
def test_sovereign_incarnation_flies_and_keeps_sword_intent_to_the_end_of_the_next_turn():
    engine, me, foe = _fight([INCARNATION])
    assert sword_sphere.sovereign_flight(engine, me) is None
    _do(engine, "Sword-Sovereign Incarnation")
    engine.state.actors[ME].resources["resource:core.qi"] = 60
    assert sword_sphere.sovereign_flight(engine, me) == {"fly_speed_ft": 40, "flight_hover": 1}
    _hit(engine, "Sword in Hand", foe.entity_id)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    intent = [c for c in foe.conditions.values() if c.condition_id == te.mark_condition_id("Sword Intent", ME)]
    assert intent, "the hit applies Sword Intent"
    # "Sword Intent lasts until the end of your next turn." The engine names the end of the source's Nth turn
    # END_OF_SOURCE_TURN_AT:N (combat/gate2_engine.py _expire_typed_for_checkpoint), so "your next turn" is N+1 --
    # a second turn more would be a different printed rule than the one the sheet prints.
    assert intent[0].expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}", intent[0].expires_on

    # ... and the mark really does last through the whole of that next turn and end with it, which is what the
    # engine's own expiry sweep does with that name.
    me.turns_started += 1
    engine._expire_typed_for_checkpoint("END_OF_TURN", AN)
    assert te.bears_mark(engine.state.actors[AN], ME), "still marked while my next turn runs"
    engine._expire_typed_for_checkpoint("END_OF_TURN", ME)
    assert not te.bears_mark(engine.state.actors[AN], ME), "the Intent ends with the end of my next turn"


def test_sovereign_incarnation_makes_ordinary_disarming_effects_fail_against_its_own_owner():
    """"ordinary disarming effects fail against you": the fighter running the Incarnation is the protected creature,
    so a rival's disarm of it fails and its own disarm of a rival still lands. Driven through the executor's own
    condition path (combat/typed_executor.py block_condition consults condition_attempt), because the printed Disarm
    is a weapon maneuver whose button needs a second dagger fighter."""
    engine, me, foe = _fight([INCARNATION])
    rival = _second_sword_fighter(engine, me, team_id=foe.team_id, entity_id="actor:factory.sword_rival")
    engine._apply_condition(rival, f"condition:typed.state.{sword_sphere.INCARNATION_STATE}", INCARNATION, rival.entity_id,
                            expires_on="UNTIL_REMOVED",
                            data={"label": "Sword-Sovereign Incarnation", "name": sword_sphere.INCARNATION_STATE})

    _disarm(engine, me, rival)
    assert not _disarmed(rival), "the Incarnation owner's weapon cannot be knocked away"
    _disarm(engine, rival, me)
    assert _disarmed(engine.state.actors[ME]), \
        "the Incarnation protects its owner from disarms; it does not stop its owner disarming others"

    # Control: with no Incarnation running, the same disarm lands.
    engine._remove_condition(rival, f"condition:typed.state.{sword_sphere.INCARNATION_STATE}", INCARNATION)
    _disarm(engine, me, rival)
    assert _disarmed(rival)


def _disarm(engine, applier, subject):
    """Apply the printed Disarm effect (combat/rules/weapon_specials.json: "Disarm" -> condition "disarmed") to
    ``subject`` through the typed executor, the way a weapon maneuver's hit does. The fight compiles one Sword
    fighter, so the catalog row is that fighter's; who applies the effect is ``applier``, as the executor's own
    ``ctx.actor``."""
    action = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                  and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_IN_HAND"))
    te.run_effects(te.Context(engine, applier, action, None, dict((action.parameters or {}).get("typed") or {}),
                              [subject], subject, {}),
                   [{"type": "condition", "condition": "disarmed", "applies_to": "target",
                     "duration": {"kind": "until_start_of_your_next_turn"}}])


def _disarmed(actor):
    return any(str(row.condition_id).endswith("disarmed") for row in actor.conditions.values())


# ================================================================ Iron Sword Body (Constitution swap, Stamina for CP)
def test_iron_sword_body_adds_a_constitution_sword_attack_only_when_constitution_is_higher():
    low = _compiled((IRON_BODY,), con=8, str_score=18)
    names = {row["display_name"] for row in low["action_catalog"]}
    assert not any("(Constitution)" in name for name in names), names
    high = _compiled((IRON_BODY,), con=18, str_score=10)
    variants = [row for row in high["action_catalog"] if row["display_name"].endswith("(Constitution)")]
    assert variants, [row["display_name"] for row in high["action_catalog"]]
    assert all(row["parameters"]["typed"]["weapon"]["ability_modifier"] == 4 for row in variants), variants
    assert all("jian" in str(row["parameters"]["typed"]["source"]) for row in variants)


def test_iron_sword_body_quotes_stamina_for_a_sword_talent_cost():
    engine, me, foe = _fight([IRON_BODY, "SWORD_BASE_SWORD_BEYOND_HAND"])
    me.resources["resource:core.stamina"] = 40
    me.resources["resource:core.qi"] = 0
    source = next(row.source_definition_id for row in engine.action_catalog.values()
                  if row.owner_id == ME and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_BEYOND_HAND"))
    plan = sword_sphere.iron_sword_body_payment(engine, me, source, {"resource:core.qi": 3}, {})
    assert plan is not None and plan.costs == (("resource:core.stamina", 3),)


def test_iron_sword_body_pays_stamina_even_when_constitution_is_not_the_higher_modifier(tmp_path):
    """"While wielding a Sword: use Constitution for Sword attack and damage rolls if higher; ... spend Stamina
    instead of CP on Sword talents." Only the Constitution swap is printed "if higher", so a Sword fighter whose
    Constitution is lower still spends Stamina for a Sword talent."""
    engine, me, foe = _fight([IRON_BODY, "SWORD_BASE_SWORD_BEYOND_HAND"], con=8, str_score=18)
    me.resources["resource:core.stamina"] = 40
    me.resources["resource:core.qi"] = 0
    assert not [row for row in engine.action_catalog.values()
                if str(row.source_definition_id).endswith(sword_sphere.IRON_VARIANT)], \
        "Constitution is lower here, so the printed '(Constitution)' attack is not compiled"
    source = next(row.source_definition_id for row in engine.action_catalog.values()
                  if row.owner_id == ME and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_BEYOND_HAND"))
    plan = sword_sphere.iron_sword_body_payment(engine, me, source, {"resource:core.qi": 3}, {"resource:core.qi"})
    assert plan is not None and plan.costs == (("resource:core.stamina", 3),)
    # Stamina that cannot cover the printed CP cost still quotes nothing.
    me.resources["resource:core.stamina"] = 1
    assert sword_sphere.iron_sword_body_payment(engine, me, source, {"resource:core.qi": 3}, {"resource:core.qi"}) is None
    # The ownership answer survives a table commit and reload (it is read from the saved compiled character, so a
    # fighter who saved the fight mid-round still spends Stamina afterwards).
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="AUTO54-IRON-STAMINA", maximum_rounds=20,
                                       typed_bundles=tuple(copy.deepcopy(b) for b in engine.typed_bundle_documents),
                                       roster_setup={"primary_actor_ids": [ME, AN],
                                                     "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                     "starting_positions": {ME: {"x": 6, "y": 6},
                                                                            AN: {"x": 7, "y": 6}}})
    candidate = next(c for c in session.engine.legal_candidates() if c.actor_id == ME and c.display_name == "End turn")
    session.mechanical.execute_intent(ActionIntent(intent_id="auto54-iron-save",
                                                   decision_id=candidate.decision_id,
                                                   candidate_id=candidate.candidate_id,
                                                   state_version=candidate.state_version,
                                                   actor_id=ME, target_ids=candidate.target_ids))
    loaded = persistence.load_match(session.match_id)
    assert loaded.verify()["status"] == "PASS"
    assert sword_sphere._owns_iron_sword_body(loaded.engine, loaded.engine.state.actors[ME]), \
        "the saved compiled character still carries Iron Sword Body"


def test_iron_sword_body_uses_constitution_for_the_sword_attacks_the_compiler_cannot_rewrite():
    """"While wielding a Sword: use Constitution for Sword attack and damage rolls if higher; use Constitution as
    your Sword key ability."

    The compiled "(Constitution)" attack covers a wielded Sword's own weapon roll. A Sword talent that carries no
    weapon row at all (Sword Beyond Hand) is a Sword attack too, and is answered here through the shared flat
    attack/damage seams -- and the already-compiled variant is skipped, so the two never stack.
    """
    engine, me, foe = _fight([IRON_BODY, "SWORD_BASE_SWORD_BEYOND_HAND"], con=18, str_score=10)
    strike = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                  and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_BEYOND_HAND"))
    typed = dict((strike.parameters or {}).get("typed") or {})
    ctx = _ctx(engine, me, typed)
    ctx.action = strike
    assert typed.get("numbers", {}).get("con_mod", 0) > typed.get("numbers", {}).get("key_mod", 0), \
        "Constitution is the higher modifier in this build"
    delta = typed["numbers"]["con_mod"] - typed["numbers"]["key_mod"]
    assert sword_sphere.iron_sword_body_attack(ctx, me) == delta, \
        "use Constitution as your Sword key ability, on a Sword attack with no weapon row"
    assert sword_sphere.iron_sword_body_damage(ctx, foe, None) == delta, "and on the matching damage roll"

    # The compiled "(Constitution)" weapon attack already carries it: the seams must not add it a second time.
    variant = next(row for row in engine.action_catalog.values()
                   if str(row.source_definition_id).endswith(sword_sphere.IRON_VARIANT))
    vctx = _ctx(engine, me, dict((variant.parameters or {}).get("typed") or {}))
    vctx.action = variant
    assert sword_sphere.iron_sword_body_attack(vctx, me) is None, "the compiled variant already has it"

    # An attack that is not a Sword attack is untouched, and so is a fighter without the talent.
    other = _ctx(engine, me, {**typed, "sphere": "tianxia.sphere.alchemy"})
    other.action = strike
    assert sword_sphere.iron_sword_body_attack(other, me) is None, "only Sword attacks"
    plain, plain_me, plain_foe = _fight(["SWORD_BASE_SWORD_BEYOND_HAND"], con=18, str_score=10)
    pctx = _ctx(plain, plain_me, typed)
    pctx.action = strike
    assert sword_sphere.iron_sword_body_attack(pctx, plain_me) is None, "inert without Iron Sword Body"

    # A fighter whose Constitution is lower gets nothing, because the printed swap is "if higher".
    low, low_me, low_foe = _fight([IRON_BODY, "SWORD_BASE_SWORD_BEYOND_HAND"], con=8, str_score=18)
    low_strike = next(row for row in low.action_catalog.values() if row.owner_id == ME
                      and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_BEYOND_HAND"))
    lctx = _ctx(low, low_me, dict((low_strike.parameters or {}).get("typed") or {}))
    lctx.action = low_strike
    low_numbers = lctx.typed.get("numbers") or {}
    assert low_numbers.get("con_mod", 0) <= low_numbers.get("key_mod", 0), "Constitution is the lower modifier here"
    assert sword_sphere.iron_sword_body_attack(lctx, low_me) is None, "'if higher' is the printed condition"


def test_iron_sword_body_quotes_nothing_for_a_character_without_it():
    engine, me, foe = _fight(["SWORD_BASE_SWORD_BEYOND_HAND"])
    source = next(row.source_definition_id for row in engine.action_catalog.values()
                  if row.owner_id == ME and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_BEYOND_HAND"))
    assert sword_sphere.iron_sword_body_payment(engine, me, source, {"resource:core.qi": 3}, {}) is None


# ------------------------------------- Iron Sword Body: the printed "While wielding a Sword" that opens all of it
IRON_TALENTS = (IRON_BODY, "SWORD_BASE_SWORD_BEYOND_HAND")


def _sword_qi_attack(engine):
    """Sword Beyond Hand -- a Sword attack that carries no weapon row, so only the shared flat seams can answer it."""
    return next(row for row in engine.action_catalog.values() if row.owner_id == ME
                and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_BEYOND_HAND"))


def _strike(engine, prefix, target_id=AN, *, natural=15, flat=5):
    """One real attack through the controller, with the attack roll and the damage rolls it actually recorded."""
    before = len(engine.events)
    _hit(engine, prefix, target_id, natural=natural, flat=flat)
    records = [(event.event_type, event.payload or {}) for event in engine.events[before:]]
    attack = next(payload for kind, payload in records if kind == "ATTACK_ROLLED")
    # The first damage roll recorded for an attack is that attack's own printed damage; a printed extra of its own,
    # such as Sword Intent Strike's 1d8 Slashing or Force, follows as a second packet.
    damage = next(payload for kind, payload in records if kind == "DAMAGE_ROLLED")
    return attack, damage


def _jian_action(engine):
    """The fighter's own wielded Jian weapon action, when it still has one in hand."""
    return next((row.source_definition_id for row in engine.action_catalog.values() if row.owner_id == ME
                 and str(row.source_definition_id).endswith(".weapon.jian")), None)


def _knocked_out_of_hand(engine, actor):
    """Disarm the fighter the printed way: the Sword it was holding is disabled and lies at its feet."""
    sword = _jian_action(engine)
    engine._apply_condition(actor, "condition:typed.disarmed", "auto54:disarm", actor.entity_id,
                            expires_on="UNTIL_REMOVED",
                            data={"disables_action": sword, "dropped_at": actor.position.model_dump(mode="json")})
    return sword


@pytest.mark.parametrize("disarmed", [False, True], ids=["unarmed", "disarmed"])
def test_iron_sword_body_needs_a_sword_in_hand_for_every_benefit_it_prints(disarmed):
    """"While wielding a Sword: ..." is the printed condition that opens all five of this ability's benefits.

    Sword Beyond Hand is a Sword-Qi attack with no weapon row of its own, so the flat attack and damage seams are
    the only thing that can carry the Constitution key ability onto it. A fighter who is unarmed (never equipped
    with a Sword) or whose Sword was knocked out of hand still owns the talent and still projects that attack, and
    must get none of it: not the Constitution bonus on the roll, not the matching damage bonus, and not the
    Stamina-for-CP payment the same printed line opens.
    """
    # Armed: a Sword in hand, so the printed benefits all apply.
    armed, me, foe = _fight(IRON_TALENTS, con=18, str_score=10)
    numbers = ((_sword_qi_attack(armed).parameters or {}).get("typed") or {}).get("numbers") or {}
    assert numbers["con_mod"] > numbers["key_mod"], "Constitution is the higher modifier in this build"
    assert _jian_action(armed), "this fighter was given a Sword, and it is not disabled"
    attack, damage = _strike(armed, "Sword Beyond Hand")
    assert int(attack["modified_total"]) - int(attack["natural_result"]) \
        == int(numbers["attack_bonus"]) + numbers["con_mod"] - numbers["key_mod"], \
        "'use Constitution as your Sword key ability' is paid on a projected Sword attack"
    assert int(damage["modifier"]) == numbers["con_mod"], \
        "and on the matching damage roll, whose printed modifier is the key ability this ability replaced"
    me.resources["resource:core.stamina"] = 40
    source = _sword_qi_attack(armed).source_definition_id
    assert sword_sphere.iron_sword_body_payment(armed, me, source, {"resource:core.qi": 3}, {"resource:core.qi"}) is not None, \
        "'While wielding a Sword: spend Stamina instead of CP on Sword talents'"

    # Unarmed or disarmed: the same fighter, the same talent, the same projected attack -- and no Sword in hand.
    # The disarmed build is the one that was given a Sword and then had it knocked away; the unarmed one never had one.
    bare, bare_me, bare_foe = _fight(IRON_TALENTS, con=18, str_score=10, sword_kit=disarmed)
    if disarmed:
        assert _knocked_out_of_hand(bare, bare_me) == _jian_action(bare), "the Sword was knocked out of hand"
        assert not [c.display_name for c in bare.legal_candidates()
                    if c.actor_id == ME and c.display_name == "Jian (Straight Sword) attack"], \
            "and the fighter can no longer attack with it"
    else:
        assert not _jian_action(bare), "this build was never given a Sword"
    bare_attack, bare_damage = _strike(bare, "Sword Beyond Hand")
    assert int(bare_attack["modified_total"]) - int(bare_attack["natural_result"]) == int(numbers["attack_bonus"]), \
        "no Sword in hand: no Constitution key ability on the roll"
    assert int(bare_damage["modifier"]) == numbers["key_mod"], "nor on the damage roll"
    bare_me.resources["resource:core.stamina"] = 40
    assert sword_sphere.iron_sword_body_payment(bare, bare_me, source, {"resource:core.qi": 3}, {"resource:core.qi"}) is None, \
        "and no Stamina-for-CP quote either"


def test_iron_sword_body_stops_while_its_sword_is_stowed_and_returns_when_it_is_drawn(tmp_path):
    """"While wielding a Sword" follows a Stow through the table, and comes back with the Draw.

    A stowed Sword is still carried -- the fighter still owns it and can still draw it -- but it is not in a hand, so
    every benefit Iron Sword Body prints over that opening line has to stop: the Constitution key ability on the
    attack and damage rolls of a Sword-Qi talent (which carries no weapon row of its own, so the shared flat seams
    are the only thing that can answer it) and the Stamina-for-CP quote. Stow and Draw are the fighter's own choice,
    recorded on the fight, so this is played through the table and read back from disk at every step: an answer that
    only works in memory is not an answer that survived the save.
    """
    from tests.hunt12_support import candidate, reload, send

    def service_fight(tmp_path):
        """A real table fight whose fighter has Constitution above its key ability.

        The swap Iron Sword Body prints is "if higher", so a build with Constitution equal to the key ability would
        hand out the same numbers with or without a wielded Sword and could not see the difference at all. Built
        here rather than through the shared service helper, which scores every ability alike.
        """
        from combat.factory_compiler import compile_character
        from combat.gate5_service import CombatService
        from combat.tabletop_service import TabletopService
        from tests.h1_support import ROOT, sheet
        from tests.test_lock2_persistence import act

        fighter = compile_character(_sheet((IRON_BODY, "SWORD_BASE_SWORD_BEYOND_HAND"), cl=18, dc=100, con=18,
                                           str_score=10), actor_id=SVC_ME, reaction_plan={"ask": True})
        sparring = sheet([], cl=18, primary="Stamina")
        sparring["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        mid = combat._finish_factory_match(
            [fighter, compile_character(sparring, actor_id=SVC_FOE)], [SVC_ME, SVC_FOE],
            {SVC_ME: "team:factory", SVC_FOE: "team:opponents"},
            {SVC_ME: {"x": 3, "y": 6}, SVC_FOE: {"x": 4, "y": 6}},
            combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [SVC_ME], [SVC_FOE],
            control_modes={SVC_ME: "MANUAL", SVC_FOE: "MANUAL"}, match_seed="FIX12",
            display_name="AUTO54 wielded-Sword grip regression", maximum_rounds=20)["match_id"]
        while table.state(mid)["menu"]["actor_id"] != SVC_ME:
            assert act(table, mid, "end")["status"] == "COMMITTED"
        return combat, table, mid

    combat, table, mid = service_fight(tmp_path)

    def beyond_hand(engine):
        """Sword Beyond Hand, the Sword-Qi attack with no weapon row: only the shared seams can carry the swap."""
        return next(row for row in engine.action_catalog.values() if row.owner_id == SVC_ME
                    and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_BEYOND_HAND"))

    def printed_benefit():
        """What the reloaded fight actually offers: a real attack roll, its damage roll, and the payment quote."""
        engine = reload(tmp_path, mid)
        numbers = ((beyond_hand(engine).parameters or {}).get("typed") or {}).get("numbers") or {}
        # A scripted hit, so the damage roll this reads is the attack's own printed damage: the sparring partner
        # stands out of reach of its AC, exactly as the module-level controller fights set it up.
        engine.state.actors[SVC_FOE].armor_class = -50
        before = len(engine.events)
        _hit(engine, "Sword Beyond Hand", SVC_FOE, natural=15, flat=5, actor=SVC_ME)
        records = [(event.event_type, event.payload or {}) for event in engine.events[before:]]
        attack = next(payload for kind, payload in records if kind == "ATTACK_ROLLED")
        damage = next(payload for kind, payload in records if kind == "DAMAGE_ROLLED")
        me = engine.state.actors[SVC_ME]
        me.resources["resource:core.stamina"] = 40
        quote = sword_sphere.iron_sword_body_payment(engine, me, beyond_hand(engine).source_definition_id,
                                                     {"resource:core.qi": 3}, {"resource:core.qi"})
        return numbers, int(attack["modified_total"]) - int(attack["natural_result"]), int(damage["modifier"]), quote

    def change_grip(verb):
        chosen = candidate(combat, mid, lambda c: f"{verb} Jian (Straight Sword)" in c.display_name)
        assert send(combat, table, mid, chosen)["status"] == "COMMITTED", f"{verb} is a normal table choice"

    numbers, attack_bonus, damage_modifier, quote = printed_benefit()
    assert numbers["con_mod"] > numbers["key_mod"], "Constitution is the higher modifier in this build"
    assert attack_bonus == int(numbers["attack_bonus"]) + numbers["con_mod"] - numbers["key_mod"], \
        "the Sword is in hand, so the Constitution key ability is on the roll"
    assert damage_modifier == numbers["con_mod"], "and on the matching damage roll"
    assert quote is not None, "and 'While wielding a Sword: spend Stamina instead of CP' is offered"

    # Stowing it is a choice the fighter makes at the table, and the printed condition follows it through a save.
    change_grip("Stow")
    numbers, attack_bonus, damage_modifier, quote = printed_benefit()
    assert attack_bonus == int(numbers["attack_bonus"]), \
        "a Sword in the pack is not a wielded Sword: no Constitution key ability on the roll"
    assert damage_modifier == numbers["key_mod"], "nor on the damage roll"
    assert quote is None, "and no Stamina-for-CP quote, though the fighter still owns the talent and the Sword"

    # Drawing it again restores every printed benefit, still through a committed table.
    change_grip("Draw")
    numbers, attack_bonus, damage_modifier, quote = printed_benefit()
    assert attack_bonus == int(numbers["attack_bonus"]) + numbers["con_mod"] - numbers["key_mod"], \
        "the drawn Sword is wielded again"
    assert damage_modifier == numbers["con_mod"], "on the roll and on the damage"
    assert quote is not None, "and the Stamina-for-CP quote is offered again"


@pytest.mark.parametrize("dex,str_score,weapon_modifier", [(10, 14, 0), (8, 14, -1), (14, 14, 2), (10, 18, 0)])
def test_iron_sword_body_keeps_the_weapon_own_modifier_however_small(dex, str_score, weapon_modifier):
    """0 is a real weapon modifier, not a missing one: "use Constitution ... if higher" is measured against it.

    The Sword in Hand action is the printed attack replacement ("Replace one attack with one Sword weapon attack"),
    which the compiler builds after Iron Sword Body's own "(Constitution)" variants, so it has no compiled variant and
    the shared seams are the only thing that can carry the swap onto it. Its Jian rolls with whatever the sheet
    records for that weapon (combat/ext/attack_abilities.py), which need not be the Path key ability: 0, -1 and +2
    are all real. Either way the printed answer is the same -- a wielded Sword attacks with the Proficiency Bonus
    plus the higher of Constitution and the modifier it already rolled with -- so every build below has to total
    Proficiency Bonus + Constitution, and never Proficiency Bonus + Path modifier.
    """
    choices = (("tianxia.mortal.weapon.jian", "DEX"),)
    engine, me, foe = _fight((IRON_BODY,), con=18, str_score=str_score, dex=dex, ability_choices=choices)
    strike = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                  and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_IN_HAND"))
    typed = (strike.parameters or {}).get("typed") or {}
    numbers = typed.get("numbers") or {}
    assert (typed.get("weapon") or {}).get("ability_modifier") == weapon_modifier, \
        f"this build's Sword in Hand attack rolls with a weapon modifier of {weapon_modifier}"
    assert numbers["con_mod"] == 4 and numbers["con_mod"] >= numbers["key_mod"] \
        and numbers["con_mod"] > weapon_modifier, \
        "Constitution is at least as high as every modifier this build rolls with, and higher than the weapon's"
    assert not [row for row in engine.action_catalog.values()
                if str(row.source_definition_id).endswith("SWORD_BASE_SWORD_IN_HAND" + sword_sphere.IRON_VARIANT)], \
        "the attack replacement has no compiled '(Constitution)' variant, so the seams are the only path"

    attack, damage = _strike(engine, "Sword in Hand")
    assert int(attack["modified_total"]) - int(attack["natural_result"]) \
        == int(numbers["attack_bonus"]) + numbers["con_mod"] - weapon_modifier, \
        "the wielded Sword attacks with the Proficiency Bonus plus Constitution"
    assert int(damage["modifier"]) == numbers["con_mod"], "and its damage with the same swap"
    # The compiled "(Constitution)" weapon attack carries that total by itself: the two never stack.
    variant = next((row for row in engine.action_catalog.values()
                    if str(row.source_definition_id).endswith(sword_sphere.IRON_VARIANT)), None)
    assert variant is not None, "this build's wielded Sword also has the compiled '(Constitution)' attack"
    _turn_of(engine, ME)
    variant_attack, variant_damage = _strike(engine, variant.display_name)
    assert int(variant_attack["modified_total"]) - int(variant_attack["natural_result"]) \
        == int(((variant.parameters or {}).get("typed") or {})["numbers"]["attack_bonus"]), \
        "the compiled variant already rolls with Constitution and gets nothing added on top"
    assert int(variant_damage["modifier"]) == numbers["con_mod"], "on its damage roll too"


# ============================================================ Sword-Qi Step: the printed move does not provoke
def test_sword_qi_step_movement_is_typed_as_not_provoking_opportunity_attacks():
    bundle = _compiled((STEP,))
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Sword-Qi Step")
    movement = [row for row in action["parameters"]["typed"]["effects"] if row.get("type") == "general_rider_step"]
    assert movement and movement[0].get("no_oa") is True
    assert movement[0].get("visible_destination") is True
    assert movement[0]["distance_ft"] == 30


# ================================== Sword Guard: the Proficiency Bonus an attacker bearing Sword Intent earns
def test_sword_guard_adds_the_proficiency_bonus_only_against_a_marked_attacker():
    engine, me, foe = _fight([GUARD])
    assert sword_sphere.sword_guard_bonus(engine, me, foe, foe, {"feature_id": GUARD}) is None
    engine._apply_condition(foe, te.mark_condition_id("Sword Intent", ME), "auto54:mark", ME, expires_on="UNTIL_REMOVED")
    assert sword_sphere.sword_guard_bonus(engine, me, foe, foe, {"feature_id": GUARD}) == 4
    assert sword_sphere.sword_guard_bonus(engine, me, foe, foe, {"feature_id": "TAL_SWORD_SWORD_PRISON"}) is None


# ====================================== Sword Intent Manifestation: the three printed manifestations, chosen one at a time
def test_silent_killing_line_widens_the_critical_range_only_against_marked_creatures():
    engine, me, foe = _fight([MANIFESTATION])
    assert sword_sphere.silent_killing_line(_ctx(engine, me), foe) is None
    engine._apply_condition(me, f"condition:typed.state.{sword_sphere.MANIFESTATION_STATE}", "auto54:state", ME,
                            expires_on="UNTIL_REMOVED", data={"label": "Sword Intent Manifestation: Silent Killing Line",
                                                              "name": sword_sphere.MANIFESTATION_STATE, "mode": "silent"})
    assert sword_sphere.silent_killing_line(_ctx(engine, me), foe) is None, "no Sword Intent on the target yet"
    engine._apply_condition(foe, te.mark_condition_id("Sword Intent", ME), "auto54:mark", ME, expires_on="UNTIL_REMOVED")
    assert sword_sphere.silent_killing_line(_ctx(engine, me), foe) == 19


def test_forest_of_swords_retaliates_on_a_five_foot_melee_swing_and_only_for_its_own_area():
    """"When a hostile creature misses an ally with a **melee attack**".

    A Sword's reach is 5 feet, and the old reading rejected any attack carrying a range at all, so an ordinary
    melee swing was never a melee attack here. The containing area must also be this owner's own Manifestation:
    a second caster's area covering the same ally must not answer for it.
    """
    engine, me, foe = _fight([MANIFESTATION])
    _do(engine, "Sword Intent Manifestation")
    me = engine.state.actors[ME]
    assert any(str(z.source_definition_id).endswith(MANIFESTATION) for z in sword_sphere._sword_areas(engine, me)), \
        "the printed 30-foot area exists"
    # The Manifestation is a choose-one, and Forest of Swords is one of its three printed modes.
    for instance in list(me.conditions.values()):
        if instance.condition_id == f"condition:typed.state.{sword_sphere.MANIFESTATION_STATE}":
            engine._remove_condition(me, instance.condition_id, instance.source_definition_id)
    engine._apply_condition(me, f"condition:typed.state.{sword_sphere.MANIFESTATION_STATE}", MANIFESTATION, ME,
                            expires_on="UNTIL_REMOVED", data={"label": "Sword Intent Manifestation: Forest of Swords",
                                                              "name": sword_sphere.MANIFESTATION_STATE, "mode": "forest"})
    assert sword_sphere._mode(engine, me, "forest") is not None, "the printed Forest of Swords mode is running"
    assert sword_sphere._in_own_forest(engine, me, me), "and its own area is around its owner"

    ally = _second_sword_fighter(engine, me, team_id=me.team_id, entity_id=ALLY)
    ally.position = me.position.model_copy(update={"x": me.position.x + 1, "y": me.position.y + 1})
    attacker = _second_sword_fighter(engine, me, team_id=foe.team_id, entity_id=AN + ":rival")
    before = attacker.current_hp

    strike = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                  and str(row.source_definition_id).endswith("SWORD_BASE_SWORD_IN_HAND"))
    typed = dict((strike.parameters or {}).get("typed") or {})

    def missed(attacker_actor, target, **typed_changes):
        """One settled melee miss as the engine reports it, with the printed area's own reach."""
        ctx = type("Ctx", (), {"engine": engine, "actor": attacker_actor, "typed": {**typed, **typed_changes},
                               "intent": None, "action": strike, "attack_effect": {"attack_kind": "melee weapon"}})()
        sword_sphere.forest_of_swords(ctx, target)

    # A 5-foot melee swing that misses the ally: 5 feet is a melee range, not a reason to ignore the retaliation.
    missed(attacker, ally, range_ft=5)
    assert attacker.current_hp == before - int(me.proficiency_bonus or 2), \
        "a hostile that misses an ally of this Forest owner with a 5-foot melee attack takes the Proficiency Bonus"

    # A second caster running the same manifestation elsewhere on the field must not answer for it.
    other = _second_sword_fighter(engine, me, team_id=me.team_id, entity_id=ALLY + ":other")
    other.proficiency_bonus = 7
    engine._apply_condition(other, f"condition:typed.state.{sword_sphere.MANIFESTATION_STATE}", MANIFESTATION,
                            other.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Sword Intent Manifestation: Forest of Swords",
                                  "name": sword_sphere.MANIFESTATION_STATE, "mode": "forest"})
    before = attacker.current_hp
    # The rival caster is far from the area, so this owner's area is the only one that can cover the ally.
    other.position = me.position.model_copy(update={"x": me.position.x + 300, "y": me.position.y})
    assert not sword_sphere._in_own_forest(engine, other, ally), "a distant caster's area is not this ally's cover"
    missed(attacker, ally, range_ft=5)
    assert attacker.current_hp == before - int(me.proficiency_bonus or 2), \
        "the owner whose own area holds the ally answers, at the owner's own Proficiency Bonus"

    # A ranged miss is not a melee attack.
    before = attacker.current_hp
    ranged = type("Ctx", (), {"engine": engine, "actor": attacker, "typed": {**typed, "range_ft": 60}, "intent": None,
                              "action": strike, "attack_effect": {"attack_kind": "ranged"}})()
    sword_sphere.forest_of_swords(ranged, ally)
    assert attacker.current_hp == before, "a ranged miss is not a melee attack, so Forest of Swords does not fire"


def test_the_sovereign_step_follows_applying_sword_intent_not_merely_being_marked():
    """"once per turn **after applying Sword Intent**, move 10 feet without provoking opportunity attacks."

    The printed trigger is the application of the Intent, so it follows one placed by a saving throw -- which no
    attack-triggered reading could ever see -- and it does not follow a hit that leaves an old mark untouched.
    """
    engine, me, foe = _fight([INCARNATION, PRESSURE])
    _do(engine, "Sword-Sovereign Incarnation")
    me = engine.state.actors[ME]
    assert _state(engine, me, sword_sphere.INCARNATION_STATE) is not None

    # The Intent is already on the creature, carried in from earlier. A hit that applies nothing new is not
    # "after applying Sword Intent", so no step is offered.
    engine._apply_condition(foe, te.mark_condition_id("Sword Intent", ME), INCARNATION, ME, expires_on="UNTIL_REMOVED")
    plain = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                 and row.display_name == "Jian (Straight Sword) attack")
    _do(engine, plain.display_name, target=foe.entity_id)
    me = engine.state.actors[ME]
    assert not me.turn_flags.get("sword_sovereign_step"), \
        "hitting a creature that already bore the Intent, without applying it, does not offer the step"

    # An Intent applied to a creature -- as a saving throw applies it -- is an application, and that is what the
    # printed step follows. It is put on through block_mark, the path that reports the application.
    _next_turn(engine)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert _state(engine, me, sword_sphere.INCARNATION_STATE) is not None, "the Incarnation is still running"
    strike = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                  and row.display_name == "Jian (Straight Sword) attack")
    te.run_effects(te.Context(engine, me, strike, None, dict((strike.parameters or {}).get("typed") or {}),
                              [foe], foe, {}),
                   [{"type": "mark", "mark": "Sword Intent", "applies_to": "target",
                     "duration": {"kind": "until_start_of_your_next_turn"}}])
    me = engine.state.actors[ME]
    assert _marked(foe, me), "the Intent is applied"
    assert me.turn_flags.get("sword_sovereign_step"), \
        "once per turn after applying Sword Intent, whoever applied it"


def test_sword_intent_manifestation_offers_the_three_printed_manifestations():
    action = next(row for row in _compiled((MANIFESTATION,))["action_catalog"]
                  if row["display_name"] == "Sword Intent Manifestation")
    menu = next(row for row in action["parameters"]["typed"]["effects"] if row.get("type") == "menu")
    assert menu["options"] == ["River of Edges", "Forest of Swords", "Silent Killing Line"]
    assert menu["count"] == 1


# ==================================== Myriad Sword Procession: allies inside the area gain Half Cover (and a free step)
def test_myriad_sword_procession_grants_allies_inside_half_cover():
    engine, me, foe = _fight([MYRIAD])
    ally = _second_sword_fighter(engine, me, team_id=me.team_id, entity_id="actor:factory.sword_ally")
    ally.position = me.position.model_copy(update={"x": me.position.x + 1, "y": me.position.y + 1})
    assert sword_sphere.myriad_cover(engine, foe, ally) is None
    _do(engine, "Myriad Sword Procession")
    ally = engine.state.actors[ally.entity_id]
    # "Allies gain Half Cover", and half cover is this engine's +2 (combat/effect_cover.py ray_bonus scores an
    # ordinary cover cell 2 and reserves 5 for three-quarters cover); 5 would be stronger than the printed word.
    assert sword_sphere.HALF_COVER == 2
    assert sword_sphere.myriad_cover(engine, foe, ally) == 2, "Allies in the area gain Half Cover"
    # The table's own cover query agrees: the ally inside the area is scored half cover, the same ally outside is not.
    from combat.shot_geometry import source_cells

    assert engine.cover_from(source_cells(engine, foe, ally), foe.entity_id, ally, purpose="attack")["bonus"] == 2
    outside = ally.model_copy(update={"position": me.position.model_copy(update={"x": me.position.x + 60, "y": me.position.y})})
    assert engine.cover_from(source_cells(engine, foe, outside), foe.entity_id, outside, purpose="attack")["bonus"] == 0


def _next_turn(engine):
    """Run the foe's turn and come back to this fighter's, so an Action spent casting is available again."""
    engine.end_turn()
    engine.end_turn()
    return engine.state.actors[ME]


def test_myriad_sword_procession_free_step_follows_any_hit_but_sword_pressure_needs_a_sword():
    """Myriad Sword Procession prints "move 5 feet without provoking opportunity attacks after hitting, once per
    turn" under "Allies"; Sword Pressure prints the same step "after hitting **with a Sword attack**"."""
    myriad, me, foe = _fight([MYRIAD], sword_kit=False)
    _do(myriad, "Myriad Sword Procession")
    _next_turn(myriad)
    assert any(c.display_name == "Unarmed Strike" for c in myriad.legal_candidates() if c.actor_id == ME), \
        "the fighter needs a hit that is not a Sword attack"
    _hit(myriad, "Unarmed Strike", foe.entity_id)
    assert myriad.state.actors[ME].turn_flags.get("sword_pressure_step"), \
        "Myriad Sword Procession: the step follows any hit"

    pressure, me, foe = _fight([PRESSURE], sword_kit=False)
    _do(pressure, "Sword Pressure")
    _next_turn(pressure)
    _hit(pressure, "Unarmed Strike", foe.entity_id)
    assert not pressure.state.actors[ME].turn_flags.get("sword_pressure_step"), \
        "Sword Pressure: the step follows a hit made with a Sword attack"


def test_sword_pressure_also_offers_the_free_step_to_the_allies_who_may_take_it():
    """"##### You and Allies ... move 5 feet without provoking opportunity attacks after hitting with a Sword
    attack, once per turn": an ally of the caster's own team takes the step from the caster's area."""
    engine, me, foe = _team_fight([PRESSURE])
    _do(engine, "Sword Pressure")
    ally = _turn_of(engine, ALLY)
    assert ally.team_id == me.team_id
    _hit(engine, "Sword in Hand", foe.entity_id, actor=ALLY)
    assert engine.state.actors[ALLY].turn_flags.get("sword_pressure_step"), \
        "an ally in the caster's Sword Pressure gets the step too"

    # ... and nobody else's: the areas are the caster's and its own team's, never a rival's.
    rival = _second_sword_fighter(engine, me, team_id=foe.team_id, entity_id="actor:factory.sword_rival")
    rival.position = me.position.model_copy(update={"x": me.position.x + 2, "y": me.position.y + 2})
    assert sword_sphere._domain_areas(engine, rival) == [], "a fighter on the other side of the table takes nothing"
    assert sword_sphere._domain_areas(engine, engine.state.actors[ALLY]), "an ally does"


def test_the_free_step_stops_at_the_edge_of_the_area(tmp_path):
    """An ally only gets the printed step while it is standing in the caster's area.

    Both abilities print their step under a "You and Allies" / "Allies" heading, so team membership alone is not
    eligibility: an ally that has walked out of the area (or was never in it) gets no free move.
    """
    engine, me, foe = _team_fight([PRESSURE])
    _do(engine, "Sword Pressure")
    ally = _turn_of(engine, ALLY)
    inside = sword_sphere._domain_areas(engine, ally)
    assert inside, "the ally starts inside the caster's Sword Pressure"

    # Step the ally well clear of the printed 30-foot aura and hit from there.
    me_now = engine.state.actors[ME]
    away = me_now.position.model_copy(update={"x": me_now.position.x + 10, "y": me_now.position.y})
    foe_now = engine.state.actors[AN]
    foe_now.position = away.model_copy(update={"x": away.x + 1})
    ally.position = away.model_copy(update={"x": away.x, "y": away.y})
    ally = engine.state.actors[ALLY]
    assert sword_sphere._domain_areas(engine, ally) == [], "an ally outside the area is not covered by it"

    _hit(engine, "Sword in Hand", foe_now.entity_id, actor=ALLY)
    ally = engine.state.actors[ALLY]
    assert not ally.turn_flags.get("sword_pressure_step"), \
        "a hit outside the area is not 'after hitting' in the area, so the printed step is not offered"


def test_the_free_step_stops_at_the_edge_of_a_myriad_sphere_cast_elsewhere():
    """Myriad Sword Procession is a 120-foot sphere, not an aura: its Allies block is the area, not the team."""
    engine, me, foe = _team_fight([MYRIAD])
    me = engine.state.actors[ME]
    ally = engine.state.actors[ALLY]
    # Cast the 60-foot sphere as far from the caster as the map allows, leaving the ally behind.
    far = max((c for c in engine.legal_candidates() if c.actor_id == ME
               and c.display_name.startswith("Myriad Sword Procession at ") and c.destination is not None),
              key=lambda c: abs(c.destination.x - me.position.x) + abs(c.destination.y - me.position.y))
    _do(engine, "Myriad Sword Procession at %d,%d" % (far.destination.x, far.destination.y))
    ally = engine.state.actors[ALLY]
    assert sword_sphere._domain_areas(engine, ally) == [], \
        "the ally the caster left behind is not standing in the sphere it cast elsewhere"
    assert sword_sphere._domain_areas(engine, ally) == [], \
        "an ally left behind when the sphere was cast elsewhere is not in it"


# ============================================ Sword Pressure: the free 5-foot step after hitting with a Sword attack
def test_a_myriad_unarmed_hit_is_asked_under_its_own_printed_name(tmp_path, monkeypatch):
    """Myriad Sword Procession's step is never presented as Sword Pressure, or as Sword-only.

    Both abilities share one choice transport, so the prompt has to be named from the ability that is actually
    running: its own printed name, its own "after hitting" wording, and no claim that a Sword attack is required.
    The hit here is a real Unarmed Strike, which Myriad allows and Sword Pressure does not, so it also proves the
    printed "after hitting" is not secretly Sword-only -- and it is played at the table, through the prompt the
    service really returns and an answer it really accepts, rather than a hand-built context.
    """
    from tests.hunt12_support import ME as ME2, FOE, candidate, fight, hit_dice, reload, send

    combat, table, mid = fight(tmp_path, [MYRIAD], cl=18, dc=100, kit=SWORD_KIT)
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    aimed = [c for c in engine.legal_candidates()
             if c.display_name.startswith("Myriad Sword Procession at ") and c.destination is not None]
    assert aimed, "the printed sphere is aimed at a square"
    square = min(aimed, key=lambda c: abs(c.destination.x - foe.position.x) + abs(c.destination.y - foe.position.y))
    send(combat, table, mid, square)
    engine = reload(tmp_path, mid)
    me = engine.state.actors[ME2]
    assert any(str(zone.source_definition_id).endswith(MYRIAD) for zone in sword_sphere._sword_areas(engine, me))
    assert sword_sphere._domain_areas(engine, me), "the caster stands inside the sphere it just cast"

    strike = lambda c: c.display_name == "Unarmed Strike" and FOE in c.target_ids  # noqa: E731
    for _ in range(6):
        session = combat._load_session(mid)
        if (table.state(mid)["menu"]["actor_id"] == ME2
                and not session.engine.state.actors[ME2].turn_flags.get("sword_pressure_step")
                and any(strike(c) for c in session.engine.legal_candidates())):
            break
        assert _act(table, mid, "end")["status"] == "COMMITTED"

    # The unarmed hit itself is what triggers the printed step, and the table asks the person playing the fighter.
    hit_dice(monkeypatch)
    start = reload(tmp_path, mid).state.actors[ME2].position
    chosen = candidate(combat, mid, strike)
    result = send(combat, table, mid, chosen)
    assert result["status"] == "REACTION_REQUIRED", result.get("status")
    prompt = result["reaction"]
    assert prompt["reaction"] == "Myriad Sword Procession", prompt["reaction"]
    assert "Sword Pressure" not in prompt["title"] + prompt["reaction"] + prompt["trigger"], prompt
    assert "choice:" not in prompt["title"] and "choice:" not in prompt["reaction"], \
        f"an internal id is player-facing text: {prompt['title']!r}"
    assert "5 feet" in prompt["trigger"] and "Myriad Sword Procession" in prompt["trigger"], prompt["trigger"]
    assert "Unarmed Strike" in prompt["moment"], f"the triggering action is named: {prompt['moment']!r}"
    assert "Sword attack" not in prompt["moment"], \
        f"Myriad prints 'after hitting', with no weapon named: {prompt['moment']!r}"
    assert prompt["choice"]["allow_decline"] is True, "may move: declining is a legal answer"
    assert all(option.get("description") for option in prompt["choice"]["options"]), "every button says what it does"

    # Answering it moves the fighter, and the move survives a save: the step is the printed 5-foot move.
    squares = [option["id"] for option in prompt["choice"]["options"]
               if option["id"].removeprefix("cell:") != f"{start.x},{start.y}"]
    assert squares, [option["id"] for option in prompt["choice"]["options"]]
    send(combat, table, mid, chosen, answers=[{**prompt["context"], "selection": "USE", "option_ids": [squares[0]]}])
    me = reload(tmp_path, mid).state.actors[ME2]
    assert me.turn_flags.get("sword_pressure_step"), \
        "Myriad Sword Procession: the printed step follows a hit and is spent for the turn"
    assert me.position != start, f"and the accepted step is committed fight state (from {start} to {me.position})"


def test_sword_pressure_pressures_the_step_to_one_per_turn():
    engine, me, foe = _fight([PRESSURE])
    assert not any(str(zone.source_definition_id).endswith(PRESSURE) for zone in sword_sphere._sword_areas(engine, me))
    _do(engine, "Sword Pressure")
    assert any(str(zone.source_definition_id).endswith(PRESSURE) for zone in sword_sphere._sword_areas(engine, me))
    _hit(engine, "Sword in Hand", foe.entity_id)
    assert engine.state.actors[ME].turn_flags.get("sword_pressure_step"), \
        "move 5 feet without provoking after hitting, once per turn"


def test_sword_pressure_applies_sword_intent_on_a_successful_save_only():
    """"Successful Save: Gain your Sword Intent." -- that one is printed unconditionally, so the table applies it.

    "Failed Save: **Choose one:**" is a different sentence with five alternatives. The table has no seam that asks
    which of a zone save's on-fail effects to apply, so this lane no longer applies any of them: a failed save
    grants nothing behind the player's back, and the five printed alternatives are all listed as a reminder.
    """
    from combat import zones
    from combat.factory_compiler import _gm_lines

    # A failed save (the default technique DC of 100) applies none of the five alternatives.
    engine, me, foe = _fight([PRESSURE])
    _do(engine, "Sword Pressure")
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    zone = next(zone for zone in sword_sphere._sword_areas(engine, me))
    zones.fire_trigger(engine, zone, foe, "start")
    assert not _marked(foe, me), \
        "'Failed Save: Choose one' is the adjudicator's choice, so the table does not pick one of the five"

    # A successful save does grant Sword Intent, because the printed sentence is unconditional.
    from combat.gate4_engine import Gate4ControllerEngine

    easy, me, foe = _fight([PRESSURE])
    _do(easy, "Sword Pressure")
    me, foe = easy.state.actors[ME], easy.state.actors[AN]
    zone = next(zone for zone in sword_sphere._sword_areas(easy, me))
    original_save = Gate4ControllerEngine._roll_save
    Gate4ControllerEngine._roll_save = lambda engine_self, *a, **k: original_save(engine_self, *a, **k).model_copy(
        update={"total": 30})
    try:
        zones.fire_trigger(easy, zone, foe, "start")
    finally:
        Gate4ControllerEngine._roll_save = original_save
    assert _marked(foe, me), "Successful Save: Gain your Sword Intent."

    # ... and the reminder names all five printed alternatives, so the choice is not hidden from anybody.
    shown = " ".join(_gm_lines(list(AUTH[PRESSURE]["riders"]), AUTH[PRESSURE], AUTH[PRESSURE]["effects"]))
    for printed in ("Frightened", "Speed is reduced by 10 feet", "cannot take Reactions", "Disadvantage on its next "
                     "attack roll", "gains your Sword Intent"):
        assert printed in shown, (printed, shown)


# ================================================= Sword-Rain Descent: Sword Intent on a failed save (data only)
def test_sword_rain_descent_marks_every_creature_that_failed_its_save():
    engine, me, foe = _fight([RAIN], dc=100)
    _do(engine, "Sword-Rain Descent", aim=True)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert _marked(foe, me), "Failed Save: ... and gain your Sword Intent."


# ============================== the printed free step on a player's own turn, through the table service and a reload
def test_sword_pressure_asks_the_player_for_the_free_step_on_their_own_turn(tmp_path, monkeypatch):
    from tests.hunt12_support import ME as ME2, FOE, candidate, fight, hit_dice, reload, send

    combat, table, mid = fight(tmp_path, [PRESSURE], cl=18, dc=100, kit=SWORD_KIT)
    send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == "Sword Pressure"))
    engine = reload(tmp_path, mid)
    me = engine.state.actors[ME2]
    assert any(str(zone.source_definition_id).endswith(PRESSURE) for zone in sword_sphere._sword_areas(engine, me)), \
        "the printed area is committed fight state"
    start = me.position
    attack = lambda c: "Sword in Hand" in c.display_name and FOE in c.target_ids and "#" not in c.source_definition_id

    # Attacking asks the player, in plain words and with the squares on the map: the free step is their decision,
    # it names the printed ability and the 5 feet, and it may be declined.
    hit_dice(monkeypatch)
    result = send(combat, table, mid, candidate(combat, mid, attack))
    assert result["status"] == "REACTION_REQUIRED", result.get("status")
    prompt = result["reaction"]
    assert prompt["reaction"] == "Sword Pressure", prompt["reaction"]
    assert "choice:" not in prompt["title"] and "choice:" not in prompt["reaction"], \
        f"an internal id is player-facing text: {prompt['title']!r}"
    assert "5 feet" in prompt["trigger"] and "Sword Pressure" in prompt["trigger"], prompt["trigger"]
    assert "Sword in Hand" in prompt["moment"], prompt["moment"]
    assert prompt["choice"]["allow_decline"] is True, "may move: declining is a legal answer"
    assert prompt["choice"]["options"], "the reachable squares are the buttons"
    assert all(option.get("description") for option in prompt["choice"]["options"]), "every button says what it does"

    # Declining moves nothing at all, and the fight keeps the step as spent for the turn.
    context = prompt["context"]
    send(combat, table, mid, candidate(combat, mid, attack),
         answers=[{**context, "selection": "DECLINE", "option_ids": []}])
    me = reload(tmp_path, mid).state.actors[ME2]
    assert me.position == start, "a declined step is no movement at all"
    assert me.turn_flags.get("sword_pressure_step"), "the printed step is spent for the turn"

    # Answering with a square does move the fighter, and the move survives a save. The printed step is once per turn
    # and the Action is spent, so it is the next turn's own hit that offers it again: come back around to a fresh turn.
    from tests.test_lock2_persistence import act

    for _ in range(4):
        session = combat._load_session(mid)
        if (table.state(mid)["menu"]["actor_id"] == ME2
                and not session.engine.state.actors[ME2].turn_flags.get("sword_pressure_step")):
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    hit_dice(monkeypatch)
    again = send(combat, table, mid, candidate(combat, mid, attack))
    assert again["status"] == "REACTION_REQUIRED", again.get("status")
    prompt = again["reaction"]
    me = reload(tmp_path, mid).state.actors[ME2]
    squares = [option["id"] for option in prompt["choice"]["options"]
               if option["id"].removeprefix("cell:") != f"{me.position.x},{me.position.y}"]
    assert squares, [option["id"] for option in prompt["choice"]["options"]]
    send(combat, table, mid, candidate(combat, mid, attack),
         answers=[{**prompt["context"], "selection": "USE", "option_ids": [squares[0]]}])
    moved = reload(tmp_path, mid).state.actors[ME2].position
    assert moved != start, "an accepted step is the printed 5-foot move, kept through a save"


def _ai_fight(tmp_path, mids, *, ai=None, manual=None, control="LOCAL_AUTO", seed="AUTO54-AI", foe_mids=()):
    """The same table fight with one fighter played by the table and the other by a person."""
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet

    ai = ai or SVC_ME
    manual = manual or SVC_FOE
    doc = sheet(list(mids), cl=18, dc=100, primary="Stamina", score=18, kit=SWORD_KIT)
    foe = sheet(list(foe_mids), cl=18, primary="Stamina")
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    bundles = [compile_character(doc, actor_id=SVC_ME, reaction_plan={"ask": True}),
               compile_character(foe, actor_id=SVC_FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [SVC_ME, SVC_FOE], {SVC_ME: "team:factory", SVC_FOE: "team:opponents"},
        {SVC_ME: {"x": 3, "y": 6}, SVC_FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [SVC_ME], [SVC_FOE],
        control_modes={ai: control, manual: "MANUAL"}, match_seed=seed,
        display_name="AUTO54 AI regression", maximum_rounds=20)["match_id"]
    for _ in range(12):
        menu = table.state(mid)["menu"]
        if menu.get("actor_id") == SVC_ME:
            return combat, table, mid
        if menu.get("actor_id") == ai:
            # The table's own actor plays itself; it is never asked to end its turn by hand.
            from tests.iron_fist_support import answering_iron_fist

            answering_iron_fist(lambda given: table.auto_step(mid, 0, given))([])
            continue
        assert _act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError(f"the Sword fighter's turn never came around (menu={table.state(mid)['menu']['actor_id']})")


def _act(table, mid, choice):
    from tests.test_lock2_persistence import act

    return act(table, mid, choice)


def _advance_to(table, mid, actor_id, *, limit=10):
    """Put ``actor_id``'s turn on the clock: end a person's turn, let the table play its own actor's."""
    from tests.iron_fist_support import answering_iron_fist

    for _ in range(limit):
        menu = table.state(mid)["menu"]
        if menu.get("actor_id") == actor_id:
            return menu
        if "end_turn" in menu:
            assert _act(table, mid, "end")["status"] == "COMMITTED"
        else:
            # The table's own actor plays itself; it is never asked to end its turn by hand.
            answering_iron_fist(lambda given: table.auto_step(mid, 0, given))([])
    raise AssertionError(f"{actor_id}'s turn never came around (menu={table.state(mid)['menu'].get('actor_id')})")


def test_the_table_ai_answers_the_printed_step_for_itself_on_its_own_turn(tmp_path, monkeypatch):
    """Checklist 9: an AI actor decides for itself at the table, not merely "nobody was there to ask".

    The fighter is under the table's own automatic control (``LOCAL_AUTO``), so the free step is put to the table's
    decision transport and answered inside the same intent. Asserting the fighter actually moved proves a real
    answer came back; a silent default would leave the position where it was.
    """
    from tests.hunt12_support import candidate, hit_dice, reload, send

    combat, table, mid = _ai_fight(tmp_path, [PRESSURE], ai=SVC_ME, manual=SVC_FOE)
    send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == "Sword Pressure"), auto=True)
    engine = reload(tmp_path, mid)
    me = engine.state.actors[SVC_ME]
    assert any(str(zone.source_definition_id).endswith(PRESSURE) for zone in sword_sphere._sword_areas(engine, me))
    start = me.position
    attack = lambda c: "Sword in Hand" in c.display_name and SVC_FOE in c.target_ids and "#" not in c.source_definition_id

    hit_dice(monkeypatch)
    result = send(combat, table, mid, candidate(combat, mid, attack), auto=True)
    assert result["status"] == "COMMITTED", \
        f"an AI actor's printed choice is decided inside its own intent, never left waiting: {result.get('status')}"
    me = reload(tmp_path, mid).state.actors[SVC_ME]
    assert me.turn_flags.get("sword_pressure_step"), \
        "the AI really did decide the printed step (it is spent for the turn)"
    assert me.position != start, "and the move it decided on is committed fight state"
    assert not [row for row in me.conditions.values() if "Sword Intent" in str(row.condition_id)], \
        "and no choice was left half-applied"


@pytest.mark.parametrize("use_counter", [True, False], ids=["use", "decline"])
def test_a_manual_owner_is_asked_for_the_sovereign_counter_during_an_ai_attack(tmp_path, monkeypatch, use_counter):
    """Checklist 9: a player-owned decision is asked on an AI's turn too, naming the ability and the creature.

    The opponent is played by the table. It is marked with the fighter's Sword Intent by a real committed hit
    (Sword Drawing Stance applies it on a hit), then on its own turn it attacks and misses -- and the fighter, who
    is a person, has to be asked for the printed Reaction counter, not have it decided for them.
    """
    from tests.hunt12_support import candidate, hit_dice, reload, send

    combat, table, mid = _ai_fight(tmp_path, [INCARNATION, DRAWING], ai=SVC_FOE, manual=SVC_ME, seed="AUTO54-SOV")
    send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == "Sword-Sovereign Incarnation"))
    engine = reload(tmp_path, mid)
    me = engine.state.actors[SVC_ME]
    assert sword_sphere.sovereign_flight(engine, me) == {"fly_speed_ft": 40, "flight_hover": 1}

    # Mark the opponent the printed way, on a committed hit, so the Intent is saved fight state. The Incarnation
    # already used this turn's Bonus Action, so the stance is opened on the fighter's next one.
    assert _act(table, mid, "end")["status"] == "COMMITTED"
    _advance_to(table, mid, SVC_ME)
    send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == "Sword Drawing Stance"))
    _advance_to(table, mid, SVC_ME)
    hit_dice(monkeypatch)
    strike = candidate(combat, mid, lambda c: "Sword in Hand" in c.display_name
                      and SVC_FOE in c.target_ids and "#" not in c.source_definition_id)
    result = send(combat, table, mid, strike)
    if result["status"] == "REACTION_REQUIRED":
        # Whatever else the table asks about that attack, decline it so the hit itself resolves.
        prompt = result["reaction"]
        send(combat, table, mid, strike,
             answers=[{**prompt["context"], "selection": "DECLINE", "option_ids": []}])
    engine = reload(tmp_path, mid)
    me, foe = engine.state.actors[SVC_ME], engine.state.actors[SVC_FOE]
    assert _marked(foe, me), "the opponent bears the fighter's Sword Intent"
    assert _state(engine, me, sword_sphere.INCARNATION_STATE) is not None, "and the Incarnation is still running"

    # The table's own turn: it attacks the fighter and misses.
    _advance_to(table, mid, SVC_FOE)
    miss_dice(monkeypatch)
    attack = candidate(combat, mid, lambda c: c.actor_id == SVC_FOE and SVC_ME in c.target_ids
                       and c.source_definition_id.endswith(".natural.unarmed_strike"))
    # A Shove is resolved by a save, so it cannot miss or trigger the printed counter.
    attack_row = reload(tmp_path, mid).action_catalog[attack.source_definition_id]
    assert any(effect.get("type") == "attack" for effect in attack_row.parameters["typed"]["effects"])
    result = send(combat, table, mid, attack, auto=True)
    assert result["status"] == "REACTION_REQUIRED", result.get("status")
    prompt = result["reaction"]
    assert prompt["reaction"] == "Sword-Sovereign Incarnation", prompt["reaction"]
    assert "Sword Intent" in prompt["trigger"], f"the printed moment is kept: {prompt['trigger']!r}"
    assert "missed" in prompt["trigger"], f"and says what just happened: {prompt['trigger']!r}"
    assert prompt["choice"]["allow_decline"] is True, "the owner may keep their Reaction"
    assert prompt["choice"]["options"], "the printed Sword attacks are the buttons"
    assert all(option.get("description") for option in prompt["choice"]["options"]), "each button says what it does"

    before = reload(tmp_path, mid)
    assert before.state.actors[SVC_ME].reaction_available
    if not use_counter:
        result = send(combat, table, mid, attack, auto=True,
                      answers=[{**prompt["context"], "selection": "DECLINE", "option_ids": []}])
        assert result["status"] == "COMMITTED", result.get("reaction")
        after = reload(tmp_path, mid)
        assert after.state.actors[SVC_ME].reaction_available, "declining keeps the player's Reaction"
        assert not any(event.sequence > before.state.event_sequence and event.event_type == "ATTACK_ROLLED"
                       and event.actor_id == SVC_ME for event in after.events)
        return

    # Selecting a counter can open its own attack/damage choices. None of the
    # preview is committed until the player has answered the entire action.
    attack_id = prompt["choice"]["options"][0]["id"]
    answers = [{**prompt["context"], "selection": "USE", "option_ids": [attack_id]}]
    for _ in range(12):
        result = send(combat, table, mid, attack, auto=True, answers=answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        assert reload(tmp_path, mid).state == before.state, "an unanswered preview must not spend the Reaction"
        followup = result["reaction"]
        assert not any(all(answer.get(k) == v for k, v in followup["context"].items()) for answer in answers), followup
        answer = {**followup["context"], "selection": "USE"}
        if followup.get("choice"):
            choice = followup["choice"]
            answer["option_ids"] = [o["id"] for o in choice["options"]][:max(1, choice.get("minimum", 1))]
        answers.append(answer)
    else:
        raise AssertionError("Counter did not finish: " + str(result.get("reaction")))
    after = reload(tmp_path, mid)
    assert not after.state.actors[SVC_ME].reaction_available, "the printed Reaction was spent"
    assert any(event.sequence > before.state.event_sequence and event.event_type == "ATTACK_ROLLED"
               and event.actor_id == SVC_ME and SVC_FOE in event.target_ids for event in after.events)


# ============================================= checklist 13: every button of a Sword choice says what it does
@pytest.mark.parametrize("choice_id", sorted(sword_sphere.STEP_CHOICES))
def test_every_sword_choice_button_says_what_it_does(choice_id):
    """Checklist 13: each choice this plug-in raises explains itself and every button says what it does.

    The three printed decisions are the Sword Pressure and Incarnation free steps (map squares) and the Incarnation
    Reaction (Sword attacks), so a button that only carried an internal id or a bare square name would leave a player
    who knows basic D&D guessing.
    """
    engine, me, foe = _fight([PRESSURE, INCARNATION])
    ability, feet = sword_sphere.STEP_CHOICES[choice_id]
    options = ["cell:7,6"] if feet else ["action:typed.attack.1"]
    context = {"reaction_source_id": choice_id, "reactor_id": ME, "target_id": foe.entity_id,
               "choice_trigger": {"needle_options": options, "labels": {key: "Sword in Hand" for key in options},
                                  "target_id": foe.entity_id, "feature_id": ability,
                                  "prompt": f"{sword_sphere.ABILITY_NAMES[ability]}: after Sword in Hand hits "
                                            f"{foe.display_name}, {me.display_name} may move 5 feet."}}
    text = sword_sphere.sword_decision_text(engine, context, {})
    assert text is not None, choice_id
    assert text["name"] == sword_sphere.ABILITY_NAMES[ability]
    assert text["cost"] and text["trigger"] and text["summary"], "what it does, who it affects, what it costs"
    assert "choice:" not in text["name"] and "choice:" not in text["trigger"], "no internal id in player-facing text"
    # The triggering moment keeps the action that fired it and the creature it landed on, rather than being
    # replaced by wording that drops both.
    assert "Sword in Hand" in text["trigger"] and foe.display_name in text["trigger"], text["trigger"]
    assert set(text["option_descriptions"]) == set(options), "every button is described"
    for description in text["option_descriptions"].values():
        assert description.strip() and "choice:" not in description, description
        if not feet:
            assert foe.display_name in description, "the Reaction buttons name the creature they attack"


def test_sword_decision_text_leaves_another_plugins_choice_alone():
    """Checklist 3: inert for anything this plug-in does not own."""
    engine, me, foe = _fight([PRESSURE])
    context = {"reaction_source_id": "choice:someone_else.choice", "reactor_id": ME,
               "choice_trigger": {"needle_options": ["cell:7,6"]}}
    assert sword_sphere.sword_decision_text(engine, context, {}) is None


# ====================================================== the GM reminder lines the sphere no longer needs
def test_sword_sphere_no_longer_shows_the_lines_the_table_resolves():
    from combat.factory_compiler import _gm_lines

    retired = {
        INFUSION: ("apply Sword Intent", "At CL 11, increase the extra damage to 2d6. At CL 17, increase it to 3d6."),
        DRAWING: ("apply Sword Intent on a hit", "After the attack resolves, the stance ends."),
        INCARNATION: ("Sword Intent lasts until the end of your next turn",
                      "once per turn when a creature bearing your Sword Intent misses you, make one Sword attack or Sword Qi Wave as a Reaction",
                      "ordinary disarming effects fail against you"),
        PRESSURE: ("move 5 feet without provoking opportunity attacks after hitting with a Sword attack, once per turn",),
        MYRIAD: ("Allies gain Half Cover", "move 5 feet without provoking opportunity attacks after hitting, once per turn",
                 "gain your Sword Intent"),
        MANIFESTATION: ("Silent Killing Line: Your Sword attacks and Sword-Qi attacks score a critical hit on 19-20 against creatures bearing your Sword Intent.",
                        "Forest of Swords: Allies gain Half Cover. When a hostile creature misses an ally with a melee attack, it takes "
                        "Slashing or Force damage equal to your Proficiency Bonus."),
        RAIN: ("Sword Qi rains into the area.", "Creatures inside make Dexterity saving throws."),
    }
    for key, lines in retired.items():
        shown = _gm_lines(list(AUTH[key]["riders"]), AUTH[key], AUTH[key]["effects"])
        for line in lines:
            assert not any(line in text for text in shown), (key, line, shown)
