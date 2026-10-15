"""Actual Glass acquisition -> hit/damage -> mixed-category mark cap -> replay."""
import pytest

from combat.gate5_service import CombatService
from combat.mark_ledger import owned
from combat.ext.glass_faultline_marks import MARK
from combat.ext.object_marks import has
from combat.tabletop import TabletopMapStore, to_battlefield
from tests.h1_support import ROOT
from tests.mgr_t14_acquisition_support import acquire_owner
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn

SOURCES = ['GLASS_BASE_FAULTLINE_MARKS', 'GLASS_BASE_TEMPER_GLASS_SURFACE', 'GLASS_BASE_GLASS_SHARD']
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'quantity': 1}]}}


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def native_fight(tmp_path, *, attended=False, miss=False, owner=True, second_owner=False):
    saved = TabletopMapStore(tmp_path).save({'display_name': 'Native Glass mark courtyard',
        'width_squares': 20, 'height_squares': 18, 'objects': [
            {'kind': 'custom', 'name': 'Wooden target', 'x': 6, 'y': 6,
                'material': 'wood', 'hp': 1000, 'blocks': False, 'unattended': not attended}]})
    acquire = acquire_owner('tianxia.sphere.glass', OWNER)
    def edit(doc, actor):
        if owner:
            acquire(doc, actor)
        if second_owner and actor == ALLY:
            acquire_owner('tianxia.sphere.glass', ALLY)(doc, actor)
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        if actor == OWNER:
            doc['ability_scores_and_statistics']['technique_attack_bonus'] = -100 if miss else 100
    combat, table, mid = fixture(tmp_path, SOURCES if owner else [], cl=1, owner_pb=2,
        owner_kit=KIT, ally_kit=KIT, foe_kit=KIT, named=True, seed='GLASS-OBJECT-MARKS',
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 4, 'y': 5}},
        battlefield=to_battlefield(saved), sheet_edit=edit)
    if owner:
        settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
            choices={'choice:needle.temper_glass_surface': ['body:' + OWNER]})
    return combat, table, mid


def shard(combat, table, mid, *, kind='SLASHING', replace=None):
    choices = {'choice:needle.glass_shard_damage_type': [kind]}
    if replace is not None:
        choices['choice:needle.glass_faultline_replace'] = [replace]
    return settle(table, mid, candidate(combat, mid, 'Glass Shard', target='object:map.1').candidate_id,
        choices=choices)


def attack_owner(combat, table, mid, actor, *, replace=None, automatic=False):
    turn(table, mid, actor)
    engine = combat._load_session(mid).engine
    attack = next(c for c in engine.legal_candidates() if OWNER in c.target_ids and 'Fu (Short Axe)' in c.display_name)
    choices = {'choice:needle.glass_surface_mark': ['mark'], 'choice:needle.refraction_response': None}
    if replace is not None:
        choices['choice:needle.glass_faultline_replace'] = [replace]
    if automatic:
        from tests.auto_worker1_support import action_sender, resolve
        name = engine.action_catalog[attack.source_definition_id].display_name
        _, prompts = resolve(action_sender(combat, table, mid, name, ai=True, target_id=OWNER), choices)
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='MANUAL')
        return prompts
    return settle(table, mid, attack.candidate_id, choices=choices)


def following_attackers(engine):
    order = list(engine.state.initiative_order)
    index = order.index(OWNER)
    return [actor for actor in order[index + 1:] + order[:index] if actor in (ALLY, FOE)]


