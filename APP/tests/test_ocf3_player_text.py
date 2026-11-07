"""OCF3: the four player-text findings of the OC13 pre-deploy hunt (int/r25x2, 5b7d5ef6).

OC13 hand-played the table on 25.x and found four places where a player was told something
untrue or unreadable. Each is fixed in the one shared code path that owns it, so every surface
that uses it is fixed with it, and each has a regression test at the level the player met it.

1. The shared hover layout (``combat/hover_text.py``) appended every unlabelled line of a printed
   card to whatever field came last, so 2,235 of the printed records printed their whole rules body
   as the value of Cost, Limit or Duration: "Cost: None You release a cutting or battering current
   at a target. Make a ranged Cultivation Attack. ...". A printed label is now followed by its own
   value and the card's prose gets its own Effect line.
2. The ground hover never named a named terrain painted on the square and said the material
   "changes nothing" about a square that burns: the card had no ``terrain:`` branch and the board
   never passed the square's terrain, and the map editor worded it a third time (dropping the
   enter/start save, and building "heavily obscured" from a field name).
3. A damage chip hid a bonus the engine already knows: a weapon technique's ``attack_ability_modifier``
   printed as "1d6 + a bonus decided when it hits" while combat rolled the weapon's own modifier.
4. An Ask-me prompt said a self-only ability "uses X on X".

Nothing here changes a fight: the fixes are presentation only (a shared formatter, one shared
formula table, one prompt clause and the ground catalog's own wording), so no saved fight, no
replay and no lock file is touched.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from combat import hover_text
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from combat.tabletop_service import TabletopService, _uses_phrase
from tests.h1_support import ROOT, sheet

RULES = ROOT / "authority" / "typed_mechanics" / "rules_text.json"
EDITS = ROOT / "authority" / "typed_mechanics" / "owner_text_edits.json"
WIND_LASH = "AIR_BASE_WIND_LASH"
HAFT = "TAL_AXES_CLOSE_HAFT_STRIKE"
FU = "tianxia.mortal.weapon.fu"


def _printed_records() -> list[tuple[str, str]]:
    """Every printed record the table can show: the rules catalog and the owner's own edits."""
    records = [(key, value) for key, value in json.loads(RULES.read_text(encoding="utf-8")).items()
               if isinstance(value, str) and value.strip()]
    edits = json.loads(EDITS.read_text(encoding="utf-8")).get("records") or {}
    records += [(key, value) for key, value in edits.items() if isinstance(value, str) and value.strip()]
    return records


def _menu(bundle) -> dict:
    """The table's own menu rows for a compiled character, described exactly as ``state`` serves them."""
    class _Row:
        def __init__(self, row):
            self._row = row
            self.economy = row.get("economy", "NONE")
            self.costs = row.get("costs", ())
            self.parameters = row.get("parameters", {})

        def model_dump(self, mode="json"):
            return self._row

    engine = SimpleNamespace(action_catalog={row["source_definition_id"]: _Row(row)
                                             for row in bundle["action_catalog"]},
                             state=SimpleNamespace(actors={}))
    menu = {"actions": [{"source_definition_id": row["source_definition_id"], "label": row["display_name"]}
                        for row in bundle["action_catalog"]]}
    TabletopService._menu_descriptions(menu, engine)
    return {group["label"]: group for group in menu["actions"]}


# --------------------------------------------------- 1. the hover layout glued the body on
def test_the_rules_body_is_not_the_value_of_the_last_printed_field():
    """The reported button: "Cost: None You release a cutting or battering current at a target...".

    Wind Lash prints its labels and then its rule, so Cost is "None" and the rule is the Effect.
    """
    menu = _menu(compile_character(sheet(WIND_LASH, cl=5), actor_id="actor:factory.ocf3-wind"))
    hover = menu["Wind Lash: Cut"]["hover"]
    fields = {field["label"]: field["value"] for field in hover["fields"]}
    assert fields["Cost"] == "None", hover
    assert fields["Effect"].startswith("You release a cutting or battering current at a target."), hover
    # The whole printed body is on the Effect line, and no other field carries a sentence of it.
    assert "Make a ranged Cultivation Attack." in fields["Effect"], hover
    for label in ("Action", "Range", "Target", "Cost"):
        assert "Cultivation Attack" not in fields[label], f"{label} swallowed the rule body: {hover}"
    assert "\n" in hover["text"] and "Cost: None\n" in hover["text"], hover["text"]


