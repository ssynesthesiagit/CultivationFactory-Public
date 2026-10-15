"""Paid Funeral Ash mercy through table commits, cold reload and replay."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

FEATURE = 'foundation.red_lotus_ash_returning_v0_2B.refined_ash_mercy_boundary'
SCENE = 'choice:needle.ash_mercy.scene'
CONTEXT = 'choice:needle.ash_mercy.context'
TARGET = 'choice:needle.ash_mercy.target'
POOL = 'resource:foundation.funeral_ash'


def scene(tmp_path, *, stage='Refined', initial=1, defeated=True, pb=4,
          positions=None, extra_fire=False):
    doc = sheet([FEATURE], foundation={'foundation_id': 'red_lotus_ash_returning_v0_2B',
        'stage': stage, 'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                                   'maximum': 1, 'current': initial}}, name='Wren')
    doc['identity']['proficiency_bonus'] = pb
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([], name='Mara')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 1 if defeated else 200
    def deliveries(bundles):
        if extra_fire:
            bundles[3] = compile_character(sheet(['FIRE_TAL_FIREBALL_ART'], name='Second enemy'),
                actor_id='actor:factory.worker2-foe1', reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=deliveries,
        ally_talents=['FIRE_TAL_FIREBALL_ART'], foe_sheet=foe, extra_foes=1,
        positions=positions or {OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':8,'y':6}},
        seed='ASH-MERCY', named=True)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(8,6)).candidate_id,
           choices={})
    turn(table, mid, OWNER)
    return combat, table, mid


def mercy(combat, table, mid, *, context='genuine', recipient=ALLY, subject=FOE):
    return settle(table, mid, candidate(combat, mid, 'Ash-Veil Mercy', target=OWNER).candidate_id,
        choices={SCENE: subject, CONTEXT: context, TARGET: recipient})


@pytest.mark.parametrize('recipient', [OWNER, ALLY, FOE, 'actor:factory.worker2-foe1'])
def test_paid_restraint_offers_one_self_ally_or_enemy_after_native_resolution(tmp_path, recipient):
    combat, table, mid = scene(tmp_path)
    before = reload(tmp_path, mid)
    assert not before.state.actors[FOE].active
    prompts = mercy(combat, table, mid, recipient=recipient)
    engine = reload(tmp_path, mid)
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE]
    assert len(grants) == 1 and grants[0].target_ids == (recipient,)
    assert grants[0].payload['offered'] == engine.state.actors[OWNER].proficiency_bonus == 4
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOL]
    assert len(spends) == 1 and spends[0].sequence < grants[0].sequence
    base = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id != FEATURE]
    assert base[-1].sequence < grants[0].sequence
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert engine.state.actors[OWNER].action_available
    assert not engine.state.actors[OWNER].bonus_action_available
    assert sum(e.payload.get('fact_kind') == 'ash_mercy_restraint' for e in engine.events) == 1
    target_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == TARGET)
    assert {OWNER, ALLY, 'actor:factory.worker2-foe1'} <= {o['id'] for o in target_prompt['choice']['options']}


@pytest.mark.parametrize('context', ['unsafe', 'farming', 'unknown'])
def test_paid_spend_without_genuine_scene_never_grants_mercy(tmp_path, context):
    combat, table, mid = scene(tmp_path)
    mercy(combat, table, mid, context=context)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE for e in engine.events)


def test_awakened_owner_has_no_refined_rider(tmp_path):
    combat, table, mid = scene(tmp_path, stage='Awakened')
    prompts = mercy(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.ash_mercy') for p in prompts)
    assert not any(e.source_definition_id == FEATURE for e in engine.events)


def test_wounded_active_creature_does_not_become_helpless_by_label(tmp_path):
    combat, table, mid = scene(tmp_path, defeated=False)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp > 0
    prompts = mercy(combat, table, mid)
    assert not any(p['context']['reaction_source_id'] == SCENE for p in prompts)


def test_repeated_preview_and_discard_leave_paid_rider_unspent(tmp_path):
    from combat.canonical import canonical_sha256
    combat, table, mid = scene(tmp_path)
    row = candidate(combat, mid, 'Ash-Veil Mercy', target=OWNER)
    payload = row.model_dump(mode='json', include={
        'candidate_id', 'decision_id', 'state_version', 'actor_id', 'target_ids', 'destination', 'option_ids'})
    before = canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json'))
    for _ in range(3):
        preview = combat.preview(mid, payload, [])
        assert preview['status'] == 'REACTION_REQUIRED'
        assert preview['authoritative_state_unchanged'] is True
        assert canonical_sha256(reload(tmp_path, mid).state.model_dump(mode='json')) == before
    mercy(combat, table, mid)
    assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == 4


@pytest.mark.parametrize('ally_x,eligible', [(9, True), (10, False)])
def test_native_recipient_range_includes_30_feet_and_excludes_35(tmp_path, ally_x, eligible):
    combat, table, mid = scene(tmp_path, positions={OWNER: {'x':3,'y':6},
        ALLY: {'x':ally_x,'y':5}, FOE: {'x':8,'y':6}})
    prompts = mercy(combat, table, mid, recipient=OWNER)
    p = next(p for p in prompts if p['context']['reaction_source_id'] == TARGET)
    assert (ALLY in {o['id'] for o in p['choice']['options']}) is eligible


def test_perfected_stage_uses_owners_actual_proficiency_bonus(tmp_path):
    combat, table, mid = scene(tmp_path, stage='Perfected', pb=3)
    mercy(combat, table, mid)
    engine = reload(tmp_path, mid)
    grant = next(e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE)
    assert grant.payload['offered'] == engine.state.actors[OWNER].proficiency_bonus == 3


@pytest.mark.parametrize('decline', [SCENE, CONTEXT, TARGET])
def test_declining_rider_never_refunds_or_repeats_the_paid_use(tmp_path, decline):
    combat, table, mid = scene(tmp_path)
    picks = {SCENE: FOE, CONTEXT: 'genuine', TARGET: ALLY, decline: None}
    settle(table, mid, candidate(combat, mid, 'Ash-Veil Mercy', target=OWNER).candidate_id, choices=picks)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.payload.get('resource_id') == POOL]) == 1
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE for e in engine.events)


def test_real_cautery_reaction_on_enemy_turn_pays_once_before_mercy_choice(tmp_path):
    combat, table, mid = scene(tmp_path, extra_fire=True)
    turn(table, mid, 'actor:factory.worker2-foe1')
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3,6)).candidate_id,
        choices={'reaction:typed.foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery': 'first',
                 SCENE: FOE, CONTEXT: 'genuine', TARGET: ALLY})
    engine = reload(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.payload.get('resource_id') == POOL]) == 1
    grant = next(e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE)
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.sequence < grant.sequence
    target_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == TARGET)
    assert 'Cautery' in target_prompt['moment']


def test_native_automatic_owner_does_not_invent_a_genuine_scene(tmp_path):
    combat, table, mid = scene(tmp_path, extra_fire=True)
    turn(table, mid, 'actor:factory.worker2-foe1')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3,6)).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
               and e.payload.get('resource_id') == POOL for e in engine.events)
    assert any(e.payload.get('fact_kind') == 'ash_mercy_restraint'
               and e.payload.get('context') == 'unknown' for e in engine.events)
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.ash_mercy') for p in prompts)
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE for e in engine.events)


def test_native_automatic_owner_public_witness_unknown_does_not_grant_mercy(tmp_path):
    combat, table, mid = scene(tmp_path, extra_fire=True)
    turn(table, mid, 'actor:factory.worker2-foe1')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3,6)).candidate_id,
                     choices={CONTEXT: 'unknown'})
    engine = reload(tmp_path, mid)
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'ash_mercy_restraint')
    assert fact.payload['context'] == 'unknown'
    assert fact.payload['declarant'] == ALLY
    assert any(p['context']['reactor_id'] == ALLY for p in prompts
               if p['context']['reaction_source_id'] == CONTEXT)
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE for e in engine.events)


def test_native_generation_and_expiry_are_not_paid_mercy_uses(tmp_path):
    from combat.ext.foundation_context import CONTEXT as GENERATION_CONTEXT
    combat, table, mid = scene(tmp_path, initial=0, extra_fire=True)
    turn(table, mid, 'actor:factory.worker2-foe1')
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3,6)).candidate_id,
                     choices={GENERATION_CONTEXT: 'real'})
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 1
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.ash_mercy') for p in prompts)
    turn(table, mid, OWNER)
    turn(table, mid, 'actor:factory.worker2-foe1')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == 'passive:resource_clock.expired'
               and e.payload.get('resource_id') == POOL for e in engine.events)
    assert not any(e.source_definition_id == FEATURE for e in engine.events)
