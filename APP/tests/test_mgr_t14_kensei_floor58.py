"""Kensei service regressions; combat-boundary proof, not acquisition admission."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_riders_c7 as C
from tests.worker2_support import settle
from tests.r10_fixup_support import fixed_dice

PREFIX = 'tianxia.subpath.body.kensei.feature.'
IRON = 'tianxia.path.body_refining.feature.iron_fist'
BLADE = 'tianxia.mortal.weapon.jian'
ME, FOE = C.ME, C.FOE


def fight(tmp_path, features, *, items=(), mods=None, cl=18):
    documents = [C.sheet([IRON, *(PREFIX + x for x in features)], items=items, mods=mods, cl=cl, spheres={}),
                 C.sheet([IRON], cl=18, spheres={}, name='Sparring partner')]
    combat = CombatService(C.ROOT, tmp_path)
    for aid, doc in zip((ME, FOE), documents):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True})
               for aid, doc in zip((ME, FOE), documents)]
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME:'team:a',FOE:'team:b'},
        {ME:{'x':3,'y':6},FOE:{'x':4,'y':6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME], [FOE],
        control_modes={ME:'MANUAL',FOE:'MANUAL'}, match_seed='KENSEI-FLOOR58',
        display_name='Kensei service regression', maximum_rounds=20)['match_id']
    return combat, TabletopService(combat,tmp_path), mid


def load(tmp_path, mid):
    session = CombatService(C.ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def advance(combat, table, mid, actor=ME):
    for _ in range(12):
        engine = combat._load_session(mid).engine
        if engine.state.setup_tasks:
            settle(table,mid,'system:combat.fight_setup')
        elif engine.state.current_actor_id == actor:
            return
        else:
            settle(table,mid,table.state(mid)['menu']['end_turn'])
    raise AssertionError('turn did not arrive')


def use(combat, table, mid, name, *, target=None, picks=None):
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates()
                  if getattr(engine.action_catalog.get(c.source_definition_id),'display_name',None) == name
                  and (target is None or c.target_ids == (target,))]
    assert candidates, name
    return settle(table,mid,candidates[0].candidate_id,picks)


def strike(combat, table, mid, picks=None):
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME
                  and '.natural.' in a.source_definition_id and '#' not in a.source_definition_id
                  and not (a.parameters.get('typed') or {}).get('unarmed_option'))
    return use(combat,table,mid,action.display_name,target=FOE,picks=picks)


def test_sword_draws_queues_before_turn_one_and_ac_expires_at_first_turn(tmp_path):
    combat, table, mid = fight(tmp_path,['sword_draws_before_thought'])
    engine = load(tmp_path,mid)
    assert engine.state.setup_tasks
    assert not any(e.event_type == 'TURN_STARTED' for e in engine.events)
    prompts = settle(table,mid,'system:combat.fight_setup',{'choice:needle.sword_draws_before_thought':['ac']})
    p = next(p for p in prompts if p['context']['reaction_source_id'].endswith('sword_draws_before_thought'))
    assert {o['id'] for o in p['choice']['options']} == {'move','strike','ac','advantage'}
    advance(combat,table,mid)
    engine = load(tmp_path,mid)
    assert engine._effective_ac(engine.state.actors[ME]) == 14
    assert sum(e.event_type == 'FIGHT_SETUP_COMPLETED' for e in engine.events) == 1


def test_blade_fist_offers_and_commits_draw_stow_after_real_hit(tmp_path,monkeypatch):
    fixed_dice(monkeypatch,[18]*100)
    combat, table, mid = fight(tmp_path,['blade_fist'],items=(BLADE,))
    advance(combat,table,mid)
    engine = load(tmp_path,mid)
    weapon = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == ME and '.weapon.jian' in a.source_definition_id and '#' not in a.source_definition_id)
    prompts = strike(combat,table,mid,{'choice:needle.blade_fist':['draw'],
        'choice:needle.kensei_readiness':['stow:'+weapon]})
    p = next(p for p in prompts if p['context']['reaction_source_id'].endswith('blade_fist'))
    assert 'draw' in {o['id'] for o in p['choice']['options']}
    from combat.ext.hand_occupancy import weapon_grips
    engine = load(tmp_path,mid)
    assert weapon not in weapon_grips(engine,engine.state.actors[ME])


@pytest.mark.parametrize('ability',['STR','DEX','CON'])
def test_blade_fist_retains_each_unarmed_ability_even_when_lower(tmp_path,monkeypatch,ability):
    fixed_dice(monkeypatch,[18]*100)
    combat, table, mid = fight(tmp_path,['blade_fist'],mods={'STR':4,'DEX':0,'CON':2})
    advance(combat,table,mid)
    prompts = strike(combat,table,mid,{'choice:needle.kensei_ability':[ability]})
    p = next(p for p in prompts if p['context']['reaction_source_id'].endswith('kensei_ability'))
    assert {o['id'] for o in p['choice']['options']} == {'STR','DEX','CON'}
    load(tmp_path,mid)


def test_flowing_move_waits_for_primary_and_late_hit_damage(tmp_path,monkeypatch):
    fixed_dice(monkeypatch,[18]*120)
    combat, table, mid = fight(tmp_path,['blade_fist','flowing_blade_stance'])
    advance(combat,table,mid)
    use(combat,table,mid,'Flowing Blade Stance')
    strike(combat,table,mid,{'choice:needle.flowing_blade_step':['cell:3,5']})
    engine = load(tmp_path,mid)
    movements = [e for e in engine.events if e.event_type == 'MOVEMENT_RESOLVED' and e.actor_id == ME]
    assert movements
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ME]
    assert damage and max(e.sequence for e in damage) < movements[-1].sequence
    assert (engine.state.actors[ME].position.x,engine.state.actors[ME].position.y) == (3,5)


def test_severing_flow_records_both_distinct_scopes(tmp_path,monkeypatch):
    fixed_dice(monkeypatch,[18]*120)
    combat, table, mid = fight(tmp_path,['severing_palm'])
    advance(combat,table,mid)
    before = load(tmp_path,mid).state.actors[ME].resources[C.STAMINA]
    strike(combat,table,mid,{'choice:needle.severing_palm':['flow']})
    engine = load(tmp_path,mid)
    target = engine.state.actors[FOE]
    assert engine.state.actors[ME].resources[C.STAMINA] == before - 4
    assert any(c.condition_id == 'condition:typed.concentration_mode' for c in target.conditions.values())
    assert any(c.condition_id == 'condition:typed.severing_flow' for c in target.conditions.values())
