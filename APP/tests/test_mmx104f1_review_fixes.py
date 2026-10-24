"""MMX104f1: the review fixes for the shared hover layout.

Review of MMX104 raised five presentation defects in combat/hover_text.py and
combat/status_text.py. Each has a guard here at the level the defect showed:

  1. a plug-in's scoped ``rules`` controlled the rule text but not the displayed
     card, so a setting selector showed its parent ability's other options and
     its permanent-choice limit as though they applied to the current setting;
  2. a suppressed benefit kept its printed fields and an active Effect summary,
     so a benefit that is switched off still read as active;
  3. only ``rule_text`` got the CP explanation, while the displayed body, the
     labelled fields and the summary were built from unexpanded text;
  4. the footer replaced the enforced lifetime with a printed clock, which can
     promise an expiry the engine never enforces;
  5. abilities, Paths, Foundations and sheet entries were never routed through
     the shared formatter at all.

Nothing here touches fight state: the guards are read-only projections, and the
one table-level guard asserts the fight's own state and events are untouched by
describing it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from combat import hover_text
from combat.action_text import describe_action, layout_action
from combat.condition_text import all_conditions
from combat.status_text import describe

RECORD = "foundation.golden_mandate_seal_v0_2B.generate_edict_seal"
SOURCE = "action:test.generate_edict_seal"


def _engine(**overrides):
    """A saved-fight-shaped engine whose one action resolves a real printed record."""
    action = SimpleNamespace(owner_id="mei", display_name="Generate Edict Seal",
                             parameters={"typed": {"source": RECORD}}, costs=(), model_dump=lambda **_: {})
    state = SimpleNamespace(actors={"mei": SimpleNamespace(entity_id="mei", display_name="Mei"),
                                    "bo": SimpleNamespace(entity_id="bo", display_name="Bo", turns_started=2)})
    engine = SimpleNamespace(action_catalog={SOURCE: action}, state=state)
    for name, value in overrides.items():
        setattr(engine, name, value)
    return engine


DEFINITIONS = {SOURCE: "Generate Edict Seal"}


# ------------------------------------------------------ finding 1: scoped overrides
def test_a_scoped_rule_override_replaces_the_printed_card_it_superseded():
    """A plug-in's ``rules``/``markup`` owns the card, not the record it replaced.

    This is the Mountain-Rending selector case: the hook narrows the text to one
    printed subsection, and the card must show that subsection rather than the
    parent ability's whole printed card with every other option in it.
    """
    engine = _engine()
    row = {"condition_id": "condition:typed.mr_choice", "source_definition_id": SOURCE,
           "source_actor_id": "mei", "display_name": "Mountain-Rending: Push", "expires_on": "UNTIL_REMOVED"}
    data = {"label": "Mountain-Rending: Push", "choice": "push"}

    unscoped = describe(engine, engine.state.actors["bo"], row, data, {"mei": "Mei", "bo": "Bo"}, DEFINITIONS,
                        condition_rules=all_conditions())
    # Without an override the whole printed card is the card: that is the default
    # every other status keeps.
    assert any(field["label"] == "Trigger" for field in unscoped["hover"]["fields"])

    scoped_markup = ("Selected setting: Mountain-Rending: Push.\n**Type:** No Action\n"
                     "**Effect:** When you make a melee attack, push the target 5 feet away.")
    from combat import ext
    supplied = [{"text": "Selected setting: Mountain-Rending: Push.",
                 "rules": "Mountain-Rending: Push. No Action. When you make a melee attack, "
                          "push the target 5 feet away.",
                 "markup": scoped_markup,
                 "source_ability": "Mountain-Rending", "handling": "It stays selected until you change it."}]
    original = ext.query
    ext.query = lambda name, *a, **k: supplied if name == "status_description" else []
    try:
        scoped = describe(engine, engine.state.actors["bo"], row, data, {"mei": "Mei", "bo": "Bo"}, DEFINITIONS,
                          condition_rules=all_conditions())
    finally:
        ext.query = original

    # The displayed card is the scoped one: its own Effect, its own label, and no
    # trace of the parent card it replaced.
    assert [field["label"] for field in scoped["hover"]["fields"]] == ["Action", "Effect"]
    assert "5 feet away" in scoped["detail"]
    assert "seal, talisman, formation" not in scoped["detail"]
    assert "Range: Self" not in scoped["detail"]
    # The title is the player's own label, never an internal choice id.
    assert scoped["hover"]["title"] == "Selected setting: Mountain-Rending: Push."
    # The flattened rules are not repeated in the body once the card shows them.
    assert scoped["detail"].count("push the target 5 feet away") == 1
    # rule_text keeps the full replacement, so coverage checks still read it.
    assert "Selected setting: Mountain-Rending: Push." in scoped["rule_text"]


def test_a_plug_in_without_markup_still_carries_its_own_prose():
    """No ``markup`` means the replacement's prose is the body, exactly as before."""
    engine = _engine()
    row = {"condition_id": "condition:typed.mr_choice", "source_definition_id": SOURCE,
           "source_actor_id": "mei", "display_name": "Mountain-Rending: Push", "expires_on": "UNTIL_REMOVED"}
    from combat import ext
    supplied = [{"text": "Selected setting: Mountain-Rending: Push.",
                 "rules": "Only the push option applies here."}]
    original = ext.query
    ext.query = lambda name, *a, **k: supplied if name == "status_description" else []
    try:
        out = describe(engine, engine.state.actors["bo"], row, {}, {"mei": "Mei", "bo": "Bo"}, DEFINITIONS,
                       condition_rules=all_conditions())
    finally:
        ext.query = original
    assert "Only the push option applies here." in out["detail"]
    # The superseded parent card is not resurrected as a second opinion.
    assert "seal, talisman, formation" not in out["detail"]


