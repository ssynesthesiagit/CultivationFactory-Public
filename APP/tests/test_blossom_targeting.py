"""Cultivate Blossom placements are selectable and resolve at the Tabletop boundary."""

import pytest

from combat.ext import placed
from combat.history_feed import format_history_feed
from tests.hunt12_support import ME, FOE, candidate, reload
from tests.test_a2_flowers import ALLY, commit, scene
from tests.test_auto86_flowers import at

FLOWERS = "TAL_FLOWERS_CULTIVATE_BLOSSOM"


@pytest.mark.parametrize(
    ("target_id", "x", "y", "attack"),
    [
        (FOE, 4, 6, True),
        (ALLY, 4, 5, False),
        (ME, 3, 6, False),
        (None, 5, 6, False),
    ],
    ids=("unwilling-enemy", "willing-ally", "willing-self", "empty-square"),
)
def test_table_cultivate_blossom_places_on_the_chosen_creature_or_square(tmp_path, target_id, x, y, attack):
    combat, table, match_id = scene(tmp_path, [FLOWERS])
    chosen = at(combat, match_id, "Cultivate Blossom", x, y)

    commit(combat, table, match_id, chosen)

    engine = reload(tmp_path, match_id)
    (zone,) = placed.of(engine, "blossom", owner_id=ME)
    data = placed.data(zone)
    assert (zone.center.x, zone.center.y) == (x, y)
    assert data.get("bearer") == target_id
    attacks = [event for event in engine.events if event.event_type == "ATTACK_ROLLED"
               and event.source_definition_id == chosen.source_definition_id]
    assert bool(attacks) is attack
    if target_id == FOE:
        assert attacks and FOE in attacks[-1].target_ids


def test_option_picker_is_not_logged_as_a_blossom_placed_on_the_caster(tmp_path):
    from combat.history_feed import format_history_feed

    combat, table, match_id = scene(tmp_path, [FLOWERS, "TAL_FLOWERS_EXPLODING_SEED"])
    selection = candidate(combat, match_id, lambda row: row.display_name == "Blossom: Exploding Seed (3 CP)")
    commit(combat, table, match_id, selection)

    engine = reload(tmp_path, match_id)
    marker_events = [event.model_dump(mode="json") for event in engine.events
                     if event.source_definition_id == selection.source_definition_id
                     and event.event_type in {"CONDITION_APPLIED", "CONDITION_REMOVED"}]
    feed = format_history_feed(marker_events, [], pre_state=None, post_state={},
                               actor_names={ME: "Guo Yuan"}, definition_names={})
    assert feed == []
    assert not placed.of(engine, "blossom", owner_id=ME)


def test_blossom_setup_selection_is_not_logged_as_a_placement(tmp_path):
    from tests.hunt12_support import candidate

    combat, table, match_id = scene(tmp_path, [FLOWERS, "TAL_FLOWERS_EXPLODING_SEED"])
    selection = candidate(combat, match_id, lambda row: row.display_name == "Blossom: Exploding Seed (3 CP)")
    commit(combat, table, match_id, selection)

    engine = reload(tmp_path, match_id)
    marker_events = [event.model_dump(mode="json") for event in engine.events
                     if event.source_definition_id == selection.source_definition_id
                     and event.event_type in {"CONDITION_APPLIED", "CONDITION_REMOVED"}]
    feed = format_history_feed(marker_events, [], pre_state=None, post_state={},
                               actor_names={ME: "Guo Yuan"}, definition_names={})
    assert feed == []
    assert not placed.of(engine, "blossom", owner_id=ME)
