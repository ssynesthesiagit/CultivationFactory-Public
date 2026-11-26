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


def test_forced_step_moves_the_printed_center_the_same_way(tmp_path):
    # Iron Cavalry Front: "The front’s center moves at least 10 feet and then
    # enters a space within 5 feet of that creature." The trigger never says
    # the ten feet must be willing, so a pushed or pulled center moves the
    # printed way instead of sliding past every save.
    from combat.canonical import canonical_sha256
    pusher = 'actor:factory.worker2-foe1'

    def setup(bundles):
        bundle = next(b for b in bundles if b['actor_id'] == pusher)
        source = 'action:test.solid_pushaway'
        bundle['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Solid shove', 'owner_id': pusher,
            'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
            'costs': [], 'parameters': {'typed': {'source': 'test:solid_pushaway',
                'effects': [{'type': 'forced_movement', 'distance_ft': 10, 'direction': 'away'}],
                'numbers': {'cl': 20, 'save_dc': 0}, 'duration': {'kind': 'instant'}, 'riders': []},
                'expected_damage': 0}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, match = fixture(tmp_path, [
        'tianxia.subpath.qi.iron_rain_cavalry_saber_cultivator.feature.iron_cavalry_front'], cl=20,
        ask=False, seed='ZONETICK1-FORCED-FRONT', owner_dc=100, bundle_transform=setup, extra_foes=1,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 6, 'y': 6}, pusher: {'x': 0, 'y': 6}})
    engine = combat._load_session(match).engine
    choice = next(c for c in engine.legal_candidates()
                  if engine.action_catalog.get(c.source_definition_id)
                  and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source')
                  .endswith('iron_cavalry_front'))
    settle(table, match, choice.candidate_id)
    engine = reload(tmp_path, match)
    hp = engine.state.actors[FOE].current_hp
    turn(table, match, pusher)
    engine = combat._load_session(match).engine
    shove = next(c for c in engine.legal_candidates()
                 if c.source_definition_id == 'action:test.solid_pushaway' and c.target_ids == (OWNER,))
    settle(table, match, shove.candidate_id)
    engine = reload(tmp_path, match)
    assert engine.state.actors[OWNER].position == Position(x=5, y=6), 'the shove pushed its own printed ten feet'
    assert engine.state.actors[FOE].current_hp < hp, 'the front shocks the creature the push brought it next to'


def test_large_center_reach_uses_the_occupied_footprint(tmp_path, monkeypatch):
    # A 2x2 Large creature is every square it occupies. Heavenly Cavalry
    # Procession: "passes within 10 feet of it for the first time during a
    # turn". Standing two squares past the far corner of the footprint, the
    # moving center is fifteen feet from the creature's anchor but its closest
    # occupied square is exactly ten feet away — the creature's own squares
    # pass, an anchor-square comparison misses.
    from combat.footprints import ActorFootprintDefinition
    from combat.footprint_registry import ACTOR_FOOTPRINTS
    monkeypatch.setitem(ACTOR_FOOTPRINTS, FOE, ActorFootprintDefinition.rectangle(2, 2,
        footprint_id='test:zonetick1.large-foe', source_definition_id='test:zonetick1.large-foe'))
    mid = 'tianxia.subpath.qi.iron_rain_cavalry_saber_cultivator.feature.heavenly_cavalry_procession'
    combat, table, match = fixture(tmp_path, [mid], cl=20, ask=False,
        seed='ZONETICK1-LARGE-FRONT', owner_dc=100,
        positions={OWNER: {'x': 8, 'y': 8}, ALLY: {'x': 9, 'y': 8}, FOE: {'x': 5, 'y': 5}})
    engine = combat._load_session(match).engine
    assert engine._footprint(engine.state.actors[FOE]).width_cells == 2
    assert sorted(engine._actor_cells(engine.state.actors[FOE])) == [(5, 5), (5, 6), (6, 5), (6, 6)]
    hp = engine.state.actors[FOE].current_hp
    choice = next(c for c in engine.legal_candidates()
                  if engine.action_catalog.get(c.source_definition_id)
                  and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == mid)
    settle(table, match, choice.candidate_id)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == hp
    move = next(c for c in engine.legal_candidates()
                if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=7, y=8))
    settle(table, match, move.candidate_id)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp < hp, 'the Large creature counts its whole footprint for the reach'


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
        seed='ZONETICK1-LONG-GRAPPLE', bundle_transform=setup, foe_position={'x': 7, 'y': 6})
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


