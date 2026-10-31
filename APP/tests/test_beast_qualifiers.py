"""Public typed creature controls for every Beast-Echo creature-set consumer."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from combat.creature_types import from_record
from combat.ext.beast_qualifiers import HOSTILE_TRIGGER_KINDS, qualifies


def creature(*labels, **extra):
    return SimpleNamespace(entity_id="subject",
                           creature_types=from_record({"creature_types": list(labels)}),
                           **extra)


def engine(rows=()):
    return SimpleNamespace(typed_passive_rows={"subject": list(rows)})


@pytest.mark.parametrize("label", [
    "Beast", "Beast-aspected", "Predator-aspected", "Monstrosity",
    "Spirit Beast", "Demon Beast", "spirit-beast", "MONSTROSITIES",
])
def test_explicit_typed_creature_labels_qualify(label):
    assert qualifies(engine(), creature(label))


@pytest.mark.parametrize("label", ["Humanoid", "Demon", "Fiend", "Dragon", "Predator", ""])
def test_unrelated_or_missing_labels_do_not_qualify(label):
    assert not qualifies(engine(), creature(label))


@pytest.mark.parametrize("label", ["Beast", "beasts"])
def test_plain_beast_label_is_not_a_generate_pack_echo_hostile_trigger(label):
    assert qualifies(engine(), creature(label))
    assert not qualifies(engine(), creature(label), HOSTILE_TRIGGER_KINDS)


@pytest.mark.parametrize("label", ["Beast-aspected", "Predator-aspected", "Monstrosity",
                                   "Spirit Beast", "Demon Beast"])
def test_printed_hostile_trigger_labels_still_qualify(label):
    assert qualifies(engine(), creature(label), HOSTILE_TRIGGER_KINDS)


def test_compiled_beast_aspects_are_typed_provenance_for_humanoid():
    rows = [{"block": "path_rider", "kind": "beast_aspects", "role": "initiate"}]
    assert qualifies(engine(rows), creature("Humanoid"))


@pytest.mark.parametrize("rows", [
    [{"block": "generic", "kind": "beast_aspects"}],
    [{"block": "path_rider", "kind": "other", "name": "Beast Aspects"}],
    [{"feature_id": "beast_aspects"}],
])
def test_names_and_unrelated_rows_are_not_aspect_provenance(rows):
    assert not qualifies(engine(rows), creature("Humanoid"))


def test_no_name_condition_or_race_inference_and_no_mutation():
    actor = creature("Humanoid", display_name="Demon Beast", race="Spirit Beast",
                     conditions={"beast_aspect_tiger": object()})
    query = engine()
    before = deepcopy(query.typed_passive_rows)
    assert not qualifies(query, actor)
    assert query.typed_passive_rows == before
    assert not qualifies(query, None)