def test_no_printed_record_puts_a_later_sentence_into_a_printed_field():
    """The whole corpus, not one ability: a printed Cost / Range / Duration / Limit is its own line.

    A line the printer began on its own, that starts a new sentence, belongs to the card's body.
    It cannot sit inside the value of a field printed before it -- that is what printed the whole
    rules body as the Cost. The body's own Effect line is where those sentences belong.

    One printed shape is exempt, because the owner's cards print it: a label the printer left
    EMPTY ("Limits:" on a line of its own) owns the sentences printed under it. Those sentences
    were printed under that label, so putting them anywhere else -- a second Effect, or the field
    above -- would misreport where the owner put them.
    """
    offenders = []
    for key, record in _printed_records():
        if hover_text.has_structural_blocks(record):
            continue
        lines = [line.strip() for line in record.split("\n") if line.strip()]
        # A whole sentence the printer began on its own. Short fragments ("Ritual", "True Name")
        # are excluded: they occur inside other fields' values by coincidence, not by being glued.
        starts_sentence = [line for line in lines[1:] if line[:1].isupper() and len(line) >= 24]
        empty_labels = _empty_printed_labels(record)
        _lead, fields = hover_text.split_fields(record)
        for label, value in fields:
            if label == hover_text.BODY_FIELD or label in empty_labels:
                continue
            for line in starts_sentence:
                if line in value:
                    offenders.append(f"{key}: {label} carries a later line {line[:40]!r}")
                    break
    assert not offenders, f"{len(offenders)} printed fields swallow a later line: {offenders[:5]}"


def _empty_printed_labels(record: str) -> set[str]:
    """The printed field labels the owner wrote with nothing after the colon."""
    labels = set()
    for raw in record.split("\n"):
        match = (hover_text._FIELD_BOLD.match(raw.strip()) or hover_text._FIELD_PLAIN.match(raw.strip()))
        name = hover_text._label(match["label"]) if match else ""
        if name and not match["value"].strip():
            labels.add(name)
    return labels


def test_every_printed_label_the_owner_left_empty_keeps_the_lines_under_it():
    """The corpus form of the same rule: a heading-only label never loses its value."""
    lost = []
    for key, record in _printed_records():
        wanted = _empty_printed_labels(record)
        if not wanted:
            continue
        _lead, fields = hover_text.split_fields(record)
        printed = dict(fields)
        for label in wanted:
            if not printed.get(label):
                lost.append(f"{key}: {label}")
    assert not lost, f"printed labels printed empty, then dropped: {lost}"


# --- OCF3f1 (2): "Limits:" on a line of its own kept no Limit field at all.
SPACE_CARDS = ("tianxia.talent.space.door_that_is_not_there",
               "tianxia.talent.space.spatial_displacement")


@pytest.mark.parametrize("card", SPACE_CARDS)
def test_a_shipped_space_talent_keeps_its_printed_limit_field(card):
    """The owner's card prints "Limits:" alone, then the restrictions under it.

    Spatial Displacement's limits are the targeting restrictions a player looks for ("You cannot
    teleport a target into hazards..."), and Door That Is Not There's are its boundary and seal
    rules. They are printed under the label, so the card's Limit field must hold them: before the
    fix they were filtered out as an empty field and the restrictions reappeared as a second
    Effect, which classifies them as the ability's own rule rather than its limits.
    """
    record = json.loads(RULES.read_text(encoding="utf-8"))[card]
    _lead, fields = hover_text.split_fields(record)
    printed = dict(fields)
    assert "Limits:" in record, f"{card} no longer prints Limits: on its own line"
    assert "Limit" in printed, f"{card} lost its printed Limit field: {fields}"
    limits = printed["Limit"]
    body = " ".join(value for label, value in fields if label == hover_text.BODY_FIELD)
    # Every printed restriction sits under Limit, and none of them is the card's own Effect.
    for sentence in (line.strip() for line in record.split("Limits:\n", 1)[1].split("\n") if line.strip()):
        assert sentence in limits, f"{card}: {sentence[:50]!r} is not under Limit"
        assert sentence not in body, f"{card}: {sentence[:50]!r} was also read as the Effect"
    # The Effect is still the ability's own rule, so the summary and the card read in order.
    assert printed["Effect"].startswith("Touch a closed door" if "door" in card else "Choose one creature"), fields


