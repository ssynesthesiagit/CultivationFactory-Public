"""Sol findings F1-F4: accepted table actions, automatic seats and cold replay."""
import pytest

from combat.ext.foundation_context import CONTEXT
from tests.h1_support import sheet
from combat.factory_compiler import compile_character
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload
from tests.test_mgr_t14_garden_sum import GARDEN_NAME, FOUNDATION
from tests.test_mgr_t14_garden_actions import native_garden, cast, turn_unknown, garden_packets, DAMAGE

GENERATE = 'choice:needle.ash_garden.generate'


def garden_ally(bundles):
    doc = sheet(['FIRE_TAL_FLAME_LASH'], cl=5)
    doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': 'Perfected',
        'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.funeral_ash',
                     'maximum': 1, 'current': 0}}
    doc['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    bundles[1] = compile_character(doc, actor_id=ALLY, reaction_plan={'ask': True})


def hit_name(combat, mid, method):
    """Pick a damaging hit variant; willing Blood Thread has no attack/damage."""
    engine = combat._load_session(mid).engine
    return next(engine.action_catalog[c.source_definition_id].display_name for c in engine.legal_candidates()
                if FOE in c.target_ids and engine.action_catalog[c.source_definition_id].display_name.startswith(method)
                and any(row.get('type') == 'attack' for row in
                    engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('effects', ())))


@pytest.mark.parametrize('method,mid_source', [('Cinder Brand', 'ASH_BASE_CINDER_BRAND'),
                                           ('Blood Thread', 'BLOOD_BASE_BLOOD_THREAD')])
def test_f3_printed_source_methods_receive_garden_damage(tmp_path, method, mid_source):
    combat, table, mid = native_garden(tmp_path, talents=(mid_source,), seed='ASH-GARDEN-fire')
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, hit_name(combat, mid, method), target=FOE).candidate_id,
                     choices={CONTEXT+'.detail':'battlefield', DAMAGE:'slashing'})
    engine = reload(tmp_path, mid)
    assert garden_packets(engine)
    assert garden_packets(engine)[-1].payload['rolled_or_pending_damage'] == engine.state.actors[OWNER].proficiency_bonus
    assert any(p['context']['reaction_source_id'] == DAMAGE for p in prompts)


def test_f3_unclassified_printed_source_retains_explicit_method_adjudication(tmp_path):
    # Wind Lash is NOT automatically aligned by its slashing damage. The table
    # can adjudicate source-supported Foundation methods; unknown is inert.
    combat, table, mid = native_garden(tmp_path, talents=('AIR_BASE_WIND_LASH',))
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    prompts = cast(combat, table, mid, 'Wind Lash: Cut', choices={CONTEXT+'.method':'unknown',
                  CONTEXT+'.detail':'battlefield'})
    assert any(p['context']['reaction_source_id'] == CONTEXT+'.method' for p in prompts)
    assert not garden_packets(reload(tmp_path, mid))


def test_f1_automatic_hit_uses_observed_native_brand_without_invented_scene_facts(tmp_path):
    combat, table, mid = native_garden(tmp_path, ally_talents=('ASH_BASE_CINDER_BRAND',), hp=200)
    cast(combat, table, mid, GARDEN_NAME)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, hit_name(combat, mid, 'Cinder Brand'), target=FOE).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert any('ashen_brand' in c.condition_id for c in engine.state.actors[FOE].conditions.values())
    first = engine.state.event_sequence
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, None, auto=True, choices={})
    engine = reload(tmp_path, mid)
    assert [e for e in garden_packets(engine) if e.sequence > first]
    assert not any(p['context']['reaction_source_id'] in (CONTEXT+'.detail', DAMAGE) for p in prompts)
    # Alignment uses observed Brand without testimony. Independent resource
    # generation may ask a human witness about danger; unknown never grants Ash.
    questions = [p for p in prompts if p['context']['reaction_source_id'] == CONTEXT]
    assert questions and all(p['context']['reactor_id'] != OWNER for p in questions)
    facts = [e for e in engine.events if e.payload.get('fact_kind') == 'foundation_event_context'
             and e.sequence > first]
    assert facts and all(e.payload['circumstances'] == 'unknown' for e in facts)
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0


def test_f1_manual_owner_is_asked_off_turn_during_automatic_ally_action(tmp_path):
    combat, table, mid = native_garden(tmp_path, hp=1, extra_foes=1,
                                    ally_talents=('FIRE_TAL_FLAME_LASH',))
    cast(combat, table, mid, GARDEN_NAME)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, None, auto=True, choices={CONTEXT:'real', GENERATE:'generate'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 1
    question = next(p for p in prompts if p['context']['reaction_source_id'] == GENERATE)
    assert question['context']['reactor_id'] == OWNER
    assert question['trigger_actor'] == engine.state.actors[ALLY].display_name
    drop = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                and e.actor_id == ALLY and FOE in e.target_ids and e.payload.get('remaining_hp') == 0)
    assert question['action'] == engine.action_catalog[drop.source_definition_id].display_name


