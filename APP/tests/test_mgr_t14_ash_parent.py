"""Funeral Ash parent through shipped builds and actual table context answers."""
import pytest
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_foundations3 import owner_bundle, pool
from combat.ext.foundation_context import CONTEXT


def native_fixture(tmp_path, *, incoming=True, seed='ASH-PARENT', initial=0, foe_hp=200,
                   foe_talents=None, owner_hp=None, owned=True, positions=None):
    bundle = owner_bundle('ash', initial=initial)
    if not incoming:
        from combat.factory_compiler import compile_character
        doc = sheet(['FIRE_TAL_FIREBALL_ART'], cl=5, foundation={
            'foundation_id': 'red_lotus_ash_returning_v0_2B', 'stage': 'Awakened',
            'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                         'maximum': 1, 'current': initial}})
        # Foundation is a real build input; sheet's helper otherwise only emits
        # it when mids itself contains a Foundation feature.
        doc['foundation'] = {'foundation_id': 'red_lotus_ash_returning_v0_2B', 'stage': 'Awakened',
            'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test', 'maximum': 1, 'current': initial}}
        bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    if owner_hp is not None:
        from combat.factory_compiler import compile_character
        doc = sheet(['foundation.red_lotus_ash_returning_v0_2B.ash_veil_mercy'], foundation={
            'foundation_id': 'red_lotus_ash_returning_v0_2B', 'stage': 'Awakened',
            'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test', 'maximum': 1, 'current': initial}})
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = owner_hp
        bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet(foe_talents or ['FIRE_TAL_FIREBALL_ART'], cl=5)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = foe_hp
    return fixture(tmp_path, [], owner_bundle=bundle if owned else None, ally_talents=['FIRE_TAL_FIREBALL_ART'],
        foe_sheet=foe, seed=seed,
        positions=positions or {OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':8,'y':6}})


def cast(combat, table, mid, *, incoming=True, circumstances='real', detail='battlefield'):
    turn(table, mid, FOE if incoming else OWNER)
    row = candidate(combat, mid, 'Fireball Art', at=(3,6) if incoming else (8,6))
    return settle(table, mid, row.candidate_id, choices={CONTEXT: circumstances,
        CONTEXT + '.detail': detail})


def test_shipped_fire_damage_generates_only_after_settlement_and_replays(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    before = reload(tmp_path, mid)
    cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    gain = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == pool('ash'))
    assert damage.sequence < gain.sequence
    assert engine.state.actors[OWNER].current_hp < before.state.actors[OWNER].maximum_hp
    contexts = [e for e in engine.events if e.payload.get('fact_kind') == 'foundation_event_context']
    assert contexts[-1].payload['damage_category'] == 'fire'
    assert contexts[-1].payload['event_sequence'] == damage.sequence


@pytest.mark.parametrize('circumstances', ['staged','harmless','voluntary','training','helpless','unknown'])
def test_excluded_or_unknown_native_fire_context_does_not_generate(tmp_path, circumstances):
    combat, table, mid = native_fixture(tmp_path, seed='ASH-'+circumstances)
    cast(combat, table, mid, circumstances=circumstances)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    assert any(e.event_type == 'DAMAGE_COMMITTED' for e in engine.events)


def test_full_health_outgoing_shipped_fire_method_is_not_wounded_trigger(tmp_path):
    combat, table, mid = native_fixture(tmp_path, incoming=False)
    cast(combat, table, mid, incoming=False)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp > 0
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0


@pytest.mark.parametrize('residue,expected', [('battlefield',1), ('fresh',0), ('unknown',0)])
def test_wounded_outgoing_source_needs_established_battlefield_residue(tmp_path, residue, expected):
    combat, table, mid = native_fixture(tmp_path, incoming=False)
    cast(combat, table, mid, incoming=False)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert 0 < before.state.actors[FOE].current_hp < before.state.actors[FOE].maximum_hp
    assert before.state.actors[OWNER].resources[pool('ash')] == 0
    cast(combat, table, mid, incoming=False, detail=residue)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == expected
    if expected:
        # Own-turn generation survives this turn's end and ends after the next.
        turn(table, mid, FOE)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('ash')] == 1
        turn(table, mid, OWNER)
        turn(table, mid, FOE)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('ash')] == 0


