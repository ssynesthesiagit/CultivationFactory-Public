"""Generate Pack Echo through real table commits and cold replay."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (OWNER, ALLY, FOE, fixture, candidate, settle,
                                   reload, turn, sealed_native_attack)

FEATURE = "foundation.beast_echo_marrow_v0_2A"
GENERATE = FEATURE + ".generate_pack_echo"
IRON = "tianxia.path.body_refining.feature.iron_fist"
PALM = "TAL_BRUTE_MOUNTAIN_MOVING_PALM"
ECHO = "resource:foundation.pack_echo"


def setup(tmp_path, *, label="Humanoid", nearby=False, owned=True, natural=False, forged=False):
    mids = ([GENERATE] if owned else []) + ([IRON] if natural else []) + ([PALM] if forged else [])
    document = sheet(mids)
    if forged:
        document["forged_techniques"] = [{"technique_id": "constructed:echo.projection",
            "name": "Projection control", "action_type": "action",
            "primary_sphere_effect": {"talent_id": PALM}, "cp_cost": {"final": 1},
            "base_form": {"form_id": "projection"}, "augments": [], "drawbacks": []}]
    if owned:
        document["foundation"] = {"foundation_id": "beast_echo_marrow_v0_2A",
            "stage": "Awakened", "resource": {"name": "Pack Echo",
                "resource_id": "foundation.resource.beast_echo_marrow_v0_2A", "current": 0, "maximum": 1}}
    bundle = compile_character(document, actor_id=OWNER)
    foe = sheet([])
    foe["identity"]["creature_types"] = [label]
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 600

    def prepare(bundles):
        sealed_native_attack(bundles[0], "Control hit", attack_bonus=100, attacks=3,
                             count=1, sides=2, modifier=0)

    return fixture(tmp_path, [], owner_bundle=bundle, foe_sheet=foe,
        bundle_transform=prepare, seed="REDOBEAST1-GENERATE", ask=False,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                   ALLY: {"x": 4, "y": 7} if nearby else {"x": 18, "y": 12}})


def gains(engine):
    return [e for e in engine.events if e.event_type == "RESOURCE_GAINED"
            and e.source_definition_id == "passive:" + GENERATE]


def hit(combat, table, mid, name="Control hit"):
    settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id)


@pytest.mark.parametrize("label", [
    "Beast-aspected", "Predator-aspected", "Monstrosity", "Spirit Beast", "Demon Beast",
])
def test_qualifying_hostile_hit_needs_no_ally_and_generates_only_after_hit(tmp_path, label):
    combat, table, mid = setup(tmp_path, label=label)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ECHO] == 0
    hit(combat, table, mid)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[ECHO] == 1
    assert len(gains(e)) == 1  # Three hits share one round budget.
    gain = gains(e)[0]
    assert any(x.event_type == "DAMAGE_COMMITTED" and x.sequence < gain.sequence
               and x.actor_id == OWNER for x in e.events)


@pytest.mark.parametrize("label,nearby,owned", [
    ("Humanoid", False, True), ("Demon", False, True),
    ("Beast-aspected", False, False), ("Humanoid", True, True),
])
def test_nonqualifying_hit_and_nonowner_are_inert(tmp_path, label, nearby, owned):
    combat, table, mid = setup(tmp_path, label=label, nearby=nearby, owned=owned)
    hit(combat, table, mid)
    assert not gains(reload(tmp_path, mid))


def test_owned_natural_weapon_hit_with_ally_uses_native_compiled_provenance(tmp_path):
    combat, table, mid = setup(tmp_path, natural=True, nearby=True)
    e = reload(tmp_path, mid)
    actions = [a for a in e.action_catalog.values() if a.owner_id == OWNER
               and a.parameters.get("beast_echo_source")]
    assert any(a.parameters["beast_echo_source"]["membership"] == "natural_weapon" for a in actions)
    action = next(a for a in actions if a.parameters["beast_echo_source"]["membership"] == "natural_weapon")
    # The real, compiled natural weapon, not the synthetic control attack.
    for _ in range(3):
        rows = [c for c in e.legal_candidates() if c.source_definition_id == action.source_definition_id
                and c.target_ids == (FOE,)]
        if rows:
            settle(table, mid, rows[0].candidate_id)
            break
    assert gains(reload(tmp_path, mid))


def test_native_forged_scope_hit_uses_owned_primary_not_opaque_action_id(tmp_path):
    combat, table, mid = setup(tmp_path, nearby=True, forged=True)
    e = reload(tmp_path, mid)
    action = next(a for a in e.action_catalog.values() if a.owner_id == OWNER
                  and a.parameters.get("typed", {}).get("forged_from") == PALM)
    assert action.parameters["beast_echo_source"]["mechanic_id"] == PALM
    hit(combat, table, mid, action.display_name)
    assert gains(reload(tmp_path, mid))


def test_echo_expiry_refresh_and_round_budget_survive_commit_reload(tmp_path):
    combat, table, mid = setup(tmp_path, label="Beast-aspected")
    hit(combat, table, mid)
    e = reload(tmp_path, mid)
    first_round = e.state.round_number
    clock = e.state.actors[OWNER].turn_flags["pressure_round_clock"][ECHO]
    assert clock == {"round": first_round, "count": 1, "ends_left": 2}
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ECHO] == 1
    turn(table, mid, OWNER)
    hit(combat, table, mid)
    e = reload(tmp_path, mid)
    assert e.state.round_number > first_round
    assert e.state.actors[OWNER].resources[ECHO] == 1
    assert e.state.actors[OWNER].turn_flags["pressure_round_clock"][ECHO]["ends_left"] == 2
    # No hit on the following turn: expires at that turn's end, not this one.
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ECHO] == 0
