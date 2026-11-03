"""Devouring Return: actual typed non-HP values through table commits and cold replay."""
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.ext import foundation_combat as f
from tests.h1_support import sheet
from tests.test_a2_foundations_two import table_fixture, use
from tests.worker2_support import turn, reload, OWNER, FOE

POOL = f.pool('devour')
CHOICE = f.CHOICE + 'foundation_combat'


def fixture(tmp_path, effects=None, *, current=1, owned=True, ask=True, modes=None):
    def transform(bundles):
        if effects is None:
            # A genuine compiled source, including its native damage and numeric
            # healing penalty. The first Return prompt (damage) is declined.
            document = sheet(['TAL_DEATH_WITHERING_HAND'], cl=15, dc=50)
            document['ability_scores_and_statistics']['technique_attack_bonus'] = 100
            foe = compile_character(document, actor_id=FOE, reaction_plan={'ask': True})
            bundles[2] = foe
        else:
            foe = bundles[2]
            source = 'action:test.return_scalar'
            foe['action_catalog'].append({'source_definition_id': source,
                'display_name': 'Declared scalar pressure', 'owner_id': FOE,
                'economy': 'ACTION', 'resolution_kind': 'TYPED',
                'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60, 'costs': [],
                'parameters': {'typed': {'source': source, 'numbers': {'pb': 12},
                    'effects': effects, 'riders': [], 'duration': {'kind': 'instant'}}}})
            foe['actor_template']['action_ids'].append(source)
        if not owned:
            bundles[0]['typed_passives'] = [r for r in bundles[0].get('typed_passives', [])
                if r.get('feature_id') != f.feature('devour', 'devouring_return')]
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = table_fixture(tmp_path, 'devour', current=current, transform=transform, ask=ask, modes=modes)
    turn(table, mid, FOE)
    return combat, table, mid


def reductions(engine):
    return [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
            and e.payload.get('receipt_kind') == 'scalar_pressure_reduced']


def test_real_withering_hand_non_damage_return_and_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    prompts = use(combat, table, mid, 'Withering Hand', OWNER,
                  choices={CHOICE: (None, ['use'])})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    receipts = reductions(engine)
    assert len(receipts) == 1
    p = receipts[0].payload
    assert p['pressure_kind'] == 'healing_denied'
    assert p['value_before'] == 4 and p['value_after'] == 0
    assert p['hostile_source_actor_id'] == FOE and p['value_id'] == 'healing_reduction'
    assert p['resource_spent'] == 1 and p['reaction_spent'] is True
    assert p['intent_id'] and p['instance_id'] and p['source_flags'] == []
    assert not [m for m in actor.modifiers.values() if m.target_field == 'healing_reduction']
    assert actor.resources[POOL] == 0 and not actor.reaction_available
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert actor.current_hp == before - damage.payload['hp_damage']
    assert len([p for p in prompts if p['context']['reaction_source_id'] == CHOICE]) == 2


@pytest.mark.parametrize('kind', ['drain', 'origin_theft', 'source_corruption'])
@pytest.mark.parametrize('accepted', [True, False])
def test_resource_value_is_reduced_once_or_declined(tmp_path, kind, accepted):
    effects = [{'type': 'spend_resource', 'applies_to': 'target', 'flat': 15,
                'resource_id': 'resource:core.qi', 'pressure_kind': kind,
                'evidence': 'Hostile loss of 15 Qi'}]
    combat, table, mid = fixture(tmp_path, effects)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    use(combat, table, mid, 'Declared scalar pressure', OWNER,
        choices={CHOICE: ['use'] if accepted else None})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    cut = 10 if kind in {'drain', 'origin_theft'} else 6
    assert actor.resources['resource:core.qi'] == before - 15 + (cut if accepted else 0)
    assert actor.resources[POOL] == (0 if accepted else 1)
    assert actor.reaction_available is (not accepted)
    assert len(reductions(engine)) == int(accepted)
    if accepted:
        assert reductions(engine)[0].payload['value_after'] == 15 - cut


@pytest.mark.parametrize('variant', ['zero', 'private', 'unknown', 'self', 'empty', 'unowned', 'private_kind', 'private_flag'])
def test_no_offer_for_ineligible_numeric_loss(tmp_path, variant):
    effect = {'type': 'spend_resource', 'applies_to': 'target', 'flat': 15,
              'resource_id': 'resource:core.qi', 'evidence': 'Hostile loss of Qi'}
    if variant == 'zero': effect['flat'] = 0
    if variant == 'private': effect['evidence'] = ''
    if variant == 'unknown': effect['resource_id'] = 'resource:unrepresented'
    if variant == 'self': effect['applies_to'] = 'self'
    if variant == 'private_kind': effect['pressure_kind'] = 'hidden_injury'
    if variant == 'private_flag': effect['source_flags'] = ['private']
    combat, table, mid = fixture(tmp_path, [effect], current=0 if variant == 'empty' else 1,
                                owned=variant != 'unowned')
    prompts = use(combat, table, mid, 'Declared scalar pressure', OWNER)
    engine = reload(tmp_path, mid)
    assert not reductions(engine)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert engine.state.actors[OWNER].reaction_available


