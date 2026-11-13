"""Qi Devourer through committed table damage, human/AI consent and cold replay."""
import pytest

from combat.ext import qi_devourer as plug
from combat.ext.essence_state import DEPLETED
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, action_sender, fight, reload, resolve, turn


def fresh(c, mid):
    e = reload(c, mid)
    session = c._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return e


def fixture(tmp_path, *, owns=True, victim_cl=15, distance=5, kind=None, independent=0, ai=False,
            witness=False):
    def sheet(doc, aid):
        if aid == LEFT:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [plug.FEATURE] if owns else []
        else:
            doc["identity"]["cultivation_level"] = victim_cl
    def bundle(b):
        if b["actor_id"] != LEFT:
            b["cl"] = victim_cl
        if distance > 5:
            for action in b["action_catalog"]:
                if action["display_name"] in {"Prepare", "Finish"}:
                    action["range_ft"] = 90  # Setup damage can reach beyond the Insight's sixty-foot trigger.
    extra = [("Finish", {"target_kind": "ANY_CREATURE", "effects": [
        {"type": "damage", "flat": 999, "applies_to": "target", "damage_types": ["force"]}]}),
        ("Heal", {"target_kind": "ANY_CREATURE", "effects": [
        {"type": "healing", "flat": 1000, "applies_to": "target"}]}),
        ("Restore Essence", {"target_kind": "ANY_CREATURE", "effects": [
        {"type": "restore_essence", "fully_rebuilt": 1, "applies_to": "target"}]}),
        ("Profile", {"target_kind": "ANY_CREATURE", "effects": [
        {"type": "essence_profile", "kind": kind or "ordinary", "independent": independent, "applies_to": "target"}]})]
    return fight(tmp_path, sheet_edit=sheet, bundle_edit=bundle, ally=True, extra_witness=witness,
        witness_position={"x": 2, "y": 5} if witness else None,
        positions={LEFT: {"x": 3, "y": 0 if distance > 5 else 6},
                   RIGHT: {"x": 3 + distance // 5, "y": 0 if distance > 5 else 6}},
        prepare=[{"type": "damage", "flat": 1, "applies_to": "target", "damage_types": ["force"]}],
        prepare_costs=[(plug.QI, 20)], prepare_target="ANY_CREATURE",
        cause=[{"type": "damage", "flat": 999, "applies_to": "target", "damage_types": ["force"]}],
        cause_target="ANY_CREATURE", extra_actions=extra, reaction_ask=not ai, maximum_rounds=15)


def recoveries(e):
    return [ev for ev in e.events if ev.source_definition_id == plug.FEATURE
            and ev.event_type == "PASSIVE_TRIGGERED"]


@pytest.mark.parametrize("disposable,independent,expected", [(0, 0, 1), (1, 0, 0), (1, 1, 1)])
def test_summoning_does_not_imply_a_disposable_refund_body(disposable, independent, expected):
    from types import SimpleNamespace
    from combat.ext.essence_state import PROFILE, profile
    actor = SimpleNamespace(creature_types=(), summon={"disposable": disposable}, conditions={
        "facts": SimpleNamespace(condition_id=PROFILE, data={"independent": independent})})
    assert profile(actor)["genuine"] == expected


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("victim_cl,amount", [(1, 1), (3, 3), (15, 4)])
def test_recovery_is_optional_free_capped_and_persisted(tmp_path, ai, victim_cl, amount):
    c, t, mid = fixture(tmp_path, victim_cl=victim_cl, ai=ai)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    before = fresh(c, mid).state.actors[LEFT]
    _, prompts = resolve(action_sender(c, t, mid, "Finish", target_id=RIGHT, ai=ai))
    after = fresh(c, mid).state.actors[LEFT]
    assert after.resources[plug.QI] == before.resources[plug.QI] + amount
    assert after.reaction_available == before.reaction_available
    assert after.action_available == before.action_available
    assert after.bonus_action_available == before.bonus_action_available
    assert len(recoveries(fresh(c, mid))) == 1
    assert any(r.condition_id == DEPLETED + LEFT for r in fresh(c, mid).state.actors[RIGHT].conditions.values())
    assert bool(prompts) != ai
    if prompts:
        assert "Qi Devourer" in str(prompts) and "Finish" in str(prompts) and "Visitor" in str(prompts)


@pytest.mark.parametrize("owns,prior", [(False, True), (True, False)])
def test_unowned_or_not_previously_damaged_are_inert(tmp_path, owns, prior):
    c, t, mid = fixture(tmp_path, owns=owns)
    if prior:
        resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    else:
        # Somebody else deals both packets; Keeper never damaged the victim.
        turn(t, mid, RIGHT)
        resolve(lambda a: act(t, mid, "Cause", a, target_id=RIGHT))
        _, prompts = resolve(lambda a: act(t, mid, "Cause", a, target_id=RIGHT))
        assert not prompts and not recoveries(fresh(c, mid))
        return
    _, prompts = resolve(lambda a: act(t, mid, "Finish", a, target_id=RIGHT))
    assert not prompts and not recoveries(fresh(c, mid))


def test_decline_preserves_allowance_and_does_not_deplete_victim(tmp_path):
    c, t, mid = fixture(tmp_path)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    _, prompts = resolve(lambda a: act(t, mid, "Finish", a, target_id=RIGHT), {plug.CHOICE: []})
    assert prompts and not recoveries(fresh(c, mid))
    assert plug.USED not in fresh(c, mid).state.actors[LEFT].turn_flags
    assert not any(r.condition_id.startswith(DEPLETED) for r in fresh(c, mid).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("distance,expected", [(60, 1), (65, 0)])
def test_sixty_foot_boundary_is_not_the_finishing_attacks_range(tmp_path, distance, expected):
    c, t, mid = fixture(tmp_path, distance=distance)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    resolve(lambda a: act(t, mid, "Finish", a, target_id=RIGHT))
    assert len(recoveries(fresh(c, mid))) == expected


@pytest.mark.parametrize("kind", ["construct", "illusion", "projected_clone", "disposable_body", "refund_body"])
@pytest.mark.parametrize("independent", [0, 1])
def test_excluded_bodies_need_explicit_independent_essence(tmp_path, kind, independent):
    c, t, mid = fixture(tmp_path, kind=kind, independent=independent)
    resolve(lambda a: act(t, mid, "Profile", a, target_id=RIGHT))
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    resolve(lambda a: act(t, mid, "Finish", a, target_id=RIGHT))
    assert len(recoveries(fresh(c, mid))) == independent


@pytest.mark.parametrize("ai", [False, True])
def test_earlier_scene_damage_qualifies_when_somebody_else_finishes_on_ai_turn(tmp_path, ai):
    c, t, mid = fixture(tmp_path, ai=ai)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=ALLY))
    turn(t, mid, RIGHT)
    if ai:
        c.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    _, prompts = resolve(action_sender(c, t, mid, "Cause", target_id=ALLY, ai=ai))
    assert len(recoveries(fresh(c, mid))) == 1
    assert bool(prompts) != ai


def receipted(e, aid):
    return [r for r in e.state.actors[aid].conditions.values() if r.condition_id.startswith(DEPLETED)]


def test_same_round_and_ordinary_revival_do_not_refresh_essence(tmp_path):
    """A spent receipt survives restoration and the round turn-over; only a rebuilt pool pays again.

    Hit Points coming back is not revival: the native heal commits HP and nothing else
    ("never revive implicitly", combat/gate2_engine._heal), and a downed creature keeps its
    initiative slot but passes its own turn (combat/turn_decisions.passes_without_decision).
    So the receipt, not the body's HP, is what makes a creature yield once.
    """
    # An untouched bystander: the only conscious creature available for a later fresh zero.
    victim = "actor:factory.auto111-witness"
    c, t, mid = fixture(tmp_path, witness=True)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=ALLY))
    resolve(lambda a: act(t, mid, "Finish", a, target_id=RIGHT))
    resolve(lambda a: act(t, mid, "Finish", a, target_id=ALLY))
    assert len(recoveries(fresh(c, mid))) == 1
    resolve(lambda a: act(t, mid, "Heal", a, target_id=RIGHT))
    e = fresh(c, mid)
    assert receipted(e, RIGHT) and len(recoveries(e)) == 1
    # Turn the round over: the two downed creatures pass their own slots.
    turn(t, mid, victim)
    turn(t, mid, LEFT)
    resolve(lambda a: act(t, mid, "Restore Essence", a, target_id=RIGHT))
    assert not receipted(fresh(c, mid), RIGHT)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=victim))
    resolve(lambda a: act(t, mid, "Finish", a, target_id=victim))
    assert len(recoveries(fresh(c, mid))) == 2
