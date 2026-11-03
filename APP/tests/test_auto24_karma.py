"""Printed non-damage Debt Causes resolve and survive real table commits."""
import pytest

from combat.ext.karma_riders import BONE, BONE_ID, TEN_ID, TRIAL_ID, TRIAL_ONCE, TEN, TRIAL
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn, action_sender
from tests.r10_fixup_support import cast_sender, commit

AIR = "tianxia.sphere.air"
STORM = "TAL_AIR_STORM_WITHOUT_DIRECTION"  # its "No Steady Foot" option fails a rushing creature's save
DEBTS = [{"type": "mark", "mark": "Grace Imprint", "applies_to": "target"},
         {"type": "mark", "mark": "Debt Imprint", "applies_to": "target"}]
POISONED = {"type": "condition", "condition": "poisoned", "applies_to": "target", "duration": "until_end_of_next_turn"}


@pytest.mark.parametrize("talent,condition,count,sides", [
    (TEN_ID, TEN, 8, 10), (TRIAL_ID, TRIAL, 2, 8),
])
@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("harmful", ["poisoned", "bound", "no_temp_hp"])
def test_harmful_condition_calls_due_consequence_after_reload(tmp_path, talent, condition, count, sides, ai, harmful):
    combat, table, mid = fight(tmp_path, [talent], prepare=[
        {"type": "mark", "mark": "Grace Imprint", "applies_to": "target"},
        {"type": "mark", "mark": "Debt Imprint", "applies_to": "target"},
    ], cause=[
        {"type": "condition", "condition": harmful, "applies_to": "target", "duration": "until_end_of_next_turn"},
        {"type": "condition", "condition": "blinded" if harmful == "poisoned" else harmful,
         "applies_to": "target", "duration": "until_end_of_next_turn"},
    ])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    name = "Ten Thousand Debts Return to Source" if talent == TEN_ID else "Trial of the Ledger"
    assert act(table, mid, name, target_id=RIGHT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert any(c.condition_id == condition for c in engine.state.actors[RIGHT].conditions.values())
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[RIGHT].current_hp
    assert action_sender(combat, table, mid, "Cause", ai=ai, target_id=LEFT)([])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    damages = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == talent]
    assert len(damages) == 1  # Two conditions and payout events cannot recursively trigger it.
    # The deterministic damage amount is bounded by the exact printed dice.
    amount = damages[0].payload["reduced_to"]
    assert count <= amount <= count * sides
    reason = "TEN_THOUSAND_DEBTS" if talent == TEN_ID else "TRIAL_OF_THE_LEDGER"
    rolled = next(r for r in engine.rolls if r.reason == reason)
    assert len(rolled.dice) == count and rolled.expression.startswith(f"{count}d{sides}")
    assert engine.state.actors[RIGHT].current_hp == before - amount
    assert bool([c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == condition]) == (talent == TRIAL_ID)
    if talent == TRIAL_ID:
        held = next(c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == condition)
        assert type(held.data["turn"]) is str
    # Another action on the same turn neither repeats the trial nor restores a spent consequence.
    if ai:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="MANUAL")
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    assert len([e for e in reload(combat, mid).events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == talent]) == 1


def test_unowned_karma_stays_inert(tmp_path):
    combat, table, mid = fight(tmp_path, cause=[
        {"type": "condition", "condition": "poisoned", "applies_to": "target", "duration": "until_end_of_next_turn"},
    ])
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[RIGHT].current_hp
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == before
    assert not any(e.source_definition_id in (TEN_ID, TRIAL_ID) for e in engine.events)


def test_benign_condition_does_not_spend_consequence(tmp_path):
    combat, table, mid = fight(tmp_path, [TEN_ID], prepare=[
        {"type": "mark", "mark": "Debt Imprint", "applies_to": "target"},
    ], cause=[
        {"type": "condition", "condition": "worker1_benefit", "applies_to": "target", "duration": "until_end_of_next_turn"},
    ])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    assert act(table, mid, "Ten Thousand Debts Return to Source", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert any(c.condition_id == TEN for c in engine.state.actors[RIGHT].conditions.values())
    assert not any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == TEN_ID for e in engine.events)


