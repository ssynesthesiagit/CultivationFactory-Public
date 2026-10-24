"""Grant headings cannot spend actions; manual and plug-in actions remain."""
from copy import deepcopy
import json

import pytest

from combat import ext
from combat.action_publication import grant_heading
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.cw2_service_support import add_action
from tests.worker2_support import FOE, OWNER, candidate, fixture, reload, settle

BUNDLE = 'TAL_DAEMONIC_CULTIVATION_BASE_SPHERE_ABILITIES'
EMPTY = 'TAL_TEST_EMPTY_ACTION'


def _synthetic_record(**changes):
    authority = json.loads(TYPED_AUTHORITY.read_bytes())
    record = deepcopy(authority['mechanics'][BUNDLE])
    record.update(mechanic_id=EMPTY, name='Unimplemented Choice', kind='talent',
                  description=[], sphere_id=None, **changes)
    authority['mechanics'][EMPTY] = record
    document = sheet([])
    document['spheres_and_talents'] = {'learned_talent_record_ids': [EMPTY]}
    return document, authority


def _compile_synthetic(**changes):
    document, authority = _synthetic_record(**changes)
    return compile_character(document, actor_id=OWNER, typed_authority=authority)


def _synthetic_actions(bundle):
    return [action for action in bundle['action_catalog']
            if action.get('parameters', {}).get('typed', {}).get('source') == EMPTY]


def test_daemonic_heading_is_absent_from_compiled_and_cold_table_menu(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Defeat enemy', [{'type': 'damage', 'flat': 100,
                   'applies_to': 'target', 'damage_types': ['force']}])
    combat, table, mid = fixture(tmp_path, [BUNDLE], bundle_transform=prepare)
    names = [action.display_name for action in combat._load_session(mid).engine.action_catalog.values()]
    assert not any('Base Sphere Abilities' in name for name in names)
    assert 'Demon Seed' in names
    assert any('Daemonic Augment' in name for name in names)
    # Devour Essence is a triggered passive, not a spurious standalone card.
    before = reload(tmp_path, mid)
    assert any(row.get('feature_id') == 'TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE'
               for row in before.typed_passive_rows[OWNER])
    assert 'Base Sphere Abilities' not in json.dumps(table.state(mid)['menu'])
    settle(table, mid, candidate(combat, mid, 'Demon Seed').candidate_id)
    cold = CombatService(ROOT, tmp_path)
    cold_table = TabletopService(cold, tmp_path)
    assert 'Base Sphere Abilities' not in json.dumps(cold_table.state(mid)['menu'])
    engine = reload(tmp_path, mid)
    assert any(condition.condition_id == 'condition:typed.stance.demon_seed'
               for condition in engine.state.actors[OWNER].conditions.values())
    assert any('Daemonic Augment' in action.display_name for action in engine.action_catalog.values())
    assert any(row.get('feature_id') == 'TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE'
               for row in engine.typed_passive_rows[OWNER])
    prompts = settle(cold_table, mid, candidate(cold, mid, 'Defeat enemy', target=FOE).candidate_id)
    assert any('Devour Essence' in json.dumps(prompt) for prompt in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:named.devoured_essence'] > 0


def test_empty_effects_and_empty_payment_variants_are_not_published():
    assert not _synthetic_actions(_compile_synthetic())


def test_general_empty_action_stays_absent_after_table_commit_and_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_bundle=_compile_synthetic())
    assert 'Unimplemented Choice' not in json.dumps(table.state(mid)['menu'])
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    cold_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert 'Unimplemented Choice' not in json.dumps(cold_table.state(mid)['menu'])
    assert not any(action.parameters.get('typed', {}).get('source') == EMPTY
                   for action in reload(tmp_path, mid).action_catalog.values())


def test_grant_heading_is_structural_and_keeps_an_actual_effect():
    record = {'mechanic_id': 'parent', 'sphere_id': 'test', 'effects': [], 'riders': []}
    mechanics = {'first': {'name': 'First Gift', 'sphere_id': 'test'},
                 'second': {'name': 'Second Gift', 'sphere_id': 'test'}}
    text = ('### Starting Gifts\nWhen you learn Test Sphere, gain First Gift and Second Gift.\n'
            '#### First Gift\nAction Type: Bonus Action\n#### Second Gift\nAction Type: Action')
    assert grant_heading(record, text, mechanics)
    assert not grant_heading({**record, 'effects': [{'type': 'temp_hp', 'amount': 2}]}, text, mechanics)
    assert not grant_heading(record, text, {'first': mechanics['first']})


