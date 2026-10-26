"""Funeral Ash parent through shipped builds and actual table context answers."""
import pytest
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_foundations3 import owner_bundle, pool
from combat.ext.foundation_context import CONTEXT, public_scene_context

# compile_blocks discovers split feature rows dynamically. The public test
# exporter follows literal inputs, so retain the same generation rules that the
# native build uses instead of silently testing a character without its ability.
ASH_GENERATION_RULES = 'combat/rules/feature_blocks.d/foundations3.json'


def native_fixture(tmp_path, *, incoming=True, seed='ASH-PARENT', initial=0, foe_hp=200,
                   foe_talents=None, owner_hp=None, owned=True, positions=None,
                   owner_talents=None, ally_talents=None, bundle_transform=None, foe_dc=16, extra_foes=0, named=False):
    bundle = owner_bundle('ash', initial=initial)
    if not incoming:
        from combat.factory_compiler import compile_character
        doc = sheet(owner_talents or ['FIRE_TAL_FIREBALL_ART'], cl=5, dc=100 if owner_talents else 16, foundation={
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
    foe = sheet(foe_talents or ['FIRE_TAL_FIREBALL_ART'], cl=5, dc=foe_dc, name='Mara' if named else None)
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = foe_hp
    if owned:
        assert (ROOT / ASH_GENERATION_RULES).is_file()
        assert any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
                   for row in bundle['typed_passives']), 'Native Ash fixture must own Funeral Ash generation'
    return fixture(tmp_path, [], owner_bundle=bundle if owned else None,
        ally_talents=['FIRE_TAL_FIREBALL_ART'] if ally_talents is None else ally_talents,
        bundle_transform=bundle_transform,
        foe_sheet=foe, seed=seed, extra_foes=extra_foes, named=named,
        positions=positions or {OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':8,'y':6}})


def controlled_settle(combat, table, mid, row, *, choices=None):
    """Native table dispatch, with deterministic primary choices for AUTO seats.

    The local adapter sees the real observed candidate context. The API provider
    is an in-process fake; neither route calls a model or bypasses table authority.
    Reaction policy, table pauses, settlement, persistence and replay remain real.
    """
    if combat.decision(mid)['control_mode'] not in ('LOCAL_AUTO', 'API_AUTO'):
        return settle(table, mid, row.candidate_id, choices=choices)
    from unittest.mock import patch
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import AI_RESPONSE_SCHEMA

    original = combat.controller
    class DirectedController:
        def __getattr__(self, name):
            return getattr(original, name)
        def choose_primary_action(self, context):
            # AI area previews may use a different legal centre for the same
            # source. Select only a candidate actually offered to this seat.
            choices = [c for c in context.legal_candidates
                       if c.source_definition_id == row.source_definition_id]
            assert choices, row.source_definition_id
            chosen = min(choices, key=lambda c: (
                0 if c.candidate_id == row.candidate_id else 1,
                abs(c.destination.x - row.destination.x) + abs(c.destination.y - row.destination.y)
                if c.destination and row.destination else 100000, c.candidate_id))
            return ManualControllerAdapter(lambda c: (chosen.candidate_id, chosen.option_ids)).choose_primary_action(context)

    class FakeProvider:
        def status(self):
            return {'ready': True}
        def complete_json(self, **kwargs):
            assert kwargs['purpose'] == 'combat_decision'
            return {'value': {'schema': AI_RESPONSE_SCHEMA,
                'action_intent': row.model_dump(mode='json', include={
                    'candidate_id', 'decision_id', 'state_version', 'actor_id',
                    'target_ids', 'destination', 'option_ids'})}}

    with patch.object(combat, 'controller', DirectedController()), patch.object(combat, 'ai_provider', FakeProvider()):
        return settle(table, mid, row.candidate_id, choices=choices, auto=True)


def controlled_turn(combat, table, mid, actor):
    for _ in range(12):
        engine = combat._load_session(mid).engine
        if engine.state.current_actor_id == actor:
            return
        row = next(c for c in engine.legal_candidates() if c.kind == 'END_TURN')
        controlled_settle(combat, table, mid, row)
    raise AssertionError('No turn')


def cast(combat, table, mid, *, incoming=True, circumstances='real', detail='battlefield'):
    controlled_turn(combat, table, mid, FOE if incoming else OWNER)
    row = candidate(combat, mid, 'Fireball Art', at=(3,6) if incoming else (8,6))
    return controlled_settle(combat, table, mid, row, choices={CONTEXT: circumstances,
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
    # Fireball Art's generic area now spares allies. Furnace Vent explicitly
    # affects "Each creature", so this exercises actual friendly damage rather
    # than assuming a generic area includes the Ash owner.
    combat, table, mid = native_fixture(tmp_path, ally_talents=['TAL_ALCHEMY_FURNACE_VENT'])
    turn(table, mid, ALLY)
    row = candidate(combat, mid, 'Furnace Vent', at=(3,6))
    prompts = settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.source_definition_id == row.source_definition_id and OWNER in e.target_ids]
    assert packets and all(e.actor_id == ALLY for e in packets)
    assert sum(e.payload['hp_damage'] for e in packets) > 0
    assert engine.state.actors[OWNER].current_hp < engine.state.actors[OWNER].maximum_hp
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                   and e.payload.get('resource_id') == pool('ash') for e in engine.events)
    assert not any(p['context']['reaction_source_id'].startswith(CONTEXT) for p in prompts)


def test_automatic_owner_keeps_unknown_scene_facts_unknown_without_model_call(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, FOE)
    for aid in (OWNER, ALLY, FOE):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode='LOCAL_AUTO')
    prompts = cast(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    assert not any(p['context']['reaction_source_id'].startswith(CONTEXT) for p in prompts)
    context = next(e for e in reversed(engine.events) if e.payload.get('fact_kind') == 'foundation_event_context')
    assert context.payload['circumstances'] == 'unknown'


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('route', ['incoming', 'outgoing', 'ending'])
def test_all_automatic_generation_uses_sealed_public_setup(tmp_path, mode, route):
    from combat.gate5_service import CombatService

    def declare(bundles):
        # Exercise the production setup validator, not fabricated bundle flags.
        bundles[0] = CombatService._with_prefight(object.__new__(CombatService), bundles[0], {
            OWNER: ['setup-choice:ash_public_circumstances:1',
                    'setup-choice:ash_public_residue:1', 'setup-choice:ash_public_ending:1']})

    combat, table, mid = native_fixture(tmp_path, incoming=route == 'incoming',
        foe_hp=1 if route == 'ending' else 200, bundle_transform=declare)
    for aid in (OWNER, ALLY, FOE):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode=mode)
    before = reload(tmp_path, mid)
    scene = public_scene_context(before, before.state.actors[OWNER])
    assert scene['circumstances'] == 'real'
    assert before.state.actors[OWNER].resources[pool('ash')] == 0
    if route == 'outgoing':
        # First hit establishes a wound; the actual second packet qualifies.
        assert cast(combat, table, mid, incoming=False) == []
        assert reload(tmp_path, mid).state.actors[OWNER].resources[pool('ash')] == 0
        controlled_turn(combat, table, mid, FOE)
        controlled_turn(combat, table, mid, OWNER)
    prompts = cast(combat, table, mid, incoming=route == 'incoming')
    engine = reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'].startswith(CONTEXT) for p in prompts)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1, 'all-automatic encounter must generate from sealed public facts'
    fact = next(e for e in reversed(engine.events) if e.payload.get('route') == route)
    assert fact.payload['circumstances'] == 'real'
    assert fact.payload['setup_sequence'] == scene['setup_sequence'] < fact.sequence
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED')
    assert damage.payload['target_context_witnesses_before'] == []


@pytest.mark.parametrize('circumstances,expected', [(0, 0), (1, 1), (2, 0), (3, 0), (4, 0), (5, 0)])
def test_all_automatic_public_setup_exclusions_and_owner_knowledge(tmp_path, circumstances, expected):
    from combat.gate5_service import CombatService

    def declare(bundles):
        # The ally also owns Ash and knows real danger. Its declaration cannot
        # supply facts unknown to OWNER, even though both share the same team.
        bundles[1] = owner_bundle('ash', initial=0, actor_id=ALLY)
        service = object.__new__(CombatService)
        for index, value in ((0, circumstances), (1, 1)):
            actor_id = bundles[index]['actor_id']
            bundles[index] = service._with_prefight(bundles[index], {
                actor_id: [f'setup-choice:ash_public_circumstances:{value}']})

    combat, table, mid = native_fixture(tmp_path, bundle_transform=declare)
    for aid in (OWNER, ALLY, FOE):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode='LOCAL_AUTO')
    assert cast(combat, table, mid) == []
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == expected
    fact = next(e for e in reversed(engine.events)
                if e.actor_id == OWNER and e.payload.get('route') == 'incoming')
    assert fact.payload['circumstances'] == ('unknown', 'real', 'staged', 'harmless', 'voluntary', 'training')[circumstances]


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('route', ['incoming', 'outgoing', 'ending'])
def test_automatic_owner_can_use_public_native_witness_testimony(tmp_path, mode, route):
    combat, table, mid = native_fixture(tmp_path, incoming=route == 'incoming',
        foe_hp=1 if route == 'ending' else 200)
    if route == 'outgoing':
        cast(combat, table, mid, incoming=False)
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    prompts = cast(combat, table, mid, incoming=route == 'incoming',
        detail='defeat' if route == 'ending' else 'battlefield')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    fact = next(e for e in reversed(engine.events) if e.payload.get('route') == route)
    assert fact.payload['circumstances'] == 'real'
    assert fact.payload['declarant'] in (ALLY, FOE)
    assert any(p['context']['reaction_source_id'] == CONTEXT for p in prompts)


def test_automatic_owner_public_witness_can_preserve_unknown_context(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    cast(combat, table, mid, circumstances='unknown')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    fact = next(e for e in reversed(engine.events) if e.payload.get('fact_kind') == 'foundation_event_context')
    assert fact.payload['declarant'] != OWNER and fact.payload['circumstances'] == 'unknown'


@pytest.mark.parametrize('target,awake', [(OWNER, False), (OWNER, True), (FOE, False)])
def test_native_dream_sleep_excludes_helpless_target_and_unconscious_owner(tmp_path, target, awake):
    from combat.ext.dreams_core import SLEEP
    from combat.ext.foundation_context import conscious
    from tests.test_a2_foundations3 import add_action

    def prepare(bundles):
        # Deterministic precondition only; Sleep itself is the shipped action,
        # and damage, waking, Ash generation and replay use native transactions.
        add_action(bundles[2 if target == OWNER else 0], 'Wound and drowse', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'drowsy', 'expires_on': 'UNTIL_REMOVED'}],
            target_kind='ANY_CREATURE', economy='NONE')
        if target == OWNER:
            from combat.factory_compiler import compile_character
            doc = sheet([], cl=5)
            doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1
            bundles[3] = compile_character(doc, actor_id=bundles[3]['actor_id'])

    victim = 'actor:factory.worker2-foe1'
    combat, table, mid = native_fixture(tmp_path, incoming=False,
        foe_talents=['TAL_DREAM_SLEEP'] if target == OWNER else None, foe_dc=100,
        owner_talents=['FIRE_TAL_FIREBALL_ART', 'TAL_DREAM_SLEEP'], bundle_transform=prepare,
        extra_foes=1 if target == OWNER else 0,
        positions={OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':8,'y':6},
                   victim: {'x':3,'y':0}} if target == OWNER else None)
    turn(table, mid, FOE if target == OWNER else OWNER)
    settle(table, mid, candidate(combat, mid, 'Wound and drowse', target=target).candidate_id,
        choices={CONTEXT: 'unknown'})
    if not awake:
        settle(table, mid, candidate(combat, mid, 'Sleep', target=target).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == SLEEP for c in engine.state.actors[target].conditions.values()) == (not awake)
    if target == OWNER:
        assert conscious(engine.state.actors[OWNER]) == awake
        assert engine.state.actors[OWNER].resources[pool('ash')] == 0
        # A real allied finishing blow is an otherwise qualifying observed
        # ending. The owner remains asleep at settlement and after cold reload.
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3,0)).candidate_id,
            choices={CONTEXT: 'real', CONTEXT + '.detail': 'defeat'})
        engine = reload(tmp_path, mid)
        assert any(c.condition_id == SLEEP for c in engine.state.actors[OWNER].conditions.values()) == (not awake)
        assert engine.state.actors[victim].current_hp == 0
        assert any(e.event_type == 'ENTITY_DEFEATED' and e.actor_id == victim for e in engine.events)
        assert engine.state.actors[OWNER].resources[pool('ash')] == int(awake), 'sleeping observer must not gain Funeral Ash'
    else:
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
        cast(combat, table, mid, incoming=False)
        engine = reload(tmp_path, mid)
        damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids)
        assert SLEEP in damage.payload['target_conditions_before']
        assert not any(c.condition_id == SLEEP for c in engine.state.actors[FOE].conditions.values())
        assert engine.state.actors[OWNER].resources[pool('ash')] == 0


