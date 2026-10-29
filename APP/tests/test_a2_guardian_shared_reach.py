"""The shared physical-reach query serves every condition-bound reach provider.

`combat.typed_reactions.physical_melee_reach` is the geometry seam several
plug-ins read (Guardian patrol, Brute Shove, Beastmastery riders, Flowing River).
Adamant's "+5 feet melee reach" needed it to honor the general
`attack_reach_bonus` query, so the change belongs to that shared seam rather than
to Adamant. This module pins the seam with a provider Adamant knows nothing
about -- Shifting Grip Scripture's Long Grip -- so a future edit that re-points
`physical_melee_reach` back at a private Adamant read still fails here.

It fails before that fix: at base, `physical_melee_reach` answered with the
compiled weapon profile alone, so a gripped fighter's query reported 5 feet
while the attack it describes reached 10.
"""
from combat.typed_reactions import physical_melee_reach

from tests.test_auto21_weapons import (FOE, GRIP_TALENT, ME, VERSATILE, ask, choose_grip,
                                        conditions, fight, grip_of, to_turn, walk_out_of_reach)

GRIP = "condition:typed.weapons_shifting_grip"


def query_reach(combat, mid, who=ME):
    """What the shared geometry query reports for ``who``, after a cold reload."""
    session = combat._load_session(mid)          # a fresh session, from disk only
    return physical_melee_reach(session.engine, session.engine.state.actors[who])


def test_the_shared_reach_query_serves_a_provider_adamant_knows_nothing_about(tmp_path):
    """Long Grip's 5 feet reach the shared query, and only while that grip is held.

    The jian's own reach is 5. Long Grip prints "+5 feet", so while it is held the
    fighter's melee profile reaches 10 -- and the seam that answers "how far does
    this creature's melee profile reach" must say 10, because Brute Shove, Guardian
    patrol, Beastmastery riders and Flowing River all read that number to decide
    whether their own reach-based clause still applies.
    """
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,), foe_at=(3, 8))
    assert grip_of(tmp_path, mid) == "", "the fighter began the fight already gripping something"
    assert query_reach(combat, mid) == 5, "the jian does not reach 5 feet, so the fixture proves nothing"

    choose_grip(table, mid, "long")
    assert grip_of(tmp_path, mid) == "long"
    held = conditions(tmp_path, mid, ME).get(GRIP)
    assert held is not None, "the Long Grip left no condition behind to justify the extra reach"
    assert query_reach(combat, mid) == 10, (
        "the shared reach query ignored a condition-bound reach provider, so every "
        "plug-in that reads this number under-counted a Long Grip fighter by 5 feet")

    assert combat._load_session(mid).verify()["status"] == "PASS"


def test_the_shared_reach_query_drops_the_bonus_when_the_grip_is_given_up(tmp_path):
    """Reach returns to the weapon's own 5 feet on the next turn without Long Grip.

    A grip is a way of holding one weapon until the start of the owner's next turn,
    so the bonus must not outlive the condition that paid for it; the seam reads the
    condition rather than remembering a total.
    """
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,), foe_at=(3, 8))
    choose_grip(table, mid, "long")
    assert query_reach(combat, mid) == 10

    to_turn(table, mid, FOE)                     # the grip is a start-of-turn choice: let the round come round
    ask(table, mid, "end")
    to_turn(table, mid, ME, choice="close")
    assert grip_of(tmp_path, mid) == "close", "the fighter did not get a second grip choice"
    assert query_reach(combat, mid) == 5, (
        "the shared reach query kept a grip's reach after the grip was given up")

    assert combat._load_session(mid).verify()["status"] == "PASS"


def test_the_shared_reach_query_is_a_melee_profile_question_not_an_opportunity_attack(tmp_path):
    """The seam answers even when the holder has genuinely spent its Reaction.

    `physical_melee_reach` is deliberately independent of Reaction availability and
    of the holder's reaction plan, because reach-based geometry clauses (Shove Aside's
    legal-space radius, Brute Shove, Guardian patrol) are about the weapon profile
    itself. Spending the holder's Reactions must not change the answer.

    The Reaction is spent by a real committed action -- the fighter walks out of the
    foe's reach and takes the Opportunity Attack the table offers -- so the state
    being asked about survives a cold reload instead of living only in a local
    variable. The seam is then asked about the reloaded engine, and the test asserts
    the Reaction really is gone there; asking a mutated in-memory engine would answer
    a state no other test or plug-in ever observes.
    """
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,), foe_at=(3, 8))
    choose_grip(table, mid, "long")
    assert query_reach(combat, mid) == 10

    to_turn(table, mid, FOE)
    ask(table, mid, walk_out_of_reach(combat, mid, ME, beyond_ft=10))

    reloaded = combat._load_session(mid).engine          # a fresh session, from disk only
    spent = reloaded.state.actors[ME]
    assert spent.reaction_available is False, (
        "the Opportunity Attack did not spend the fighter's Reaction, so this test would "
        "prove nothing about a Reaction-independent query")

    assert physical_melee_reach(reloaded, spent) == 10, (
        "the shared reach query started answering a question about Reactions instead of "
        "about the weapon profile")
    assert query_reach(combat, mid) == 10, (
        "the shared reach query changed its answer once the holder's Reaction was spent")

    assert combat._load_session(mid).verify()["status"] == "PASS"