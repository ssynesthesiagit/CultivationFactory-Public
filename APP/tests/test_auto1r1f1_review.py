"""AUTO1r1f1 (review round): the Tempered Response coverage claim, and Thousand-Hand's additional Reaction.

Finding 1: the printed "It does not stack with saving-throw proficiency from another source." line is
not enforced, so it must stay a GM line (combat/rules/feature_blocks.d/auto1_paths_a.json).
Finding 2: the additional Reaction is exercised as real play -- an ordinary Reaction is spent first, the
Circle answers on its additional Reaction, and that spend resets next round, ends with the incarnation
and survives a table commit plus a cold reload. Nothing here patches the engine; the one synthetic
setup (an earlier reaction that spent the ordinary Reaction) runs inside an accepted Hold transaction.
"""

from __future__ import annotations

import pytest

from combat import typed_reactions as reactions
from combat.ext import reaction_economy as economy

from tests import test_riders_c7 as C7
from tests.test_auto1_paths_a import CIRCLE, THOUSAND, TEMPERED

HANDS = "resource:named.battle_hand"
USAGE = economy.FLAG + THOUSAND
STRIKE = "tianxia.path.body_refining.feature.iron_fist"


def _circles(events):
    return [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == CIRCLE]


def _circle_row(engine, actor_id=C7.ME):
    return next(row for row in reactions._rows(engine, actor_id, "generic") if row.get("feature_id") == CIRCLE)


def _grant(engine, actor):
    return next(row for row in economy._rows(engine, actor) if row.get("feature_id") == THOUSAND)


def _end_state(engine, actor, state):
    for condition in list(actor.conditions.values()):
        if condition.condition_id.endswith(state):
            engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)


# ============================================ Finding 1: the stacking line is the GM's, not the table's
def test_tempered_response_leaves_the_proficiency_stacking_rule_to_the_gm():
    """The rescue bonus lands on a total that already carries proficiency, so the table cannot enforce this."""
    from combat.typed_reactions import rules as block_rules

    line = "It does not stack with saving-throw proficiency from another source."
    covers = (block_rules().get("features") or {})[TEMPERED].get("covers") or []
    assert line not in covers
    reminder = next(r for r in C7.riders(TEMPERED) if "does not stack with saving-throw proficiency from another source" in r)
    assert "already add your Proficiency" in reminder, "the GM must be told when the bonuses cannot stack"
    assert "Not automated" in block_rules()["features"][TEMPERED]["why"]


# ============================================ Finding 2: the additional Reaction, spent for real
def _circle_fight(*, incarnate=True):
    """Circle of Uncounted Arms and Thousand-Hand Incarnation, with a live FOE beside the owner."""
    engine = C7.fight(C7.bundle([CIRCLE, THOUSAND], cl=20), foe=C7._typed_foe())
    me = engine.state.actors[C7.ME]
    me.armor_class = 1  # a strike on the owner lands whatever it rolls
    C7.answers(engine)
    C7.turn(engine, C7.ME)
    if incarnate:
        C7.use(engine, "Thousand-Hand Incarnation")
    return engine, me


def _cross_the_reach_edge(engine):
    """The FOE walks out of the owner's reach and back in.

    Leaving reach makes the owner's own Opportunity Attack fire, which spends the ordinary Reaction;
    walking back is the printed trigger ("willingly moves at least 5 feet") for the Circle.
    """
    me = engine.state.actors[C7.ME]
    C7.turn(engine, C7.foe_id(engine))
    C7.use(engine, "Move to 6,6", actor_id=C7.foe_id(engine))
    assert not me.reaction_available, "the owner's Opportunity Attack should have spent its Reaction"
    return C7.use(engine, "Move to 4,6", actor_id=C7.foe_id(engine))


def test_the_additional_reaction_answers_the_circle_after_the_ordinary_one_is_gone():
    engine, me = _circle_fight()
    assert me.reaction_available and me.resources[HANDS] == 12  # 2 x Proficiency Bonus
    answer = _cross_the_reach_edge(engine)
    assert len(_circles(answer)) == 1, "the Circle is the printed use of the additional Reaction"
    assert me.resources[HANDS] == 10, "its printed cost of 2 Battle Hands"
    assert any("uses its additional Reaction of this round for Circle of Uncounted Arms" in str(e.payload)
               for e in answer), [str(e.payload) for e in answer if e.payload]
    assert me.turn_flags[USAGE] == engine.state.round_number
    assert type(me.turn_flags[USAGE]) is int  # persisted state is integers and strings only


def test_the_additional_reaction_is_one_per_round_and_comes_back_next_round():
    engine, me = _circle_fight()
    assert len(_circles(_cross_the_reach_edge(engine))) == 1
    grant = _grant(engine, me)
    assert not economy._unused(engine, me, grant)
    assert not reactions.reaction_waived(engine, me, _circle_row(engine)), "no second spend this round"
    # Next round: the grant is available again, and the Circle's own limit resets with it.
    engine.state.round_number = int(engine.state.round_number) + 1
    C7.turn(engine, C7.ME)
    assert economy._unused(engine, me, grant)
    assert len(_circles(_cross_the_reach_edge(engine))) == 1