def test_tribulation_cloud_core_saves_cultivation_point_spend_inside(tmp_path):
    # Printed: "Spends Cultivation Points inside the field for the first time
    # during a turn." together with "A creature is affected once per turn."
    from combat.canonical import canonical_sha256
    from tests.worker2_support import sealed_native_attack
    mid = 'tianxia.subpath.qi.heaven_thunder_storm_soul.feature.tribulation_cloud_core'
    spend = 'action:test.spend_test_qi'

    def build_foe_sheet():
        document = sheet([], cl=20)
        stats = document['ability_scores_and_statistics']
        stats['hit_points']['maximum'] = 10000
        stats['abilities'] = [{**row, 'modifier': 1000} if row['ability'] == 'CON' else dict(row)
                              for row in stats['abilities']]
        return document

    def setup(bundles):
        foe = next(b for b in bundles if b['actor_id'] == FOE)
        foe['action_catalog'].append({
            'source_definition_id': spend, 'display_name': 'Spend test Qi', 'owner_id': FOE,
            'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'SELF', 'range_ft': 0,
            'costs': [['resource:core.qi', 1]], 'parameters': {'typed': {'source': 'test:spend_test_qi',
                'effects': [{'type': 'rider', 'evidence': 'test: this technique spends Cultivation Points'}],
                'numbers': {'cl': 20}, 'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 0}})
        foe['actor_template']['action_ids'].append(spend)
        foe['typed_reactions'].append({'block': 'generic', 'kind': 'damaged', 'feature_id': 'TEST_QI_SPENT_STANCE',
            'name': 'Overchannel discipline', 'ask': False, 'costs': [['resource:core.qi', 1]], 'range_ft': 60,
            'numbers': {'cl': 20, 'pb': 4},
            'effects': [{'type': 'rider', 'evidence': 'test: the discipline spends Qi when hurt'}]})
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        sealed_native_attack(owner, 'Bitting jab', damage_type='POISON', count=1, sides=4, modifier=0,
                             attack_bonus=20, range_ft=60)
        for bundle in (foe, owner):
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    def moments(engine):
        return [(e.payload.get('moment'), e.target_ids) for e in engine.events
                if e.event_type == 'PASSIVE_TRIGGERED' and (e.payload or {}).get('moment') in
                ('cp_spent', 'start') and (e.payload or {}).get('zone_id')]
    combat, table, match = fixture(tmp_path, [mid], cl=20, ask=False, seed='ZONETICK1-CP-SPEND',
                                  owner_dc=100, foe_sheet=build_foe_sheet(), bundle_transform=setup,
                                  positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 6, 'y': 6}})
    engine = combat._load_session(match).engine
    hp = engine.state.actors[FOE].current_hp
    with placement_menu.query():
        choice = next(c for c in engine.legal_candidates()
                      if engine.action_catalog.get(c.source_definition_id)
                      and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == mid)
    settle(table, match, choice.candidate_id, picks={placement_menu.CHOICE: ['cell:6,6,0']})
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp == hp, 'creating the cloud saves nobody'
    jab = next(c for c in engine.legal_candidates() if c.display_name == 'Bitting jab' and c.target_ids == (FOE,))
    settle(table, match, jab.candidate_id)
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp < hp, 'the Qi spend inside the cloud got its printed save'
    assert moments(engine).count(('cp_spent', (FOE,))) == 1
    assert moments(engine).count(('start', (FOE,))) == 0
    turn(table, match, FOE)
    engine = reload(tmp_path, match)
    # A new turn resets the shared "affected once per turn" clock on its own,
    # so the start trigger fires even after the Qi spend of the last turn.
    assert moments(engine).count(('start', (FOE,))) == 1
    # Inside the same turn: the start trigger already affected this creature.
    hit = engine.state.actors[FOE].current_hp
    technique = next(c for c in engine.legal_candidates() if c.source_definition_id == spend)
    settle(table, match, technique.candidate_id)
    engine = reload(tmp_path, match)
    assert moments(engine).count(('cp_spent', (FOE,))) == 1
    assert moments(engine).count(('start', (FOE,))) == 1
    assert engine.state.actors[FOE].current_hp == hit, 'the second spend of the turn still shares the once-per-turn clock'


def test_the_court_of_the_living_flame_extracts_extra_fire_once_per_turn(tmp_path):
    # Printed: enemies "take extra Fire damage equal to your Proficiency Bonus
    # the first time each turn they take Fire damage". The extra packet is
    # itself Fire damage and a second strike still answers within one turn.
    from tests.worker2_support import sealed_native_attack

    def setup(bundles):
        # The ally holds the burning blade so the domain's own Action cast and
        # the strikes stay separate activations on different turns.
        ally = next(b for b in bundles if b['actor_id'] == ALLY)
        sealed_native_attack(ally, 'Wandering flame jab', damage_type='FIRE', count=1, sides=6, modifier=0,
                             attack_bonus=20, range_ft=60, attacks=2)

    combat, table, match = fixture(tmp_path, ['tianxia.talent.fire.court_of_the_living_flame'], cl=20,
        ask=False, seed='ZONETICK1-LIVING-FLAME', owner_dc=100, bundle_transform=setup)
    engine = combat._load_session(match).engine
    cast = next(c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '')
                == 'Court of the Living Flame: Fire Damage')
    settle(table, match, cast.candidate_id)
    engine = reload(tmp_path, match)
    assert [z for z in engine.state.zones.values() if z.active], 'the court was cast'
    hp = engine.state.actors[FOE].current_hp
    turn(table, match, ALLY)
    engine = combat._load_session(match).engine
    jab = next(c for c in engine.legal_candidates()
               if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '')
               == 'Wandering flame jab' and c.target_ids == (FOE,))
    settle(table, match, jab.candidate_id)
    engine = reload(tmp_path, match)
    extra = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
             and e.payload.get('moment') == 'fire_damage' and e.target_ids == (FOE,)]
    assert engine.state.actors[FOE].current_hp < hp
    assert len(extra) == 1, 'one extra Fire packet: the packet itself and the second strike do not recursively retrigger'