@pytest.mark.parametrize('attended', [False, True])
def test_native_shard_hits_object_chooses_damage_and_marks_until_next_turn_end(tmp_path, attended):
    combat, table, mid = native_fight(tmp_path, attended=attended)
    prompts = shard(combat, table, mid)
    choice = next(p for p in prompts if p['context']['reaction_source_id'].endswith('glass_shard_damage_type'))
    assert {o['id'] for o in choice['choice']['options']} == {'PIERCING', 'SLASHING'}
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark' for p in prompts)
    engine = cold(tmp_path, mid)
    obj = engine.state.objects['object:map.1']
    assert obj.current_hp < obj.maximum_hp == 1000
    assert has(obj, MARK, OWNER)
    assert not owned(engine, MARK, FOE)
    assert [(entry['kind'], entry['recipient'].object_id) for entry in owned(engine, MARK, OWNER)] == [('object', obj.object_id)]
    damage = next(e.payload['damage'] for e in engine.events if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage'))
    assert all(packet['damage_type'] == 'SLASHING' for packet in damage['packets'])
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert has(cold(tmp_path, mid).state.objects[obj.object_id], MARK, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert not owned(cold(tmp_path, mid), MARK, OWNER)


@pytest.mark.parametrize('automatic', [False, True])
def test_creature_mark_capacity_can_end_a_creature_and_preserve_an_owned_object_mark(tmp_path, automatic):
    combat, table, mid = native_fight(tmp_path)
    shard(combat, table, mid)
    first, second = following_attackers(cold(tmp_path, mid))
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    attack_owner(combat, table, mid, first)
    engine = cold(tmp_path, mid)
    before = owned(engine, MARK, OWNER)
    assert {entry['kind'] for entry in before} == {'creature', 'object'}
    creature = next(entry for entry in before if entry['kind'] == 'creature')
    prompts = attack_owner(combat, table, mid, second, replace=creature['id'], automatic=automatic)
    pick = next(p for p in prompts if p['context']['reaction_source_id'].endswith('glass_faultline_replace'))
    assert pick['context']['reactor_id'] == OWNER
    assert {o['id'] for o in pick['choice']['options']} == {entry['id'] for entry in before}
    after = owned(cold(tmp_path, mid), MARK, OWNER)
    assert len(after) == 2 and creature['id'] not in {entry['id'] for entry in after}
    assert any(entry['kind'] == 'object' for entry in after)


def test_object_mark_capacity_can_end_a_creature_and_preserve_independent_expiry(tmp_path):
    combat, table, mid = native_fight(tmp_path)
    first, second = following_attackers(cold(tmp_path, mid))
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    attack_owner(combat, table, mid, first)
    attack_owner(combat, table, mid, second)
    before = owned(cold(tmp_path, mid), MARK, OWNER)
    assert len(before) == 2 and all(entry['kind'] == 'creature' for entry in before)
    turn(table, mid, OWNER)
    prompts = shard(combat, table, mid, replace=before[-1]['id'])
    pick = next(p for p in prompts if p['context']['reaction_source_id'].endswith('glass_faultline_replace'))
    assert pick['context']['reactor_id'] == OWNER
    assert {o['id'] for o in pick['choice']['options']} == {entry['id'] for entry in before}
    after = owned(cold(tmp_path, mid), MARK, OWNER)
    assert len(after) == 2 and any(entry['id'] == before[0]['id'] for entry in after)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    after = owned(cold(tmp_path, mid), MARK, OWNER)
    assert len(after) == 1 and after[0]['kind'] == 'object'
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert not owned(cold(tmp_path, mid), MARK, OWNER)


def test_real_miss_neither_chooses_damage_nor_marks_an_object(tmp_path):
    combat, table, mid = native_fight(tmp_path, miss=True)
    prompts = shard(combat, table, mid)
    assert not any(p['context']['reaction_source_id'].endswith('glass_shard_damage_type') for p in prompts)
    engine = cold(tmp_path, mid)
    assert not owned(engine, MARK, OWNER)
    assert engine.state.objects['object:map.1'].current_hp == 1000


def test_unowned_native_character_has_no_glass_shard_or_mark_ledger(tmp_path):
    combat, table, mid = native_fight(tmp_path, owner=False)
    engine = cold(tmp_path, mid)
    assert not owned(engine, MARK, OWNER)
    assert not any(c.display_name == 'Glass Shard' for c in engine.legal_candidates())


@pytest.mark.parametrize('target', [ALLY, FOE])
def test_specific_faultline_strike_hit_places_its_printed_automatic_mark(tmp_path, target):
    combat, table, mid = native_fight(tmp_path)
    prompts = settle(table, mid, candidate(combat, mid, 'Faultline Strike', target=target).candidate_id,
        choices={'choice:needle.glass_surface_mark': None})
    engine = cold(tmp_path, mid)
    marks = owned(engine, MARK, OWNER)
    assert len(marks) == 1 and marks[0]['recipient'].entity_id == target
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.glass_surface_mark' for p in prompts)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER and e.target_ids == (target,)
        for e in engine.events)


def test_another_actual_cultivators_object_mark_keeps_its_own_capacity_and_clock(tmp_path):
    combat, table, mid = native_fight(tmp_path, second_owner=True)
    shard(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Temper Glass Surface').candidate_id,
        choices={'choice:needle.temper_glass_surface': ['body:' + ALLY]})
    shard(combat, table, mid)
    engine = cold(tmp_path, mid)
    assert len(owned(engine, MARK, OWNER)) == len(owned(engine, MARK, ALLY)) == 1
    assert has(engine.state.objects['object:map.1'], MARK, OWNER)
    assert has(engine.state.objects['object:map.1'], MARK, ALLY)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = cold(tmp_path, mid)
    assert not owned(engine, MARK, OWNER)
    assert len(owned(engine, MARK, ALLY)) == 1