@pytest.mark.parametrize('initial', [0, 1])
def test_native_incoming_cannot_spend_the_ash_it_is_about_to_generate(tmp_path, initial):
    cautery = 'foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery'
    combat, table, mid = native_fixture(tmp_path, incoming=False, initial=initial,
        owner_talents=['FIRE_TAL_FIREBALL_ART', cautery])
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    assert any(r.get('feature_id') == cautery for r in before.typed_reaction_rows[OWNER])
    prompts = settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(3,6)).candidate_id,
        choices={'reaction:typed.' + cautery: 'first', CONTEXT: 'real'})
    engine = reload(tmp_path, mid)
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
             and e.payload.get('resource_id') == pool('ash')]
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == cautery]
    assert len(spent) == len(resolved) == initial
    assert any('cautery' in p['context']['reaction_source_id'].lower() for p in prompts) == bool(initial)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    gain = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.payload.get('resource_id') == pool('ash'))
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert damage.sequence < gain.sequence
    if initial:
        assert resolved[0].payload['reduction'] > 0
        assert spent[0].sequence < damage.sequence
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
    combat, table, mid = native_fixture(tmp_path, incoming=False, foe_hp=1, named=True)
    prompts = cast(combat, table, mid, incoming=False, detail=ending)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.terminal_result is not None
    assert engine.state.actors[OWNER].resources[pool('ash')] == expected
    defeated = next(e for e in engine.events if e.event_type == 'ENTITY_DEFEATED' and e.actor_id == FOE)
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == pool('ash')]
    assert all(e.sequence > defeated.sequence for e in gains)
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and FOE in e.target_ids and e.payload.get('remaining_hp') == 0)
    assert damage.sequence < defeated.sequence
    action = engine.action_catalog[damage.source_definition_id]
    assert action.display_name == 'Fireball Art'
    subject_name = engine.state.actors[FOE].display_name
    context_prompts = [p for p in prompts if p['context']['reaction_source_id'].startswith(CONTEXT)]
    assert context_prompts
    for p in context_prompts:
        # context is the three-field answer binding. Assert actual player-facing
        # fields, with distinct creature names, rather than nonexistent keys.
        assert p['action'] == 'Fireball Art'
        assert p['affected'] == subject_name == 'Mara'
        assert 'Funeral Ash' in p['moment']
        assert 'Fireball Art' in p['moment'] and subject_name in p['moment']
    receipt = next(e for e in engine.events if e.payload.get('route') == 'ending')
    assert receipt.payload['event_sequence'] == defeated.sequence
    assert receipt.source_definition_id == action.source_definition_id
    assert 'Fireball Art' in receipt.payload['log'] and subject_name in receipt.payload['log']


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
