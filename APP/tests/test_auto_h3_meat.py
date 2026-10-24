"""Meat Shield: real Rider Package mount, edge coverage and reactive consent."""
import pytest

from combat import attack_declaration
from combat.ext import meat_shield, mounts
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate5_service import _ReactionRequired
from tests.test_mounts import ME, FOE, MOUNT, actors, fight, rider_bundle, take


def engine():
    return fight(rider_bundle([meat_shield.ABILITY]))


def request(e):
    return ActionIntent(intent_id="meat:attack", decision_id="test", candidate_id="test", state_version=e.state.state_version,
                        actor_id=FOE, target_ids=(ME,))


def decline(data):
    return ReactionDecision(checkpoint=data["checkpoint"], reactor_id=data["reactor_id"],
                            reaction_source_id=data["reaction_source_id"], selection="DECLINE"), None


def accept(data):
    preferred = data["extension_choice"].get("preferred_option_ids") or data["legal_option_ids"]
    return ReactionDecision(checkpoint=data["checkpoint"], reactor_id=data["reactor_id"],
                            reaction_source_id=data["reaction_source_id"], selection="USE", option_ids=(preferred[0],)), None


def test_meat_shield_chooses_an_edge_while_mounted_and_ends_without_an_action():
    e = engine()
    rider, mount, foe = actors(e)
    assert mounts.mount_of(e, rider) is mount
    take(e, "Meat Shield")
    assert meat_shield.held(rider) and not rider.bonus_action_available
    before = rider.action_available
    take(e, "End Meat Shield")
    assert meat_shield.held(rider) is None and rider.action_available == before
    e._remove_condition(rider, mounts.MOUNTED, "test:dismount")
    assert not any(c.display_name == "Meat Shield" for c in e.legal_candidates())


@pytest.mark.parametrize("edge,offset", [("N", (0, -3)), ("E", (3, 0)), ("S", (0, 3)), ("W", (-3, 0))])
def test_meat_shield_total_cover_blocks_only_the_chosen_inbound_edge_and_not_the_mount(edge, offset):
    from combat.ext import shield_faces

    e = engine()
    rider, mount, foe = actors(e)
    foe.position = Position(x=rider.position.x + offset[0], y=rider.position.y + offset[1])
    meat_shield.raise_cover(e, rider, mount, edge)
    rays = shield_faces.rays(e, foe, rider)
    assert rays and all(meat_shield.stops(e, rider, ray) for ray in rays)
    assert not any(meat_shield.stops(e, mount, ray) for ray in shield_faces.rays(e, foe, mount))
    from types import SimpleNamespace

    action = SimpleNamespace(parameters={}, attack_bonus=10)
    assert meat_shield.candidates(e, foe, SimpleNamespace(target_ids=(ME,)), action) is False
    assert meat_shield.candidates(e, foe, SimpleNamespace(target_ids=(MOUNT,)), action) is None
    opposite = {"N": "S", "E": "W", "S": "N", "W": "E"}[edge]
    meat_shield.raise_cover(e, rider, mount, opposite)
    assert not any(meat_shield.stops(e, rider, ray) for ray in rays)


def test_reactive_cover_redirects_to_mount_and_spends_exactly_focus_and_reaction():
    e = engine()
    rider, mount, foe = actors(e)
    rider.resources[mounts.FOCUS] = 1
    e.set_reaction_provider(accept)
    target, bonus = attack_declaration.declare(e, foe, rider, "test:attack", request(e), range_ft=60)
    assert target is mount and bonus == 0
    assert not rider.reaction_available and rider.resources[mounts.FOCUS] == 0 and meat_shield.held(rider)
    assert any(ev.event_type == "ATTACK_RETARGETED" and ev.target_ids == (MOUNT,) for ev in e.events)


def test_reactive_cover_table_pause_unwinds_and_decline_preserves_focus_and_target():
    e = engine()
    rider, mount, foe = actors(e)
    rider.resources[mounts.FOCUS] = 1
    calls = []

    def pause(data):
        calls.append(data)
        raise _ReactionRequired(None, None)

    e.set_reaction_provider(pause)
    before = e.state.model_dump(mode="json")
    with pytest.raises(_ReactionRequired):
        with e._transaction("test:attack", "meat:attack", FOE):
            attack_declaration.declare(e, foe, rider, "test:attack", request(e), range_ft=60)
    assert e.state.model_dump(mode="json") == before and calls[-1]["reactor_id"] == ME
    rider, mount, foe = actors(e)
    e.set_reaction_provider(decline)
    target, bonus = attack_declaration.declare(e, foe, rider, "test:attack", request(e), range_ft=60)
    assert target is rider and bonus == 0 and rider.resources[mounts.FOCUS] == 1 and rider.reaction_available


def test_no_talent_or_no_mount_is_inert_and_defensive_rider_is_disabled_while_covering():
    e = fight(rider_bundle())
    rider, mount, foe = actors(e)
    assert attack_declaration.declare(e, foe, rider, "test:attack", request(e), range_ft=60)[0] is rider
    e = engine()
    rider, mount, foe = actors(e)
    meat_shield.raise_cover(e, rider, mount, "N")
    assert meat_shield.defensive_rider(e, rider, {"feature_id": "TAL_BEASTMASTERY_DEFENSIVE_RIDER"}) is False
    e._remove_condition(rider, mounts.MOUNTED, "test:dismount")
    assert meat_shield.reactive(e, foe, rider, request(e), {"range_ft": 60}) is None
