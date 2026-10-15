"""Printed zone clocks must survive table transactions and cold replay."""
import json

import pytest

from combat import placement_menu
from combat.gate2_runtime_models import Position
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn

CASES = [
    ('tianxia.subpath.qi.dream_qi_cultivator.feature.dream_ascension', 'Dream Ascension',
     'when it enters for the first time during a turn or starts there'),
    ('tianxia.subpath.qi.black_sea_leviathan_womb.feature.gate_of_the_inner_sea', 'Gate of the Inner Sea',
     'Enters the field for the first time during a turn.'),
    ('tianxia.subpath.qi.saber_wind_cultivator.feature.saber_gale_field', 'Saber-Gale Field',
     'Starts its turn inside the aura.'),
]


@pytest.mark.parametrize('mid,name,printed', CASES, ids=[c[1] for c in CASES])
def test_stationary_occupant_waits_for_its_printed_trigger_after_cold_reload(tmp_path, mid, name, printed):
    # HUNT212 F4 seq 197 then 200-219; HUNT211 F1 seq 15 then 16-41.
    # Printed: "A creature is affected once per turn." Creation is not entry.
    rules = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    assert printed in rules[mid]
    combat, table, match = fixture(tmp_path, [mid], cl=20, ask=False,
                                 seed='ZONETICK1', owner_dc=100,
                                 positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6},
                                            FOE: {'x': 5, 'y': 6}})
    engine = combat._load_session(match).engine
    before_hp = engine.state.actors[FOE].current_hp
    sequence = engine.state.event_sequence
    with placement_menu.query():
        choice = next(c for c in engine.legal_candidates()
                      if engine.action_catalog.get(c.source_definition_id)
                      and engine.action_catalog[c.source_definition_id].display_name == name)
    settle(table, match, choice.candidate_id,
           picks={placement_menu.CHOICE: ['cell:5,6,0']})
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == before_hp
    assert not [e for e in engine.events if e.sequence > sequence
                and e.event_type in ('SAVE_ROLLED', 'DAMAGE_COMMITTED')]
    [zone] = [z for z in engine.state.zones.values() if z.active]
    assert Position(x=5, y=6) in zone.affected_cells
    assert {'enter', 'start'} <= set(zone.trigger_profile['triggers'][0]['on'])
    turn(table, match, FOE)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp < before_hp
    fired = [e for e in engine.events if e.sequence > sequence
             and e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('moment') == 'start']
    assert len(fired) == 1
