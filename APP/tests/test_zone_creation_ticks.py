"""Printed zone clocks must survive table transactions and cold replay."""
import json

import pytest

from combat import placement_menu
from combat.gate2_runtime_models import Position
from tests.h1_support import ROOT, sheet, mechanics
from combat.factory_compiler import compile_character
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn

CASES = [
    ('tianxia.subpath.qi.dream_qi_cultivator.feature.dream_ascension', 'Dream Ascension',
     'when it enters for the first time during a turn or starts there'),
    ('tianxia.subpath.qi.black_sea_leviathan_womb.feature.gate_of_the_inner_sea', 'Gate of the Inner Sea',
     'Enters the field for the first time during a turn.'),
    ('tianxia.subpath.qi.saber_wind_cultivator.feature.saber_gale_field', 'Saber-Gale Field',
     'Starts its turn inside the aura.'),
    ('tianxia.subpath.qi.storm_soul_cultivator.feature.eye_of_the_storm', 'Eye of the Storm',
     'when it enters the storm for the first time during a turn or starts there'),
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


AUDITED = (
    'gate_of_the_inner_sea', 'calamity_court_field', 'procession_of_ten_thousand_demons',
    'cremate_heaven_and_earth', 'cremation_prison', 'dream_ascension', 'sandstorm_field',
    'field_of_the_broken_array', 'heaven_devouring_cauldron', 'tribulation_cloud_core',
    'thousand_ribbons', 'feast_of_sleeping_minds', 'palace_of_the_final_riddle',
    'saber_gale_field', 'eye_of_the_storm', 'sword_array_field', 'plague_of_one_hundred_meridians',
    'toxic_cloud', 'monsoon_wall', 'dragon_pin',
    'world_beneath_the_black_sea', 'ten_thousand_seed_ascension',
    'weather_of_the_heart', 'flame_that_welcomes_all', 'court_of_the_living_flame',
)
AUDITED_IDS = sorted(k for k in mechanics() if k.rsplit('.', 1)[-1] in AUDITED
                     and k != 'tianxia.talent.poison.toxic_cloud')


@pytest.mark.parametrize('mid', AUDITED_IDS)
def test_audited_native_producers_keep_saves_only_in_the_zone(mid):
    """Printed enter/start saves include abbreviated 'starts there/inside'."""
    rows = [a for a in compile_character(sheet([mid], cl=20), actor_id=OWNER)['action_catalog']
            if a.get('parameters', {}).get('typed', {}).get('source') == mid]
    assert rows
    for action in rows:
        typed = action['parameters']['typed']
        # All variants and options, not just the first menu row, use the clock.
        assert not [e for e in typed['effects'] if e.get('type') == 'save' and not e.get('deferred')]
        triggers = typed['zone_spec']['triggers']
        expected = {'start'} if mid.endswith(('world_beneath_the_black_sea', 'flame_that_welcomes_all',
                                             'court_of_the_living_flame')) else {'enter', 'start'}
        assert triggers and any(set(t['on']) >= expected for t in triggers)
        all_moments = {on for trigger in triggers for on in trigger['on']}
        if mid.endswith('tribulation_cloud_core'):
            expected |= {'cp_spent'}
        elif mid.endswith('court_of_the_living_flame'):
            expected |= {'fire_damage'}
        assert all_moments == expected, 'No inferred or unrelated extra clock'
        if mid.endswith('court_of_the_living_flame'):
            # "ignore your Fire Terrain" does not create Fire Terrain.
            assert typed['zone_spec']['terrain'] == []
            assert not any('enter' in t['on'] for t in triggers)


@pytest.mark.parametrize('suffix,step', [('iron_cavalry_front', 5), ('heavenly_cavalry_procession', 4)])
def test_moving_front_saves_only_after_its_printed_motion(tmp_path, suffix, step):
    # Front: "the front’s center moves at least 10 feet and then enters a
    # space within 5 feet of that creature". Procession: "passes within 10
    # feet of it for the first time during a turn". Neither says on creation.
    mid = 'tianxia.subpath.qi.iron_rain_cavalry_saber_cultivator.feature.' + suffix
    combat, table, match = fixture(tmp_path, [mid], cl=20, ask=False,
        seed='ZONETICK1-MOVING', owner_dc=100,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 6, 'y': 6}})
    engine = combat._load_session(match).engine
    hp = engine.state.actors[FOE].current_hp
    choice = next(c for c in engine.legal_candidates()
                  if engine.action_catalog.get(c.source_definition_id)
                  and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == mid)
    settle(table, match, choice.candidate_id)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == hp
    move = next(c for c in engine.legal_candidates()
                if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=step, y=6))
    settle(table, match, move.candidate_id)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp < hp


def test_flame_mantle_does_not_burn_an_unrelated_stationary_creature(tmp_path):
    # Printed: "a creature that starts its turn Grappling you takes Fire or
    # Radiant damage equal to your Proficiency Bonus + your Key Ability modifier".
    combat, table, match = fixture(tmp_path, ['TAL_YANG_COMPLETING_FLAME_MANTLE'],
                                   cl=20, ask=False, seed='ZONETICK1-MANTLE')
    engine = combat._load_session(match).engine
    hp = engine.state.actors[FOE].current_hp
    choice = next(c for c in engine.legal_candidates() if c.display_name == 'Completing Flame Mantle')
    settle(table, match, choice.candidate_id)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == hp
    turn(table, match, FOE)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == hp