def test_native_friendly_fire_is_excluded_without_scene_prompt(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3,6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp < engine.state.actors[OWNER].maximum_hp
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    assert not any(p['context']['reaction_source_id'].startswith(CONTEXT) for p in prompts)


def test_automatic_owner_keeps_unknown_scene_facts_unknown_without_model_call(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    # No player-controlled witness can establish public facts for either seat.
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompts = cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    assert not any(p['context']['reaction_source_id'].startswith(CONTEXT) for p in prompts)
    context = next(e for e in reversed(engine.events) if e.payload.get('fact_kind') == 'foundation_event_context')
    assert context.payload['circumstances'] == 'unknown'


@pytest.mark.parametrize('answer', ['unknown', None])
def test_automatic_owner_witness_unknown_or_declined_facts_do_not_generate(tmp_path, answer):
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = cast(combat, table, mid, circumstances=answer)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'foundation_event_context')
    assert fact.payload['circumstances'] == 'unknown'
    assert fact.payload['declarant'] == ALLY
    assert any(p['context']['reactor_id'] == ALLY for p in prompts
               if p['context']['reaction_source_id'] == CONTEXT)


def test_native_incoming_cannot_spend_the_ash_it_is_about_to_generate(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    prompts = cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
                   and e.payload.get('resource_id') == pool('ash') for e in engine.events)
    assert not any('cautery' in p['context']['reaction_source_id'].lower() for p in prompts)
    turn(table, mid, OWNER)
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('ash')] == 0


def test_native_held_pool_is_not_stacked_or_refreshed(tmp_path):
    combat, table, mid = native_fixture(tmp_path, initial=1)
    cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == pool('ash')
                   for e in engine.events)


@pytest.mark.parametrize('ending,expected', [('defeat',1), ('mercy',1), ('unknown',0)])
def test_meaningful_native_enemy_ending_settles_even_on_terminal_action(tmp_path, ending, expected):
    combat, table, mid = native_fixture(tmp_path, incoming=False, foe_hp=1)
    cast(combat, table, mid, incoming=False, detail=ending)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.terminal_result is not None
    assert engine.state.actors[OWNER].resources[pool('ash')] == expected
    defeated = next(e for e in engine.events if e.event_type == 'ENTITY_DEFEATED' and e.actor_id == FOE)
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == pool('ash')]
    assert all(e.sequence > defeated.sequence for e in gains)


def test_native_observed_enemy_defeat_does_not_require_own_finishing_blow(tmp_path):
    combat, table, mid = native_fixture(tmp_path, foe_hp=1)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(8,6)).candidate_id,
        choices={CONTEXT: 'real', CONTEXT + '.detail': 'defeat'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1


def test_native_unowned_character_is_inert(tmp_path):
    combat, table, mid = native_fixture(tmp_path, owned=False)
    cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert pool('ash') not in engine.state.actors[OWNER].resources
    assert not any(e.payload.get('fact_kind') == 'foundation_event_context' for e in engine.events)
    assert all('target_conditions_before' not in e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED')


def test_native_defeated_owner_does_not_generate(tmp_path):
    combat, table, mid = native_fixture(tmp_path, owner_hp=1)
    cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 0
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0


def test_shipped_disease_method_carries_its_source_category_after_actual_hit(tmp_path):
    combat, table, mid = native_fixture(tmp_path, foe_talents=['DISEASE_BASE_SOW_THE_FEVER_SEED'])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Sow the Fever Seed', target=OWNER).candidate_id,
        choices={CONTEXT: 'real'})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids for e in engine.events)
    context = next(e for e in reversed(engine.events) if e.payload.get('fact_kind') == 'foundation_event_context')
    assert context.payload['damage_category'] == 'disease'
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1


@pytest.mark.parametrize('category,expected', [('attrition',1), ('blood_loss',1), ('other',0), ('unknown',0)])
def test_actual_native_damage_requires_explicit_non_colour_attrition_context(tmp_path, category, expected):
    combat, table, mid = native_fixture(tmp_path, positions={
        OWNER: {'x':3,'y':6}, ALLY: {'x':3,'y':7}, FOE: {'x':4,'y':6}})
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    row = next(c for c in engine.legal_candidates() if c.target_ids == (OWNER,)
               and engine.action_catalog.get(c.source_definition_id)
               and engine.action_catalog[c.source_definition_id].display_name.startswith('Unarmed Strike'))
    settle(table, mid, row.candidate_id, choices={CONTEXT: 'real', CONTEXT + '.detail': category})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids for e in engine.events)
    assert engine.state.actors[OWNER].resources[pool('ash')] == expected


def test_repeated_native_context_previews_can_be_discarded_without_mutation(tmp_path):
    from combat.canonical import canonical_sha256
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, FOE)
    row = candidate(combat, mid, 'Fireball Art', at=(3,6))
    payload = row.model_dump(mode='json', include={
        'candidate_id','decision_id','state_version','actor_id','target_ids','destination','option_ids'})
    before = canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json'))
    for _ in range(3):
        preview = combat.preview(mid, payload, [])
        assert preview['status'] == 'REACTION_REQUIRED'
        assert preview['authoritative_state_unchanged'] is True
        assert canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json')) == before
    # Discarding all previews neither paid, rolled, generated nor consumed any
    # mechanical receipt. A fresh actual table submission still commits once.
    settle(table, mid, row.candidate_id, choices={CONTEXT: 'real'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == pool('ash')]
    assert len(gains) == 1
