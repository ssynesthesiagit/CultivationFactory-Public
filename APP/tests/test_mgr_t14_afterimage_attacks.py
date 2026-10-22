"""Targeted attack contracts; movement-earned coverage lives in the review tests."""
import pytest

from combat import ext, motion, senses
from combat.gate2_runtime_models import RuntimeObjectState, Position
from combat.ext.afterimage_targeting import FEATURE as ABILITY, perceived_image
from tests.test_c2_review import table_fixture
from tests.test_auto_athletics import _sheet
from tests.hunt15_support import act, turn, reload
from tests.auto_worker1_support import cell_send, resolve

OWNER = "actor:factory.afterimage-owner"
ATTACKER = "actor:factory.afterimage-attacker"
IMAGE = "object:test.afterimage"
SETUP = "test_afterimage_setup"


def image(engine):
    owner = engine.state.actors[OWNER]
    held = next((c for c in owner.conditions.values() if c.condition_id == motion.AFTERIMAGE), None)
    if held is not None:
        return engine.state.map_images[held.data["image_object_id"]]
    return next(o for o in engine.state.map_images.values() if o.owner_id == OWNER)


@pytest.fixture(autouse=True)
def producer(monkeypatch):
    def seed(ctx, effect):
        owner = ctx.actor
        ctx.engine._apply_condition(owner, motion.AFTERIMAGE, "passive:" + ABILITY,
            owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Afterimage"})
        held = next(c for c in owner.conditions.values() if c.condition_id == motion.AFTERIMAGE)
        object_id = held.data.get("image_object_id", IMAGE)
        ctx.engine._update_condition_data(owner, held, {**held.data, "image_object_id": object_id}, ctx.source)
        original = ctx.engine.state.map_images.get(object_id)
        ctx.engine._update_object(RuntimeObjectState(object_id=object_id, object_kind="TEMPORARY_IMAGE",
            position=Position(x=effect.get("x", 3), y=effect.get("y", 5)),
            unattended=True, flammable=False, owner_id=owner.entity_id,
            component={**(original.component if original else {}), "map_marker": 1, "condition_instance_id": held.instance_id,
                "source_definition_id": held.source_definition_id, "peer_field": "preserved"}), ctx.source, owner.entity_id)
    monkeypatch.setitem(ext.effects(), SETUP, seed)


def setup(tmp_path, seed, *, route="native", owned=True, image_xy=(3, 5), count=1, bonus=100, attacker_turn=True):
    def configure(bundles):
        for bundle in bundles:
            aid = bundle["actor_id"]
            source = "action:test.afterimage." + aid
            if aid == OWNER:
                action = {"source_definition_id": source, "display_name": "Seed image", "owner_id": aid,
                    "economy": "BONUS_ACTION", "resolution_kind": "TYPED", "target_kind": "SELF",
                    "parameters": {"typed": {"effects": [{"type": SETUP, "x": image_xy[0], "y": image_xy[1]}],
                        "numbers": {}, "riders": []}}}
            else:
                action = {"source_definition_id": source, "display_name": "Test strike", "owner_id": aid,
                    "economy": "ACTION", "resolution_kind": "ATTACK", "target_kind": "HOSTILE_ENTITY",
                    "costs": [["resource:core.stamina", 1]],
                    "reach_ft": 5, "attack_bonus": bonus,
                    "damage": {"count": 1, "sides": 6, "modifier": 4}, "damage_type": "SLASHING"}
                if route == "typed":
                    action.update(resolution_kind="TYPED", parameters={"typed": {
                        "numbers": {"attack_bonus": bonus, "cl": 10, "pb": 4}, "riders": [],
                        "effects": [{"type": "attack", "attack_kind": "melee", "count": count,
                            "on_hit": [{"type": "damage", "dice": "1d6+4", "damage_types": ["slashing"]}]}]}})
            bundle["actor_template"]["action_ids"].append(source)
            bundle["action_catalog"].append(action)
    combat, table, mid = table_fixture(tmp_path,
        {OWNER: _sheet([ABILITY] if owned else []), ATTACKER: _sheet([])},
        {OWNER: (3, 6), ATTACKER: (4, 6)}, seed=seed, foes=(ATTACKER,), configure=configure)
    turn(table, mid, OWNER)
    assert act(table, mid, "Seed image")["status"] == "COMMITTED"
    before = reload(combat, mid)
    assert image(before).component["peer_field"] == "preserved"
    if attacker_turn:
        turn(table, mid, ATTACKER)
    return combat, table, mid


@pytest.mark.parametrize("route", ["native", "typed"])
@pytest.mark.parametrize("seed", ["image-1", "image-2", "image-3", "image-4"])
def test_real_table_recipient_cost_and_cold_reload(tmp_path, route, seed):
    c, t, mid = setup(tmp_path, seed, route=route)
    before = reload(c, mid)
    hp = before.state.actors[OWNER].current_hp
    stamina = before.state.actors[ATTACKER].resources["resource:core.stamina"]
    assert perceived_image(before, before.state.actors[ATTACKER], before.state.actors[OWNER])
    start = len(before.events)
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    events = e.events[start:]
    decisions = [v for v in events if v.payload.get("kind") == "afterimage_targeting"]
    assert len(decisions) == 1
    result = decisions[0].payload["result"]
    assert not e.state.actors[ATTACKER].action_available
    assert e.state.actors[ATTACKER].resources["resource:core.stamina"] == stamina - 1
    rolls = [v for v in events if v.event_type == "ATTACK_ROLLED"]
    if result == 1:
        assert e.state.actors[OWNER].current_hp == hp
        assert not rolls and not motion.has_afterimage(e.state.actors[OWNER])
        assert image(e).destroyed
        receipt = next(v for v in events if v.payload.get("kind") == "attack_target_intercepted")
        assert receipt.target_ids == (image(e).object_id,) and receipt.payload["original_target_id"] == OWNER
    else:
        assert len(rolls) == 1
        assert e.state.actors[OWNER].current_hp < hp or rolls[0].payload.get("natural_result") == 1
        assert motion.has_afterimage(e.state.actors[OWNER]) and not image(e).destroyed
    assert image(e).component["peer_field"] == "preserved"


@pytest.mark.parametrize("owned,image_xy", [(False, (3, 5)), (True, (18, 12))])
def test_nonowner_or_unperceived_image_does_not_intercept(tmp_path, owned, image_xy):
    c, t, mid = setup(tmp_path, "image-unseen", owned=owned, image_xy=image_xy)
    e = reload(c, mid)
    if owned:
        assert not senses.perceives_object(e, e.state.actors[ATTACKER], image(e))
        assert senses.perceives(e, e.state.actors[ATTACKER], e.state.actors[OWNER])
    start = len(e.events)
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    assert not any(v.payload.get("kind") == "afterimage_targeting" for v in e.events[start:])
    assert any(v.event_type == "ATTACK_ROLLED" for v in e.events[start:])
    assert not image(e).destroyed


@pytest.mark.parametrize("seed", ["image-multi", "image-multi-destroy-5"])
def test_multiattack_has_one_decision_per_actual_strike_until_image_destroyed(tmp_path, seed):
    c, t, mid = setup(tmp_path, seed, route="typed", count=3)
    start = len(reload(c, mid).events)
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    decisions = [v for v in e.events[start:] if v.payload.get("kind") == "afterimage_targeting"]
    assert decisions and [v.payload["attack_index"] for v in decisions] == list(range(1, len(decisions) + 1))
    assert len({v.payload["roll_id"] for v in decisions}) == len(decisions)
    if any(v.payload["result"] == 1 for v in decisions):
        assert decisions[-1].payload["result"] == 1 and image(e).destroyed
        assert len([v for v in e.events[start:] if v.event_type == "ATTACK_ROLLED"]) == 2
    else:
        assert len(decisions) == 3


@pytest.mark.parametrize("seed", ["image-1", "image-2", "image-3", "image-4"])
def test_native_miss_retains_natural_die_and_does_not_destroy_owner_targeted_image(tmp_path, seed):
    c, t, mid = setup(tmp_path, seed, bonus=-100)
    before = reload(c, mid)
    hp = before.state.actors[OWNER].current_hp
    start = len(before.events)
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    events = e.events[start:]
    decision = next(v for v in events if v.payload.get("kind") == "afterimage_targeting")
    if decision.payload["result"] == 2:
        attack = next(v for v in events if v.event_type == "ATTACK_ROLLED")
        natural = attack.payload["natural_result"]
        assert 1 <= natural <= 20
        assert attack.payload["modifier"] == -100
        if natural != 20:
            assert e.state.actors[OWNER].current_hp == hp
        assert motion.has_afterimage(e.state.actors[OWNER]) and not image(e).destroyed


@pytest.mark.parametrize("seed", ["image-oa-1", "image-oa-2"])
def test_real_movement_opportunity_attack_spends_reaction_and_targets_once(tmp_path, seed):
    c, t, mid = setup(tmp_path, seed, attacker_turn=False)
    before = reload(c, mid)
    start = len(before.events)
    resolve(cell_send(t, mid, "Move", (2, 6)))
    e = reload(c, mid)
    events = e.events[start:]
    decisions = [v for v in events if v.payload.get("kind") == "afterimage_targeting"]
    assert len(decisions) == 1
    assert not e.state.actors[ATTACKER].reaction_available
    assert e.state.actors[OWNER].position == Position(x=2, y=6)
    assert e.state.actors[OWNER].movement_remaining_ft == before.state.actors[OWNER].movement_remaining_ft - 5
    if decisions[0].payload["result"] == 1:
        assert e.state.actors[OWNER].current_hp == before.state.actors[OWNER].current_hp
        assert image(e).destroyed
        assert not any(v.event_type == "ATTACK_ROLLED" for v in events)


def test_native_natural_twenty_hits_and_doubles_damage_after_owner_d2_branch(tmp_path):
    # Deterministic native draws: initiative counters 0/1; d2=2 at 2,
    # natural 20 at 3. No patched roller or fabricated roll outcomes.
    c, t, mid = setup(tmp_path, "image-critical-14", bonus=-100)
    before = reload(c, mid)
    start = len(before.events)
    hp = before.state.actors[OWNER].current_hp
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    events = e.events[start:]
    assert next(v for v in events if v.payload.get("kind") == "afterimage_targeting").payload["result"] == 2
    attack = next(v for v in events if v.event_type == "ATTACK_ROLLED")
    assert attack.payload["natural_result"] == 20 and attack.payload["provisional_hit"]
    damage_roll = next(r for r in e.rolls if r.reason.startswith("DAMAGE:action:test.afterimage"))
    assert len(damage_roll.dice) == 2
    assert e.state.actors[OWNER].current_hp == hp - damage_roll.total
    assert motion.has_afterimage(e.state.actors[OWNER]) and not image(e).destroyed


def test_image_perception_does_not_use_invisible_owner_visibility(tmp_path):
    from combat import stealth
    c, t, mid = setup(tmp_path, "image-query")
    e = reload(c, mid)
    owner, attacker = e.state.actors[OWNER], e.state.actors[ATTACKER]
    e._apply_condition(owner, "condition:typed.invisible", "test:invisible-owner", OWNER,
        expires_on="START_OF_SOURCE_NEXT_TURN")
    assert not stealth.sees(e, attacker, owner)
    assert perceived_image(e, attacker, owner) is not None


def test_an_interception_outside_a_table_intent_keeps_its_receipt(tmp_path):
    """A reaction attack declared outside any table intent (combat/attack_declaration.py accepts it)
    still lets the image d2 resolve: its decision and receipt record no intent instead of crashing."""
    from combat.attack_declaration import intercepted
    c, t, mid = setup(tmp_path, "image-no-intent", route="native")
    e = reload(c, mid)
    attacker, owner = e.state.actors[ATTACKER], e.state.actors[OWNER]
    source = next(a.source_definition_id for a in e.action_catalog.values()
                  if a.owner_id == ATTACKER and a.display_name == "Test strike")
    start = len(e.events)
    intercepted(e, attacker, owner, source, None, 1, spec={})
    events = e.events[start:]
    decision = next(v for v in events if v.payload.get("kind") == "afterimage_targeting")
    # main's shared boundary normalizes "no table intent" to the empty causal id.
    assert decision.payload["intent_id"] == ""
    assert decision.payload["attack_source_id"] == source
    if decision.payload["result"] == 1:
        receipt = next(v for v in events if v.payload.get("kind") == "attack_target_intercepted")
        assert receipt.payload["intent_id"] == ""
        assert image(e).destroyed
