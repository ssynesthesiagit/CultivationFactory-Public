"""Refined: Clotted Iron Blood — the Blackblood Guard evolution rider.

The selected Refined expression adds one PB to the same Blackblood
Guard reduction: the same actual spend of 1 Blackblood Pressure and
the same Reaction, in the same damage packet, with no second Reaction
or resource spend. Unselected, unowned and suppressed expressions
leave the base reduction alone, the selection is once per fight, an
AI owner auto-selects it, and it survives a table commit and cold
reload.
"""
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (OWNER, FOE, ALLY, fixture, settle, candidate,
                                   reload, turn, sealed_native_attack)

B = 'true_blackblood_physique_v0_2C'
POOL = 'resource:foundation.blackblood_pressure'
GUARD = f'foundation.{B}.blackblood_guard'
REACTION = f'reaction:typed.{GUARD}'
EXPRESSION = f'foundation.{B}.refined_clotted_iron_blood'
EXPRESSION_NAME = 'Foundation expression: Refined: Clotted Iron Blood'
BASE = 6   # PB 4 + CON key modifier 2
EXTRA = 4  # the Refined expression's additional PB


def setup(tmp_path, *, stage='Refined', held=1, ask=True, modes=None,
          maxhp=500, hostile_mod=40, transform=None):
    document = sheet([], kit={'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.weapon.jian', 'name': 'Jian', 'quantity': 1}]}})
    document['foundation'] = {'foundation_id': B, 'stage': stage,
        'resource': {'name': 'Blackblood Pressure', 'resource_id': 'tianxia.resource.foundation.' + B,
                     'maximum': 1, 'current': held}}
    owner = compile_character(document, actor_id=OWNER, reaction_plan={'ask': ask})
    for action in owner['action_catalog']:
        if action.get('parameters', {}).get('typed', {}).get('weapon'):
            action['attack_bonus'] = 100
            action['parameters']['typed']['attack_bonus'] = 100
    sealed_native_attack(owner, 'Owner hit', attack_bonus=100, modifier=0, attacks=1)
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)

    def seal(bundles):
        sealed_native_attack(bundles[2], 'Hostile hit', modifier=hostile_mod, attack_bonus=100, attacks=1)
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = maxhp
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        if transform:
            transform(bundles)

    return fixture(tmp_path, [], owner_bundle=owner, ask=ask, seed='A2GFOU4',
                   bundle_transform=seal, foe_position={'x': 5, 'y': 6}, modes=modes)


def use(combat, table, mid, name, target=None, choices=None):
    found = candidate(combat, mid, name, target=target)
    return settle(table, mid, found.candidate_id, choices=choices or {})


def foe_attack(combat, table, mid, *, choices=None):
    return use(combat, table, mid, 'Hostile hit', target=OWNER, choices=choices or {})


def guard_prompts(prompts):
    return [p for p in prompts if p['context'].get('reaction_source_id') == REACTION]


def guard_logs(engine):
    return [e.payload.get('log') for e in engine.events
            if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == GUARD]


def held_expression(engine):
    owner = engine.state.actors[OWNER]
    return next((c for c in owner.conditions.values()
                 if c.condition_id.endswith('condition:typed.foundation_combat.expression')), None)


def named_candidates(engine, name):
    return [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == name]


def damage_chain(engine):
    rolled = next(e for e in engine.events if e.event_type == 'DAMAGE_ROLLED')
    committed = next(e for e in engine.events
                     if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    return rolled.payload['combined_total'], committed.payload['hp_damage']


def suppress_expression(bundles):
    """A hostile native effect that ends the Refined expression condition."""
    foe = bundles[2]
    source = 'action:test.clotted_suppress'
    foe['action_catalog'].append({
        'source_definition_id': source, 'display_name': 'Hostile suppress',
        'owner_id': FOE, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
        'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60, 'costs': [],
        'parameters': {'typed': {'source': 'test.clotted_suppress',
                                 'effects': [{'type': 'remove_condition',
                                              'condition': 'foundation_combat.expression',
                                              'applies_to': 'target'}],
                                 'riders': [], 'duration': {'kind': 'instant'}}},
    })
    foe['actor_template']['action_ids'].append(source)
    foe.pop('bundle_sha256', None)
    foe['bundle_sha256'] = canonical_sha256(foe)


def test_selected_refined_adds_pb_in_same_guard_resolution(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, EXPRESSION_NAME)
    turn(table, mid, FOE)
    prompts = foe_attack(combat, table, mid, choices={REACTION: 'USE'})
    prompt = next(p for p in guard_prompts(prompts))
    assert 'Blackblood Guard' in prompt['summary']
    assert f'Clotted Iron Blood adds {EXTRA} to the reduction' in prompt['table_note']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    logs = guard_logs(engine)
    assert logs and f'reduce damage by {BASE + EXTRA}' in logs[-1]
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.source_definition_id == GUARD]
    assert len(spends) == 1
    assert spends[0].payload['amount'] == 1
    assert spends[0].payload['resource_id'] == POOL
    assert owner.resources[POOL] == 0
    assert not owner.reaction_available
    rolled, committed = damage_chain(engine)
    assert committed == rolled - (BASE + EXTRA)