DREAM_ASCENSION = 'tianxia.subpath.qi.dream_qi_cultivator.feature.dream_ascension'
DREAM_BURDEN_OPTIONS = [
    'No Reactions',
    'Speed reduced by 15 feet',
    'Disadvantage on its next attack',
    'Disadvantage on its next Concentration save',
    'No willing teleportation',
]
SIXTH_BURDEN_LABEL = 'No benefit from Invisible or ordinary visual concealment'


def _dream_ascension_action(bundle):
    return next(
        a for a in bundle['action_catalog']
        if a.get('parameters', {}).get('typed', {}).get('source') == DREAM_ASCENSION
    )


def _foe_high_hp_sheet(*, talents=(), wis=None, con=None, name=None):
    document = sheet(list(talents), cl=20, name=name)
    stats = document['ability_scores_and_statistics']
    stats['hit_points']['maximum'] = 400
    if wis is not None:
        stats.setdefault('saving_throws', {})['WIS'] = wis
    if con is not None:
        stats.setdefault('saving_throws', {})['CON'] = con
    return document


def _place_dream_ascension(combat, table, match, cell='cell:5,5,0'):
    engine = combat._load_session(match).engine
    with placement_menu.query():
        choice = next(
            c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].display_name == 'Dream Ascension'
        )
    settle(table, match, choice.candidate_id, picks={placement_menu.CHOICE: [cell]})


def _assert_only_burden(engine, selected):
    from combat import typed_reactions

    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert typed_reactions.can_react(engine, foe) is (selected != 'No Reactions')
    assert engine._effective_speed(foe) == (15 if selected == 'Speed reduced by 15 feet' else 30)
    assert engine._attack_mode(foe, owner) == (
        'DISADVANTAGE' if selected == 'Disadvantage on its next attack' else 'NORMAL'
    )
    has_conc = any(
        c.condition_id == 'condition:typed.concentration_mode'
        and (c.data or {}).get('rule', {}).get('concentration_mode') == 'DISADVANTAGE'
        for c in foe.conditions.values()
    )
    assert has_conc is (selected == 'Disadvantage on its next Concentration save')
    has_no_tp = any(c.condition_id == 'condition:typed.cannot_willingly_teleport' for c in foe.conditions.values())
    assert has_no_tp is (selected == 'No willing teleportation')
    has_no_invis = any(c.condition_id == 'condition:typed.no_invisible_benefit' for c in foe.conditions.values())
    assert has_no_invis is (selected == SIXTH_BURDEN_LABEL)


def _burden_expiry(engine, selected):
    foe = engine.state.actors[FOE]
    if selected == 'No Reactions':
        return next(c.expires_on for c in foe.conditions.values() if c.condition_id == 'condition:typed.reaction_denied')
    if selected == 'Speed reduced by 15 feet':
        return next(m.expires_on for m in foe.modifiers.values() if m.target_field == 'speed_ft' and int(m.value) == -15)
    if selected == 'Disadvantage on its next attack':
        return next(m.expires_on for m in foe.modifiers.values() if m.target_field == 'attack_mode' and m.value == 'DISADVANTAGE')
    if selected == 'Disadvantage on its next Concentration save':
        return next(c.expires_on for c in foe.conditions.values() if c.condition_id == 'condition:typed.concentration_mode')
    if selected == 'No willing teleportation':
        return next(c.expires_on for c in foe.conditions.values() if c.condition_id == 'condition:typed.cannot_willingly_teleport')
    return next(c.expires_on for c in foe.conditions.values() if c.condition_id == 'condition:typed.no_invisible_benefit')


def _advance_ending_into_foe_turn(combat, table, match, label):
    while True:
        menu = table.state(match)['menu']
        cur = menu['actor_id']
        engine = combat._load_session(match).engine
        next_idx = (engine.state.initiative_order.index(cur) + 1) % len(engine.state.initiative_order)
        if engine.state.initiative_order[next_idx] == FOE:
            return settle(table, match, menu['end_turn'], picks={'choice:needle.effect_choices': label})
        settle(table, match, menu['end_turn'])


