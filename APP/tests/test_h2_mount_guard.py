"""Automation lane H2: Defensive Rider and Meat Shield (combat/ext/mount_guard.py) on the lock round's retarget_attack hook.

Each case compiles a real Rider Package character with the talent(s), starts the fight on its 2x2 Warhorse (An Eui is the foe), and
lets the foe attack: the redirection is recorded (ATTACK_RETARGETED) before the d20, the attack is rolled against the new target and
its damage lands there.
"""
import pytest

from combat import ext
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from combat.ext import mount_guard
from tests.test_mounts import ME, MOUNT, FOE, actors, fight, rider_bundle, take

FOCUS = "resource:core.martial_focus"
SHIELD = "condition:typed.meat_shield"
TALENTS = ["TAL_BEASTMASTERY_DEFENSIVE_RIDER", "TAL_BEASTMASTERY_MEAT_SHIELD"]


@pytest.fixture(scope="module")
def guard_bundle():
    return rider_bundle(TALENTS)


@pytest.fixture(scope="module")
def rider_only_bundle():
    return rider_bundle(["TAL_BEASTMASTERY_DEFENSIVE_RIDER"])


def _foe_turn(e):
    e.state.current_slot_index = e.state.initiative_order.index(FOE)
    e.state.current_actor_id = FOE
    e._system_start_turn()


def _my_turn(e):
    e.state.current_slot_index = e.state.initiative_order.index(ME)
    e.state.current_actor_id = ME
    e._system_start_turn()


