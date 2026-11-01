"""Second-pass Talismans: service intents, committed setup, cold reload and replay."""
from copy import deepcopy
import pytest

from combat.canonical import canonical_sha256
from combat.ext.talismans import PREPARED, TALENT
from combat.ext.talisman_preparation import ADEPT, FAMILY_NAMES, LIBRARY, LIBRARY_SLOT
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, turn
from tests.test_auto2_talismans import execute, take, family
from tests.hunt12_support import send

EMBER = TALENT + 'ember_talisman'
HEALING = TALENT + 'healing_talisman'
SCRIPT = 'TALISMANS_BASE_READ_THE_SCRIPT'


def setup_choices(tmp_path, **choices):
    def transform(bundles):
        combat = CombatService(ROOT, tmp_path)
        bundles[0] = combat._with_prefight(bundles[0], {OWNER: [
            'setup-choice:' + key + ':' + str(value) for key, value in choices.items()]})
    return transform


def empty_prepared(tmp_path, *, family_name='Attack', benefit=3):
    def transform(bundles):
        for row in bundles[0]['actor_template']['resources']:
            if row['resource_id'] == PREPARED:
                row['initial'] = 0
        bundles[0]['bundle_sha256'] = canonical_sha256({k: v for k, v in bundles[0].items() if k != 'bundle_sha256'})
        setup_choices(tmp_path, library_family=FAMILY_NAMES.index(family_name) + 1, library_benefit=benefit)(bundles)
    return transform


def objects(monkeypatch, *, x=5, material='wood'):
    original = CombatService.factory_arenas
    def arenas(self, *args, **kwargs):
        result = deepcopy(original(self, *args, **kwargs))
        result['battlefield:factory_pillar_arena']['map_objects'] = [
            {'id': 1, 'x': x, 'y': 5, 'material': material, 'size': 'large', 'kind': 'crate',
             'resilient': True}]
        return result
    monkeypatch.setattr(CombatService, 'factory_arenas', arenas)


@pytest.mark.parametrize('cl,dice', [(1, 1), (5, 2), (11, 3), (17, 4)])
def test_ember_object_uses_printed_dice_consumes_and_cold_replays(tmp_path, monkeypatch, cl, dice):
    objects(monkeypatch)
    combat, table, mid = fixture(tmp_path, [EMBER], cl=cl)
    before = reload(tmp_path, mid)
    hp = before.state.objects['object:map.1'].current_hp
    prepared = before.state.actors[OWNER].resources[PREPARED]
    chosen = candidate(combat, mid, 'Ember Talisman', target='object:map.1')
    execute(combat, mid, chosen, dice=[15, *([5] * dice)])
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PREPARED] == prepared - 1
    assert engine.state.objects['object:map.1'].current_hp == hp - dice * 5
    assert not engine.state.actors[OWNER].action_available
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.target_ids == ('object:map.1',)]
    assert len(attacks) == 1
    assert not any(e.event_type == 'GM_RIDER' and e.source_definition_id.endswith(EMBER) for e in engine.events)


def test_ember_object_miss_still_consumes_and_far_objects_are_illegal(tmp_path, monkeypatch):
    objects(monkeypatch)
    combat, table, mid = fixture(tmp_path, [EMBER])
    prepared = reload(tmp_path, mid).state.actors[OWNER].resources[PREPARED]
    execute(combat, mid, candidate(combat, mid, 'Ember Talisman', target='object:map.1'), dice=[1])
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PREPARED] == prepared - 1
    assert not any(r.reason.startswith('DAMAGE:') for r in engine.rolls)
    objects(monkeypatch, x=17)
    combat, table, mid = fixture(tmp_path / 'far', [EMBER], positions={
        OWNER: {'x': 1, 'y': 5}, ALLY: {'x': 2, 'y': 5}, FOE: {'x': 3, 'y': 5}})
    assert not any(c.target_ids == ('object:map.1',) and c.display_name == 'Ember Talisman'
                   for c in combat._load_session(mid).engine.legal_candidates())
    execute(combat, mid, candidate(combat, mid, 'Ember Talisman', target=FOE))
    reload(tmp_path / 'far', mid)


