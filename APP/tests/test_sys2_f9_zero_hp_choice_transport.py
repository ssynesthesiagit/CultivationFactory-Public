"""SYS2 review finding 1 (blocking): the zero-HP "choose one" prompt never reached the table.

typed_reactions asks "choice:typed.zero_hp_replacer" through needle.ask, which publishes the options in the trigger
context. No choice_options provider owned the "choice:typed." prefix, so choice_checkpoints.dynamic_choice returned
(False, None) and the player got no menu. These tests run the real needle.ask path (no monkeypatch of ask) and route
its context through the same dynamic_choice the table uses.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from combat import choice_checkpoints, typed_reactions
from combat.factory_compiler import compile_character
from tests.test_auto_bodya import AN, BODY_REFINING_SHEET, ME, _engine

PATH = "tianxia.path.body_refining.feature."
STAMINA = "resource:core.stamina"
CHOICE = "choice:typed.zero_hp_replacer"


def transport_authority():
    """Synthetic trigger inputs; retain the shipped costs, effects and limits.

    Public exports replace prose used by the trigger classifier. Feeding that
    prose to the compiler produced *zero* survival rows, so the old regression
    never exercised transport at all. Supply the printed trigger explicitly,
    through the compiler's authority input, not by patching engine methods.
    """
    root = Path(__file__).resolve().parents[1]
    authority = json.loads((root / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    authority = copy.deepcopy(authority)
    for feature in (PATH + "blood_pump", "tianxia.subpath.body.iron_shirt.feature.invincible_iron"):
        authority["mechanics"][feature]["activation"]["trigger"] = (
            "You would be reduced to 0 Hit Points but are not killed outright.")
    return authority


def _owner(*features):
    sheet = {**BODY_REFINING_SHEET, "path_and_subpath": {"path_feature_record_ids": [PATH + "iron_fist", *features]}}
    engine = _engine(compile_character(sheet, actor_id=ME, typed_authority=transport_authority()))
    assert len(typed_reactions._generic_rows(engine, ME, "drop_to_zero")) == 2
    me = engine.state.actors[ME]
    me.resources[STAMINA], me.current_hp = 10, 20
    return engine, me


def _table_prompts(engine):
    """Route every reaction-decision request through the table's own dynamic_choice; record what it returned."""
    seen = []

    def table(checkpoint, reactor_id, reaction_id, *, context=None):
        handled, decision = choice_checkpoints.dynamic_choice(engine, engine._active_intent, checkpoint, reactor_id,
                                                              reaction_id, context)
        seen.append((reaction_id, handled, decision, dict(context or {})))
        return None

    engine._reaction_decision = lambda intent, checkpoint, reactor_id, reaction_id, *, context=None: table(
        checkpoint, reactor_id, reaction_id, context=context)
    return seen


def test_zero_hp_choice_reaches_the_table_with_its_options():
    engine, me = _owner(PATH + "blood_pump", "tianxia.subpath.body.iron_shirt.feature.invincible_iron")
    seen = _table_prompts(engine)
    engine._active_intent = SimpleNamespace(actor_id=AN, target_ids=(ME,), reaction_decisions=[], intent_id="t", decision_id="t",
                                            candidate_id="t", state_version=0)
    pending = typed_reactions.on_damage(engine, me, 999, 0, source_definition_id=None, source_actor_id=AN)
    engine._commit_damage(me, pending, "FORCE", "reaction:test.lethal", AN, None, reaction_depth=0)
    prompts = [row for row in seen if row[0] == CHOICE]
    assert prompts, "the zero-HP choice was never asked"
    _, handled, decision, context = prompts[0]
    # The table must hand the player a real menu, not fall back to a bare Use/Pass window.
    assert handled is True, "no choice_options provider owned choice:typed.zero_hp_replacer"
    options = list(context["needle_options"])
    assert len(options) == 2 and context["minimum"] == 1 and context["maximum"] == 1
    labels = context["labels"]
    assert set(labels) == set(options)
    for option in options:
        name = labels[option]
        assert name and "feature." not in name and not name.startswith("tianxia."), name  # readable, not an internal id
    assert decision is None  # no answer given in this test: the default fallback applies, the menu was still offered


def test_other_choice_ids_stay_on_the_default_window():
    from combat.ext import typed_choice
    assert typed_choice.typed_options(None, None, "c", ME, "choice:needle.something", {"needle_options": ["a"]}) is None
    assert typed_choice.typed_options(None, None, "c", ME, CHOICE, {}) is None  # a question nobody put
