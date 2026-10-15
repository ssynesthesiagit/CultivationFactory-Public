"""Darkness a fighter can't see through blocks its fog-of-war view like a wall (owner 2026-09-30); the table's
per-fighter blocks follow the fight's own sight rules."""

from combat import zones, senses
from combat.gate2_runtime_models import Position
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from tests.test_auto_tabik import ME, _do, _engine


def test_the_enemy_cannot_see_into_tabiks_darkness_but_its_owner_can():
    engine, _bundle = _engine([], foe_at=(12, 1))
    _do(engine, "Darkness", at=(8, 6))
    zone = next(z for z in zones.typed_zones(engine) if z.owner_id == ME)
    cells = {(c.x, c.y) for c in zone.affected_cells}
    assert not zones._inside(engine, engine.state.actors[AN], zone)
    assert all(not senses.perceives_cell(engine, engine.state.actors[AN], Position(x=x, y=y))
               for x, y in cells)  # every square of it is dark to the foe outside


def test_no_darkness_no_blocks():
    engine, _bundle = _engine([])
    viewer = engine.state.actors[AN]
    assert senses.perceives_cell(engine, viewer, viewer.position)
    assert not zones._heavy(engine)


def test_plugin_toggle_labels_find_their_owning_ability_text():
    from combat.tabletop import _toggle_description

    text = _toggle_description("Crawling Fever: 2d8 Necrotic", {})
    assert text and "Court of the Crawling Fever" in text
    assert "Hidden Strike" in (_toggle_description("Hidden Strike: Sever Awareness", {}) or "")


def test_a_reactions_standing_choice_is_listed_as_a_free_choice_not_an_action():
    from combat.tabletop import auto_buttons

    row = {"source_definition_id": "action:typed.x.flowing_response.step2", "display_name": "Flowing Response: Empty Step",
           "economy": "NONE", "target_kind": "SELF", "costs": [],
           "parameters": {"setting_only": True, "typed": {"effects": [{"type": "flowing_choice"}], "numbers": {}, "riders": []}}}
    button = next(b for b in auto_buttons({"action_catalog": [row]}, {"cultivation_level": 5}) if b["label"] == row["display_name"])
    assert button["group"] == "reactions" and "choice" in button["tags"]
    assert "Flowing Response" in button["description"]
    assert button["description"].endswith("Choosing this option takes no action and costs nothing; it stays selected until you change it.")