def test_dream_ascension_burden_compiles_shared_failed_save_choice():
    bundle = compile_character(sheet([DREAM_ASCENSION], cl=20), actor_id=OWNER)
    action = _dream_ascension_action(bundle)
    typed = action['parameters']['typed']
    triggers = typed['zone_spec']['triggers']
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger['on'] == ['enter', 'start']
    assert trigger['who'] == 'hostile'
    assert trigger.get('choice_owner') == 'source'
    assert len(trigger['effects']) == 1
    save = trigger['effects'][0]
    assert save['type'] == 'save' and save['ability'] == 'wis' and save['dc'] == 'technique_save_dc'
    assert len(save['on_fail']) == 2
    dmg, choice = save['on_fail']
    assert dmg['type'] == 'damage' and dmg['dice'] == {'count': 4, 'sides': 8} and dmg['damage_types'] == ['psychic']
    assert choice['type'] == 'choose_effects'
    assert choice['name'] == 'Dream Burden'
    assert choice['count'] == 1
    assert choice['result'] == 'failed its Wisdom save'
    options = choice['options']
    assert [opt['label'] for opt in options] == [*DREAM_BURDEN_OPTIONS, SIXTH_BURDEN_LABEL]
    assert options[0]['effects'][0]['type'] == 'reaction_denied'
    assert options[1]['effects'][0]['type'] == 'speed' and options[1]['effects'][0]['flat'] == -15
    assert options[2]['effects'][0]['type'] == 'disadvantage'
    assert options[2]['effects'][0]['roll_target']['kind'] == 'attack' and options[2]['effects'][0]['roll_target']['next'] is True
    assert options[3]['effects'][0]['type'] == 'disadvantage'
    assert options[3]['effects'][0]['roll_target']['kind'] == 'concentration' and options[3]['effects'][0]['roll_target']['next'] is True
    assert options[4]['effects'][0]['type'] == 'condition' and options[4]['effects'][0]['condition'] == 'cannot_willingly_teleport'
    for opt in options[:5]:
        assert opt['effects'][0]['applies_to'] == 'target'
        assert opt['effects'][0]['expires_on'] == 'START_OF_TARGET_NEXT_TURN'
    sixth = options[5]['effects']
    assert sixth[0]['type'] == 'no_invisible_benefit'
    assert sixth[0]['applies_to'] == 'target'
    assert sixth[0]['expires_on'] == 'START_OF_TARGET_NEXT_TURN'
    assert sixth[1]['type'] == 'rider' and 'ordinary visual concealment' in sixth[1]['evidence']
    assert len(save['on_success']) == 1
    assert save['on_success'][0]['type'] == 'half_damage' and save['on_success'][0]['damage_types'] == ['psychic']

    riders = mechanics()[DREAM_ASCENSION]['riders']
    assert riders and 'apply one by hand' not in riders[0]
    assert 'ordinary visual concealment is not automated' in riders[0]
    assert 'other five alternatives are typed failed-save choices' in riders[0]
    assert 'Ascendant Dreamer' in riders[0]
    assert 'Dream Roads and Lucid Revision are GM-adjudicated.' in riders[0]


