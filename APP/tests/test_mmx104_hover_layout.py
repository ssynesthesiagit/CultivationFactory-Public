"""MMX104: one shared hover layout for every ability, condition, mark, Path and Foundation.

Owner 2026-10-03 (round 24, Luo Shuofen's Edict Seal mark hover): the hover was
one wall of text with the printed field labels glued to the words before them
("Generate Edict Seal Type: No Action / Triggered Trigger: ..."), a generated
"Lasts until removed." that contradicted the printed "It expires at the end of
your next turn", and engine wording ("the table's implemented abilities read
it") that means nothing to a player.

These guards run over every compiled character in the owner pool, not over a
hand-picked sample, so a new ability cannot ship a new shape.
"""
from __future__ import annotations

import copy
import json
import os
import re
import zipfile
from pathlib import Path

import pytest

from combat import hover_text
from combat.condition_text import all_conditions
from combat.factory_compiler import compile_character
from combat.status_text import describe, markup, printed_excerpt
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_prefight import SHEET as MELD_SHEET

ROOT = Path(__file__).resolve().parents[1]
POOL = Path(os.environ.get("P6_CHARACTER_POOL", "/var/tmp/auto-audit/astra/lock3-inputs/portable_characters"))

# A printed label glued to the word before it ("Generate Edict Seal Type: No
# Action", "Self Target: Self"): the layout puts every label at the start of its
# own line, so a label can never follow another word.
GLUED_LABEL = re.compile(
    r"\b[A-Za-z']\s+(?:Type|Trigger|Range|Target|Area|Effect|Duration|Limit|Cost|"
    r"Counterplay and Boundaries|Attack or Save|Available At|Prerequisite)\s*:")
# Engine wording a player cannot act on. "GM" and "rider" are the OWNER's own
# vocabulary (corkboard #61/#181), so they are never guarded here; these are
# phrases the builder wrote that name the implementation instead of the rule.
INTERNAL_PHRASES = (
    "the table's implemented abilities read it",
    "the table has applied it",
    "Rule description unavailable for this saved status",
)


def _hover_parts(hover: dict) -> str:
    return "\n".join([hover.get("title", ""), hover.get("summary", ""),
                      *[f"{field['label']}: {field['value']}" for field in hover.get("fields", [])],
                      hover.get("footer", "")])


def _assert_polite(text: str, where: str) -> None:
    glued = GLUED_LABEL.search(text)
    assert not glued, f"{where}: printed label glued to the word before it: {glued[0]!r}\n{text}"
    for phrase in INTERNAL_PHRASES:
        assert phrase not in text, f"{where}: internal phrase {phrase!r}\n{text}"


def _body(hover: dict) -> str:
    """The hover without its generated footer (title, summary, printed fields)."""
    return "\n".join([hover.get("title", ""), hover.get("summary", ""),
                     *[f"{field['label']}: {field['value']}" for field in hover.get("fields", [])]])