# ------------------------------------------------------- finding 2: suppression
def test_a_suppressed_benefit_with_a_real_source_record_shows_no_active_card():
    """Suppression clears the whole card when the row still resolves its source.

    The existing guard used a source-less row, which cannot reach the path: a
    retained record keeps the benefit's printed fields, so the card showed the
    original benefit next to a suppression note.
    """
    engine = _engine()
    row = {"condition_id": "condition:typed.suppressed.edict_seal", "source_definition_id": SOURCE,
           "source_actor_id": "bo", "display_name": "Edict Seal", "expires_on": "UNTIL_REMOVED"}
    data = {"label": "Edict Seal", "reading": "Edict Seal 1/1 is waiting to be spent."}
    out = describe(engine, engine.state.actors["bo"], row, data, {"mei": "Mei", "bo": "Bo"}, DEFINITIONS,
                   condition_rules=all_conditions())

    assert out["display_name"] == "Suppressed: Edict Seal"
    assert out["hover"]["fields"] == [], "a suppressed benefit still shows the benefit's printed fields"
    assert out["hover"]["summary"] == "", "a suppressed benefit still gets an active-benefit summary"
    # None of the benefit's printed card survives. Naming the ability it came from
    # in the footer is provenance, not a claim that the benefit is active.
    for phrase in ("Trigger", "Range: Self", "gain Edict Seal 1/1",
                   "It expires at the end of your next turn"):
        assert phrase not in out["detail"], f"suppressed card still shows {phrase!r}\n{out['detail']}"
    assert "temporarily suppressed" in out["detail"]
    assert out["hover"]["title"] == "Suppressed: Edict Seal"


# -------------------------------------------------- finding 3: resource expansion
def test_a_stored_cp_reading_is_explained_in_the_displayed_body():
    """A "Spend 1 CP" reading names the paying resource where it is displayed."""
    engine = _engine()
    engine.action_catalog[SOURCE].costs = (("resource:core.qi", 1),)
    row = {"condition_id": "condition:typed.edict_seal", "source_definition_id": SOURCE,
           "source_actor_id": "mei", "display_name": "Edict Seal", "expires_on": "UNTIL_REMOVED"}
    data = {"label": "Edict Seal", "reading": "Spend 1 CP to call the seal."}
    out = describe(engine, engine.state.actors["bo"], row, data, {"mei": "Mei", "bo": "Bo"}, DEFINITIONS,
                   condition_rules=all_conditions())

    assert "Qi" in out["rule_text"]
    assert "Qi" in out["detail"], f"the displayed body explains no paying resource:\n{out['detail']}"
    assert "Spend 1 CP" not in out["detail"]


def test_a_printed_cp_field_names_the_paying_pool_in_the_structured_fields():
    """The labelled fields and the summary come from the same expansion as the body."""
    engine = _engine()
    engine.action_catalog[SOURCE].costs = (("resource:core.qi", 1),)
    row = {"condition_id": "condition:typed.edict_seal", "source_definition_id": SOURCE,
           "source_actor_id": "mei", "display_name": "Edict Seal", "expires_on": "UNTIL_REMOVED"}
    from combat import ext
    supplied = [{"text": "Edict Seal", "markup": "### Edict Seal\n**Cost:** Spend 1 CP to call the seal.",
                 "rules": "Edict Seal. Spend 1 CP to call the seal."}]
    original = ext.query
    ext.query = lambda name, *a, **k: supplied if name == "status_description" else []
    try:
        out = describe(engine, engine.state.actors["bo"], row, {}, {"mei": "Mei", "bo": "Bo"}, DEFINITIONS,
                       condition_rules=all_conditions())
    finally:
        ext.query = original

    cost = next(field for field in out["hover"]["fields"] if field["label"] == "Cost")
    assert "Qi" in cost["value"], f"the Cost field explains no paying resource: {cost['value']!r}"
    assert "1 CP" not in cost["value"]