@pytest.mark.parametrize('label', DREAM_BURDEN_OPTIONS)
def test_dream_ascension_burden_choice_commits_and_cold_reloads(tmp_path, label):
    from combat import roll_reasons
    from tests.worker2_support import NAMED, sealed_native_attack

    def setup(bundles):
        foe_b = next(b for b in bundles if b['actor_id'] == FOE)
        ally_b = next(b for b in bundles if b['actor_id'] == ALLY)
        sealed_native_attack(foe_b, 'Foe jab', damage_type='SLASHING', count=1, sides=6, modifier=2,
                             attack_bonus=10, range_ft=60, attacks=2)
        sealed_native_attack(ally_b, 'Ally poke', damage_type='FIRE', count=1, sides=6, modifier=2,
                             attack_bonus=50, range_ft=60, attacks=2)

    foe_doc = _foe_high_hp_sheet(talents=['TAL_SPACE_FOLD_STEP', 'TAL_SOUND_DAMPEN_SOUND'], con=50, name=NAMED[2])
    combat, table, match = fixture(
        tmp_path, [DREAM_ASCENSION, 'tianxia.talent.space.spatial_displacement'], cl=20, ask=True, seed='DREAM-BURDEN-' + label,
        owner_dc=100, named=True, foe_sheet=foe_doc, bundle_transform=setup,
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 2, 'y': 5}, FOE: {'x': 5, 'y': 5}},
    )
    engine = combat._load_session(match).engine
    before_hp = engine.state.actors[FOE].current_hp
    seq = engine.state.event_sequence
    _place_dream_ascension(combat, table, match, cell='cell:5,5,0')
    prompts = _advance_ending_into_foe_turn(combat, table, match, label)

    choice_prompts = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.effect_choices']
    assert len(choice_prompts) == 1
    prompt = choice_prompts[0]
    assert prompt['context']['reactor_id'] == OWNER
    assert prompt['reactor'] == NAMED[0]
    assert prompt['affected'] == NAMED[2]
    assert NAMED[2] in prompt['moment'] and 'Dream Burden' in prompt['moment']

    engine = reload(tmp_path, match)
    foe = engine.state.actors[FOE]
    assert foe.current_hp < before_hp
    assert [z for z in engine.state.zones.values() if z.active]
    dmg_rolled = [e for e in engine.events if e.sequence > seq and e.event_type == 'DAMAGE_ROLLED']
    dmg_committed = [e for e in engine.events if e.sequence > seq and e.event_type == 'DAMAGE_COMMITTED'
                     and e.target_ids == (FOE,)]
    assert len(dmg_rolled) == 1 and dmg_rolled[0].payload['expression'].startswith('4d8')
    assert len(dmg_committed) == 1

    expected_expiry = f'START_OF_TURN_AT:{FOE}:{foe.turns_started + 1}'
    assert _burden_expiry(engine, label) == expected_expiry
    _assert_only_burden(engine, label)

    if label == 'Disadvantage on its next attack':
        assert engine._attack_mode(foe, engine.state.actors[OWNER]) == 'DISADVANTAGE'
        jab = next(c for c in engine.legal_candidates()
                   if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Foe jab'
                   and c.target_ids == (OWNER,))
        settle(table, match, jab.candidate_id)
        engine = reload(tmp_path, match)
        atk_modes = [e.payload['mode'] for e in engine.events if e.sequence > seq and e.event_type == 'ATTACK_ROLLED']
        assert atk_modes == ['DISADVANTAGE', 'NORMAL']
        assert engine._attack_mode(engine.state.actors[FOE], engine.state.actors[OWNER]) == 'NORMAL'
    elif label == 'Disadvantage on its next Concentration save':
        assert any('concentration' in line.lower() and 'disadvantage' in line.lower()
                   for line in roll_reasons.standing(engine, foe))
        dampen = next(c for c in engine.legal_candidates()
                      if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Dampen Sound'
                      and c.destination == foe.position)
        settle(table, match, dampen.candidate_id)
        turn(table, match, ALLY)
        engine = combat._load_session(match).engine
        poke = next(c for c in engine.legal_candidates()
                    if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Ally poke'
                    and c.target_ids == (FOE,))
        settle(table, match, poke.candidate_id)
        engine = reload(tmp_path, match)
        conc_modes = [e.payload['mode'] for e in engine.events
                      if e.sequence > seq and e.event_type == 'SAVE_ROLLED'
                      and e.source_definition_id == 'system:combat.concentration']
        assert conc_modes == ['DISADVANTAGE', 'NORMAL']
        assert not any(c.condition_id == 'condition:typed.concentration_mode'
                       for c in engine.state.actors[FOE].conditions.values())
    elif label == 'No willing teleportation':
        start_pos = foe.position
        fold = next(c for c in engine.legal_candidates()
                    if c.display_name.startswith('Fold Step') and c.destination != start_pos)
        settle(table, match, fold.candidate_id, picks={'choice:needle.teleport_destination': ['cell:6,5,0']})
        engine = reload(tmp_path, match)
        assert engine.state.actors[FOE].position == start_pos
        assert any(e.event_type == 'GM_RIDER' and 'sealed against teleportation' in (e.payload or {}).get('rider', '')
                   for e in engine.events if e.sequence > seq)
        turn(table, match, OWNER)
        engine = reload(tmp_path, match)
        assert _burden_expiry(engine, label) == expected_expiry
        displacement = next(c for c in engine.legal_candidates()
                            if c.display_name.startswith('Spatial Displacement') and FOE in c.target_ids)
        displacement_seq = engine.state.event_sequence
        prompts = settle(table, match, displacement.candidate_id,
                         picks={'choice:needle.subject_destination': 'first'})
        assert any(p['context']['reaction_source_id'] == 'choice:needle.subject_destination' for p in prompts)
        engine = reload(tmp_path, match)
        assert engine.state.actors[FOE].position != start_pos
        assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE
                   and e.payload.get('teleport') is True for e in engine.events if e.sequence > displacement_seq)
        assert _burden_expiry(engine, label) == expected_expiry


@pytest.mark.parametrize('label', DREAM_BURDEN_OPTIONS)
def test_dream_ascension_burden_expires_at_recipient_next_start(tmp_path, label):
    foe_doc = _foe_high_hp_sheet()
    combat, table, match = fixture(
        tmp_path, [DREAM_ASCENSION], cl=20, ask=True, seed='DREAM-EXPIRY-' + label,
        owner_dc=100, foe_sheet=foe_doc,
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 2, 'y': 5}, FOE: {'x': 5, 'y': 5}},
    )
    _place_dream_ascension(combat, table, match, cell='cell:12,5,0')
    turn(table, match, FOE)

    engine = combat._load_session(match).engine
    foe_turn = engine.state.actors[FOE].turns_started
    move_in = next(c for c in engine.legal_candidates()
                   if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=6, y=5))
    settle(table, match, move_in.candidate_id, picks={'choice:needle.effect_choices': label})

    engine = combat._load_session(match).engine
    move_out = next(c for c in engine.legal_candidates()
                    if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=5, y=5))
    settle(table, match, move_out.candidate_id)

    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].position == Position(x=5, y=5)
    assert _burden_expiry(engine, label) == f'START_OF_TURN_AT:{FOE}:{foe_turn + 1}'
    _assert_only_burden(engine, label)

    saw_owner_turn = False
    for _ in range(10):
        menu = table.state(match)['menu']
        settle(table, match, menu['end_turn'])
        engine = reload(tmp_path, match)
        if engine.state.current_actor_id == FOE:
            break
        if engine.state.current_actor_id == OWNER:
            saw_owner_turn = True
            _assert_only_burden(engine, label)
    assert saw_owner_turn
    assert engine.state.current_actor_id == FOE
    assert engine.state.actors[FOE].turns_started == foe_turn + 1
    _assert_only_burden(engine, None)


