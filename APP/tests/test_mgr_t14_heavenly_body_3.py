"""Whole-row Heavenly Body delivery: real hostile hits, table commits, cold replay.

The retained providers are exercised, not replaced. No resource, expression,
damage-history receipt, or round-use flag is injected into fight state.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.ext import foundation_combat as foundation
from tests.h1_support import sheet
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, sealed_native_attack, turn, settle, reload, candidate,
)

PREFIX = 'foundation.heavenly_body_v0_2F.'
POOL = 'resource:foundation.heavenly_integrity'
STRIKE = PREFIX + 'integrity_strike'
ORTHODOX = PREFIX + 'orthodox_answering_strike'
JADE = PREFIX + 'jade_gold_guard'
GUARD = PREFIX + 'integrity_guard'
STRIKE_ASK = 'reaction:typed.' + STRIKE
GUARD_ASK = foundation.CHOICE + 'foundation_combat'
RECORDS = (STRIKE, JADE, ORTHODOX)


def fight(tmp_path, *, stage='Perfected', expression=None, attacks=1, ask=True,
          owner=True, talents=(), miss=False, resistance=False, modes=None):
    source = {'foundation_id': 'heavenly_body_v0_2F', 'stage': stage,
              'resource': {'name': 'Heavenly Integrity', 'resource_id': 'res.heavenly_integrity',
                           'maximum': 1, 'current': 0}}
    document = sheet(list(talents), cl=15, name='Wren')
    if owner:
        document['foundation'] = source
    document['ability_scores_and_statistics']['hit_points']['maximum'] = 500
    document['ability_scores_and_statistics']['technique_attack_bonus'] = 50
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': ask})

    def seal(bundles):
        from combat.canonical import canonical_sha256
        sealed_native_attack(bundles[0], 'Return blow', damage_type='POISON',
                             attack_bonus=-50 if miss else 50, modifier=10, range_ft=5)
        sealed_native_attack(bundles[2], 'Hostile blow', damage_type='POISON',
                             attack_bonus=50, modifier=40, range_ft=5, attacks=attacks)
        # An independent opponent, so the attacker and Integrity producer can differ.
        sealed_native_attack(bundles[1], 'Minion blow', damage_type='POISON',
                             attack_bonus=50, modifier=40, range_ft=5)
        if not ask:
            from tests.test_a2_foundations3 import add_action
            add_action(bundles[0], 'AI return attack', [{'type': 'attack', 'attack_kind': 'weapon',
                'on_hit': [{'type': 'damage', 'flat': 40, 'damage_types': ['poison'], 'applies_to': 'target'}]}], bonus=100)
            bundles[0]['action_catalog'][-1]['parameters']['expected_damage'] = 40
        for b in bundles:
            b['actor_template']['maximum_hp'] = 500
            if b['actor_id'] == FOE:
                b['actor_template']['armor_class'] = 1
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)

    combat, table, mid = fixture(
        tmp_path, [], owner_bundle=bundle, ask=ask, named=True,
        foe_position={'x': 3, 'y': 5}, bundle_transform=seal,
        team_overrides={ALLY: 'team:opponents'}, seed='A2GFOU2', modes=modes,
        # Factory actors intentionally ignore runtime-only template traits.
        # Obtain resistance from an actually owned, compiled passive instead.
        foe_sheet=sheet(['tianxia.talent.poison.venom_body_method'], cl=15, name='Mara')
                  if resistance else None,
    )
    if expression:
        use(combat, table, mid, 'Foundation expression: ' + expression)
        chosen = foundation.held(reload(tmp_path, mid).state.actors[OWNER], 'expression')
        assert chosen and chosen.data['feature'] == PREFIX + expression.lower().replace('-', '_').replace(' ', '_')
    return combat, table, mid


def use(combat, table, mid, name, target=None, *, accept_strike=True, accept_guard=False):
    c = candidate(combat, mid, name, target=target)
    return settle(table, mid, c.candidate_id, choices={
        STRIKE_ASK: 'first' if accept_strike else None,
        GUARD_ASK: 'use' if accept_guard else None,
    })


def generate(combat, table, mid, tmp_path):
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[POOL] == 1
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.source_definition_id == 'passive:' + GUARD]
    # The real damage receipt precedes the real generator's gain receipt.
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    gain = next(e for e in reversed(engine.events) if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                and e.payload.get('resource_id') == POOL)
    assert damage.sequence < gain.sequence
    turn(table, mid, OWNER)


def strike_receipts(engine, after=0):
    return [e for e in engine.events if e.sequence > after and e.event_type == 'PASSIVE_TRIGGERED'
            and e.source_definition_id == STRIKE]


@pytest.mark.parametrize('stage,expression,bonus', [
    ('Awakened', None, 4),
    ('Refined', None, 4),
    ('Refined', 'Jade-Gold Guard', 4),
    ('Refined', 'Orthodox Answering Strike', 8),
    ('Perfected', None, 8),
    ('Perfected', 'Orthodox Answering Strike', 12),
])
def test_strike_whole_numeric_contract_one_spend_and_reload(tmp_path, stage, expression, bonus):
    combat, table, mid = fight(tmp_path, stage=stage, expression=expression)
    generate(combat, table, mid, tmp_path)
    before = reload(tmp_path, mid)
    sequence = before.state.event_sequence
    prompts = use(combat, table, mid, 'Return blow', FOE)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[POOL] == 0 and actor.reaction_available
    receipts = strike_receipts(engine, sequence)
    assert len(receipts) == 1 and f'adds {bonus} damage' in receipts[0].payload['log']
    damage = [e for e in engine.events if e.sequence > sequence and e.event_type == 'DAMAGE_COMMITTED'
              and e.actor_id == OWNER and FOE in e.target_ids]
    rolled = next(e for e in engine.events if e.sequence > sequence and e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER)
    assert len(damage) == 1
    assert damage[0].payload['hp_damage'] == rolled.payload['total'] + bonus
    spent = [e for e in engine.events if e.sequence > sequence and e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == STRIKE_ASK)
    assert 'Integrity Strike' in str(prompt)
    assert prompt['action'] == 'Return blow'
    assert prompt['affected'] == engine.state.actors[FOE].display_name


@pytest.mark.parametrize('stage,expression,cut', [
    ('Awakened', None, 6),
    ('Refined', None, 6),
    ('Refined', 'Orthodox Answering Strike', 6),
    ('Refined', 'Jade-Gold Guard', 10),
    ('Perfected', 'Jade-Gold Guard', 14),
])
def test_jade_same_guard_spend_only_after_prior_hit(tmp_path, stage, expression, cut):
    combat, table, mid = fight(tmp_path, stage=stage, expression=expression, attacks=2)
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Hostile blow', OWNER, accept_guard=True)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    guards = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == GUARD]
    assert len(damage) == 2 and len(guards) == 1
    assert damage[0].sequence < guards[0].sequence < damage[1].sequence
    opened = [e for e in engine.events if e.event_type == 'REACTION_WINDOW_OPENED'
              and e.payload.get('checkpoint') == 'DAMAGE_APPLICATION']
    assert damage[-1].payload['hp_damage'] == opened[-1].payload['pending_damage'] - cut
    assert owner.resources[POOL] == 0 and not owner.reaction_available
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.payload.get('resource_id') == POOL]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == GUARD_ASK)
    assert 'Hostile blow' in prompt['moment'] and owner.display_name in prompt['moment']


@pytest.mark.parametrize('boundary', ['decline', 'miss', 'empty', 'wrong_owner', 'expired'])
def test_strike_boundaries_do_not_spend_or_add_damage(tmp_path, boundary):
    combat, table, mid = fight(tmp_path, owner=boundary != 'wrong_owner', miss=boundary == 'miss')
    if boundary not in {'empty', 'wrong_owner'}:
        generate(combat, table, mid, tmp_path)
    if boundary == 'expired':
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 0
    before = reload(tmp_path, mid)
    use(combat, table, mid, 'Return blow', FOE, accept_strike=boundary != 'decline')
    engine = reload(tmp_path, mid)
    assert not strike_receipts(engine, before.state.event_sequence)
    assert engine.state.actors[OWNER].resources.get(POOL, 0) == before.state.actors[OWNER].resources.get(POOL, 0)


def test_orthodox_uses_actual_attacker_not_another_enemy(tmp_path):
    combat, table, mid = fight(tmp_path, stage='Refined', expression='Orthodox Answering Strike')
    generate(combat, table, mid, tmp_path)
    before = reload(tmp_path, mid).state.event_sequence
    use(combat, table, mid, 'Return blow', ALLY)
    receipts = strike_receipts(reload(tmp_path, mid), before)
    assert len(receipts) == 1 and 'adds 4 damage' in receipts[0].payload['log']
    assert 'Orthodox Answering Strike' not in receipts[0].payload['log']


def test_automatic_strike_needs_no_player_answer(tmp_path, monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.raw_d20
    def draw(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        return roll.model_copy(update={'dice': (19,), 'natural_result': 19, 'total': 19 + modifier}) \
            if actor_id == OWNER and reason.startswith('ATTACK:') else roll
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', draw)
    combat, table, mid = fight(tmp_path, stage='Refined', expression='Orthodox Answering Strike', ask=False)
    generate(combat, table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER,
        'other': ALLY, 'relation': 'ALLY'}, expected_state_version=engine.state.state_version)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid).state.event_sequence
    prompts = []
    for _ in range(16):
        prompts.extend(settle(table, mid, 'ignored-for-real-ai-step', auto=True))
        engine = reload(tmp_path, mid)
        if strike_receipts(engine, before) or engine.state.current_actor_id != OWNER:
            break
    assert not [p for p in prompts if p['context']['reaction_source_id'] == STRIKE_ASK]
    assert 'adds 8 damage' in strike_receipts(reload(tmp_path, mid), before)[0].payload['log']


def test_orthodox_prior_turn_damage_does_not_qualify_after_new_minion_damage(tmp_path):
    combat, table, mid = fight(tmp_path, stage='Refined', expression='Orthodox Answering Strike')
    generate(combat, table, mid, tmp_path)
    # End Wren's turn, then complete another initiative cycle without damage.
    # The old attack is outside the printed window; only the new minion hurt Wren.
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    turn(table, mid, ALLY)
    use(combat, table, mid, 'Minion blow', OWNER)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    before = engine.state.event_sequence
    use(combat, table, mid, 'Return blow', FOE)
    receipt, = strike_receipts(reload(tmp_path, mid), before)
    assert 'adds 4 damage' in receipt.payload['log']
    assert 'Orthodox Answering Strike' not in receipt.payload['log']


def test_strike_bonus_respects_target_resistance(tmp_path):
    from combat.typed_reactions import damage_factor

    combat, table, mid = fight(tmp_path, stage='Refined', expression='Orthodox Answering Strike', resistance=True)
    generate(combat, table, mid, tmp_path)
    initial = reload(tmp_path, mid)
    assert damage_factor(initial, initial.state.actors[FOE], 'POISON', None, OWNER) == 0.5
    before = initial.state.event_sequence
    use(combat, table, mid, 'Return blow', FOE)
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.sequence > before and e.event_type == 'DAMAGE_COMMITTED'
              and e.actor_id == OWNER and FOE in e.target_ids]
    rolled = next(e for e in engine.events if e.sequence > before and e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER)
    assert len(damage) == 1
    assert damage[0].payload['rolled_or_pending_damage'] == rolled.payload['total'] + 8
    assert damage[0].payload['hp_damage'] == (rolled.payload['total'] + 8) // 2
    assert 'adds 8 damage' in strike_receipts(engine, before)[0].payload['log']


def test_integrity_strike_also_applies_to_compiled_attack_technique(tmp_path):
    combat, table, mid = fight(tmp_path, stage='Refined', expression='Orthodox Answering Strike',
                               talents=['STARS_TAL_COMET_SPEAR'])
    generate(combat, table, mid, tmp_path)
    before = reload(tmp_path, mid).state.event_sequence
    prompts = use(combat, table, mid, 'Comet Spear', FOE)
    engine = reload(tmp_path, mid)
    assert 'adds 8 damage' in strike_receipts(engine, before)[0].payload['log']
    assert engine.state.actors[OWNER].resources[POOL] == 0
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == STRIKE_ASK)
    assert prompt['action'] == 'Comet Spear'


def test_ask_me_strike_on_enemy_turn_names_the_nested_attack_and_target(tmp_path):
    combat, table, mid = fight(tmp_path, stage='Refined', expression='Orthodox Answering Strike')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert engine.state.current_actor_id == FOE
    move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y) == (3, 3))
    prompts = settle(table, mid, move.candidate_id, choices={
        'reaction:typed.opportunity_attack': 'first',
        'system:combat.opportunity_attack': 'first',
        STRIKE_ASK: 'first',
        GUARD_ASK: None,
    })
    engine = reload(tmp_path, mid)
    receipt, = strike_receipts(engine)
    assert 'adds 8 damage' in receipt.payload['log']
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == STRIKE_ASK)
    assert prompt['trigger_actor'] == engine.state.actors[OWNER].display_name
    assert prompt['affected'] == engine.state.actors[FOE].display_name
    assert prompt['action'] and 'move' not in prompt['action'].lower()


def test_stage_admission_and_exclusive_expression_persist(tmp_path):
    combat, table, mid = fight(tmp_path, expression='Jade-Gold Guard')
    engine = reload(tmp_path, mid)
    assert foundation.held(engine.state.actors[OWNER], 'expression').data['feature'] == JADE
    assert not [c for c in engine.legal_candidates() if 'foundation_expression.' in c.source_definition_id]
    for stage, owned in [('Latent', set()), ('Awakened', {STRIKE}), ('Refined', {STRIKE, JADE, ORTHODOX})]:
        doc = sheet([], cl=15)
        doc['foundation'] = {'foundation_id': 'heavenly_body_v0_2F', 'stage': stage}
        bundle = compile_character(doc, actor_id=OWNER)
        present = {r['feature_id'] for r in bundle['typed_passives']} & set(RECORDS)
        assert present == owned