def test_ember_object_applies_recorded_affinity_attack_bonus(tmp_path, monkeypatch):
    objects(monkeypatch)
    combat, table, mid = fixture(tmp_path, [EMBER, TALENT + 'talisman_affinity'])
    family(combat, table, mid, 'Attack')
    action = combat._load_session(mid).engine.action_catalog[candidate(combat, mid, 'Ember Talisman', target='object:map.1').source_definition_id]
    expected = action.parameters['typed']['numbers']['attack_bonus'] + 1
    take(combat, table, mid, 'Ember Talisman', 'object:map.1', {'choice:needle.talisman_affinity_benefit': 'attack'})
    engine = reload(tmp_path, mid)
    roll = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.target_ids == ('object:map.1',))
    assert roll.payload['modifier'] == expected


@pytest.mark.parametrize('initial,ready,expected', [(0, 1, 1), (0, 0, 0), (3, 1, 4)])
def test_hidden_sleeve_adept_readies_once_at_initiative(tmp_path, initial, ready, expected):
    combat, table, mid = fixture(tmp_path, [EMBER, TALENT + 'hidden_sleeve_preparation', ADEPT],
        bundle_transform=setup_choices(tmp_path, sleeve_starting_prepared=initial, sleeve_initiative_ready=ready))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[PREPARED] == expected
    assert owner.resource_maximums[PREPARED] == owner.proficiency_bonus + 2 + 2 + 1  # fixture INT 14
    assert owner.action_available and owner.bonus_action_available
    execute(combat, mid, next(c for c in engine.legal_candidates() if c.display_name == 'End turn'))
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[PREPARED] == expected
    assert len([e for e in reload(tmp_path, mid).events if e.event_type == 'RESOURCE_GAINED'
                and e.source_definition_id == ADEPT]) == int(ready == 1)


def test_hidden_sleeve_adept_cannot_exceed_limit_or_appear_without_ownership(tmp_path):
    combat, table, mid = fixture(tmp_path, [EMBER, ADEPT],
        bundle_transform=setup_choices(tmp_path, sleeve_initiative_ready=1))
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert owner.resources[PREPARED] == owner.resource_maximums[PREPARED]
    execute(combat, mid, candidate(combat, mid, 'Ember Talisman', target=FOE))
    reload(tmp_path, mid)
    combat, table, mid = fixture(tmp_path / 'unowned', [EMBER])
    bundle = combat._load_session(mid).engine.typed_bundle_documents[0]
    from combat.ext import query
    assert not any(row['id'].startswith('sleeve_') for rows in query('prefight_setup_choices', bundle) or [] for row in rows or [])


def test_library_extra_slot_cannot_activate_another_family_and_can_be_readied(tmp_path):
    combat, table, mid = fixture(tmp_path, [LIBRARY, EMBER, HEALING], bundle_transform=empty_prepared(tmp_path))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[PREPARED] == 0 and owner.resources[LIBRARY_SLOT] == 1
    assert not any(c.display_name == 'Healing Talisman' for c in engine.legal_candidates())
    execute(combat, mid, candidate(combat, mid, 'Ember Talisman', target=FOE))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[LIBRARY_SLOT] == 0
    assert not any(c.display_name == 'Ember Talisman' for c in engine.legal_candidates())
    execute(combat, mid, next(c for c in engine.legal_candidates() if c.display_name == 'End turn'))
    turn(table, mid, OWNER)
    execute(combat, mid, candidate(combat, mid, 'Ready a Formula Library talisman'))
    assert reload(tmp_path, mid).state.actors[OWNER].resources[LIBRARY_SLOT] == 1


@pytest.mark.parametrize('writing,mode', [('Attack', 'ADVANTAGE'), ('Binding', 'NORMAL'), ('unrecorded', 'NORMAL')])
def test_library_reading_advantage_scopes_to_recorded_family(tmp_path, writing, mode):
    combat, table, mid = fixture(tmp_path, [LIBRARY, SCRIPT], bundle_transform=setup_choices(
        tmp_path, library_family=FAMILY_NAMES.index('Attack') + 1, library_benefit=4))
    take(combat, table, mid, 'Read the Script', choices={
        'choice:needle.library_script_family': writing, 'choice:needle.read_script_skill': 'Arcana',
        'choice:needle.read_script_dc': 'clear and deliberate'})
    engine = reload(tmp_path, mid)
    roll = next(r for r in engine.rolls if r.reason.startswith('CHECK:') and r.reason.endswith(':Arcana'))
    assert roll.mode == mode