@pytest.mark.parametrize('label', ['Disadvantage on its next attack', 'Disadvantage on its next Concentration save'])
def test_dream_ascension_burden_next_roll_consumes_once(tmp_path, label):
    from combat.canonical import canonical_sha256
    from tests.worker2_support import sealed_native_attack

    con_check_id = 'action:test.ordinary_con_save'

    def setup(bundles):
        foe_b = next(b for b in bundles if b['actor_id'] == FOE)
        owner_b = next(b for b in bundles if b['actor_id'] == OWNER)
        ally_b = next(b for b in bundles if b['actor_id'] == ALLY)
        sealed_native_attack(foe_b, 'Foe jab', damage_type='SLASHING', count=1, sides=6, modifier=2,
                             attack_bonus=10, range_ft=60, attacks=1)
        sealed_native_attack(owner_b, 'Owner poke', damage_type='FIRE', count=1, sides=6, modifier=2,
                             attack_bonus=50, range_ft=60, attacks=1)
        sealed_native_attack(ally_b, 'Ally poke', damage_type='FIRE', count=1, sides=6, modifier=2,
                             attack_bonus=50, range_ft=60, attacks=1)
        owner_b['action_catalog'].append({
            'source_definition_id': con_check_id, 'display_name': 'Ordinary CON save', 'owner_id': OWNER,
            'economy': 'BONUS_ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
            'costs': [], 'parameters': {'typed': {'source': 'test:ordinary_con_save',
                'effects': [{'type': 'save', 'ability': 'con', 'applies_to': 'target', 'on_fail': [], 'on_success': []}],
                'numbers': {'cl': 20, 'save_dc': 10}, 'duration': {'kind': 'instant'}, 'riders': []},
                'expected_damage': 0},
        })
        owner_b['actor_template']['action_ids'].append(con_check_id)
        for bundle in (foe_b, owner_b, ally_b):
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    foe_doc = _foe_high_hp_sheet(talents=['TAL_SOUND_DAMPEN_SOUND'], con=50)
    combat, table, match = fixture(
        tmp_path, [DREAM_ASCENSION], cl=20, ask=False, seed='DREAM-NEXTROLL-' + label,
        owner_dc=100, foe_sheet=foe_doc, bundle_transform=setup,
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 5, 'y': 6}, FOE: {'x': 5, 'y': 5}},
    )
    _place_dream_ascension(combat, table, match, cell='cell:12,5,0')
    turn(table, match, FOE)

    engine = combat._load_session(match).engine
    foe_turn = engine.state.actors[FOE].turns_started
    if label == 'Disadvantage on its next Concentration save':
        dampen = next(c for c in engine.legal_candidates()
                      if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Dampen Sound'
                      and c.destination == Position(x=5, y=5))
        settle(table, match, dampen.candidate_id)

    engine = combat._load_session(match).engine
    move_in = next(c for c in engine.legal_candidates()
                   if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=6, y=5))
    settle(table, match, move_in.candidate_id, picks={'choice:needle.effect_choices': label})

    engine = combat._load_session(match).engine
    move_out = next(c for c in engine.legal_candidates()
                    if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=5, y=5))
    settle(table, match, move_out.candidate_id)
    engine = reload(tmp_path, match)
    seq = engine.state.event_sequence

    if label == 'Disadvantage on its next attack':
        jab = next(c for c in engine.legal_candidates()
                   if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Foe jab'
                   and c.target_ids == (OWNER,))
        settle(table, match, jab.candidate_id)
        engine = reload(tmp_path, match)
        roll1 = [e for e in engine.events if e.sequence > seq and e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
        assert [e.payload['mode'] for e in roll1] == ['DISADVANTAGE']
        assert engine._attack_mode(engine.state.actors[FOE], engine.state.actors[OWNER]) == 'NORMAL'

        turn(table, match, ALLY)
        engine = combat._load_session(match).engine
        assert engine.state.actors[FOE].turns_started == foe_turn
        ally_move = next(c for c in engine.legal_candidates()
                         if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=5, y=8))
        settle(table, match, ally_move.candidate_id)
        engine = reload(tmp_path, match)
        rolls = [e for e in engine.events if e.sequence > seq and e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
        assert [e.payload['mode'] for e in rolls] == ['DISADVANTAGE', 'NORMAL']
        assert engine.state.actors[FOE].turns_started == foe_turn
    else:
        turn(table, match, OWNER)
        engine = combat._load_session(match).engine
        assert engine.state.actors[FOE].turns_started == foe_turn
        ord_con = next(c for c in engine.legal_candidates()
                       if c.source_definition_id == con_check_id and c.target_ids == (FOE,))
        settle(table, match, ord_con.candidate_id)
        engine = reload(tmp_path, match)
        ord_saves = [e for e in engine.events if e.sequence > seq and e.event_type == 'SAVE_ROLLED'
                     and e.source_definition_id == con_check_id]
        assert [e.payload['mode'] for e in ord_saves] == ['NORMAL']
        _assert_only_burden(engine, label)

        poke1 = next(c for c in engine.legal_candidates()
                     if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Owner poke'
                     and c.target_ids == (FOE,))
        settle(table, match, poke1.candidate_id)
        engine = reload(tmp_path, match)
        conc1 = [e for e in engine.events if e.sequence > seq and e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id == 'system:combat.concentration']
        assert [e.payload['mode'] for e in conc1] == ['DISADVANTAGE']

        turn(table, match, ALLY)
        engine = combat._load_session(match).engine
        assert engine.state.actors[FOE].turns_started == foe_turn
        poke2 = next(c for c in engine.legal_candidates()
                     if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Ally poke'
                     and c.target_ids == (FOE,))
        settle(table, match, poke2.candidate_id)
        engine = reload(tmp_path, match)
        conc2 = [e for e in engine.events if e.sequence > seq and e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id == 'system:combat.concentration']
        assert [e.payload['mode'] for e in conc2] == ['DISADVANTAGE', 'NORMAL']
        assert engine.state.actors[FOE].turns_started == foe_turn


def test_dream_ascension_burden_success_and_once_per_turn(tmp_path):
    combat, table, match = fixture(
        tmp_path / 'success', [DREAM_ASCENSION], cl=20, ask=True, seed='DREAM-SUCCESS',
        owner_dc=10, foe_sheet=_foe_high_hp_sheet(wis=100),
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 2, 'y': 5}, FOE: {'x': 5, 'y': 5}},
    )
    _place_dream_ascension(combat, table, match, cell='cell:12,5,0')
    turn(table, match, FOE)
    engine = combat._load_session(match).engine
    before_hp = engine.state.actors[FOE].current_hp
    seq = engine.state.event_sequence
    move_in = next(c for c in engine.legal_candidates()
                   if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=6, y=5))
    prompts = settle(table, match, move_in.candidate_id)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.effect_choices' for p in prompts)
    engine = reload(tmp_path / 'success', match)
    saves = [e for e in engine.events if e.sequence > seq and e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]
    assert len(saves) == 1 and saves[0].payload['success'] is True
    assert engine.state.actors[FOE].current_hp < before_hp
    _assert_only_burden(engine, None)

    combat2, table2, match2 = fixture(
        tmp_path / 'reentry', [DREAM_ASCENSION], cl=20, ask=True, seed='DREAM-REENTRY',
        owner_dc=100, foe_sheet=_foe_high_hp_sheet(),
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 2, 'y': 5}, FOE: {'x': 5, 'y': 5}},
    )
    _place_dream_ascension(combat2, table2, match2, cell='cell:12,5,0')
    turn(table2, match2, FOE)
    engine2 = combat2._load_session(match2).engine
    seq2 = engine2.state.event_sequence
    enter1 = next(c for c in engine2.legal_candidates()
                  if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=6, y=5))
    settle(table2, match2, enter1.candidate_id, picks={'choice:needle.effect_choices': 'No Reactions'})
    engine2 = reload(tmp_path / 'reentry', match2)
    hp_after_first = engine2.state.actors[FOE].current_hp
    assert len([e for e in engine2.events if e.sequence > seq2 and e.event_type == 'SAVE_ROLLED']) == 1
    assert len([e for e in engine2.events if e.sequence > seq2 and e.event_type == 'DAMAGE_COMMITTED']) == 1

    leave1 = next(c for c in engine2.legal_candidates()
                  if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=5, y=5))
    settle(table2, match2, leave1.candidate_id)
    engine2 = reload(tmp_path / 'reentry', match2)
    enter2 = next(c for c in engine2.legal_candidates()
                  if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=6, y=5))
    reentry_prompts = settle(table2, match2, enter2.candidate_id)
    assert not reentry_prompts
    engine2 = reload(tmp_path / 'reentry', match2)
    assert engine2.state.actors[FOE].current_hp == hp_after_first
    assert len([e for e in engine2.events if e.sequence > seq2 and e.event_type == 'SAVE_ROLLED']) == 1
    assert len([e for e in engine2.events if e.sequence > seq2 and e.event_type == 'DAMAGE_COMMITTED']) == 1


