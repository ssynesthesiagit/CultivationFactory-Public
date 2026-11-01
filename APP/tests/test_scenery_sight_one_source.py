"""A placed object's sight comes from one kind: the state's object_kind, the field the service reads too (review F3R2 finding 3).

combat/ext/objects.py used to read component.kind first, so the fight's zone and the table's object row could disagree
about one object. Both now resolve the sight from object_kind (combat/object_rules.py sight).
"""
from __future__ import annotations

from combat import object_rules, zones
from combat.gate2_runtime_models import Position, RuntimeObjectState
from tests.h1_support import duel


def test_fight_zone_takes_the_sight_of_object_kind_not_of_a_component_kind_that_disagrees():
    engine = duel([])
    engine.state.objects['object:mixed'] = RuntimeObjectState(
        object_id='object:mixed', object_kind='boulder_pile', position=Position(x=3, y=3), unattended=True,
        flammable=False, ac=15, current_hp=10, maximum_hp=10, height_ft=10,
        component={'kind': 'door', 'name': 'Mixed', 'blocks': True})
    zones.sync_walls(engine)
    row = next(row for row in engine.grid.sight_line_sources if row['name'] == 'Mixed')
    assert object_rules.sight('boulder_pile') == {'occluder': 'centerline', 'sight_class': 'object'}
    assert row['kind'] == 'BLOCKED'
    # sight_lines.source exports the structured stroke kind as 'tag' (static/tabletop/los-lines.js reads it);
    # the same 'object' class the zone's wall rule and object_rules.sight carry, never a name or description.
    assert row['occluder'] == 'centerline' and row['tag'] == 'object'
