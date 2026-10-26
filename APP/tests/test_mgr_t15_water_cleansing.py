"""Cleansing Water's actual zone trigger/choices through table commit and replay.

Fixture actions record surface residue and present an entry to the native zone
dispatcher. No production cleansing, accounting or Temporary HP is mocked.
"""
from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from combat.ext import effect
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload

CLEANSING = 'TAL_WATER_CLEANSING_WATER'


@effect('test_mgr_cleansing_scene', harmful=False)
def scene(ctx, row):
    for actor in (ctx.actor, ctx.engine.state.actors[ALLY]):
        ctx.engine._apply_condition(actor, 'condition:typed.covered_in_smoke', ctx.source, ctx.actor.entity_id,
                                    expires_on='UNTIL_REMOVED')
        ctx.engine._apply_condition(actor, 'condition:typed.dust', ctx.source, ctx.actor.entity_id,
                                    expires_on='UNTIL_REMOVED')
        ctx.engine._apply_condition(actor, 'condition:typed.poisoned', ctx.source, ctx.actor.entity_id,
                                    expires_on='UNTIL_REMOVED')
    obj = ctx.engine.state.objects['object:map.83']
    obj.component['mundane_residue'] = 'acid_residue'
    ctx.engine._update_object(obj, ctx.source, actor_id=ctx.actor.entity_id)


@effect('test_mgr_cleansing_entry', harmful=False)
def enter(ctx, row):
    from combat.zones import fire_trigger
    for zone in ctx.engine.state.zones.values():
        if zone.active and zone.owner_id == ctx.actor.entity_id:
            fire_trigger(ctx.engine, zone, ctx.target, 'enter')


def prepare(bundles):
    owner = next(b for b in bundles if b['actor_id'] == OWNER)
    template = next(a for a in owner['action_catalog']
                    if a.get('parameters', {}).get('typed', {}).get('source') == 'WATER_BASE_WATER_LASH')
    for name, etype, kind in [('Fixture residue', 'test_mgr_cleansing_scene', 'SELF'),
                              ('Fixture entered Basin', 'test_mgr_cleansing_entry', 'ALLY_OR_SELF')]:
        action = deepcopy(template)
        aid = 'action:test.' + etype
        action.update(source_definition_id=aid, display_name=name, economy='NONE', target_kind=kind,
                      costs=[], range_ft=60, reach_ft=None)
        action['parameters'] = {'free_primary': True, 'typed': {
            'source': etype, 'numbers': deepcopy(template['parameters']['typed']['numbers']),
            'effects': [{'type': etype}], 'riders': []}}
        owner['action_catalog'].append(action)
        owner['actor_template']['action_ids'].append(aid)
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)


def map_scene(arena):
    arena['map_objects'] = [{'id': 83, 'kind': 'crate', 'x': 3, 'y': 5}]


def test_wash_description_reserves_smoke_for_budgeted_basin_benefit(tmp_path):
    combat, table, mid = fixture(tmp_path, [CLEANSING])
    engine = reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Cleansing Water: Wash Residue')
    description = action.parameters['description']
    assert 'dust, ash or filth from one creature or object' in description
    assert 'Smoke removal uses the Basin benefit, limited to one creature per round.' in description


