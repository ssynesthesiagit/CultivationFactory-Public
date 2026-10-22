"""Portable table regressions for real shields, asset prisons and field extent.

Only synthetic sheets/maps and public source fixtures; no history or live clients.
The printed prison rule forbids fields *beyond* the prison, not contained fields.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import orbiting_shield_warden as w
from combat.ext import object_subjects
from combat.ext.qi_path import ARMAMENT
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, CombatServiceError
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
        'target_kind': target, 'range_ft': 90, 'parameters': {'free_primary': True, 'typed': typed}})
    bundle['actor_template']['action_ids'].append(aid)
    seal(bundle)


def bundles(cl=18):
    out = []
    for aid, features in ((s.OWNER, list(w.LEVELS) + [ARMAMENT, 'SHIELD_BASE_SHIELD_TRAINING',
            'tianxia.path.qi_cultivation.feature.domain_armament_link', 'TAL_LIGHTNING_LIGHTNING_LASH']), (s.FOE, [])):
        doc = sheet(features, cl=cl, dc=50, kit={'starting_kit': {'items': [
            {'item_id': 'tianxia.mortal.armor.shield', 'quantity': 1}]}} if aid == s.OWNER else None)
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
        out.append(compile_character(doc, actor_id=aid))
    return out


def commit(table, mid, cid, select=None):
    answers = []
    for _ in range(60):
        menu = table.state(mid)['menu']
        try:
            result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        except CombatServiceError as exc:
            raise AssertionError(exc.to_dict()) from exc
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


def bound_fight(tmp_path, cl=18):
    combat = CombatService(ROOT, tmp_path)
    packs = bundles(cl=cl)
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
    assert combat.journey_replay(jid)['status'] == 'PASS'
    mid = combat.journey_start_combat(jid, state['revision'], {s.OWNER: 'team:a', s.FOE: 'team:b'})['match_id']
    table = TabletopService(combat, tmp_path)
    advance(table, mid, s.OWNER)
    return combat, table, mid, state, item


def test_real_bound_shield_releases_guards_attacks_and_calls_after_cold_reload(tmp_path):
    combat, table, mid, state, item = bound_fight(tmp_path)
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
    from combat.object_rules import has_tag
    assert has_tag(real, 'shield') and has_tag(real, 'item') and has_tag(real, 'cultivation_implement')
    assert real.maximum_hp == state['actors'][s.OWNER]['source_states'][w.BOND]['profile']['hp']
    from combat.ext.hand_occupancy import occupancy
    from combat.armour import shield_bonus_earning
    assert not any('shield:' + item['key'] in occupied for occupied in occupancy(engine, owner).values())
    assert shield_bonus_earning(engine, owner) == 0
    from combat.ext.scoundrel_riders import possessions
    assert not any(row['object'] == real.object_id for row in possessions(engine, owner))
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
    # Domain Armament Link uses the same real item as a paid remote Sphere origin.
    # Candidate identity binds the selected remote origin and its extra cost.
    engine = fresh(combat, mid)
    remote = next(c for c in engine.legal_candidates() if 'Lightning Lash: Charge' in c.display_name
        and (c.metadata.get('effect_origin') or {}).get('id') == w.LINK_ORIGIN + real.object_id
        and s.FOE in c.target_ids)
    qi = engine.state.actors[s.OWNER].resources[QI]
    commit(table, mid, remote.candidate_id)
    engine = fresh(combat, mid)
    assert engine.state.actors[s.OWNER].resources[QI] == qi - 1
    assert sum(o.object_id == real.object_id for o in engine.state.objects.values()) == 1
    commit(table, mid, table.state(mid)['menu']['end_turn'], select)
    advance(table, mid, s.OWNER)
    commit(table, mid, s.candidate(table, mid, 'Call bound Shield'))
    engine = fresh(combat, mid)
    assert not w.shields(engine, engine.state.actors[s.OWNER])
    assert shield_bonus_earning(engine, engine.state.actors[s.OWNER]) == 2
    assert any('shield:' + item['key'] in held for held in occupancy(engine, engine.state.actors[s.OWNER]).values())
    # Constellation Movement may also change the actual item's use for free,
    # including after the Bonus Action was already spent calling it.
    qi = engine.state.actors[s.OWNER].resources[QI]
    commit(table, mid, s.candidate(table, mid, 'Constellation Movement'),
        lambda p, ids: ['floating'] if 'floating' in ids else select(p, ids))
    engine = fresh(combat, mid)
    assert w.shields(engine, engine.state.actors[s.OWNER])[0].object_id == real.object_id
    assert engine.state.actors[s.OWNER].resources[QI] == qi
    commit(table, mid, table.state(mid)['menu']['end_turn'], select)
    advance(table, mid, s.OWNER)
    commit(table, mid, s.candidate(table, mid, 'Constellation Movement'),
        lambda p, ids: ['wielded'] if 'wielded' in ids else select(p, ids))
    engine = fresh(combat, mid)
    assert not w.shields(engine, engine.state.actors[s.OWNER])
    assert engine.state.actors[s.OWNER].bonus_action_available
    assert engine.state.actors[s.OWNER].resources[QI] == qi


def test_cl9_bound_shield_uses_native_armament_attack_before_constellation(tmp_path):
    combat, table, mid, state, item = bound_fight(tmp_path, cl=9)
    def place(prompt, ids):
        return ['cell:4,5,0'] if 'cell:4,5,0' in ids else None
    commit(table, mid, s.candidate(table, mid, 'Release bound Shield'), place)
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(table, mid, s.OWNER)
    assert not options(table, mid, 'Revolving Shield Strike')
    commit(table, mid, s.candidate(table, mid, 'Bound Shield: change Guard'),
        lambda p, ids: ['assault'] if 'assault' in ids else None)
    before = fresh(combat, mid).state.actors[s.FOE].current_hp
    commit(table, mid, s.candidate(table, mid, 'Bound Shield Domain Armament Attack: Force', s.FOE))
    engine = fresh(combat, mid)
    assert engine.state.actors[s.FOE].current_hp < before
    assert engine.state.actors[s.OWNER].resources[QI] == 30
    assert len(w.shields(engine, engine.state.actors[s.OWNER])) == 1


def test_additive_origin_cost_uses_one_native_quote_and_preserves_inert_actions(monkeypatch, tmp_path):
    from combat import ext, technique_costs
    ext._load()
    original = list(ext._HOOKS.get('technique_additional_costs', []))
    monkeypatch.setitem(ext._HOOKS, 'technique_additional_costs', original + [
        lambda engine, actor, source, listed: {QI: 1} if source == 'test:remote' else None])
    # Use an unowned native actor: Warden's own subscriber must remain inert.
    combat, _, mid = match(tmp_path)
    engine = fresh(combat, mid)
    actor = engine.state.actors[s.FOE]
    assert technique_costs.effective(engine, actor, 'test:remote', ()) == ((QI, 1),)
    assert technique_costs.effective(engine, actor, 'test:remote', ((QI, 2),)) == ((QI, 2), (QI, 1))
    assert technique_costs.effective(engine, actor, 'test:ordinary', ()) == ()


def test_binding_fact_authority_and_private_consent_are_separate_native_transactions(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    packs = bundles()
    state = combat.journeys.create(packs, arena(combat),
        {s.OWNER: {'x': 3, 'y': 6}, s.FOE: {'x': 4, 'y': 6}}, {s.OWNER: 3000, s.FOE: 3000})
    item = next(i for i in packs[0]['carrying']['items'] if i.get('shield'))
    jid = state['journey_id']
    payload = {'source': ARMAMENT, 'subject': s.OWNER, 'kind': 'shield_binding_permission',
        'scope': 'item:' + s.OWNER + '|' + item['key'] + '|binder:' + s.FOE,
        'value': 1, 'expires_at': 1000, 'readers': [s.FOE]}
    with pytest.raises(ValueError, match='private consent'):
        combat.journey_world_fact(jid, state['revision'], payload)
    with pytest.raises(ValueError, match='Only this creature'):
        combat.journey_act(jid, state['revision'], s.FOE, 'declare_fact', payload)
    assert combat.journey_state(jid) == state
    state = combat.journey_act(jid, state['revision'], s.OWNER, 'declare_fact', payload)
    assert combat.journey_replay(jid)['status'] == 'PASS'
    from combat.fact_consent_admission import read
    record = read(combat.journeys.load(jid), ARMAMENT, s.OWNER, payload['kind'], payload['scope'], s.FOE)
    assert record['authority'] == s.OWNER and record['value'] == 1
    assert state['revision'] == 1


def test_asset_success_uses_source_clocked_half_speed_and_expires(tmp_path):
    row = asset()
    row['spiritual_profile']['saving_throws'] = {'STR': 100, 'CHA': 100}
    combat, table, mid = match(tmp_path, objects=[row])
    commit(table, mid, s.candidate(table, mid, 'Imprisoning Earth', 'object:map.1'))
    engine = fresh(combat, mid)
    obj = engine.state.objects['object:map.1']
    assert not object_subjects.movement_held(obj)
    assert object_subjects.movement_allowance(obj, 30) == 15
    assert object_subjects.records(obj, 'speed_halved')[0]['data']['no_willing_teleport'] == 1
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(table, mid, s.OWNER)
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    engine = fresh(combat, mid)
    assert object_subjects.movement_allowance(engine.state.objects['object:map.1'], 30) == 30


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


def test_imprisoned_native_ward_cannot_deliver_a_linked_attack_outside(tmp_path):
    combat, table, mid = match(tmp_path)
    commit(table, mid, s.candidate(table, mid, 'Manifest Ward'))
    engine = fresh(combat, mid)
    ward = w.shields(engine, engine.state.actors[s.OWNER])[0]
    commit(table, mid, s.candidate(table, mid, 'Imprisoning Earth', ward.object_id))
    assert object_subjects.movement_held(fresh(combat, mid).state.objects[ward.object_id])
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(table, mid, s.OWNER)
    assert not options(table, mid, 'Move Shields')
    engine = fresh(combat, mid)
    assert engine.state.objects[ward.object_id].position == ward.position
    assert not list(w.protection(engine, engine.state.actors[s.OWNER]))
    lash = [c for c in engine.legal_candidates() if 'Lightning Lash: Charge' in c.display_name and s.FOE in c.target_ids]
    assert lash  # The ordinary body origin remains legal.
    assert not any((c.metadata.get('effect_origin') or {}).get('id') == w.LINK_ORIGIN + ward.object_id for c in lash)


def test_asset_targeting_does_not_reveal_gm_only_cultivation_classification(tmp_path):
    row = asset()
    row['spiritual_profile']['known_to'] = []
    _, table, mid = match(tmp_path, objects=[row])
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