def test_a_condition_imposed_inside_another_rider_still_calls_the_consequence(tmp_path):
    """No Steady Foot's Prone is raised inside Air's MOVEMENT_COMMITTED subscriber, so it
    reaches Karma only as a nested Condition event. The Air caster is the creature under
    Trial here, so the printed Debt Cause is the bearer's own: it pays, after a reload."""
    combat, table, mid = fight(tmp_path, [STORM], right_talents=(TRIAL_ID,), spheres=(AIR,), cause=[
        {"type": "mark", "mark": "Grace Imprint", "applies_to": "target"},
        {"type": "mark", "mark": "Debt Imprint", "applies_to": "target"},
    ])
    commit(cast_sender(combat, table, mid, "Storm Without Direction: No Steady Foot"))  # LEFT's zone, LEFT's Action
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    assert act(table, mid, "Trial of the Ledger", target_id=LEFT)["status"] == "COMMITTED"
    assert any(c.condition_id == TRIAL for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[LEFT].current_hp
    commit(cast_sender(combat, table, mid, "Move", at=(8, 6)))  # four squares: more than half its Speed
    engine = reload(combat, mid)
    assert any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[RIGHT].conditions.values())
    damages = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == TRIAL_ID]
    assert len(damages) == 1
    amount = damages[0].payload["reduced_to"]
    assert 2 <= amount <= 16
    rolled = [r for r in engine.rolls if r.reason == "TRIAL_OF_THE_LEDGER"]
    assert len(rolled) == 1 and len(rolled[0].dice) == 2
    assert engine.state.actors[LEFT].current_hp == before - amount
    held = next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == TRIAL)
    assert type(held.data["turn"]) is str  # the repeated form's once-per-turn clock survived the commit


def test_successful_save_trial_charges_the_first_harm_it_causes(tmp_path):
    """The passing-save branch of Trial of the Ledger: PB + key Psychic, once, on the
    bearer's first harm before the start of the caster's next turn."""
    combat, table, mid = fight(tmp_path, [TRIAL_ID], left_save_dc=1, prepare=DEBTS, cause=[POISONED])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    assert act(table, mid, "Trial of the Ledger", target_id=RIGHT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert not any(c.condition_id == TRIAL for c in engine.state.actors[RIGHT].conditions.values())
    saved = next(c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == TRIAL_ONCE)
    assert saved.data["amount"] == 6  # PB 4 + key modifier 2, no dice of its own
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[RIGHT].current_hp
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    damages = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == TRIAL_ID]
    assert [e.payload["reduced_to"] for e in damages] == [6]
    assert engine.state.actors[RIGHT].current_hp == before - 6
    assert not any(c.condition_id == TRIAL_ONCE for c in engine.state.actors[RIGHT].conditions.values())
    assert not [r for r in engine.rolls if r.reason == "TRIAL_OF_THE_LEDGER"]  # a fixed amount, not 2d8
    # A second harm on the same turn is not charged again.
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    assert len([e for e in reload(combat, mid).events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == TRIAL_ID]) == 1


def test_a_caster_under_trial_does_not_pay_for_its_own_payout(tmp_path):
    """Debt Written on Bone: Deny Reactions pays by imposing No Reactions on the bearer,
    attributed to this caster -- who is itself under Trial here. A Karma consequence is not
    a Cause that its own caster creates, and the payer may not pay itself."""
    combat, table, mid = fight(tmp_path, [BONE_ID], right_talents=(TRIAL_ID,), prepare=DEBTS,
                               cause=[{"type": "mark", "mark": "Grace Imprint", "applies_to": "target"},
                                      {"type": "mark", "mark": "Debt Imprint", "applies_to": "target"}])
    assert act(table, mid, "Prepare", target_id=RIGHT)["status"] == "COMMITTED"
    assert act(table, mid, "Debt Written on Bone: Deny Reactions", target_id=RIGHT)["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"  # LEFT's ledger
    assert act(table, mid, "Trial of the Ledger", target_id=LEFT)["status"] == "COMMITTED"
    assert any(c.condition_id == TRIAL for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[LEFT].current_hp
    commit(cast_sender(combat, table, mid, "Bi Shou (Dagger) attack", target=LEFT))  # the bearer's hit
    engine = reload(combat, mid)
    # The bearer paid its printed consequence: exactly one No-Reactions condition, no damage.
    assert len([e for e in engine.events if e.event_type == "CONDITION_APPLIED"
                and (e.payload.get("condition_id") or "").endswith("reaction_denied")
                and e.source_definition_id == BONE_ID]) == 1
    assert not [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == BONE]
    # The caster, who is under Trial, paid nothing for its own consequence.
    assert not [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == TRIAL_ID]
    assert not [r for r in engine.rolls if r.reason == "TRIAL_OF_THE_LEDGER"]
    # LEFT lost exactly the printed dagger damage and nothing else.
    hit = [e.payload["reduced_to"] for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
           and e.source_definition_id.endswith(".bi_shou") and LEFT in (e.target_ids or ())]
    assert len(hit) == 1 and engine.state.actors[LEFT].current_hp == before - hit[0]
    assert any(c.condition_id == TRIAL for c in engine.state.actors[LEFT].conditions.values())