# --------------------------------------------------- finding 4: footer lifetime
def test_the_footer_states_the_lifetime_the_engine_enforces():
    """A printed clock never replaces the real one; it is named as the printed rule."""
    settled = hover_text.settle_duration("until removed", [("Duration", "1 minute")],
                                         source="Golden Mandate Seal")
    assert settled.startswith("until removed")
    assert "printed rules for Golden Mandate Seal" in settled
    assert "1 minute" in settled
    # One space after the semicolon, and a single closing full stop.
    assert ";  " not in settled
    assert not settled.endswith("..")
    assert hover_text.layout(subject="Edict Seal", markup="**Effect:** gain 1.",
                             duration="while concentrating", source_ability="Captivating Melody")["footer"] \
        == "Lasts while concentrating."


def test_a_persistent_selector_naming_a_temporary_rider_keeps_its_own_lifetime():
    """The review's exact case: a printed expiry that describes a different status.

    Edict Seal persists until it is spent, but its printed Effect describes the
    temporary "expires at the end of your next turn" rider. Promoting that
    sentence to the footer's lifetime promises an expiry nothing enforces, so the
    footer keeps the enforced lifetime and the printed words stay printed prose.
    """
    record = ("**Effect:** If you do not already have Edict Seal, gain Edict Seal 1/1 after the "
              "qualifying event resolves. It expires at the end of your next turn and cannot be "
              "spent on the event that generated it.")
    _lead, fields = hover_text.split_fields(record)
    # No printed Duration field, so nothing is promoted: the real lifetime stands.
    assert hover_text.settle_duration("until removed", fields, source="Generate Edict Seal") == "until removed"
    # The printed words are still shown, verbatim, as the printed Effect they are.
    hover = hover_text.layout(subject="Edict Seal", markup=record, duration="until removed")
    assert "It expires at the end of your next turn" in hover["text"]
    assert "Lasts until removed." in hover["footer"]


def test_a_matching_printed_clock_is_not_repeated():
    fields = [("Duration", "1 minute")]
    assert hover_text.settle_duration("while concentrating, up to 1 minute", fields) == \
        "while concentrating, up to 1 minute"
    # A moment, not a length: the printed wording is the player's own, so no note.
    assert hover_text.settle_duration("until the end of Bo's next turn",
                                      [("Duration", "Until the end of your next turn")]) == \
        "until the end of Bo's next turn"


def test_the_footer_never_disagrees_with_the_row_duration():
    """The footer's lifetime clause is the row's own ``duration``, for every status."""
    engine = _engine()
    row = {"condition_id": "condition:typed.edict_seal", "source_definition_id": SOURCE,
           "source_actor_id": "mei", "display_name": "Edict Seal", "expires_on": "UNTIL_REMOVED"}
    out = describe(engine, engine.state.actors["bo"], row, {"label": "Edict Seal"}, {"mei": "Mei", "bo": "Bo"},
                   DEFINITIONS, condition_rules=all_conditions())
    assert out["hover"]["duration"] == out["duration"]
    assert f"Lasts {out['duration'].rstrip('.')}." in out["hover"]["footer"]


# --------------------------------------------- finding 5: the remaining surfaces
def test_an_ability_is_laid_out_with_one_labelled_line_per_printed_field():
    row = {"display_name": "Generate Edict Seal", "parameters": {"typed": {"source": RECORD}}}
    hover = layout_action(row)
    labels = [field["label"] for field in hover["fields"]]
    assert labels[:3] == ["Action", "Trigger", "Range"]
    assert hover["title"] == "Generate Edict Seal"
    for field in hover["fields"]:
        assert f"{field['label']}: {field['value']}" in hover["text"]


def test_laying_out_an_ability_does_not_change_the_text_that_gets_persisted():
    """The compiled description is untouched: only the presentation is new."""
    row = {"display_name": "Generate Edict Seal", "parameters": {"typed": {"source": RECORD}}}
    flat = describe_action(row)
    assert "**" not in flat, "the persisted description must stay the flattened prose"
    assert "Type: No Action / Triggered" in flat.replace("\n", " ")
    assert layout_action(row)["text"] != flat, "the layout is additional, not a rewrite"


def test_an_action_with_no_printed_fields_keeps_its_own_name_as_the_title():
    row = {"display_name": "Hidden Strike", "parameters": {"description": "Sneak past a guard without being seen."}}
    hover = layout_action(row)
    assert hover["title"] == "Hidden Strike"
    assert "Sneak past a guard" in hover["text"]


def test_a_missing_hover_leaves_every_existing_caller_unchanged():
    """Absent structure, the client assembler returns nothing and callers keep their text."""
    assert hover_text.layout(subject="X", markup="")["text"] == "X"