def test_empty_option_is_removed_but_a_real_option_remains():
    bundle = _compile_synthetic(options=[{'label': 'Empty', 'effects': []},
                                        {'label': 'Protect yourself', 'effects': [
                                            {'type': 'temp_hp', 'amount': 2, 'applies_to': 'self'}]}])
    actions = _synthetic_actions(bundle)
    assert actions and all('Protect yourself' in row['display_name'] for row in actions)


def test_empty_manual_rider_is_still_offered():
    actions = _synthetic_actions(_compile_synthetic(riders=['The GM decides whether the door opens.']))
    assert actions and all(row['parameters']['typed']['riders'] for row in actions)


def test_plugin_can_claim_only_its_owned_empty_action(monkeypatch):
    ext.subscribers('compile_action')  # load the normal providers before scoped registration
    def implements(action, info):
        if EMPTY in info['owned_ids'] and action.parameters.get('typed', {}).get('source') == EMPTY:
            return True
    monkeypatch.setitem(ext._HOOKS, 'empty_action_implemented', [implements])
    assert _synthetic_actions(_compile_synthetic())
    assert not implements(type('OtherAction', (), {'parameters': {'typed': {'source': 'other'}}})(),
                          {'owned_ids': [EMPTY]})


def test_existing_immortal_spirit_implementation_keeps_its_empty_marker():
    source = 'tianxia.path.spirit_awakening.feature.immortal_spirit'
    bundle = compile_character(sheet([source], cl=20), actor_id=OWNER)
    markers = [action for action in bundle['action_catalog']
               if action['parameters'].get('sovereign_identity_marker')]
    assert len(markers) == 1 and not markers[0]['parameters']['typed']['effects']
    unrelated = compile_character(sheet([]), actor_id=OWNER)
    assert not any(action['parameters'].get('sovereign_identity_marker') for action in unrelated['action_catalog'])


def test_existing_puppetry_object_actions_keep_their_empty_implemented_rows():
    bundle = compile_character(sheet(['PUPPETRY_BASE_THREAD_THE_OBJECT']), actor_id=OWNER)
    rows = [action for action in bundle['action_catalog'] if action['parameters'].get('thread_object_move')
            or action['parameters'].get('thread_object_door')]
    assert {row['display_name'] for row in rows} == {'Thread the Object: move object',
                                                  'Thread the Object: open/close simple door'}
    assert all(not row['parameters']['typed']['effects'] for row in rows)


@pytest.mark.parametrize('source', ['ASH_BASE_ASHFALL', 'DREAMS_BASE_DREAMSCAPE', 'FLOWERS_BASE_FRAGRANCE',
                                  'tianxia.talent.equipment.instant_harness',
                                  'tianxia.talent.equipment.armor_answers_the_soul'])
def test_zones_and_reviewed_gm_actions_survive(source):
    bundle = compile_character(sheet([source]), actor_id=OWNER)
    assert any(action['parameters'].get('typed', {}).get('source') == source
               for action in bundle['action_catalog'])


@pytest.mark.parametrize('source,name', [('FORMATIONS_BASE_PULSE_ARRAY', 'Pulse Array'),
                                       ('tianxia.talent.formations.disrupt_node', 'DISRUPT NODE')])
def test_plugin_replacement_does_not_keep_its_generic_placeholder(source, name):
    bundle = compile_character(sheet([source]), actor_id=OWNER)
    assert not any(action['display_name'] == name for action in bundle['action_catalog'])
    if source == 'FORMATIONS_BASE_PULSE_ARRAY':
        assert any('Pulse:' in action['display_name'] and action['parameters']['typed']['effects']
                   for action in bundle['action_catalog'])
    else:
        assert any(action['display_name'] == 'Disrupt Node' and not action['parameters']['typed']['effects']
                   for action in bundle['action_catalog'])