@pytest.mark.parametrize('owned', [True, False])
def test_cleansing_beneficiary_hp_and_round_budget_survive_reload(tmp_path, owned):
    combat, table, mid = fixture(tmp_path, [CLEANSING] if owned else ['WATER_BASE_SHAPE_CURRENT'],
                                 bundle_transform=prepare, battlefield_transform=map_scene, ally_position={'x': 2, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Fixture residue').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Shape Current: Cleansing Basin', at=(3, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == engine.state.actors[ALLY].temporary_hp == 0
    prompts = settle(table, mid, candidate(combat, mid, 'Fixture entered Basin', target=OWNER).candidate_id,
                     {'choice:needle.water_cleansing': 'cleanse' if owned else 'save'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == (engine.state.actors[OWNER].proficiency_bonus if owned else 0)
    assert any(c.condition_id == 'condition:typed.covered_in_smoke'
               for c in engine.state.actors[OWNER].conditions.values()) is (not owned)
    assert any(c.condition_id == 'condition:typed.poisoned' for c in engine.state.actors[OWNER].conditions.values())
    if owned:
        zone = next(z for z in engine.state.zones.values() if z.owner_id == OWNER and z.active)
        assert zone.per_turn_triggered['cleansing_water_round'] == engine.state.round_number
    prompts = settle(table, mid, candidate(combat, mid, 'Fixture entered Basin', target=ALLY).candidate_id,
                     {'choice:needle.water_cleansing': 'save'})
    assert not any(o['id'] == 'cleanse' for p in prompts for o in p['choice']['options'])
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == (engine.state.actors[OWNER].proficiency_bonus if owned else 0)
    assert any(c.condition_id == 'condition:typed.covered_in_smoke' for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('target', [ALLY, 'object:map.83'])
@pytest.mark.parametrize('decline', [True, False])
def test_cleansing_wash_creature_and_object_preserves_poisoned(tmp_path, target, decline):
    combat, table, mid = fixture(tmp_path, [CLEANSING], bundle_transform=prepare, battlefield_transform=map_scene, ally_position={'x': 2, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Fixture residue').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Shape Current: Cleansing Basin', at=(3, 6)).candidate_id)
    from combat.ext.water_basins import wash_targets
    engine = reload(tmp_path, mid)
    assert target in wash_targets(engine, engine.state.actors[OWNER]), 'Recorded in-Basin target must remain reachable'
    settle(table, mid, candidate(combat, mid, 'Cleansing Water: Wash Residue').candidate_id,
           {'choice:needle.water_wash_residue': None if decline else target})
    engine = reload(tmp_path, mid)
    if target == ALLY:
        assert any(c.condition_id == 'condition:typed.dust' for c in engine.state.actors[ALLY].conditions.values()) is decline
        assert any(c.condition_id == 'condition:typed.poisoned' for c in engine.state.actors[ALLY].conditions.values())
        assert any(c.condition_id == 'condition:typed.covered_in_smoke' for c in engine.state.actors[ALLY].conditions.values())
    else:
        assert ('mundane_residue' in engine.state.objects[target].component) is decline
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99


def test_cleansing_ai_beneficiary_decides_without_prompt(tmp_path):
    combat, table, mid = fixture(tmp_path, [CLEANSING], bundle_transform=prepare, battlefield_transform=map_scene, ally_position={'x': 2, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Fixture residue').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Shape Current: Cleansing Basin', at=(3, 6)).candidate_id)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Fixture entered Basin', target=ALLY).candidate_id)
    assert not prompts
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == engine.state.actors[OWNER].proficiency_bonus
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke' for c in engine.state.actors[ALLY].conditions.values())


def test_cleansing_player_beneficiary_is_asked_during_ai_turn(tmp_path):
    from tests.test_hunt27_table import commit
    combat, table, mid = fixture(tmp_path, [CLEANSING], bundle_transform=prepare, battlefield_transform=map_scene, ally_position={'x': 2, 'y': 6})
    settle(table, mid, candidate(combat, mid, 'Fixture residue').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Shape Current: Cleansing Basin', at=(3, 6)).candidate_id)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    answers = commit(combat, table, mid, tmp_path,
                     candidate(combat, mid, 'Fixture entered Basin', target=ALLY).candidate_id,
                     choose=lambda prompt: ['cleanse'])
    assert any(a['reactor_id'] == ALLY for a in answers)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == engine.state.actors[OWNER].proficiency_bonus
    assert not any(c.condition_id == 'condition:typed.covered_in_smoke' for c in engine.state.actors[ALLY].conditions.values())