def test_f1_automatic_generation_consumes_same_event_public_testimony(tmp_path):
    combat, table, mid = native_garden(tmp_path, hp=1, extra_foes=1, bundle_transform=garden_ally,
                                    seed='GARDEN-ZERO-generate')
    cast(combat, table, mid, GARDEN_NAME)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, GARDEN_NAME, target=ALLY).candidate_id,
           choices={CONTEXT:'unknown'})
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    cast(combat, table, mid, 'Flame Lash', choices={CONTEXT:'real', GENERATE:'generate'})
    engine = reload(tmp_path, mid)
    assert all(engine.state.actors[a].resources['resource:foundation.funeral_ash'] == 1 for a in (OWNER, ALLY))
    facts = [e for e in engine.events if e.payload.get('fact_kind') == 'foundation_event_context']
    assert len(facts) == 1 and facts[0].payload['declarant'] == OWNER
    assert ALLY in facts[0].payload['observer_ids']
    # Same source/subject in a different accepted execution cannot reuse it.
    from types import SimpleNamespace
    from combat.ext.foundation_context import public_event_context
    event = next(e for e in engine.events if e.sequence == facts[0].payload['event_sequence'])
    assert not public_event_context(engine, engine.state.actors[ALLY], event,
                                    SimpleNamespace(intent_id='another-execution'), 'zero_hp')
    # Nor can an unobserving creature learn it by sharing a team.
    assert not public_event_context(engine, engine.state.actors['actor:factory.worker2-foe1'], event,
                                    SimpleNamespace(intent_id=facts[0].payload['intent_id']), 'zero_hp')


def test_f2_paralyzed_wounded_target_still_takes_garden_damage_but_generates_no_ash(tmp_path):
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    def fixture_action(compiled, name, effects):
        # Ordinary accepted typed actions establish the conditions. Keep this
        # fixture independent of unrelated tests that require private history.
        action = ActionDefinition(source_definition_id=f"action:test.fruit.{name}", display_name=name,
            owner_id=compiled['actor_template']['entity_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=60,
            parameters={'free_primary': True, 'typed': {'source': f'test:{name}', 'effects': effects,
                'numbers': {}, 'duration': {'kind': 'until_removed'}, 'riders': []}})
        compiled['action_catalog'].append(action.model_dump(mode='json'))
        compiled['actor_template']['action_ids'].append(action.source_definition_id)

    def setup(bundles):
        fixture_action(bundles[1], 'Fixture paralysis', [{'type':'condition', 'condition':'paralyzed',
            'applies_to':'target', 'duration':{'kind':'until_removed'}}])
        fixture_action(bundles[0], 'Fixture finish', [{'type':'damage', 'flat':999,
            'damage_types':['slashing'], 'applies_to':'target'}])
    combat, table, mid = native_garden(tmp_path, hp=200, bundle_transform=setup, seed='ASH-GARDEN-fire')
    cast(combat, table, mid, 'Flame Lash')
    cast(combat, table, mid, GARDEN_NAME)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Fixture paralysis', target=FOE).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT:'unknown'})
    turn_unknown(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id.endswith('paralyzed') for c in engine.state.actors[FOE].conditions.values())
    cast(combat, table, mid, 'Flame Lash', choices={CONTEXT:'helpless', CONTEXT+'.detail':'battlefield'})
    engine = reload(tmp_path, mid)
    assert garden_packets(engine)
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0
    prompts = settle(table, mid, candidate(combat, mid, 'Fixture finish', target=FOE).candidate_id,
                     choices={CONTEXT:'real', GENERATE:'generate'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0
    assert not any(p['context']['reaction_source_id'] == GENERATE for p in prompts)


def test_f4_generation_prompt_names_only_actual_zero_hp_event_and_action(tmp_path):
    combat, table, mid = native_garden(tmp_path, hp=1, extra_foes=1, seed='GARDEN-ZERO-generate')
    cast(combat, table, mid, GARDEN_NAME)
    prompts = cast(combat, table, mid, 'Flame Lash', choices={CONTEXT:'real', GENERATE:'generate'})
    question = next(p for p in prompts if p['context']['reaction_source_id'] == GENERATE)
    assert question['action'] == 'Flame Lash'
    assert 'Flame Lash' in question['moment'] and 'reached 0 HP' in question['moment']
    assert 'spared' not in question['moment'] and 'cautery' not in question['moment']
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].display_name in question['moment']