def test_a_populated_label_does_not_take_the_body_that_follows_it():
    """The other half: only an EMPTY label adopts the lines under it."""
    _lead, fields = hover_text.split_fields(
        "**Cost:** 1 CP\n"
        "Touch a closed door and create a false opening through it.\n"
        "**Limits:**\n"
        "The door must be no more than 1 foot thick.\n"
        "The talent cannot pass through a Dimensional Lock.")
    printed = dict(fields)
    assert printed["Cost"] == "1 CP", fields
    assert printed["Effect"] == "Touch a closed door and create a false opening through it.", fields
    assert printed["Limit"] == ("The door must be no more than 1 foot thick. "
                                "The talent cannot pass through a Dimensional Lock."), fields


def test_a_table_menu_row_for_a_shipped_space_talent_shows_its_limit_field():
    """The level the player met it: the button the table offers for the talent.

    Spatial Displacement is the one whose printed Limits are targeting restrictions ("You cannot
    teleport a target into hazards..."), so a hover without them tells a player the ability has no
    limits at all. Both shipped Space talents are checked, through ``_menu_descriptions`` on a
    compiled character, which is the row ``state()`` serves.
    """
    for card, label, restriction in (
            ("tianxia.talent.space.spatial_displacement", "Spatial Displacement",
             "You cannot teleport a target into hazards"),
            ("tianxia.talent.space.door_that_is_not_there", "Door That Is Not There",
             "The boundary must be no more than 1 foot thick")):
        hover = _menu(compile_character(sheet(card, cl=5), actor_id="actor:ocf3f1-space"))[label]["hover"]
        fields = {field["label"]: field["value"] for field in hover["fields"]}
        assert "Limit" in fields, f"{label}: the button has no Limit field: {fields}"
        assert restriction in fields["Limit"], f"{label}: {fields['Limit'][:60]}"
        assert restriction not in fields["Effect"], f"{label}: the limit was filed as the Effect"
        assert f"Limit: {restriction[:20]}" in hover["text"], hover["text"]


def test_a_wrapped_printed_sentence_still_stays_one_field():
    """The other half of the same rule: a line the printer wrapped keeps its field."""
    _lead, fields = hover_text.split_fields(
        "**Cost:** 3 Qi and\nyour Proficiency Bonus.\n**Limit:** Once per day.")
    assert fields == [("Cost", "3 Qi and your Proficiency Bonus."), ("Limit", "Once per day.")]


def test_a_printed_saving_throw_is_its_own_line_not_part_of_the_cost():
    """"Saving Throw: Constitution" is a label the owner's cards print, so it is not body prose."""
    _lead, fields = hover_text.split_fields(
        "**Action:** Action\n**Range:** 30 feet\n**Cost:** 1 Stamina\n**Saving Throw:** Constitution\n\n"
        "On a failed save, the creature is Frightened of you.")
    assert ("Saving Throw", "Constitution") in fields, fields
    assert fields[-1][0] == "Effect", fields


