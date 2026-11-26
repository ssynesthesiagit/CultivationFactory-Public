"""Named-creature step exemptions through real table commits and cold reloads."""
import pytest

from combat.gate2_rolls import DeterministicRollAuthority
from tests.cw2_service_support import seal
from tests.worker2_support import (
    ALLY, FOE, OWNER, candidate, fixture, reload, sealed_native_attack, settle, turn,
)

CAULDRON = "TAL_ALCHEMY_CAULDRON_GUARD"
RIDICULOUS = "tianxia.talent.jester.ridiculous_weapon"
REFLECTIVE = "tianxia.subpath.qi.mirror_cultivator.feature.reflective_skin"
SECOND = "actor:factory.worker2-foe1"
STEP = "choice:needle.rider_step"
OA = "reaction:typed.opportunity_attack"
DAGGER = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1},
]}}


@pytest.fixture(autouse=True)
def fixed_dice(monkeypatch):
    # Noncritical hits: +4 just reaches AC 14, then Cauldron Guard turns it
    # into a miss. Saves succeed so Reflective Skin cannot mask the OA check
    # by denying the attacker its Reactions on a failed save.
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return min(10, sides), counter
    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)


def fight(tmp_path, mechanic, *, hard_hit=False):
    def setup(bundles):
        for bundle, initiative in zip(bundles, (100, 50, 0, -50)):
            template = bundle["actor_template"]
            template["initiative_bonus"] = initiative
            template["saving_throws"]["DEX"] = 100
            template["maximum_hp"] = 1000
            if bundle["actor_id"] == FOE:
                template["armor_class"] = 0
                sealed_native_attack(bundle, "Triggering melee attack", range_ft=5,
                                     attack_bonus=20 if hard_hit else 4,
                                     count=1, sides=4, modifier=0)
            seal(bundle)
    return fixture(tmp_path, [mechanic], cl=6, seed="OA-FROM-" + mechanic,
        named=True, owner_kit=DAGGER, ally_kit=DAGGER, foe_kit=DAGGER,
        extra_foes=1, bundle_transform=setup,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                   SECOND: {"x": 4, "y": 7}, ALLY: {"x": 3, "y": 7}})


def activate(combat, table, mid, mechanic, destination):
    if mechanic == RIDICULOUS:
        settle(table, mid, candidate(combat, mid, "Grab an improvised weapon").candidate_id)
        engine = combat._load_session(mid).engine
        # Turn the real modifier on; select its free-move variant, not a
        # synthetic attack with the desired effect injected into it.
        toggle = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.owner_id == OWNER
                      and (a.parameters.get("attack_modifier_setting") or {}).get("modifier") == RIDICULOUS
                      and a.parameters["attack_modifier_setting"]["field"] == "on"
                      and a.parameters["attack_modifier_setting"]["family"].endswith(".improvised.attack"))
        settle(table, mid, next(c.candidate_id for c in engine.legal_candidates()
                               if c.source_definition_id == toggle))
        engine = combat._load_session(mid).engine
        sources = {a.source_definition_id for a in engine.action_catalog.values()
                   if a.owner_id == OWNER and "Free 5-Foot Move" in a.display_name
                   and (a.parameters.get("typed") or {}).get("attack_modifier_family", "").endswith(".improvised.attack")}
        chosen = next(c.candidate_id for c in engine.legal_candidates()
                      if c.source_definition_id in sources and c.target_ids == (FOE,))
        # The structured selector must not offer the rider on a normal dagger.
        assert not any("Ridiculous Weapon" in a.display_name and ".weapon." in
                       (a.parameters.get("typed") or {}).get("attack_modifier_family", "")
                       for a in engine.action_catalog.values())
    else:
        turn(table, mid, FOE)
        chosen = candidate(combat, mid, "Triggering melee attack", target=OWNER).candidate_id
    before = combat._load_session(mid).engine.state.actors[OWNER].movement_remaining_ft
    prompts = settle(table, mid, chosen, {
        "reaction:typed." + mechanic: "first", STEP: destination, OA: "use",
        "system:combat.opportunity_attack": "use",
    })
    return before, prompts


@pytest.mark.parametrize("mechanic", [CAULDRON, RIDICULOUS, REFLECTIVE])
@pytest.mark.parametrize("decline", [False, True], ids=["move", "decline"])
def test_named_step_exempts_only_named_creature_and_second_enemy_still_attacks(tmp_path, mechanic, decline):
    combat, table, mid = fight(tmp_path, mechanic)
    before, prompts = activate(combat, table, mid, mechanic, None if decline else "cell:2,6")
    steps = [p for p in prompts if p["context"]["reaction_source_id"] == STEP]
    assert len(steps) == 1, prompts
    step = steps[0]
    assert step["context"]["reactor_id"] == OWNER
    moment = step["moment"]
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].display_name in moment
    assert "cannot make an Opportunity Attack against you because of this step" in moment
    assert "5 feet" in moment and "No extra action, resource or ordinary movement is spent" in moment
    options = [o["id"] for o in step["choice"]["options"]]
    assert "cell:2,6" in options
    for option in options:
        _, x, y = option.replace(",", ":").split(":")
        assert max(abs(int(x) - 3), abs(int(y) - 6)) <= 1
    owner = engine.state.actors[OWNER]
    assert (owner.position.x, owner.position.y) == ((3, 6) if decline else (2, 6))
    assert owner.movement_remaining_ft == before
    moves = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER]
    assert len(moves) == (0 if decline else 1)
    assert engine.state.actors[FOE].reaction_available
    assert engine.state.actors[SECOND].reaction_available == decline
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == SECOND]
    assert bool(attacks) != decline
    if attacks:
        assert attacks[-1].target_ids == (OWNER,)
    assert not owner.turn_flags.get("oa_free_ft")

    if mechanic == RIDICULOUS and not decline:
        # Before the target has another turn, a different ally leaves its reach.
        # The free step must not install NO_OPPORTUNITY on that creature.
        turn(table, mid, ALLY)
        engine = combat._load_session(mid).engine
        walk = next(c.candidate_id for c in engine.legal_candidates()
                    if c.kind.value == "MOVE" and c.destination
                    and (c.destination.x, c.destination.y) == (2, 7))
        later = settle(table, mid, walk, {OA: "use", "system:combat.opportunity_attack": "use"})
        engine = reload(tmp_path, mid)
        assert any(p["context"]["reactor_id"] == FOE for p in later)
        assert not engine.state.actors[FOE].reaction_available
        assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE and e.target_ids == (ALLY,)
                   for e in engine.events)


def test_cauldron_guard_does_not_offer_a_step_when_the_attack_still_hits(tmp_path):
    combat, table, mid = fight(tmp_path, CAULDRON, hard_hit=True)
    _, prompts = activate(combat, table, mid, CAULDRON, "cell:2,6")
    assert not any(p["context"]["reaction_source_id"] == STEP for p in prompts)
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (3, 6)
    assert not [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER]
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.target_ids == (OWNER,) for e in engine.events)