def test_library_crafting_benefit_does_not_grant_reading_advantage(tmp_path):
    combat, table, mid = fixture(tmp_path, [LIBRARY, SCRIPT], bundle_transform=setup_choices(
        tmp_path, library_family=FAMILY_NAMES.index('Attack') + 1, library_benefit=1))
    take(combat, table, mid, 'Read the Script')
    roll = next(r for r in reload(tmp_path, mid).rolls if r.reason.startswith('CHECK:'))
    assert roll.mode == 'NORMAL'


def test_ai_ember_with_ally_and_enemy_in_range_harms_only_enemy(tmp_path):
    combat, table, mid = fixture(tmp_path, [LIBRARY, EMBER, HEALING], bundle_transform=empty_prepared(tmp_path))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine = reload(tmp_path, mid)
    ally_hp = engine.state.actors[ALLY].current_hp
    owner_hp = engine.state.actors[OWNER].current_hp
    foe_hp = engine.state.actors[FOE].current_hp
    result = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED', result
    after = reload(tmp_path, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.source_definition_id.endswith(EMBER)
               and e.target_ids == (FOE,) for e in after.events)
    assert after.state.actors[ALLY].current_hp == ally_hp
    assert after.state.actors[OWNER].current_hp == owner_hp
    assert after.state.actors[FOE].current_hp < foe_hp
    assert after.state.actors[OWNER].resources[LIBRARY_SLOT] == 0


def test_ember_object_uses_elemental_type_and_one_paid_crafting_bonus(tmp_path, monkeypatch):
    objects(monkeypatch)
    combat, table, mid = fixture(tmp_path, [EMBER, TALENT + 'elemental_talisman'], cl=1)
    take(combat, table, mid, 'Elemental Talisman: choose a damage type', choices={
        'choice:needle.talisman_element': 'cold'})
    take(combat, table, mid, 'Ember Talisman', 'object:map.1', {
        'choice:needle.talisman_crafting': 'spent_cp'})
    engine = reload(tmp_path, mid)
    packet = next(e for e in engine.events if e.event_type == 'OBJECT_UPDATED'
                  and e.source_definition_id.endswith(EMBER) and e.target_ids == ('object:map.1',))
    assert packet.payload['damage']['kinds'] == 'cold'
    roll = next(r for r in engine.rolls if r.reason.startswith('DAMAGE:') and 'ember_talisman' in r.reason)
    assert roll.modifier == engine.state.actors[OWNER].proficiency_bonus


def test_ai_library_reading_does_not_invent_writing_family(tmp_path):
    combat, table, mid = fixture(tmp_path, [LIBRARY, SCRIPT], bundle_transform=setup_choices(
        tmp_path, library_family=FAMILY_NAMES.index('Attack') + 1, library_benefit=4))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    assert send(combat, table, mid, candidate(combat, mid, 'Read the Script'), auto=True)['status'] == 'COMMITTED'
    roll = next(r for r in reload(tmp_path, mid).rolls if r.reason.startswith('CHECK:'))
    assert roll.mode == 'NORMAL'


def test_library_prepared_talisman_can_supply_a_printed_wall_bundle(tmp_path):
    combat, table, mid = fixture(tmp_path, [LIBRARY, TALENT + 'talisman_wall'],
                                bundle_transform=empty_prepared(tmp_path))
    before = reload(tmp_path, mid).state.actors[OWNER].resources.copy()
    take(combat, table, mid, 'Talisman Wall', choices={'choice:needle.talisman_wall': '1'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[LIBRARY_SLOT] == 0
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before['resource:core.qi'] - 1
    walls = [z for z in engine.state.zones.values() if z.source_definition_id.endswith(TALENT + 'talisman_wall')]
    assert walls and all(z.trigger_profile['numbers']['talismans'] == 1 for z in walls)