def test_flame_mantle_burns_an_actual_grappler_outside_its_light_after_reload(tmp_path):
    from combat.canonical import canonical_sha256

    def setup(bundles):
        # Seal a setup-only established hold before genesis. The mantle's
        # printed damage has no range limit; its light radius is not a limit
        # on an already established long-reach grapple.
        bundle = next(b for b in bundles if b['actor_id'] == FOE)
        source = 'action:test.established_long_reach_grapple'
        bundle['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Establish fixture grapple',
            'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'costs': [],
            'parameters': {'typed': {'source': 'test:established_grapple',
                'effects': [{'type': 'condition', 'condition': 'grappled', 'applies_to': 'target',
                             'duration': 'until_removed'}],
                'numbers': {'cl': 20, 'pb': 4, 'save_dc': 100},
                'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 0}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, match = fixture(tmp_path, ['TAL_YANG_COMPLETING_FLAME_MANTLE'], cl=20, ask=False,
        seed='ZONETICK1-LONG-GRAPPLE', bundle_transform=setup, foe_position={'x': 9, 'y': 6})
    turn(table, match, FOE)
    engine = combat._load_session(match).engine
    grab = next(c for c in engine.legal_candidates() if c.display_name == 'Establish fixture grapple'
                and c.target_ids == (OWNER,))
    settle(table, match, grab.candidate_id)
    turn(table, match, OWNER)
    engine = combat._load_session(match).engine
    cast = next(c for c in engine.legal_candidates() if c.display_name == 'Completing Flame Mantle')
    settle(table, match, cast.candidate_id)
    engine = reload(tmp_path, match)
    hp = engine.state.actors[FOE].current_hp
    turn(table, match, FOE)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp < hp


@pytest.mark.parametrize('patron', ['air', 'cold', 'earth', 'fire', 'lightning', 'metal', 'water', 'wood'])
def test_patron_aura_is_built_without_a_creation_save_and_survives_reload(tmp_path, patron):
    mid = 'tianxia.subpath.qi.shugenja.feature.avatar_of_the_element'
    # Printed: "A hostile creature makes the aura’s save when it enters for
    # the first time during a turn or starts there."
    combat, table, match = fixture(tmp_path, [mid], cl=20, ask=False,
                                  seed='ZONETICK1-PATRON-' + patron, owner_dc=100,
                                  foe_position={'x': 5, 'y': 6})
    engine = combat._load_session(match).engine
    hp = engine.state.actors[FOE].current_hp
    with placement_menu.query():
        choice = next(c for c in engine.legal_candidates()
                      if c.display_name.startswith('Avatar of the Element'))
    settle(table, match, choice.candidate_id,
           picks={'choice:needle.shugenja_patron': [patron]})
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == hp
    [zone] = [z for z in engine.state.zones.values() if z.active]
    [trigger] = zone.trigger_profile['triggers']
    assert trigger['on'] == ['enter', 'start']
    assert len(trigger['effects']) == 1, 'Only the recorded Patron saves; never all eight table rows'
    turn(table, match, FOE)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp < hp


@pytest.mark.parametrize('formula', ['Bitter Smoke', 'Mourning Myrrh', 'Calming Sandalwood', 'Dreaming Jasmine'])
def test_incense_damage_waits_for_the_formula_clock(tmp_path, formula):
    mid = 'tianxia.subpath.qi.incense_cultivator.feature.foundational_incenses'
    # Printed Bitter Smoke: "Enters the cloud for the first time during a
    # turn." / "Starts its turn inside the cloud." Mourning Myrrh:
    # "A hostile Spirit, Incorporeal creature, Possessing Entity, or Undead
    # starting its turn in the cloud makes a Charisma saving throw."
    foe = sheet([], cl=20)
    foe['identity']['creature_type'] = 'Spirit'
    combat, table, match = fixture(tmp_path, [mid], cl=20, ask=False,
                                  seed='ZONETICK1-INCENSE', owner_dc=100, foe_sheet=foe)
    engine = combat._load_session(match).engine
    hp = engine.state.actors[FOE].current_hp
    sequence = engine.state.event_sequence
    with placement_menu.query():
        choice = next(c for c in engine.legal_candidates()
                      if engine.action_catalog.get(c.source_definition_id)
                      and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == mid)
    settle(table, match, choice.candidate_id,
           picks={placement_menu.CHOICE: ['cell:6,6,0'], 'choice:needle.zone_incense_formula': [formula]})
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == hp
    assert not [e for e in engine.events if e.sequence > sequence and 'SAVE' in e.event_type]
    [zone] = [z for z in engine.state.zones.values() if z.active]
    assert zone.trigger_profile['profile']['formula'] == formula
    turn(table, match, FOE)
    engine = reload(tmp_path, match)
    if formula in ('Bitter Smoke', 'Mourning Myrrh'):
        assert engine.state.actors[FOE].current_hp < hp
    else:
        assert engine.state.actors[FOE].current_hp == hp
    assert len([e for e in engine.events if e.sequence > sequence and e.event_type == 'PASSIVE_TRIGGERED'
                and e.payload.get('trigger') == formula and e.payload.get('moment') == 'start']) == 1