def test_dream_ascension_burden_source_choice_enrollment(tmp_path):
    from combat.ext import effect_choices

    combat, table, match = fixture(
        tmp_path, [DREAM_ASCENSION], cl=20, ask=False, seed='DREAM-ENROLL',
        owner_dc=100, named=True, modes={OWNER: 'MANUAL', ALLY: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO'},
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 2, 'y': 5}, FOE: {'x': 5, 'y': 5}},
    )
    engine = combat._load_session(match).engine
    assert OWNER not in effect_choices.zone_choice_owners(engine)
    assert OWNER not in engine.typed_ask_reactors

    _place_dream_ascension(combat, table, match, cell='cell:5,5,0')
    engine = reload(tmp_path, match)
    assert OWNER in effect_choices.zone_choice_owners(engine)
    assert OWNER in engine.typed_ask_reactors
    before_hp = engine.state.actors[FOE].current_hp

    settle(table, match, table.state(match)['menu']['end_turn'])
    paused_prompt = None
    for _ in range(12):
        res = table.auto_step(match, 0, [])
        if res['status'] == 'REACTION_REQUIRED':
            paused_prompt = res['reaction']
            break
    assert paused_prompt is not None
    assert paused_prompt['context']['reactor_id'] == OWNER
    assert paused_prompt['context']['reaction_source_id'] == 'choice:needle.effect_choices'

    # The turn-boundary transaction has not committed before OWNER's choice is answered.
    mid_engine = reload(tmp_path, match)
    assert mid_engine.state.actors[FOE].current_hp == before_hp
    _assert_only_burden(mid_engine, None)

    answer = {**paused_prompt['context'], 'selection': 'USE', 'option_ids': ['No Reactions']}
    committed = table.auto_step(match, 0, [answer])
    assert committed['status'] == 'COMMITTED'
    after_engine = reload(tmp_path, match)
    assert after_engine.state.actors[FOE].current_hp < before_hp
    _assert_only_burden(after_engine, 'No Reactions')


