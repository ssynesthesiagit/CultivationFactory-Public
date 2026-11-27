"""Review regressions: automatic facts, private receipts and ending prompts."""
import socket

import pytest

from tests.test_mgr_t14_ash_parent import OLD_FACT_PROMPT, native_fixture, cast
from tests.test_mgr_t14_ash_mercy_parent import scene, FEATURE, POOL
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Combat regressions must never contact a live server')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_generation_uses_incoming_damage_type_with_manual_observers(tmp_path, mode):
    from tests.test_a2_foundations3 import pool
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    prompts = cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1, 'incoming fire must generate Funeral Ash'
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.payload['damage_type'] == 'FIRE'
    assert not any(p['context']['reaction_source_id'].startswith(OLD_FACT_PROMPT) for p in prompts)



@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_owner_observes_ally_defeat_enemy_without_a_witness(tmp_path, mode):
    from tests.test_a2_foundations3 import pool
    combat, table, mid = native_fixture(tmp_path, foe_hp=1)
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(8, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1, 'an observed enemy defeat must generate Funeral Ash'
    assert not any(p['context']['reaction_source_id'].startswith(OLD_FACT_PROMPT) for p in prompts)




@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_paid_mercy_uses_public_restraint_then_chooses_recipient(tmp_path, mode):
    from tests.test_mgr_t14_ash_mercy_parent import CONTEXT as MERCY_CONTEXT
    combat, table, mid = scene(tmp_path, extra_fire=True)
    turn(table, mid, 'actor:factory.worker2-foe1')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3, 6)).candidate_id,
                     choices={MERCY_CONTEXT: 'genuine'})
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
               and e.payload.get('resource_id') == POOL for e in engine.events)
    grant = next(e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
                 and e.source_definition_id == FEATURE)
    assert len(grant.target_ids) == 1
    assert grant.payload['offered'] == engine.state.actors[OWNER].proficiency_bonus
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'ash_mercy_restraint')
    assert 'context' not in fact.payload
    assert not any(p['context']['reactor_id'] == ALLY for p in prompts
               if p['context']['reaction_source_id'] == MERCY_CONTEXT)




@pytest.mark.parametrize('unseen_observer', [False, True])
def test_native_damage_receipt_stays_private_without_hiding_visible_damage(tmp_path, monkeypatch, unseen_observer):
    from combat import ext, target_knowledge
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.h1_support import ROOT
    from tests.test_a2_foundations3 import owner_bundle
    observer_id = 'actor:factory.worker2-foe1'
    private_condition_id = 'condition:test.private_ash_receipt'

    def bundles(rows):
        rows[3] = owner_bundle('ash', actor_id=observer_id)

    def setup(engine):
        if not {FOE, observer_id} <= engine.state.actors.keys():
            return
        engine._apply_condition(engine.state.actors[FOE], private_condition_id, 'test:setup', FOE,
                                expires_on='UNTIL_REMOVED', data={})
        if unseen_observer:
            engine._apply_condition(engine.state.actors[observer_id], 'condition:typed.invisible',
                                    'test:setup', observer_id, expires_on='UNTIL_REMOVED', data={})
            # This genesis fixture starts unseen. _create_match observes the
            # bare roster before match_start installs the starting conditions;
            # remove that pre-setup memory before the genesis state is sealed.
            for observations in engine.state.observations.values():
                observations.pop(observer_id, None)

    # Load providers before monkeypatch snapshots the registry; otherwise its
    # teardown can remove providers lazily registered by the first fixture.
    ext.has('match_start')
    monkeypatch.setitem(ext._HOOKS, 'match_start', [*ext._HOOKS.get('match_start', ()), setup])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner_bundle('ash'),
        ally_talents=['FIRE_TAL_FIREBALL_ART'], extra_foes=1, bundle_transform=bundles,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                   FOE: {'x': 8, 'y': 6}, observer_id: {'x': 8, 'y': 5}})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(8, 6)).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    raw = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids)
    assert private_condition_id in raw.payload['target_conditions_before']
    assert observer_id in raw.payload['target_perceived_by']
    assert (target_knowledge.knowledge(engine, engine.state.actors[ALLY], engine.state.actors[observer_id]) is None) == unseen_observer
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    policy, _ = PolicyLibrary(ROOT).for_actor(ALLY)
    context = build_decision_context(engine, policy, for_ai=True, recent_event_limit=len(engine.events))
    projected = next((e for e in context.recent_events if e['sequence'] == raw.sequence), None)
    assert projected is not None, 'visible damage must remain in AI projection'
    assert not {'target_conditions_before', 'target_perceived_by', 'target_active_before'} & projected['payload'].keys(), 'private damage snapshots must be absent from AI projection'
    assert 'hp_damage' in projected['payload']
    assert private_condition_id in next(e for e in engine.events if e.sequence == raw.sequence).payload['target_conditions_before']


def test_paid_mercy_restrains_a_dream_sleeping_creature_after_commit_and_reload(tmp_path, monkeypatch):
    """Dream Sleep is unconscious (Dreams core): a living sleeper is still a helpless restraint subject."""
    from combat import ext
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    from tests.test_mgr_t14_ash_mercy_parent import mercy, SCENE

    def sleep(engine):
        if FOE in engine.state.actors:
            engine._apply_condition(engine.state.actors[FOE], 'condition:typed.dream_sleep', 'test:setup',
                                    FOE, expires_on='UNTIL_REMOVED', data={})

    # Load providers before monkeypatch snapshots the registry, as the receipt regression above does.
    ext.has('match_start')
    monkeypatch.setitem(ext._HOOKS, 'match_start', [*ext._HOOKS.get('match_start', ()), sleep])
    doc = sheet([FEATURE], foundation={'foundation_id': 'red_lotus_ash_returning_v0_2B',
        'stage': 'Refined', 'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                                       'maximum': 1, 'current': 1}}, name='Wren')
    doc['identity']['proficiency_bonus'] = 4
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([], name='Mara')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 200
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, ally_talents=['FIRE_TAL_FIREBALL_ART'],
        foe_sheet=foe, positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 8, 'y': 6}},
        seed='ASH-MERCY', named=True)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.dream_sleep' for c in before.state.actors[FOE].conditions.values())
    assert before.state.actors[FOE].current_hp > 0
    prompts = mercy(combat, table, mid, context='genuine', recipient=ALLY, subject=FOE)
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == SCENE for p in prompts), 'sleeping creature must reach the restraint choice'
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE]
    assert len(grants) == 1 and grants[0].target_ids == (ALLY,)
    fact = next(e for e in engine.events if e.payload.get('fact_kind') == 'ash_mercy_restraint')
    assert 'context' not in fact.payload