# --------------------------------------------------- 3. the damage chip hid a known bonus
def _haft_bundle():
    """Close Haft Strike with a Strength weapon and a Constitution key ability, so the two differ."""
    from factory_authoring.starting_kits import item_definition

    doc = sheet(HAFT, cl=10, key="CON")
    doc["ability_scores_and_statistics"]["abilities"] = [
        {"ability": ability, "score": score, "modifier": (score - 10) // 2}
        for ability, score in (("STR", 14), ("DEX", 12), ("CON", 18), ("INT", 10), ("WIS", 12), ("CHA", 10))]
    doc["equipment"] = [{"starting_kit": {"items": [
        {"item_id": FU, "name": item_definition(FU)["name"], "quantity": 1}]}}]
    return compile_character(doc, actor_id="actor:factory.ocf3-haft")


def test_a_weapon_technique_chip_shows_the_bonus_combat_rolls():
    """The reported chip: "1d6 + a bonus decided when it hits bludgeoning" for a row combat resolves."""
    buttons = auto_buttons(_haft_bundle(), {"cultivation_level": 10})
    haft = [button for button in buttons if "CLOSE_HAFT" in (button.get("combat") or {}).get("source_definition_id", "")]
    assert haft, "the compiled character offers no Close Haft Strike button"
    damage = haft[0]["detail"]["damage"]
    assert "decided when it hits" not in damage, damage
    # The delivered weapon's Strength +2, never the key ability's Constitution +4.
    assert damage.startswith("1d6+2"), damage
    assert damage.endswith("bludgeoning"), damage


def test_a_display_still_says_nothing_rather_than_guessing():
    """A formula no table can answer is left out, as before: the fix adds known ones, not numbers."""
    from combat.display_values import display_formula_value

    with pytest.raises(ValueError):
        display_formula_value("half_trigger_damage", {"pb": 4, "cl": 5})
    with pytest.raises(ValueError):
        display_formula_value("not_a_formula", {"pb": 4, "cl": 5})


# --------------------------------------------------- 4. a self-only prompt said "uses X on X"
def _choice_prompt(choice_trigger, names=None):
    service = TabletopService.__new__(TabletopService)
    service._names_for = lambda match_id: (names if names is not None
                                           else {"actor:a": "Song Sheruo", "actor:b": "Stone Warden"}, {})
    context = {"checkpoint": "choice:dash_or_disengage:actor:a", "reactor_id": "actor:a",
               "reaction_source_id": "choice:dash_or_disengage",
               "extension_choice": {"option_ids": ["dash", "disengage"], "minimum_selections": 1,
                                    "maximum_selections": 1, "allow_decline": False},
               "choice_trigger": choice_trigger}
    return service._reaction_prompt("match:ocf3", context)


def test_a_self_only_choice_prompt_does_not_name_the_actor_as_its_own_target():
    """The reported prompt: "Stomping Step ... -- Song Sheruo uses Stomping Step on Song Sheruo."."""
    prompt = _choice_prompt({"affected_id": "actor:a", "actor_id": "actor:a",
                             "action_name": "Stomping Step", "feature_id": HAFT,
                             "labels": {"dash": "Dash", "disengage": "Disengage"}})
    assert prompt["moment"].endswith("Song Sheruo uses Stomping Step."), prompt["moment"]
    assert "on Song Sheruo" not in prompt["moment"], prompt["moment"]
    # The ability and both options are still named, so nothing the player needs is lost.
    assert "Stomping Step" in prompt["moment"] and prompt["choice"]["options"], prompt


def test_a_choice_prompt_still_names_another_creature():
    """The general clause is unchanged when the ability really does land on somebody else."""
    prompt = _choice_prompt({"affected_id": "actor:b", "actor_id": "actor:a",
                             "action_name": "Hidden Strike", "feature_id": "TAL_BEAST_ASpects",
                             "labels": {"sever": "Sever Awareness"}})
    assert prompt["moment"].endswith("Song Sheruo uses Hidden Strike on Stone Warden."), prompt["moment"]


# --- OCF3f1 (1): a second creature printing the SAME name is still a second creature.
# Two owners can field two summons that both print "Warhorse" and the roster keeps both
# names as printed (``_roster_names`` only refreshes them), so "are these two the same
# creature?" can never be answered by the two display strings: it took an action against
# the other Warhorse and the sentence said only "Warhorse uses Hidden Strike".
def test_a_choice_prompt_names_a_different_creature_that_prints_the_same_name():
    names = {"actor:a": "Warhorse", "actor:b": "Warhorse"}
    prompt = _choice_prompt({"affected_id": "actor:b", "actor_id": "actor:a",
                             "action_name": "Hidden Strike", "feature_id": "TAL_BEAST_ASpects",
                             "labels": {"sever": "Sever Awareness"}}, names)
    assert prompt["moment"].endswith("Warhorse uses Hidden Strike on Warhorse."), prompt["moment"]
    assert prompt["affected"] == "Warhorse", prompt


def test_a_choice_prompt_asks_which_creature_acted_when_two_actors_print_one_name():
    """The reverse guard: identity is the id, so equal ids never name a second creature."""
    names = {"actor:a": "Stone Warden", "actor:b": "Warhorse"}
    prompt = _choice_prompt({"affected_id": "actor:a", "actor_id": "actor:a",
                             "action_name": "Hidden Strike", "feature_id": "TAL_BEAST_ASpects",
                             "labels": {"sever": "Sever Awareness"}}, names)
    assert prompt["moment"].endswith("Stone Warden uses Hidden Strike."), prompt["moment"]


def test_the_reaction_roll_sentence_names_a_same_named_target():
    """The second clause, on the reaction-roll prompt: same defect, same fix."""
    service = TabletopService.__new__(TabletopService)
    service._names_for = lambda match_id: ({"actor:a": "Warhorse", "actor:b": "Warhorse"}, {})
    prompt = service._reaction_prompt_fields("match:ocf3", {
        "reactor_id": "actor:a", "checkpoint": "TYPED:REACTION_ROLL",
        "reaction_source_id": "reaction:typed.system:combat.opportunity_attack",
        "choice_trigger": {"roll_kind": "reaction", "actor_id": "actor:a", "target_id": "actor:b",
                           "action_name": "Warhorn Rush"}})
    assert prompt["moment"] == "Warhorse uses Warhorn Rush against Warhorse", prompt


def test_an_older_packet_without_ids_still_compares_the_printed_names():
    """A saved fight whose packet carries no ids reads exactly as it did before."""
    assert _uses_phrase("Stomping Step", "Song Sheruo", "Song Sheruo") == "uses Stomping Step"
    assert _uses_phrase("Hidden Strike", "Stone Warden", "Song Sheruo") == "uses Hidden Strike on Stone Warden"

# ------------------------------------- 2. the ground card never named a named terrain
def test_a_named_terrain_the_catalog_publishes_says_what_it_does():
    """Fire Terrain: the save it makes, what a failure does, and what a success gets.

    The card is assembled from ``combat/rules/terrain.json``'s own player-facing fields, so a
    terrain the owner gave an ``enter_start`` rule says so -- and a successful save is part of what
    the ground does, not something the card may leave out.
    """
    from combat.ground_text import catalog

    fire = catalog()["terrain:fire terrain"]
    lines = " ".join(fire["lines"])
    assert fire["name"] == "Fire Terrain", fire
    assert "entering it, or starting its turn inside, makes a Dexterity save" in lines, lines
    assert "Fire damage equal to its Proficiency Bonus" in lines, lines
    assert "on a success, gains Kindled" in lines, lines


def test_a_painted_floor_claims_nothing_about_the_square_it_is_painted_on():
    """The reported card: a Fire Terrain square read "The material itself changes nothing"."""
    from combat.ground_text import catalog

    floor = " ".join(catalog()["floor:graveyard"]["lines"])
    assert "changes nothing" not in floor, floor
    assert "only the look" in floor, floor
    # What the paint itself does is still said, and where the square's real rules come from is named.
    assert "costs no movement, gives no cover and deals no damage" in floor, floor
    assert "terrain" in floor, floor


def test_the_material_brush_says_what_a_named_terrain_does(tmp_path):
    """The map editor's Material brush, over HTTP, in the same words the table's card uses."""
    from fastapi.testclient import TestClient

    from app.api import create_app
    from app.core import Settings

    app = create_app(Settings.from_env(ROOT, tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/tabletop/terrains")
        assert response.status_code == 200, response.text
        payload = response.json()
    rows = {row["name"]: row for row in payload["terrains"]}
    fire = rows["fire terrain"]["does"]
    assert "Dexterity save" in fire, fire
    assert "on a success, gains Kindled" in fire, fire
    # The brush's wording is the catalog's, not a third one assembled from the rule's field names.
    assert fire == " ".join(payload["ground"]["terrain:fire terrain"]["lines"]), fire
    # The brush used to build its own phrases from rule["obscured"] + "ly obscured", which spells
    # the heavy one wrong. No shipped terrain is heavily obscured, so that was latent -- the words
    # now come from the catalog, which spells both correctly.
    for name, entry in payload["ground"].items():
        for line in entry["lines"]:
            assert "heavyly" not in line, f"{name}: {line!r}"
