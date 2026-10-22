"""Portable table regressions for real shields, asset prisons and field extent.

Only synthetic sheets/maps and public source fixtures; no history or live clients.
The printed prison rule forbids fields *beyond* the prison, not contained fields.
"""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.ext import orbiting_shield_warden as w
from combat.ext import object_subjects
from combat.ext.qi_path import ARMAMENT
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import r1i_service_support as s
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_orbiting_shield_warden_floor58 import record_native_shield_profile

QI = 'resource:core.qi'


def seal(bundle):
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def extra(bundle, key, *, effects, zone=None, target='SELF'):
    aid = 'test:warden.f9.' + key
    typed = {'source': aid, 'numbers': {'cl': 18, 'pb': 6, 'key_mod': 4, 'save_dc': 50, 'attack_bonus': 100},
             'effects': effects, 'duration': {'kind': 'instant'}, 'riders': []}
    if zone:
        typed['zone_spec'] = zone
    bundle['action_catalog'].append({'source_definition_id': aid, 'display_name': key,
        'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
        'target_kind': target, 'range_ft': 90, 'parameters': {'typed': typed}})
    bundle['actor_template']['action_ids'].append(aid)
    seal(bundle)


def bundles():
    out = []
    for aid, features in ((s.OWNER, list(w.LEVELS) + [ARMAMENT, 'SHIELD_BASE_SHIELD_TRAINING']), (s.FOE, [])):
        doc = sheet(features, cl=18, dc=50, kit={'starting_kit': {'items': [
            {'item_id': 'tianxia.mortal.armor.shield', 'quantity': 1}]}} if aid == s.OWNER else None)
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        out.append(compile_character(doc, actor_id=aid))
    return out