def test_dream_ascension_burden_invisible_half_applies(tmp_path):
    from combat import senses
    from tests.worker2_support import candidate, sealed_native_attack

    def setup(bundles):
        owner_b = next(b for b in bundles if b['actor_id'] == OWNER)
        sealed_native_attack(owner_b, 'Owner strike', damage_type='SLASHING', count=1, sides=6, modifier=2,
                             attack_bonus=15, range_ft=60, attacks=1)

    foe_doc = _foe_high_hp_sheet(
        talents=['tianxia.subpath.qi.ninpo_adept.feature.vanishing_technique'],
        con=100,
    )
    combat, table, match = fixture(
        tmp_path, [DREAM_ASCENSION], cl=20, ask=True, seed='DREAM-INVISIBLE-HALF',
        owner_dc=100, foe_sheet=foe_doc, bundle_transform=setup,
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 2, 'y': 5}, FOE: {'x': 5, 'y': 5}},
    )
    _place_dream_ascension(combat, table, match, cell='cell:12,5,0')
    turn(table, match, FOE)

    vanish = candidate(combat, match, 'Vanishing Technique')
    settle(table, match, vanish.candidate_id)
    engine = reload(tmp_path, match)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    invisible_ids = {iid for iid, c in foe.conditions.items() if c.condition_id == 'condition:typed.invisible'}
    assert invisible_ids
    assert not (invisible_ids & senses.masked_conditions(engine, owner, foe).get(FOE, set()))
    assert engine._attack_mode(owner, foe) == 'DISADVANTAGE'

    foe_turn = foe.turns_started
    seq = engine.state.event_sequence
    move_in = next(c for c in engine.legal_candidates()
                   if str(c.kind) in ('MOVE', 'CandidateKind.MOVE') and c.destination == Position(x=6, y=5))
    settle(table, match, move_in.candidate_id, picks={'choice:needle.effect_choices': SIXTH_BURDEN_LABEL})

    engine = reload(tmp_path, match)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert _burden_expiry(engine, SIXTH_BURDEN_LABEL) == f'START_OF_TURN_AT:{FOE}:{foe_turn + 1}'
    _assert_only_burden(engine, SIXTH_BURDEN_LABEL)
    assert invisible_ids <= set(foe.conditions)
    assert invisible_ids <= senses.masked_conditions(engine, owner, foe).get(FOE, set())
    assert engine._attack_mode(owner, foe) == 'NORMAL'
    assert engine._attack_mode(foe, owner) == 'NORMAL'
    assert any(
        e.sequence > seq and e.event_type == 'GM_RIDER'
        and 'ordinary visual concealment' in (e.payload or {}).get('rider', '')
        for e in engine.events
    )

    turn(table, match, OWNER)
    strike = candidate(combat, match, 'Owner strike', target=FOE)
    settle(table, match, strike.candidate_id)
    engine = reload(tmp_path, match)
    atk = [e for e in engine.events if e.sequence > seq and e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert [e.payload['mode'] for e in atk] == ['NORMAL']