def _sheets() -> list[dict]:
    paths = sorted(POOL.glob("*/current.zip")) if POOL.exists() else []
    sheets = []
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            sheets.append(json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json")))
    sheets.extend([copy.deepcopy(SHEET), copy.deepcopy(MELD_SHEET)])
    return sheets


def _compiled_rows() -> list[tuple[str, dict, str]]:
    """Every declared condition/mark effect of every compiled character."""
    from combat.gate2_runtime_content import AN
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.typed_executor import mark_condition_id

    def effects(value):
        if isinstance(value, dict):
            if value.get("type") in {"condition", "mark"}:
                yield value
            for child in value.values():
                yield from effects(child)
        elif isinstance(value, list):
            for child in value:
                yield from effects(child)

    rows: list[tuple[str, dict, str]] = []
    for i, sheet in enumerate(_sheets()):
        aid = f"actor:factory.mmx104-{i}"
        try:
            bundle = compile_character(sheet, actor_id=aid)
            engine = Gate4ControllerEngine(
                ROOT, match_seed=f"MMX104-{i}", typed_bundles=(bundle,),
                roster_setup={"primary_actor_ids": [aid, AN], "team_by_actor": {aid: "team:a", AN: "team:b"},
                              "starting_positions": {aid: {"x": 2, "y": 2}, AN: {"x": 14, "y": 6}}})
        except Exception as exc:
            pytest.fail(f"Hover pool omitted sheet {i} ({aid}): {exc!r}")
        actor = engine.state.actors[aid]
        actors = {aid: actor.display_name}
        definitions = {key: action.display_name for key, action in engine.action_catalog.items()}
        # A Foundation's Passive / triggered ability is a typed reaction, not an
        # action, so its marks (Golden Mandate Seal's Edict Seal) are only visible
        # if the sweep reads those rows too.
        for reaction in getattr(engine, "typed_reaction_rows", {}).get(aid, []) or []:
            if reaction.get("feature_id"):
                definitions[str(reaction["feature_id"])] = str(reaction.get("name") or reaction["feature_id"])
        sources = [(action.source_definition_id, action.display_name, action.parameters.get("typed") or {})
                   for action in engine.action_catalog.values() if action.owner_id == aid]
        sources += [(str(reaction.get("feature_id") or ""), str(reaction.get("name") or ""), reaction)
                    for reaction in (getattr(engine, "typed_reaction_rows", {}).get(aid, []) or [])
                    if reaction.get("feature_id")]
        for source_id, display_name, payload in sources:
            for effect in effects(payload):
                if effect["type"] == "mark":
                    cid = mark_condition_id(str(effect.get("mark") or "Marked"), aid)
                else:
                    name = str(effect.get("condition") or "")
                    if not name:
                        continue
                    cid = name if name.startswith("condition:") else "condition:typed." + name
                row = {"condition_id": cid, "source_definition_id": source_id,
                       "source_actor_id": aid, "expires_on": effect.get("expires_on")}
                text = describe(engine, actor, row, effect.get("data") or {}, actors, definitions,
                                condition_rules=all_conditions(), mark_readings=TabletopService.MARK_READINGS)
                rows.append((f"{aid} {cid} ({display_name})", row, text))
    return rows


@pytest.fixture(scope="module")
def compiled_rows() -> list[tuple[str, dict, str]]:
    return _compiled_rows()


# --------------------------------------------------------------------- the guards
def test_every_compiled_hover_uses_the_shared_layout(compiled_rows):
    """Every condition and mark hover is the shared layout, not a flat wall of text."""
    assert len(compiled_rows) > 500, f"expected the whole pool, got {len(compiled_rows)} rows"
    for where, _row, text in compiled_rows:
        assert text.get("hover"), f"{where}: no shared hover structure"
        # The footer names who applied it and how long it lasts, on its own line.
        assert text["hover"]["footer"], f"{where}: no footer naming who applied it / how long it lasts"
        assert "\n" in text["detail"] or len(text["detail"]) < 200, (
            f"{where}: hover is still one wall of text ({len(text['detail'])} chars)")


def test_no_compiled_hover_glues_a_printed_label_to_a_word(compiled_rows):
    bad = [where for where, _row, text in compiled_rows
           if GLUED_LABEL.search(_hover_parts(text["hover"]) + "\n" + text["detail"])]
    assert not bad, f"{len(bad)} hovers glue a printed label to a word: {bad[:5]}"


def test_no_compiled_hover_promotes_a_printed_clock_to_its_lifetime(compiled_rows):
    """The footer's lifetime clause is the row's own enforced ``duration``.

    Changed in MMX104f1. This used to forbid a hover from mentioning an expiry and
    "until removed" together, which forced the footer to adopt a printed clock
    that may describe a different status entirely. Now the footer always leads
    with the enforced lifetime, and any differing printed clock must be marked as
    printed so the player can see which claim is the engine's.
    """
    bad = []
    for where, _row, text in compiled_rows:
        hover = text["hover"]
        footer, duration = hover.get("footer", ""), text["duration"]
        # The lifetime clause ends the footer (". ") or is followed by a named
        # printed clock ("; the printed rules for ...").
        if duration and not re.search(rf"Lasts {re.escape(duration.rstrip('.'))}[.;]", footer):
            bad.append(f"{where}: footer {footer!r} does not state the enforced lifetime {duration!r}")
        if "printed rules" in footer and not re.search(r"Lasts [^;.]+", footer):
            bad.append(f"{where}: a printed clock is shown without the enforced lifetime: {footer!r}")
    assert not bad, f"{len(bad)} hovers misstate their lifetime: {bad[:3]}"


def test_no_compiled_hover_shows_engine_wording(compiled_rows):
    bad = [where for where, _row, text in compiled_rows
           if any(phrase in _hover_parts(text["hover"]) + "\n" + text["detail"] for phrase in INTERNAL_PHRASES)
           and text["rule_text"]]
    assert not bad, f"{len(bad)} hovers still show engine wording: {bad[:5]}"


def test_every_printed_hover_field_is_a_known_label(compiled_rows):
    """Only printed labels the owner writes are turned into labelled lines."""
    known = {label for label, _ in hover_text.FIELD_LABELS}
    bad = [where for where, _row, text in compiled_rows
           if any(field["label"] not in known for field in text["hover"].get("fields", []))]
    assert not bad, f"{len(bad)} hovers use an unknown field label: {bad[:5]}"


# ------------------------------------------------------------------- the owner case
def test_edict_seal_mark_hover_is_labelled_lines_not_a_wall_of_text(compiled_rows):
    """Owner 2026-10-03 screenshot: the Edict Seal mark hover."""
    seals = [(where, row, text) for where, row, text in compiled_rows if "edict_seal" in row["condition_id"]]
    if not seals:
        pytest.skip("No owner-pool character carries the Golden Mandate Seal foundation.")
    for where, row, text in seals:
        hover = text["hover"]
        assert hover["title"], f"{where}: no title"
        assert hover["summary"], f"{where}: no one-line summary for a player"
        labels = [field["label"] for field in hover["fields"]]
        # Each printed field is its own line, so no label is ever glued to a word.
        for label in labels:
            assert f"{label}: " in text["detail"], f"{where}: {label} is not on its own labelled line"
        assert "Trigger: After a hostile creature" in text["detail"], f"{where}: printed Trigger lost"
        # The mark's own lifetime is what the footer states. The printed Effect
        # still shows the words "expires at the end of your next turn" -- that
        # describes the temporary rider, and it stays printed prose (MMX104f1).
        assert f"Lasts {text['duration'].rstrip('.')}." in hover["footer"], f"{where}: footer states no lifetime"
        assert "Generate Edict Seal" in hover["footer"], f"{where}: footer does not name the applying ability"
        _assert_polite(text["detail"], where)
    # The wall of text is gone: labelled lines, not one run of prose.
    longest = max((text["detail"] for _where, _row, text in seals), key=len)
    assert "\n" in longest, "the Edict Seal hover is still one wall of text"


# -------------------------------------------------------------- the shared formatter
def test_printed_fields_split_onto_their_own_labelled_lines():
    lead, fields = hover_text.split_fields(
        "#### Golden Seal Bearing\n\n**Type:** Bonus Action\n**Cost:** 1 Edict Seal\n"
        "**Range:** Self\n**Effect:** Gain temporary Hit Points.\n"
        "**Counterplay and Boundaries:** Bind, silence, obscure.")
    assert lead == "Golden Seal Bearing"
    assert fields == [("Action", "Bonus Action"), ("Cost", "1 Edict Seal"), ("Range", "Self"),
                      ("Effect", "Gain temporary Hit Points."),
                      ("Counterplay", "Bind, silence, obscure.")]


def test_a_wrapped_printed_sentence_stays_one_field():
    _lead, fields = hover_text.split_fields("**Effect:** Gain temporary Hit Points equal to\nyour Proficiency Bonus.\n**Limit:** Maximum 1.")
    assert fields == [("Effect", "Gain temporary Hit Points equal to your Proficiency Bonus."),
                      ("Limit", "Maximum 1.")]


def test_an_ordinary_sentence_is_not_mistaken_for_a_field():
    lead, fields = hover_text.split_fields("Your Path key ability modifier: the first step.\nNot a field.")
    assert fields == []
    assert "Path key ability modifier" in lead


def test_a_printed_expiry_never_overrides_the_enforced_lifetime():
    """The footer's authority is what the engine will do, not a printed clock.

    Changed in MMX104f1: this used to assert the opposite, that a printed expiry
    replaced "until removed". That let the footer promise an expiry nothing
    enforces -- a persistent Edict Seal whose printed Effect describes a
    short-lived rider. The printed clock is now named beside the real lifetime.
    """
    fields = [("Duration", "1 minute")]
    settled = hover_text.settle_duration("until removed", fields, source="Golden Mandate Seal")
    assert settled.startswith("until removed")
    assert "printed rules for Golden Mandate Seal" in settled
    # A record that states no differing clock keeps the engine's own wording.
    assert hover_text.settle_duration("until removed", [("Effect", "It does a thing.")]) == "until removed"


def test_markup_keeps_the_printed_fields_and_their_line_structure():
    text = markup("#### Golden Seal Bearing\n\n**Type:** Bonus Action\n**Cost:** 1 Edict Seal")
    assert "**Type:** Bonus Action" in text
    assert len(text.split("\n")) == 3  # blank lines are dropped; printed lines are kept
    assert "#### Golden Seal Bearing" in text


def test_printed_excerpt_with_markup_splits_into_fields():
    record = "foundation.golden_mandate_seal_v0_2B.generate_edict_seal"
    lead, fields = hover_text.split_fields(printed_excerpt(record, "Generate Edict Seal", with_markup=True))
    assert lead == "Generate Edict Seal"
    assert ("Action", "No Action / Triggered") in fields
    assert [name for name, _ in fields][:4] == ["Action", "Trigger", "Range", "Target"]
    # The default flattening is unchanged for every existing caller.
    assert "**" not in printed_excerpt(record, "Generate Edict Seal")
