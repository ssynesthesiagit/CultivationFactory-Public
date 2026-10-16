"""HUNT203: completed Moon-Sea events and Sunken Marsh opening turns."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_builtin_arenas import ROOT, _fight

from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.ext.moon_sea import GENERATE, POOL
from tests.h1_support import sheet
from tests.test_auto_paths import DIVINE_KING
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn


def _moon_fixture(tmp_path, *, transform=None, **kwargs):
    doc = sheet([GENERATE, 'TAL_WATER_WATER_SHIELD'], foundation=DIVINE_KING)
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def prepare(bundles):
        if transform:
            transform(bundles)
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)

    return fixture(tmp_path, ['TAL_WATER_WATER_SHIELD'], owner_bundle=bundle,
                   bundle_transform=prepare, **kwargs)


def _roll_action(bundles, *, kind='save', sphere='water', success=False):
    """A free visible manifestation delivered through the shared typed seams.

    No production ability is changed: this isolates generation from CP payment.
    Both sides still roll real dice and all effects commit through the table.
    """
    owner = next(b for b in bundles if b['actor_id'] == OWNER)
    base = next(a for a in owner['action_catalog'] if a['display_name'] == 'Shape Current: Mist Basin')
    action = deepcopy(base)
    source = 'action:test.h203.visible_roll'
    action.update(source_definition_id=source, display_name='Visible manifestation', target_kind='HOSTILE_ENTITY',
                  radius_ft=None, costs=[], range_ft=60)
    numbers = {**action['parameters']['typed']['numbers'], 'key_mod': -100 if success else 100,
               'save_dc': -100 if success else 100}
    consequence = [{'type': 'condition', 'condition': 'prone', 'applies_to': 'target',
                    'duration': 'until_end_of_next_turn'}]
    effect = ({'type': 'save', 'ability': 'str', 'dc': 'technique_save_dc',
               'applies_to': 'target', 'on_fail': consequence, 'on_success': []} if kind == 'save'
              else {'type': 'contest_against', 'actor_check': {'kind': 'cultivation'},
                    'target_check': {'kind': 'cultivation'}, 'on_success': consequence, 'on_fail': []})
    action['parameters'] = {'typed': {'source': source, 'sphere': 'tianxia.sphere.' + sphere,
        'numbers': numbers, 'duration': {'kind': 'instant'}, 'effects': [effect], 'riders': []}}
    owner['action_catalog'].append(action)
    owner['actor_template']['action_ids'].append(source)


@pytest.mark.parametrize('kind', ['save', 'check'])
def test_failed_hostile_roll_generates_after_its_consequences_and_reloads(tmp_path, kind):
    combat, table, mid = _moon_fixture(tmp_path, transform=lambda b: _roll_action(b, kind=kind))
    settle(table, mid, candidate(combat, mid, 'Visible manifestation', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    gained = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == POOL)
    prone = next(e for e in engine.events if e.event_type == 'CONDITION_APPLIED' and 'prone' in str(e.payload))
    assert prone.sequence < gained.sequence
    assert not any(r.get('feature_id') == GENERATE for r in engine.typed_reaction_rows[OWNER])
    assert len([r for r in engine.typed_passive_rows[OWNER] if r.get('feature_id') == GENERATE]) == 1


@pytest.mark.parametrize('kind,sphere,success', [('save', 'water', True), ('check', 'water', True),
                                               ('save', 'death', False)])
def test_successful_or_ineligible_roll_does_not_generate(tmp_path, kind, sphere, success):
    combat, table, mid = _moon_fixture(tmp_path, transform=lambda b: _roll_action(b, kind=kind, sphere=sphere, success=success))
    settle(table, mid, candidate(combat, mid, 'Visible manifestation', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0


def test_blinded_target_does_not_hide_a_visible_manifestation(tmp_path):
    def prepare(bundles):
        _roll_action(bundles)
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        action = next(a for a in owner['action_catalog'] if a['display_name'] == 'Visible manifestation')
        action['parameters']['typed']['effects'].insert(0,
            {'type': 'condition', 'condition': 'blinded', 'applies_to': 'target',
             'duration': 'until_end_of_next_turn'})
    combat, table, mid = _moon_fixture(tmp_path, transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Visible manifestation', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1


@pytest.mark.parametrize('at,expected', [((6, 6), 1), ((3, 10), 0)])
def test_paid_visible_basin_requires_meaningful_outward_use(tmp_path, at, expected):
    combat, table, mid = _moon_fixture(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=at).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99
    assert engine.state.actors[OWNER].resources[POOL] == expected


@pytest.mark.parametrize('target,accept', [(OWNER, True), (ALLY, True), (ALLY, False)])
def test_actual_water_shield_reduction_generates_for_provider(tmp_path, target, accept):
    from tests.test_auto38_water import prepare
    from tests.test_carry import KIT
    combat, table, mid = _moon_fixture(tmp_path, transform=prepare,
        foe_position={'x': 3, 'y': 5}, foe_kit={'starting_kit': {'items': [KIT['items'][-1]]}})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=target).candidate_id,
           {'choice:needle.water_shield': 'use' if accept else None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == int(accept)


def test_round_cap_and_expiry_survive_table_reload(tmp_path):
    from combat import pressure
    combat, table, mid = _moon_fixture(tmp_path, transform=_roll_action)
    settle(table, mid, candidate(combat, mid, 'Visible manifestation', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not pressure.generate(engine, engine.state.actors[OWNER], 'moon_sea_completed')
    # The resource lasts through this turn and the holder's next turn.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0


@pytest.mark.parametrize('manual_opening', [False, True])
def test_sunken_marsh_starts_and_commits_three_steps(tmp_path, manual_opening):
    combat, mid = _fight(tmp_path, 'battlefield:map.builtin-realm-sunken-marsh', size=2)
    table = TabletopService(combat, tmp_path)
    engine = combat._load_session(mid).engine
    assert engine.legal_candidates()
    if manual_opening:
        combat.set_controller_mode(mid, actor_id=engine.state.current_actor_id, controller_mode='MANUAL')
    else:
        # Automatic turns deliberately expose only a menu header. A playtest
        # driver must dispatch auto_step instead of treating it as no actions.
        assert table.state(mid)['menu']['manual'] is False
        assert not table.state(mid)['menu'].get('end_turn')
    for _ in range(3):
        state = table.state(mid)
        before, menu = state['last_sequence'], state['menu']
        response = (table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], before)
                    if menu['manual'] else table.auto_step(mid, before))
        assert response['status'] == 'COMMITTED', response
        assert response['state']['last_sequence'] > before
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.events
    assert cold.mechanical.replay()['status'] == 'PASS'
