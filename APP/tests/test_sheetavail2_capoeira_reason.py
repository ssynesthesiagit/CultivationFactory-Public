"""SHEETAVAIL2: Capoeira Spin says it needs Prone, and the sheet's row is greyed until the character is.

Owner report: the "Capoeira Spin: stand and make one Unarmed Strike" Bonus Action row looked usable on the sheet
while the character was standing, and clicking it failed because the server had no candidate for it
(no_engine_issued_candidate). The desktop table reads a compact ("lazy") menu in which an action appears as an
unexpanded header, and nothing in that answer said the action was unusable, so the sheet had no reason to grey it
(static/tabletop/sheet.js applyLegal greys a row when the server names a reason).

Capoeira Spin now declares the precondition the print already states -- Prone now, and the start-of-turn snapshot
the plug-in keeps -- as the typed requirements the engine reads (combat/ext/athletics.py). The engine refuses the
action before offering it and names the missing stance (combat/gate2_engine.py), so one sentence reaches the table
menu, the sheet's hover card and the refusal of an actual click.
"""
from tests.auto8f1_table_support import OWNER
from tests.test_a2_athletics import CAPOEIRA, commit, finish, game_for

PRONE_REASON = "You must be Prone to use this."
TURN_FLAG_REASON = "The required earlier action or trigger has not happened this turn."


def capoeira_source(engine):
    """The compiled row's source, as the table and the sheet name it."""
    sources = [source for source in engine.action_catalog if source.endswith(".capoeira_spin")]
    assert len(sources) == 1, sources
    return sources[0]


def capoeira_rows(state):
    """The table's own menu rows for Capoeira Spin, keyed the way the sheet keys its buttons."""
    return {f"act:{group['source_definition_id']}": group for group in state["menu"]["actions"]
            if group["source_definition_id"].endswith(".capoeira_spin")}


def capoeira_reasons(state):
    return {key: reason for key, reason in (state.get("unavailable_reasons") or {}).items()
            if key.endswith(".capoeira_spin")}


def test_standing_character_sees_the_row_greyed_with_the_named_condition(tmp_path):
    game = game_for(tmp_path, [CAPOEIRA])
    table, mid = game["table"], game["match_id"]
    source = capoeira_source(table._load_state_session(mid).engine)
    owner = next(row for row in table.state(mid, lazy=True)["presentation"]["actors"]
                 if row["entity_id"] == OWNER)
    # The character really can still spend a Bonus Action: the row is refused for its own reason, not for economy.
    assert owner["turn_state"]["bonus_action"] is True
    for lazy in (True, False):
        state = table.state(mid, lazy=lazy)
        assert capoeira_rows(state) == {}, f"a standing character is not offered Capoeira Spin (lazy={lazy})"
        assert capoeira_reasons(state) == {f"act:{source}": PRONE_REASON}
    finish(game)


def test_engine_answer_for_the_row_names_the_missing_condition(tmp_path):
    # The sentence the sheet shows is the engine's own answer for this source: no ability text lives in the client.
    game = game_for(tmp_path, [CAPOEIRA])
    session = game["table"]._load_state_session(game["match_id"])
    answer = session.engine.action_availability(OWNER, capoeira_source(session.engine))
    assert answer["available"] is False
    assert answer["code"] == "REQUIRES_CONDITION"
    assert answer["reason"] == PRONE_REASON
    finish(game)


def test_starting_the_turn_prone_offers_the_row_with_no_reason(tmp_path):
    game = game_for(tmp_path, [CAPOEIRA])
    commit(game, "Lie down")
    game["commit"](game["menu"]()["end_turn"])
    game["to_owner"]()
    state = game["table"].state(game["match_id"], lazy=True)
    assert capoeira_rows(state), "a character who started the turn Prone is offered Capoeira Spin"
    # tabletop.js sends every menu source with no reason as a legal button, so the sheet keeps this row clickable.
    assert capoeira_reasons(state) == {}
    finish(game)


def test_prone_after_the_turn_started_keeps_the_generic_turn_reason(tmp_path):
    # Lying down mid-turn does not earn the start-of-turn snapshot, so the row is still refused -- and says so with
    # the engine's general sentence, because that requirement cannot be named the way a condition can.
    game = game_for(tmp_path, [CAPOEIRA])
    commit(game, "Lie down")
    reasons = capoeira_reasons(game["table"].state(game["match_id"], lazy=True))
    assert list(reasons.values()) == [TURN_FLAG_REASON]
    finish(game)


def test_ai_planner_reads_the_prone_requirement_when_the_turn_started_prone(tmp_path):
    """The AI planner must agree with the engine about Capoeira Spin's declared requirement.

    The planner stores "ready" per owned action and drops every unready action from its attack list
    (combat/ai_tactics.py _own_prerequisites). It used to compare the declared plain name "prone"
    with the raw condition ids ("condition:typed.prone"), so no Capoeira creature was ever ready and
    the Bonus Action was never planned. Both now read the same matcher.
    """
    game = game_for(tmp_path, [CAPOEIRA])
    combat, mid = game["combat"], game["match_id"]
    source = capoeira_source(combat._load_session(mid).engine)
    standing = combat.ai_decision_context(combat._load_session(mid)).tactics["actions"].get(source)
    assert standing is not None, "the planner must see the creature's own Capoeira Spin row"
    assert standing["ready"] is False, "a standing creature cannot use Capoeira Spin"
    commit(game, "Lie down")
    game["commit"](game["menu"]()["end_turn"])
    game["to_owner"]()
    prone = combat.ai_decision_context(combat._load_session(mid)).tactics["actions"].get(source)
    assert prone["ready"] is True, "a creature that started its turn Prone can use Capoeira Spin"
    finish(game)


def test_a_scope_word_does_not_satisfy_a_condition_requirement():
    """A plain requirement is the condition's own name, never a scope or namespace word.

    Before this round the matcher accepted any dotted part of the carried id, so a future
    requirement such as "state" or "typed" would have matched every scoped condition. The engine's
    gate reads the shared matcher (combat/condition_requirements.py), so this holds for legality,
    the refusal sentence and the planner's readiness alike.
    """
    from types import SimpleNamespace
    from combat.gate2_engine import Gate2Engine
    actor = SimpleNamespace(conditions={
        "a": SimpleNamespace(condition_id="condition:typed.state.calamity_briar_incarnation"),
        "b": SimpleNamespace(condition_id="condition:typed.prone"),
    })
    # The method reads only the actor, so no fight is needed to state the rule.
    assert Gate2Engine._has_condition(None, actor, "calamity_briar_incarnation") is True
    assert Gate2Engine._has_condition(None, actor, "prone") is True
    assert Gate2Engine._has_condition(None, actor, "state") is False
    assert Gate2Engine._has_condition(None, actor, "typed") is False
    assert Gate2Engine._has_condition(None, actor, "condition:typed.prone") is True
    assert Gate2Engine._has_condition(None, actor, "condition:core.prone") is False
