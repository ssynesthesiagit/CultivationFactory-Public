"""Sect Check's printed after-d20 window: "You may spend one Merit Die before or after rolling the d20 but
before the GM declares the result."

Table level: compile a character, commit through TabletopService, answer the real prompt, reload from disk.
Every test here fails on a tree without ``after_roll_merit``: the bare line must pause and ask, accepting must
spend exactly one die and add exactly that result to the printed total, declining must cost nothing, and the paid
line must never be offered a second die.
"""
import pytest

from combat.ext.sect_stewardship import BASE_DIE, MERIT
from tests.hunt12_support import ME, candidate, fight as unchosen_fight, reload, send

SPHERE = "SECT_STEWARDSHIP_BASE_SECT_CHECK"
BARE = "Sect Check"
PAID = "Sect Check (spend 1 Merit Die)"
CHOICE = "choice:needle.sect_stewardship.add_merit_die"

PB = 4  # the harness sheet's proficiency bonus
KEY_MOD = 4  # and its key ability modifier (a score of 18 is +4)


def prepared(tmp_path, mids=(SPHERE,)):
    """A character who has recorded the printed learning choice, so the check may be rolled."""
    combat, table, mid = unchosen_fight(tmp_path, list(mids))
    choices = [c for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name == "Sect Stewardship: choose Intelligence"]
    if choices:
        assert send(combat, table, mid, choices[0])["status"] == "COMMITTED"
    return combat, table, mid


def last_check(engine):
    return [e for e in engine.events if e.event_type == "CHECK_ROLLED"][-1]


def merit_rolls(engine):
    return [r for r in engine.rolls if str(r.reason or "").startswith("MERIT_DIE:")]


def prompt_of(result):
    """The after-d20 ask, or None when the action committed without pausing."""
    reaction = result.get("reaction") or {}
    return reaction if reaction.get("context", {}).get("reaction_source_id") == CHOICE else None


def reply_for(prompt, *, accept):
    """The answer a player gives to this prompt, in the table's own answer shape."""
    answer = {**prompt["context"], "selection": "USE" if accept else "DECLINE"}
    if accept:
        answer["option_ids"] = ["add"]
    return answer


def test_bare_line_asks_after_the_d20_and_before_any_result(tmp_path):
    '''"before or after rolling the d20 but before the GM declares the result": the ask happens in that window.'''
    combat, table, mid = prepared(tmp_path)
    chosen = candidate(combat, mid, lambda c: c.display_name == BARE)
    result = send(combat, table, mid, chosen)
    prompt = prompt_of(result)
    assert prompt is not None, "the bare line must pause and ask once the d20 exists"
    assert result["status"] == "REACTION_REQUIRED"
    # The pause is inside the printed window: the d20 is already drawn and visible to the table...
    engine = reload(tmp_path, mid)
    assert not [e for e in engine.events if e.event_type == "CHECK_ROLLED"], "nothing is decided while it waits"
    assert engine.state.actors[ME].resources[MERIT] == PB, "and no die is spent while it waits"
    # ...and the prompt says what it is, what it costs, and the printed limit that bounds it.
    assert prompt["reaction"] == "Sect Check"
    assert "Spend 1 Merit Die" in prompt["moment"] and str(PB) in prompt["moment"]
    assert "Only one Merit Die may be added" in prompt["moment"]
    assert "Costs 1 Merit Die" in prompt["cost"]
    assert prompt["choice"]["options"][0]["id"] == "add" and prompt["choice"]["allow_decline"]