def test_numeric_healing_penalty_persists_actual_reduced_value(tmp_path):
    effect = {'type': 'healing_reduction', 'applies_to': 'target',
              'evidence': 'healing the target receives is reduced by your Proficiency Bonus',
              'duration': 'until_start_of_your_next_turn'}
    combat, table, mid = fixture(tmp_path, [effect])
    use(combat, table, mid, 'Declared scalar pressure', OWNER)
    engine = reload(tmp_path, mid)
    modifiers = [m for m in engine.state.actors[OWNER].modifiers.values()
                 if m.target_field == 'healing_reduction']
    assert len(modifiers) == 1 and modifiers[0].value == 'minus:6'
    assert reductions(engine)[0].payload['value_after'] == 6
    from combat.typed_executor import stored_healing_reductions
    assert stored_healing_reductions(engine, engine.state.actors[OWNER], 20, consume=False) == 14
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    assert not [m for m in reload(tmp_path, mid).state.actors[OWNER].modifiers.values()
                if m.target_field == 'healing_reduction']


def test_same_source_numeric_reapplication_refreshes_instead_of_stacking(tmp_path):
    effect = {'type': 'healing_reduction', 'applies_to': 'target',
              'evidence': 'healing the target receives is reduced by your Proficiency Bonus',
              'duration': 'one_minute'}
    combat, table, mid = fixture(tmp_path, [effect])
    use(combat, table, mid, 'Declared scalar pressure', OWNER,
        choices={CHOICE: ['use']})
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Declared scalar pressure', OWNER)
    engine = reload(tmp_path, mid)
    penalties = [m for m in engine.state.actors[OWNER].modifiers.values()
                 if m.target_field == 'healing_reduction']
    # Reaction protects the first activation; the second refreshes it at the
    # original value, without a second Reaction or an extra stacked penalty.
    assert len(penalties) == 1 and penalties[0].value == 'minus:12'
    assert len(reductions(engine)) == 1


@pytest.mark.parametrize('evidence', ['healing it receives is halved', 'it cannot regain Hit Points'])
def test_non_numeric_healing_prohibitions_do_not_invent_pressure(tmp_path, evidence):
    combat, table, mid = fixture(tmp_path, [{'type': 'healing_reduction',
        'applies_to': 'target', 'evidence': evidence, 'duration': 'one_minute'}])
    prompts = use(combat, table, mid, 'Declared scalar pressure', OWNER)
    engine = reload(tmp_path, mid)
    assert not reductions(engine)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert engine.state.actors[OWNER].reaction_available
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]


def test_local_ai_defender_uses_legal_numeric_return_without_player_prompt(tmp_path):
    combat, table, mid = fixture(tmp_path, [{'type': 'spend_resource',
        'applies_to': 'target', 'flat': 15, 'resource_id': 'resource:core.qi',
        'evidence': 'Hostile drain of 15 Qi'}], ask=False)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    use(combat, table, mid, 'Declared scalar pressure', OWNER)
    engine = reload(tmp_path, mid)
    assert len(reductions(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOL] == 0


def test_same_event_spark_cannot_pay_scalar_return(tmp_path):
    effects = [{'type': 'gain_resource', 'applies_to': 'target', 'flat': 1,
                'resource_id': POOL, 'evidence': 'Gain one Devoured Origin Spark'},
               {'type': 'spend_resource', 'applies_to': 'target', 'flat': 15,
                'resource_id': 'resource:core.qi', 'evidence': 'Hostile drain of 15 Qi'}]
    combat, table, mid = fixture(tmp_path, effects, current=0)
    prompts = use(combat, table, mid, 'Declared scalar pressure', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert engine.state.actors[OWNER].reaction_available
    assert not reductions(engine)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]


def test_return_prompt_and_settlement_name_the_drained_resource(tmp_path):
    # Review finding: the Reaction prompt and history line said only "resource loss",
    # so the player could not tell which resource Devouring Return was protecting.
    import json
    from combat.scalar_pressure import pressure_label
    effects = [{'type': 'spend_resource', 'applies_to': 'target', 'flat': 15,
                'resource_id': 'resource:core.qi', 'pressure_kind': 'drain',
                'evidence': 'Hostile loss of 15 Qi'}]
    combat, table, mid = fixture(tmp_path, effects)
    prompts = use(combat, table, mid, 'Declared scalar pressure', OWNER, choices={CHOICE: ['use']})
    offered = [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert offered and 'Qi loss by 10 (from 15 to 5)' in json.dumps(offered)
    engine = reload(tmp_path, mid)
    assert any('Qi loss reduced from 15 to 5' in repr(e) for e in engine.events)
    assert pressure_label('drain', 'resource:core.qi') == 'Qi loss'
    assert pressure_label('origin_theft', 'resource:core.stamina') == 'origin theft of Stamina'
    assert pressure_label('source_corruption', 'resource:core.qi') == 'Qi lost to source corruption'
    assert pressure_label('healing_denied', 'healing_reduction') == 'healing penalty'