def _foe_attacks(e, target, before_hit=True):
    """An Eui's attack action aimed at ``target``; the return is the events it produced."""
    if before_hit:
        e.state.actors[ME].armor_class = e.state.actors[MOUNT].armor_class = -50  # every roll but a natural 1 hits
    candidate = next(c for c in e.legal_candidates() if c.kind == "ACTION" and c.target_ids == (target,) and c.display_name.startswith("Paired"))
    n = len(e.events)
    e.execute_intent(ActionIntent(intent_id=f"foe:{n}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                  state_version=candidate.state_version, actor_id=FOE, target_ids=candidate.target_ids, option_ids=()))
    return e.events[n:]


def _rolled_at(events):
    return [ev.target_ids[0] for ev in events if ev.event_type == "ATTACK_ROLLED"]


def _retargeted(events):
    return [ev for ev in events if ev.event_type == "ATTACK_RETARGETED"]


def _answering(e, answers):
    """The table's answers to the Reactive Cover choice: an edge letter, or None to decline."""
    asked = []

    def provider(request):
        asked.append(request)
        pick = answers.get(request["reaction_source_id"])
        if pick is None:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=(pick,)), None

    e.set_reaction_provider(provider)
    return asked


# ------------------------------------------------------------------------------------------------ Defensive Rider
def test_an_attack_on_the_mount_is_redirected_to_the_rider_and_damages_the_rider(rider_only_bundle):
    e = fight(rider_only_bundle)
    me, mount, foe = actors(e)
    _foe_turn(e)
    hp = (me.current_hp, mount.current_hp)
    events = _foe_attacks(e, MOUNT)
    moves = _retargeted(events)
    assert len(moves) == 2  # both strikes of the Paired attack: the hook runs for each declared attack
    assert all(m.source_definition_id == "ability:defensive_rider" and m.payload["original_target_id"] == MOUNT and m.target_ids == (ME,) for m in moves)
    assert set(_rolled_at(events)) == {ME}
    assert me.current_hp < hp[0] and mount.current_hp == hp[1]
    e._assert_invariants()


def test_a_character_without_the_talent_is_not_shielded_and_an_attack_on_the_rider_stays_put(plain_bundle_fixture):
    e = fight(plain_bundle_fixture)
    me, mount, _ = actors(e)
    _foe_turn(e)
    events = _foe_attacks(e, MOUNT)
    assert not _retargeted(events) and set(_rolled_at(events)) == {MOUNT}
    _my_turn(e)
    _foe_turn(e)
    assert set(_rolled_at(_foe_attacks(e, ME))) == {ME}


@pytest.fixture(scope="module")
def plain_bundle_fixture():
    return rider_bundle()


def test_the_redirect_needs_the_rider_to_be_a_legal_target_of_that_attack(rider_only_bundle):
    e = fight(rider_only_bundle)
    me, mount, foe = actors(e)
    _foe_turn(e)
    intent = ActionIntent(intent_id="x", decision_id="d", candidate_id="c", state_version=0, actor_id=FOE, target_ids=(MOUNT,))
    assert mount_guard.defensive_rider(e, foe, mount, intent, {"range_ft": 5})["target_id"] == ME
    assert mount_guard.defensive_rider(e, foe, mount, intent, {"range_ft": 0}) is None  # the rider is out of that attack's reach
    foe.team_id = me.team_id
    assert mount_guard.defensive_rider(e, foe, mount, intent, {"range_ft": 5}) is None  # only a hostile attacker is turned aside


def test_defensive_rider_replays_from_its_events(rider_only_bundle):
    e = fight(rider_only_bundle)
    _foe_turn(e)
    before, start = e.state.model_copy(deep=True), len(e.events)
    _foe_attacks(e, MOUNT)
    docs = enrich_committed_events(e.events[start:], post_engine=e)
    replayed = Gate3EventReducer().apply_events(before, docs)
    assert replayed.actors[ME].current_hp == e.state.actors[ME].current_hp and replayed.actors[MOUNT].current_hp == e.state.actors[MOUNT].current_hp


# ------------------------------------------------------------------------------------------------ Meat Shield
def test_meat_shield_is_a_bonus_action_that_picks_an_edge_and_switches_defensive_rider_off(guard_bundle):
    e = fight(guard_bundle)
    me, mount, _ = actors(e)
    assert "Meat Shield" in {c.display_name for c in e.legal_candidates()} and "End Meat Shield" not in {c.display_name for c in e.legal_candidates()}
    asked = _answering(e, {"choice:needle.meat_shield_edge": "E"})
    take(e, "Meat Shield")
    held = next(c for c in me.conditions.values() if c.condition_id == SHIELD)
    assert held.data["edge"] == "E" and held.data["mount"] == MOUNT and not me.bonus_action_available
    assert [row["reaction_source_id"] for row in asked] == ["choice:needle.meat_shield_edge"] and "End Meat Shield" in {c.display_name for c in e.legal_candidates()}
    _foe_turn(e)
    # "You cannot use Defensive Rider while using the mount as cover": an attack on the mount stays on the mount.
    assert set(_rolled_at(_foe_attacks(e, MOUNT))) == {MOUNT}


def test_total_cover_across_the_edge_hides_the_attack_and_reroutes_a_forced_one_to_the_mount(guard_bundle):
    e = fight(guard_bundle)
    me, mount, foe = actors(e)
    _answering(e, {"choice:needle.meat_shield_edge": "E"})  # the foe is to the east of the rider at (4,6)
    take(e, "Meat Shield")
    assert mount_guard.covered(e, foe, me, "E") and not mount_guard.covered(e, foe, me, "W") and not mount_guard.covered(e, foe, me, "N")
    _foe_turn(e)
    offered = {c.target_ids for c in e.legal_candidates() if c.kind == "ACTION" and c.display_name.startswith("Paired")}
    assert (ME,) not in offered and (MOUNT,) in offered  # Total Cover: it cannot be targeted from there; the mount "remains targetable"
    # An attack that reaches the rider anyway (a reaction attack made at it) is aimed at the mount.
    action = e.action_catalog[next(a for a in e.state.actors[FOE].action_ids if e.action_catalog[a].display_name.startswith("Paired"))]
    intent = ActionIntent(intent_id="forced", decision_id="d", candidate_id="c", state_version=0, actor_id=FOE, target_ids=(ME,))
    n = len(e.events)
    e._resolve_attack_spec(foe, me, {"attack_bonus": 100, "range_ft": 5, "damage": None}, intent, source_definition_id=action.source_definition_id)
    [moved] = _retargeted(e.events[n:])
    assert moved.source_definition_id == "ability:meat_shield" and moved.target_ids == (MOUNT,)


def test_an_edge_the_attack_does_not_cross_gives_no_cover(guard_bundle):
    e = fight(guard_bundle)
    me, mount, foe = actors(e)
    _answering(e, {"choice:needle.meat_shield_edge": "W"})  # the far side
    take(e, "Meat Shield")
    _foe_turn(e)
    assert (ME,) in {c.target_ids for c in e.legal_candidates() if c.kind == "ACTION" and c.display_name.startswith("Paired")}


def test_end_meat_shield_is_free_and_dismounting_ends_it(guard_bundle):
    e = fight(guard_bundle)
    me, mount, _ = actors(e)
    _answering(e, {"choice:needle.meat_shield_edge": "E"})
    take(e, "Meat Shield")
    take(e, "End Meat Shield")
    assert not any(c.condition_id == SHIELD for c in me.conditions.values()) and me.action_available
    _answering(e, {"choice:needle.meat_shield_edge": "E"})
    me.bonus_action_available = True
    take(e, "Meat Shield")
    from combat.ext import mounts

    mounts.unbind(e, me, mount)
    assert mount_guard.edge_of(e, me) is None
    _my_turn(e)
    assert not any(c.condition_id == SHIELD for c in me.conditions.values())


def test_reactive_cover_spends_focus_and_reaction_and_turns_the_attack_onto_the_mount(guard_bundle):
    e = fight(guard_bundle)
    me, mount, foe = actors(e)
    me.resources[FOCUS] = 1
    _foe_turn(e)
    asked = _answering(e, {"choice:needle.meat_shield": "E"})
    before, start = e.state.model_copy(deep=True), len(e.events)
    events = _foe_attacks(e, ME)
    assert [row["reaction_source_id"] for row in asked].count("choice:needle.meat_shield") >= 1
    [moved] = _retargeted(events)[:1]
    assert moved.source_definition_id == "ability:meat_shield" and moved.payload["original_target_id"] == ME and moved.target_ids == (MOUNT,)
    assert me.resources[FOCUS] == 0 and not me.reaction_available
    assert mount_guard.edge_of(e, me) == "E"  # it "activates Meat Shield": the edge stays covered
    assert set(_rolled_at(events)) == {MOUNT}
    replayed = Gate3EventReducer().apply_events(before, enrich_committed_events(e.events[start:], post_engine=e))
    assert replayed.actors[ME].reaction_available is False and replayed.actors[ME].resources[FOCUS] == 0


def test_reactive_cover_can_be_declined_and_needs_focus_and_a_reaction(guard_bundle):
    e = fight(guard_bundle)
    me, mount, _ = actors(e)
    me.resources[FOCUS] = 1
    _foe_turn(e)
    _answering(e, {})  # declined
    assert set(_rolled_at(_foe_attacks(e, ME))) == {ME} and me.resources[FOCUS] == 1 and me.reaction_available
    for spend in ("focus", "reaction"):
        e2 = fight(guard_bundle)
        me2, _, _ = actors(e2)
        me2.resources[FOCUS] = 0 if spend == "focus" else 1
        me2.reaction_available = spend != "reaction"
        _foe_turn(e2)
        asked = _answering(e2, {"choice:needle.meat_shield": "E"})
        assert set(_rolled_at(_foe_attacks(e2, ME))) == {ME} and not asked


def test_the_built_in_ai_accepts_reactive_cover_only_while_its_mount_is_the_healthier(guard_bundle):
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    from tests.test_auto_tabik import ROOT

    def run(mount_hp, rider_hp):
        e = fight(guard_bundle)
        me, mount, _ = actors(e)
        me.resources[FOCUS] = 1
        me.current_hp, mount.maximum_hp = rider_hp, max(mount_hp, mount.maximum_hp)
        mount.current_hp = mount_hp
        _foe_turn(e)
        policy = PolicyLibrary(ROOT).fallback()

        def provider(request):
            return LocalDeterministicController().choose_reaction(build_reaction_context(e, policy, request)).decision, None

        e.set_reaction_provider(provider)
        return set(_rolled_at(_foe_attacks(e, ME)))

    assert run(mount_hp=100, rider_hp=30) == {MOUNT}
    assert run(mount_hp=10, rider_hp=30) == {ME}


def test_plain_fights_have_no_redirection_providers_answering(plain_bundle_fixture):
    e = fight(plain_bundle_fixture)
    me, mount, foe = actors(e)
    intent = ActionIntent(intent_id="x", decision_id="d", candidate_id="c", state_version=0, actor_id=FOE, target_ids=(MOUNT,))
    assert ext.run_strict("retarget_attack", e, foe, mount, intent, {"range_ft": 5}) == []
