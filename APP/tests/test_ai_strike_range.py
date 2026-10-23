"""The AI strikes from the square it holds: a priced utility row is not an attack.

MAINREDTHROW1: "Pick up <weapon>" is compiled with an expected_damage price so the
planner values recovering a disarmed weapon. TurnPlan read that price as an
attack, so the recovery row's nominal 5-foot reach became the turn's attack
range and its sharing value became the reward for an enabling move: the AI
walked 15 feet into contact instead of throwing the axe it already had in reach,
and the thrown axe stayed where the thrower stood.
"""
from combat.ai_tactics import TurnPlan
from tests.test_lock2_persistence import act
from tests.test_thrown_possession import fixture, throw


def test_priced_recovery_row_is_not_the_turns_attack(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    plan = TurnPlan(context)
    recovery = [aid for aid in plan.actions if aid.endswith(".pickup")]
    assert recovery, "the recovery row must be in the owned profile"
    assert plan.actions[recovery[0]]["damage"] > 0, "its damage price is kept for scoring"
    assert not plan.actions[recovery[0]]["attack"], "a recovery row is not an attack"
    assert plan.range_error(plan.actor.position) == 0, "the offered throw already covers this square"
    # The axe is still in hand here, so the offered throw is a real strike and counts.
    throw_rows = [aid for aid in plan.actions if aid.endswith(".weapon.fu#thrown")]
    assert throw_rows and plan.actions[throw_rows[0]]["attack"], "the throw from this square is an attack"
    assert plan.has_strike, "a real throw from this square is a strike for follow-up planning"


def test_priced_pickup_alone_is_not_a_strike(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path)
    throw(table, mid)  # the axe leaves the hand and lands on the foe's side
    # Approach the dropped axe, then let the foe retreat. On the next turn
    # recovery is legal, but neither the missing axe nor a melee strike is.
    def move_to(x, y):
        state = table.state(mid)
        move = next(m for m in state["menu"]["moves"] if m["destination"] == {"x": x, "y": y})
        assert table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"

    move_to(5, 4)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == foe
    move_to(9, 4)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == actor
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    plan = TurnPlan(context)
    recovery = [aid for aid in plan.actions if aid.endswith(".pickup")]
    assert recovery, "the disarmed axe leaves a recovery row for the owner"
    pickups = [c for c in context.legal_candidates if c.source_definition_id in recovery]
    assert pickups, "a recovery candidate must actually be legal, not merely owned"
    assert any(c.metadata.get("expected_damage", 0) > 0 for c in pickups), "exercise the old damage-price fallback"
    assert plan.actions[recovery[0]]["damage"] > 0
    assert not plan.actions[recovery[0]]["attack"], "a recovery row is not an attack"
    strikers = [c for c in context.legal_candidates
                if c.kind in {"ACTION", "BONUS_ACTION"} and plan.actions.get(c.source_definition_id, {}).get("attack")
                and not c.metadata.get("placement_ai_unavailable")
                and c.metadata.get("target_knowledge") != "LAST_OBSERVED"]
    assert not strikers, "the fixture must offer no legal damaging strike"
    assert plan.has_strike is False, "a legal priced pickup must not suppress move-plus-action planning"
    assert not plan.offered_strikes, "a priced recovery row is not an offered strike"
    assert not plan.offers, "a priced recovery row must not inflate rival-strike conflict costs"


def test_ai_throws_from_where_it_stands(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    choice = combat.controller.choose_primary_action(context)
    chosen = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert chosen.source_definition_id.endswith("#thrown"), chosen.source_definition_id


def test_custom_effect_attack_keeps_its_reach_beside_priced_recovery(tmp_path):
    """A plug-in damaging action (Calamity Gaze) is a real strike, not a priced utility row.

    MAINREDTHROW1 F5 review: a custom effect kind outside STRIKE_KINDS made Gaze a non-attack,
    so its 60-foot reach vanished from TurnPlan and its offer no longer counted as a strike.
    The disarmed axe in the same turn keeps its priced pickup row, which must stay non-attack.
    """
    combat, table, mid, actor, foe = fixture(tmp_path, revelation=True)
    state = table.state(mid)
    menu = state["menu"]
    reveal = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Thousand-Eyed Revelation"
                  for o in g["options"])
    assert table.act(mid, reveal, menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    throw(table, mid)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == foe
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    assert context is not None
    plan = TurnPlan(context)
    gaze_rows = [aid for aid in plan.actions if aid.endswith(".calamity_gaze")]
    assert gaze_rows, "Thousand-Eyed Revelation must own Calamity Gaze"
    row = plan.actions[gaze_rows[0]]
    assert row["damage"] > 0 and row["attack"], "a custom damaging effect with delivers_strike is a strike"
    assert row["range"] == 60, "the printed 60-foot reach stays the attack range"
    offers = [c for c in context.legal_candidates if c.source_definition_id == gaze_rows[0]]
    assert offers, "Gaze must be a legal offer from this square"
    assert gaze_rows[0] in plan.offered_strikes, "a legal Gaze offer is an offered strike"
    assert plan.has_strike
    recovery = [aid for aid in plan.actions if aid.endswith(".pickup")]
    assert recovery and not plan.actions[recovery[0]]["attack"], "the priced pickup stays a non-attack"