def test_the_additional_reaction_is_gone_when_the_incarnation_ends():
    """The printed duration: the extra Reaction lasts only while Thousand-Hand Incarnation lasts."""
    engine, me = _circle_fight()
    _end_state(engine, me, "thousand_hand_incarnation")
    assert not economy._on(engine, me, _grant(engine, me))
    hands = me.resources[HANDS]
    answer = _cross_the_reach_edge(engine)
    assert _circles(answer) == [], "with no Reaction left the Circle cannot answer"
    assert me.resources[HANDS] == hands and USAGE not in me.turn_flags


def test_the_circle_alone_never_reaches_for_the_additional_reaction():
    """The printed restriction: the extra Reaction is for Circle of Uncounted Arms only."""
    engine, me = _circle_fight()
    row = {**_circle_row(engine), "feature_id": "tianxia.subpath.body.kensei.feature.some_other_reaction"}
    me.reaction_available = False
    assert not reactions.reaction_waived(engine, me, row)


# ================================================ the same spend, committed at the table and reloaded
def _strike_action(actor_id):
    """A real compiled attack for the FOE, so the Circle's printed attack-roll trigger can happen."""
    from combat.factory_compiler import compile_character

    from tests.h1_support import sheet

    bundle = compile_character(sheet([STRIKE], cl=17, dc=50), actor_id=actor_id)
    action = dict(next(a for a in bundle["action_catalog"] if a["display_name"] == "Iron Fist attack"))
    action["source_definition_id"] = "action:typed.test.auto1r1f1.strike"
    return action


def test_the_spent_additional_reaction_survives_a_table_commit_and_a_cold_reload(tmp_path, monkeypatch):
    """Checklist 7: the grant's use is stored state, so a committed fight keeps it after a reload."""
    from combat.canonical import canonical_sha256
    from combat.gate5_service import CombatService
    from tests.h48_table_support import FOE, OWNER, assert_reload_verify_replay, candidate, fixture
    from tests.test_solfauto1_review import automatic_action
    from tests.test_tabletop_hunt6 import on_hold

    def give_the_foe_a_strike(bundles):
        action = _strike_action(FOE)
        foe = next(bundle for bundle in bundles if bundle["actor_id"] == FOE)
        foe["action_catalog"].append(action)
        foe["actor_template"]["action_ids"].append(action["source_definition_id"])
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)

    def earlier_reaction(engine):
        """A synthetic earlier reaction inside the accepted Hold: the ordinary Reaction is spent."""
        owner = engine.state.actors[OWNER]
        row = {"feature_id": "test:auto1r1f1.earlier_reaction", "name": "An earlier reaction",
               "block": "generic", "effects": []}
        reactions._open(engine, row, owner, (), "AUTO1r1f1_EARLIER_REACTION")
        reactions.spend_reaction(engine, owner, row)
        assert not owner.reaction_available

    combat, table, mid, _send, commit = fixture(tmp_path, [], seed="AUTO1r1f1-CIRCLE",
                                               path_features=[CIRCLE, THOUSAND], primary="Stamina",
                                               bundle_transform=give_the_foe_a_strike)
    commit(candidate(table, mid, "Thousand-Hand Incarnation"))
    on_hold(monkeypatch, earlier_reaction)
    commit(candidate(table, mid, "Hold"))

    # The FOE's own turn: it strikes the owner, whose ordinary Reaction is already gone.
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    automatic_action(combat, "action:typed.test.auto1r1f1.strike")

    def answer(prompt):
        choice = prompt.get("choice") or {}
        options = (choice.get("preferred") or [option["id"] for option in choice.get("options") or []])[:1]
        return {**prompt["context"], "selection": "USE", "option_ids": options}

    asked, answers = [], []
    for _ in range(8):
        result = table.auto_step(mid, 0, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert prompt["context"]["reactor_id"] == OWNER
        asked.append(prompt["reaction"])
        answers.append(answer(prompt))
    else:
        raise AssertionError("the Circle never resolved")
    assert "Circle of Uncounted Arms" in asked, asked
    assert_reload_verify_replay(combat, mid, tmp_path)

    engine = CombatService(combat.source_root, tmp_path)._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    assert len(_circles(engine.events)) == 1, "the additional Reaction answered the Circle"
    assert owner.turn_flags[USAGE] == engine.state.round_number
    assert not owner.reaction_available, "the additional Reaction never returns an ordinary one"
    assert not reactions.reaction_waived(engine, owner, _circle_row(engine, OWNER)), "no second spend"
    assert any("uses its additional Reaction of this round" in str(e.payload) for e in engine.events)