def test_unselected_refined_keeps_base_reduction(tmp_path):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, FOE)
    prompts = foe_attack(combat, table, mid, choices={REACTION: 'USE'})
    prompt = next(p for p in guard_prompts(prompts))
    assert 'Refined expression' not in prompt['table_note']
    engine = reload(tmp_path, mid)
    assert f'reduce damage by {BASE}' in guard_logs(engine)[-1]
    rolled, committed = damage_chain(engine)
    assert committed == rolled - BASE


def test_unowned_awakened_offers_no_expression(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Awakened')
    engine = reload(tmp_path, mid)
    assert not named_candidates(engine, EXPRESSION_NAME)
    turn(table, mid, FOE)
    foe_attack(combat, table, mid, choices={REACTION: 'USE'})
    engine = reload(tmp_path, mid)
    assert f'reduce damage by {BASE}' in guard_logs(engine)[-1]


def test_suppressed_expression_keeps_base_reduction(tmp_path):
    combat, table, mid = setup(tmp_path, transform=suppress_expression)
    use(combat, table, mid, EXPRESSION_NAME)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile suppress', target=OWNER)
    engine = reload(tmp_path, mid)
    assert held_expression(engine) is None
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    foe_attack(combat, table, mid, choices={REACTION: 'USE'})
    engine = reload(tmp_path, mid)
    assert held_expression(engine) is None
    assert f'reduce damage by {BASE}' in guard_logs(engine)[-1]


def test_refined_expression_is_once_per_fight(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, EXPRESSION_NAME)
    engine = reload(tmp_path, mid)
    assert held_expression(engine) is not None
    assert held_expression(engine).data.get('feature') == EXPRESSION
    assert not named_candidates(engine, EXPRESSION_NAME)


def test_guard_cannot_pay_with_pressure_the_same_hit_generates(tmp_path):
    combat, table, mid = setup(tmp_path, held=0, maxhp=20, hostile_mod=12)
    use(combat, table, mid, EXPRESSION_NAME)
    turn(table, mid, FOE)
    prompts = foe_attack(combat, table, mid)
    assert not guard_prompts(prompts)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOL] == 1
    assert 0 < owner.current_hp <= owner.maximum_hp // 2


def test_declining_the_guard_spends_nothing_and_stays_pure(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, EXPRESSION_NAME)
    turn(table, mid, FOE)
    prompts = foe_attack(combat, table, mid, choices={REACTION: None})
    assert guard_prompts(prompts)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOL] == 1
    assert owner.reaction_available
    assert not guard_logs(engine)
    rolled, committed = damage_chain(engine)
    assert committed == rolled
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    foe_attack(combat, table, mid, choices={REACTION: None})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOL] == 1
    assert owner.reaction_available


def test_ai_owner_auto_selects_the_refined_expression(tmp_path):
    combat, table, mid = setup(tmp_path, modes={OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL'})
    engine = reload(tmp_path, mid)
    assert held_expression(engine) is not None
    assert held_expression(engine).data.get('feature') == EXPRESSION
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    turn(table, mid, FOE)
    foe_attack(combat, table, mid, choices={REACTION: 'USE'})
    engine = reload(tmp_path, mid)
    assert f'reduce damage by {BASE + EXTRA}' in guard_logs(engine)[-1]


def test_selected_refined_survives_commit_and_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, EXPRESSION_NAME)
    turn(table, mid, FOE)
    foe_attack(combat, table, mid, choices={REACTION: 'USE'})
    engine = reload(tmp_path, mid)
    assert held_expression(engine) is not None
    assert held_expression(engine).data.get('feature') == EXPRESSION
    assert f'reduce damage by {BASE + EXTRA}' in guard_logs(engine)[-1]
    rolled, committed = damage_chain(engine)
    assert committed == rolled - (BASE + EXTRA)


def test_perfected_owner_also_gets_the_refined_rider(tmp_path):
    """Refined rows are cumulative: a Perfected owner still owns and uses them."""
    combat, table, mid = setup(tmp_path, stage='Perfected')
    engine = reload(tmp_path, mid)
    assert named_candidates(engine, EXPRESSION_NAME)
    use(combat, table, mid, EXPRESSION_NAME)
    turn(table, mid, FOE)
    prompts = foe_attack(combat, table, mid, choices={REACTION: 'USE'})
    prompt = next(p for p in guard_prompts(prompts))
    assert f'Clotted Iron Blood adds {EXTRA} to the reduction' in prompt['table_note']
    engine = reload(tmp_path, mid)
    assert f'reduce damage by {BASE + EXTRA}' in guard_logs(engine)[-1]
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.source_definition_id == GUARD]
    assert len(spends) == 1
    rolled, committed = damage_chain(engine)
    assert committed == rolled - (BASE + EXTRA)


def test_absent_selection_reply_adds_no_pb(tmp_path):
    """Only an explicit True selects; a hook that answers nothing grants nothing."""
    from combat.ext.foundations4 import conversion_evolution_pb
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    row = {'refined_expression': EXPRESSION, 'pb': EXTRA}
    assert conversion_evolution_pb(engine, engine.state.actors[FOE], row) == 0
    assert conversion_evolution_pb(engine, engine.state.actors[OWNER], row) == 0

