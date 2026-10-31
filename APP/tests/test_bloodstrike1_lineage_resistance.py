"""Public synthetic table regressions for Lineage Resistance (CL3 Ancestral Bloodline Awakening).

Printed text: "Gain Resistance to your lineage's chosen affinity damage type.
If the chosen affinity is Force or Psychic, reduce the first damage packet of
that type you take each round by your Proficiency Bonus instead of gaining
Resistance." Every packet below is an ordinary committed table transaction,
and the recorded affinity is the Subpath construction choice, not the separate
Insight's gift type.
"""
import pytest

from combat.ext import ancestral_bloodline as bloodline
from combat.factory_compiler import compile_character
from tests.cw2_service_support import add_action
from tests.h1_support import sheet
from tests.test_bloodstrike1 import use
from tests.worker2_support import OWNER, FOE, fixture, reload, turn

ACTIONS = (("Fire Blow", "fire"), ("Cold Blow", "cold"),
           ("Force Blow", "force"), ("Club Blow", "bludgeoning"))


def document(lineage, affinity, owns=True):
    doc = sheet([], cl=3)
    doc.setdefault("path_and_subpath", {}).update(
        path_feature_record_ids=[bloodline.BLOODLINE] if owns else [],
        bloodline_lineage=lineage, bloodline_affinity=affinity)
    return doc


def make(tmp_path, lineage, affinity, owns=True):
    bundle = compile_character(document(lineage, affinity, owns), actor_id=OWNER)
    def prepare(bundles):
        for row in bundles:
            for name, damage_type in ACTIONS:
                add_action(row, name, [{"type": "damage", "applies_to": "target", "flat": 10,
                                        "damage_types": [damage_type]}])
    return fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=prepare, named=True)


def packets(engine, start):
    return [event for event in engine.events[start:]
            if event.event_type == "DAMAGE_COMMITTED" and OWNER in event.target_ids]


@pytest.mark.parametrize("lineage,affinity,title,expected", [
    ("azure_dragon", "fire", "Fire Blow", 5),
    ("azure_dragon", "fire", "Cold Blow", 10),
    ("jade_tortoise", "earth", "Club Blow", 5),
    ("jade_tortoise", "earth", "Fire Blow", 10),
])
def test_resistance_halves_only_the_chosen_affinity_type(tmp_path, lineage, affinity, title, expected):
    combat, table, mid = make(tmp_path, lineage, affinity)
    turn(table, mid, FOE)
    start = len(reload(tmp_path, mid).events)
    use(combat, table, mid, title, target=OWNER)
    committed, = packets(reload(tmp_path, mid), start)
    assert committed.payload["hp_damage"] == expected


def test_force_affinity_reduces_the_first_packet_each_round_only(tmp_path):
    combat, table, mid = make(tmp_path, "kunpeng", "force")
    engine = reload(tmp_path, mid)
    pb = engine.state.actors[OWNER].proficiency_bonus
    assert pb == 4
    first_round = engine.state.round_number
    turn(table, mid, FOE)
    start = len(reload(tmp_path, mid).events)
    use(combat, table, mid, "Force Blow", target=OWNER)
    use(combat, table, mid, "Force Blow", target=OWNER)
    assert [event.payload["hp_damage"] for event in packets(reload(tmp_path, mid), start)] == [10 - pb, 10]
    # A new round restores the printed first-packet reduction.
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert engine.state.round_number > first_round
    start = len(engine.events)
    use(combat, table, mid, "Force Blow", target=OWNER)
    committed, = packets(reload(tmp_path, mid), start)
    assert committed.payload["hp_damage"] == 10 - pb


def test_inert_without_the_record(tmp_path):
    combat, table, mid = make(tmp_path, "azure_dragon", "fire", owns=False)
    turn(table, mid, FOE)
    start = len(reload(tmp_path, mid).events)
    use(combat, table, mid, "Fire Blow", target=OWNER)
    committed, = packets(reload(tmp_path, mid), start)
    assert committed.payload["hp_damage"] == 10