def test_accepting_spends_exactly_one_die_and_adds_exactly_that_result(tmp_path):
    """"Roll the Merit Die and add it to the check." Nothing is spent unless the die is accepted."""
    combat, table, mid = prepared(tmp_path)
    before = reload(tmp_path, mid).state.actors[ME].resources[MERIT]
    chosen = candidate(combat, mid, lambda c: c.display_name == BARE)
    first = send(combat, table, mid, chosen)
    prompt = prompt_of(first)
    assert prompt is not None
    # Answer the real prompt the table opened, in a second cold request against the reloaded match.
    send(combat, table, mid, chosen, answers=[reply_for(prompt, accept=True)])
    engine = reload(tmp_path, mid)
    event = last_check(engine)
    rolled = merit_rolls(engine)
    assert len(rolled) == 1, "exactly one Merit Die was rolled for this check"
    die = int(rolled[0].total)
    assert 1 <= die <= BASE_DIE
    roll = event.payload["actor"]
    assert roll["total"] == roll["natural_result"] + PB + KEY_MOD + die
    assert event.payload["merit_die"] == die
    assert engine.state.actors[ME].resources[MERIT] == before - 1, "acceptance costs exactly one die"
    lines = [e.payload.get("log", "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"]
    assert any("added from one Merit Die after the d20 was rolled" in line for line in lines), \
        "the table is told the die landed after the d20"


def test_declining_costs_nothing_and_leaves_the_total_alone(tmp_path):
    """"You may" is a real choice: the table can decline and the check is the printed roll and nothing more."""
    combat, table, mid = prepared(tmp_path)
    before = reload(tmp_path, mid).state.actors[ME].resources[MERIT]
    chosen = candidate(combat, mid, lambda c: c.display_name == BARE)
    prompt = prompt_of(send(combat, table, mid, chosen))
    assert prompt is not None
    send(combat, table, mid, chosen, answers=[reply_for(prompt, accept=False)])
    engine = reload(tmp_path, mid)
    roll = last_check(engine).payload["actor"]
    assert roll["total"] == roll["natural_result"] + PB + KEY_MOD, "no die reached the check"
    assert engine.state.actors[ME].resources[MERIT] == before, "a declined offer spends nothing"
    assert not merit_rolls(engine), "and rolls no die"


def test_the_paid_line_is_never_asked_for_a_second_die(tmp_path):
    """"you cannot add more than one Merit Die to the same d20 roll" -- whoever gets there first, the other stops."""
    combat, table, mid = prepared(tmp_path)
    chosen = candidate(combat, mid, lambda c: c.display_name == PAID)
    result = send(combat, table, mid, chosen)
    assert result["status"] == "COMMITTED", "the paid line already carries its die and never pauses again"
    assert prompt_of(result) is None
    engine = reload(tmp_path, mid)
    roll = last_check(engine).payload["actor"]
    assert engine.state.actors[ME].resources[MERIT] == PB - 1, "the paid line costs exactly one die"
    assert roll["total"] == roll["natural_result"] + PB + KEY_MOD + last_check(engine).payload["merit_die"]


def test_the_ask_is_only_asked_of_a_character_who_owns_the_sphere(tmp_path):
    """A character that printed no Sect Stewardship row is never prompted (checklist 3)."""
    combat, table, mid = unchosen_fight(tmp_path, [])
    engine = reload(tmp_path, mid)
    assert MERIT not in engine.state.actors[ME].resources
    assert not [c for c in engine.legal_candidates() if "Sect" in c.display_name]
    for actor in engine.state.actors.values():
        assert not [c for c in actor.conditions.values() if CHOICE in str(c.condition_id)]


def test_no_die_left_means_no_ask(tmp_path):
    """Nothing is asked of a character who holds no Merit Die to spend."""
    combat, table, mid = prepared(tmp_path)
    from tests.test_auto97_sect_stewardship import hold_merit_dice
    hold_merit_dice(tmp_path, combat, table, mid, 0)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources[MERIT] == 0
    spent_to_get_here = len(merit_rolls(engine))
    chosen = candidate(combat, mid, lambda c: c.display_name == BARE)
    result = send(combat, table, mid, chosen)
    assert result["status"] == "COMMITTED", "an empty pool must not open a prompt"
    assert prompt_of(result) is None
    assert len(merit_rolls(reload(tmp_path, mid))) == spent_to_get_here, "and rolls no die for the check"
    roll = last_check(reload(tmp_path, mid)).payload["actor"]
    assert roll["total"] == roll["natural_result"] + PB + KEY_MOD


def test_the_prompt_carries_the_authoritative_printed_rules_and_limit(tmp_path):
    """The table is shown this row's own printed text and its limitation, not a summary."""
    import json

    combat, table, mid = prepared(tmp_path)
    chosen = candidate(combat, mid, lambda c: c.display_name == BARE)
    prompt = prompt_of(send(combat, table, mid, chosen))
    assert prompt is not None
    rules = json.load(open("authority/typed_mechanics/rules_text.json"))["SECT_STEWARDSHIP_BASE_SECT_CHECK"]
    assert prompt["rules"] in rules, "the prompt quotes the authoritative printed row"
    authoritative_limit = rules.rsplit("\n", 1)[-1]
    assert prompt["limits"] == authoritative_limit


def test_the_built_in_ai_is_never_offered_this_check_at_all(tmp_path):
    """The Sect Check is player_only, so no AI turn can even reach the after-d20 offer (checklist 9)."""
    combat, table, mid = prepared(tmp_path)
    engine = reload(tmp_path, mid)
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.h1_support import ROOT

    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    engine = reload(tmp_path, mid)
    policy = PolicyLibrary(ROOT).for_actor(ME)[0]
    context = build_decision_context(engine, policy, for_ai=True)
    assert not [c for c in context.legal_candidates if "sect_check" in c.source_definition_id], \
        "the built-in AI is not offered the Sect Check, so it is never asked this question"


def test_the_offer_is_asked_on_the_players_own_turn_and_only_of_the_owner(tmp_path):
    """Checklist 9: the printed offer is asked of the player who owns it, at the table, on their own turn.

    The Sect Check is ``player_only``: the built-in AI is never offered it, so no AI turn can reach this offer at all.
    Were one ever to, the producer asks through ``needle.ask(automatic=True)`` with a decline default, which is what
    makes a computer-controlled chooser decide for itself instead of stalling the fight.
    """
    from combat import ext

    combat, table, mid = prepared(tmp_path)
    chosen = candidate(combat, mid, lambda c: c.display_name == BARE)
    prompt = prompt_of(send(combat, table, mid, chosen))
    assert prompt is not None, "the owner is asked on their own turn"
    assert prompt["context"]["reactor_id"] == ME, "and only the owner is asked"
    assert any(fn.__name__ == "after_roll_merit" for fn in ext.subscribers("d20_bonus")), \
        "the offer runs on the engine's own d20_bonus seam, not a patched call"