def commit(table, mid, cid, select=None):
    answers = []
    for _ in range(60):
        menu = table.state(mid)['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        if prompt.get('choice'):
            choice = prompt['choice']
            ids = [o['id'] for o in choice['options']]
            picked = select(prompt, ids) if select else None
            if picked is None:
                picked = ids[:choice.get('minimum_selections', 1)] if not choice.get('allow_decline') else []
            if picked:
                answer.update(selection='USE', option_ids=picked)
        answers.append(answer)
    raise AssertionError('unresolved table choice')


def advance(table, mid, actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        commit(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('turn not reached')


def cold(combat, mid):
    session = CombatService(ROOT, combat.data_root)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def fresh(combat, mid):
    session = combat._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def arena(combat):
    saved = combat.tabletop_maps.save({'display_name': 'Warden F9', 'width_squares': 30,
        'height_squares': 20, 'walls': [], 'terrain': [], 'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]}})
    return combat.factory_arenas()['battlefield:map.' + saved['map_id']]


def match(tmp_path, *, objects=(), field_sizes=()):
    packs = bundles()
    for size in field_sizes:
        extra(packs[1], 'Field ' + str(size), effects=[{'type': 'zone'}],
              zone={'name': 'Field ' + str(size), 'centered_on_self': True, 'shape': 'cube',
                    'size_ft': size, 'duration': {'kind': 'one_minute'}})
    extra(packs[0], 'Break anchor', effects=[{'type': 'object_damage', 'flat': 10000, 'damage_types': ['force']}],
          target='ANY_CREATURE')
    combat = CombatService(ROOT, tmp_path)
    battlefield = arena(combat)
    battlefield['map_objects'] = list(objects)
    ids = [s.OWNER, s.FOE]
    mid = combat._finish_factory_match(packs, ids, {s.OWNER: 'team:a', s.FOE: 'team:b'},
        {s.OWNER: {'x': 3, 'y': 6}, s.FOE: {'x': 4, 'y': 6}}, battlefield, [], [],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed='WARDEN-F9',
        display_name='Warden F9', maximum_rounds=20)['match_id']
    table = TabletopService(combat, tmp_path)
    advance(table, mid, s.OWNER)
    return combat, table, mid


def asset(*, size='large', cultivation=True):
    return {'id': 1, 'name': 'Synthetic cultivation asset', 'x': 5, 'y': 6,
        'size': size, 'material': 'stone', 'ac': 10, 'hp': 500, 'blocks': False,
        'spiritual_profile': {'cultivation_asset': int(cultivation), 'affectable': 1, 'known_to': [s.OWNER]}}


def options(table, mid, label):
    return [o for g in table.state(mid)['menu']['actions'] if label in g['label'] for o in g['options']]


def test_real_bound_shield_releases_guards_attacks_and_calls_after_cold_reload(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    packs = bundles()
    battlefield = arena(combat)
    state = combat.journeys.create(packs, battlefield,
        {s.OWNER: {'x': 3, 'y': 6}, s.FOE: {'x': 4, 'y': 6}},
        {s.OWNER: 3000, s.FOE: 3000}, control_modes={s.OWNER: 'MANUAL', s.FOE: 'MANUAL'})
    item = next(i for i in packs[0]['carrying']['items'] if i.get('shield'))
    state = record_native_shield_profile(combat, state, item)
    jid = state['journey_id']
    state = combat.journey_act(jid, state['revision'], s.OWNER, 'activity_start',
        {'source': ARMAMENT, 'parameters': {'inventory_owner': s.OWNER, 'item_key': item['key']}})
    state = combat.journey_act(jid, state['revision'], s.OWNER, 'activity_work', {'seconds': 600})
    assert w.BOND in state['actors'][s.OWNER]['source_states']
    mid = combat.journey_start_combat(jid, state['revision'], {s.OWNER: 'team:a', s.FOE: 'team:b'})['match_id']
    table = TabletopService(combat, tmp_path)
    advance(table, mid, s.OWNER)
    # This was absent before the fix: native binding never reached the fight.
    assert options(table, mid, 'Release bound Shield')
    def select(prompt, ids):
        if any(i.startswith('cell:') for i in ids):
            return ['cell:4,5,0'] if 'cell:4,5,0' in ids else []
        if s.OWNER in ids:
            return [s.OWNER]
        return None
    commit(table, mid, s.candidate(table, mid, 'Release bound Shield'), select)
    engine = fresh(combat, mid)
    owner = engine.state.actors[s.OWNER]
    real = next(o for o in w.shields(engine, owner) if not o.component[w.TAG]['projected'])
    assert real.object_kind == 'BOUND_SHIELD'
    assert real.maximum_hp == state['actors'][s.OWNER]['source_states'][w.BOND]['profile']['hp']
    from combat.ext.hand_occupancy import occupancy
    from combat.armour import shield_bonus_earning
    assert not any('shield:' + item['key'] in occupied for occupied in occupancy(engine, owner).values())
    assert shield_bonus_earning(engine, owner) == 0
    # No new actor/initiative slot and no duplicate actual item.
    assert set(engine.state.actors) == {s.OWNER, s.FOE}
    assert real.object_id not in engine.state.initiative_order
    commit(table, mid, table.state(mid)['menu']['end_turn'], select)
    engine = fresh(combat, mid)
    assert any(o.object_id == real.object_id for _, held in w.protection(engine, engine.state.actors[s.OWNER]) for o in held)
    from combat.action_geometry import origins
    deflect = next(a for a in engine.action_catalog.values() if a.owner_id == s.OWNER and a.parameters.get('warden') == 'deflect')
    assert real.object_id in {r['id'] for r in origins(engine, engine.state.actors[s.OWNER], deflect)}
    advance(table, mid, s.OWNER)
    commit(table, mid, s.candidate(table, mid, 'Constellation Movement'),
           lambda p, ids: ['assault'] if 'assault' in ids else select(p, ids))
    before = fresh(combat, mid).state.actors[s.FOE].current_hp
    commit(table, mid, s.candidate(table, mid, 'Revolving Shield Strike: Force', s.FOE), select)
    engine = fresh(combat, mid)
    assert engine.state.actors[s.FOE].current_hp < before
    assert sum(o.object_id == real.object_id for o in engine.state.objects.values()) == 1
    commit(table, mid, table.state(mid)['menu']['end_turn'], select)
    advance(table, mid, s.OWNER)
    commit(table, mid, s.candidate(table, mid, 'Call bound Shield'))
    engine = fresh(combat, mid)
    assert not w.shields(engine, engine.state.actors[s.OWNER])
    assert shield_bonus_earning(engine, engine.state.actors[s.OWNER]) == 2
    assert any('shield:' + item['key'] in held for held in occupancy(engine, engine.state.actors[s.OWNER]).values())


def test_large_noncreature_asset_prison_anchor_destroy_and_cold_replay(tmp_path):
    combat, table, mid = match(tmp_path, objects=[asset()])
    oid = 'object:map.1'
    assert any(oid in o['target_ids'] for o in options(table, mid, 'Imprisoning Earth'))
    commit(table, mid, s.candidate(table, mid, 'Imprisoning Earth', oid))
    engine = fresh(combat, mid)
    obj = engine.state.objects[oid]
    assert object_subjects.movement_held(obj)
    assert len(w.asset_prisons(engine, obj)) == 1
    assert obj.current_hp == 500 and oid not in engine.state.actors
    assert engine.state.actors[s.OWNER].resources[QI] == 22
    anchor = next(o for o in engine.state.objects.values() if o.component.get('name') == 'Shield Prison Anchor')
    assert anchor.maximum_hp == 162 and anchor.damage_threshold == 8
    commit(table, mid, s.candidate(table, mid, 'Break anchor', anchor.object_id))
    engine = fresh(combat, mid)
    assert engine.state.objects[anchor.object_id].destroyed
    assert not object_subjects.movement_held(engine.state.objects[oid])
    assert not w.asset_prisons(engine, engine.state.objects[oid])


@pytest.mark.parametrize('size,cultivation', [('huge', True), ('large', False)])
def test_prison_does_not_admit_oversized_or_nonasset_objects(tmp_path, size, cultivation):
    _, table, mid = match(tmp_path, objects=[asset(size=size, cultivation=cultivation)])
    assert not any('object:map.1' in o['target_ids'] for o in options(table, mid, 'Imprisoning Earth'))


def test_contained_field_stays_legal_but_field_beyond_prison_is_blocked(tmp_path):
    combat, table, mid = match(tmp_path, field_sizes=[5, 15])
    commit(table, mid, s.candidate(table, mid, 'Imprisoning Earth', s.FOE))
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(table, mid, s.FOE)
    assert options(table, mid, 'Field 5')
    assert not options(table, mid, 'Field 15')
    commit(table, mid, s.candidate(table, mid, 'Field 5'))
    engine = fresh(combat, mid)
    assert any(z.active and z.trigger_profile.get('name') == 'Field 5' for z in engine.state.zones.values())


def test_prison_ends_existing_field_only_when_it_extends_beyond_body(tmp_path):
    combat, table, mid = match(tmp_path, field_sizes=[5, 15])
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(table, mid, s.FOE)
    assert options(table, mid, 'Field 15')  # default-inert without prison
    commit(table, mid, s.candidate(table, mid, 'Field 5'))
    commit(table, mid, s.candidate(table, mid, 'Field 15'))
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(table, mid, s.OWNER)
    commit(table, mid, s.candidate(table, mid, 'Imprisoning Earth', s.FOE))
    engine = fresh(combat, mid)
    assert any(z.active and z.trigger_profile.get('name') == 'Field 5' for z in engine.state.zones.values())
    assert not any(z.active and z.trigger_profile.get('name') == 'Field 15' for z in engine.state.zones.values())
