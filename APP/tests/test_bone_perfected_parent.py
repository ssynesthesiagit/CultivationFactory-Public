"""Perfected Sword Bones through real compiled ownership and table settlement."""
import json
from hashlib import sha256

import pytest

from combat.ext.foundation_conversion_bonus import CLOCK, conversion_bonus, conversion_consent_note
from tests.test_a2_foundations4 import setup, S, B, POOLS, attack_owner
from tests.worker2_support import OWNER, FOE, candidate, settle, reload, turn

PREFIX = 'foundation.sword_bones_v0_2B.'
PERFECTED = PREFIX + 'perfected_bone_deep_severance'


def receipts(engine):
    return [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
            and e.payload.get('receipt_kind') == 'foundation_conversion_bonus']


def cut(combat, table, mid, answer='USE'):
    return settle(table, mid, candidate(combat, mid, 'Owner hit', target=FOE).candidate_id,
                  choices={'reaction:typed.' + PREFIX + 'sword_bone_cut': answer})


@pytest.mark.parametrize('conversion', ['cut', 'sheath', 'severing_clarity'])
def test_one_native_conversion_increased_and_cold_replayed(tmp_path, conversion):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True, prepare=True)
    if conversion == 'cut':
        prompts = cut(combat, table, mid)
    elif conversion == 'sheath':
        prompts = attack_owner(combat, table, mid,
            choices={'reaction:typed.' + PREFIX + 'sheath_bone_guard': 'USE'})
    else:
        turn(table, mid, FOE)
        prompts = settle(table, mid, candidate(combat, mid, 'Prone pressure', target=OWNER).candidate_id,
            choices={'reaction:typed.' + PREFIX + 'severing_clarity': 'USE'})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert prompts
    consent = ' '.join(p['table_note'] for p in prompts)
    assert 'Bone-Deep Severance' in consent
    assert 'shared once-per-round benefit' in consent
    assert all(name in consent for name in ('Sword-Bone Cut', 'Sheath-Bone Guard', 'Severing Clarity'))
    assert 'until the next round' in consent
    assert actor.resources[POOLS[S]] == 0
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.payload.get('resource_id') == POOLS[S]]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    used = receipts(engine)
    assert len(used) == 1
    assert used[0].payload['conversion'] == conversion
    assert used[0].payload['bonus'] == 4
    clock = actor.turn_flags[CLOCK]
    assert clock[PERFECTED] == engine.state.round_number
    assert clock['receipt']['payment_sequence'] == spent[0].sequence
    assert all(type(v) in (int, str) for v in clock['receipt'].values())
    assert conversion_bonus(engine, actor, conversion) == 0
    if conversion == 'cut':
        damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
        assert len(damage) == 2 and damage[1].payload['hp_damage'] == 8
        assert actor.reaction_available
        assert any('8 damage' in p['summary'] for p in prompts)
    elif conversion == 'sheath':
        assert not actor.reaction_available
        guard = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                 and e.source_definition_id == PREFIX + 'sheath_bone_guard']
        # Incoming 1d6+6 damage is capped at the actual rolled amount.
        damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == FOE)
        assert damage.payload['hp_damage'] <= 2
        assert any('reduce damage by' in e.payload.get('log', '') for e in guard)
    else:
        saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
        assert saves[-1].payload['modifier'] == 10
        rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN']
        assert len(rewrites) == 1
        assert actor.reaction_available


@pytest.mark.parametrize('stage,status,foundation', [
    ('Awakened', None, S), ('Refined', None, S), ('Perfected', 'Suppressed', S),
    ('Perfected', None, B)])
def test_stage_explicit_suppression_and_peer_are_inert(tmp_path, stage, status, foundation):
    combat, table, mid = setup(tmp_path, foundation, stage=stage, status=status, held=1, ask=True)
    feature = PREFIX + 'sword_bone_cut' if foundation == S else 'foundation.' + B + '.blackblood_return'
    settle(table, mid, candidate(combat, mid, 'Owner hit', target=FOE).candidate_id,
           choices={'reaction:typed.' + feature: 'USE'})
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert damage[-1].payload['hp_damage'] == 4
    assert not receipts(engine)
    if status:
        bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == OWNER)
        assert bundle['foundation_source_status']['status'] == status
        assert bundle['foundation_source_status']['provenance'] == 'owner_sheet.foundation.status'


@pytest.mark.parametrize('answer,held', [(None, 1), ('USE', 0)])
def test_preview_decline_and_no_prior_edge_do_not_claim_round(tmp_path, answer, held):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=held, ask=True)
    engine = combat._load_session(mid).engine
    before = json.dumps(engine.state.model_dump(mode='json'), sort_keys=True)
    for _ in range(3):
        table.state(mid)
        assert conversion_bonus(engine, engine.state.actors[OWNER], 'cut') == 4
    assert json.dumps(engine.state.model_dump(mode='json'), sort_keys=True) == before
    cut(combat, table, mid, answer)
    engine = reload(tmp_path, mid)
    assert not receipts(engine)
    assert CLOCK not in engine.state.actors[OWNER].turn_flags
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.payload.get('resource_id') == POOLS[S]]


def test_full_decoded_source_matches_inventory():
    from pathlib import Path
    texts = json.loads((Path(__file__).parents[1] / 'authority/typed_mechanics/rules_text.json').read_text())
    assert sha256(texts[PERFECTED].encode()).hexdigest() == '1f0632cc4907b5d177a5673f1270b41e86e24217c19dc6c8d789f528ffab037d'


def test_native_suppression_and_recovery_settings_persist_without_resetting_round(tmp_path):
    from combat.ext.foundation_conversion_bonus import SOURCE_STATUS
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True)
    settle(table, mid, candidate(combat, mid, 'Foundation: record suppression').candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert conversion_bonus(engine, owner, 'cut') == 0
    status = next(c for c in owner.conditions.values() if c.condition_id == SOURCE_STATUS)
    assert status.data['status'] == 'suppressed'
    assert status.data['provenance'] == 'accepted table setting: Game Master ruling'
    assert owner.resources[POOLS[S]] == 1 and owner.reaction_available
    settle(table, mid, candidate(combat, mid, 'Foundation: record recovery').candidate_id)
    assert conversion_bonus(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[OWNER], 'cut') == 4
    cut(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert len(receipts(engine)) == 1
    settle(table, mid, candidate(combat, mid, 'Foundation: record suppression').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Foundation: record recovery').candidate_id)
    engine = reload(tmp_path, mid)
    assert conversion_bonus(engine, engine.state.actors[OWNER], 'cut') == 0
    assert len(receipts(engine)) == 1


def test_suppressed_native_spend_does_not_consume_perfected_allowance(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True)
    settle(table, mid, candidate(combat, mid, 'Foundation: record suppression').candidate_id)
    cut(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not receipts(engine)
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 0
    settle(table, mid, candidate(combat, mid, 'Foundation: record recovery').candidate_id)
    engine = reload(tmp_path, mid)
    assert conversion_bonus(engine, engine.state.actors[OWNER], 'cut') == 4


def test_one_round_receipt_shared_by_cut_and_guard_then_native_round_resets(tmp_path):
    from tests.test_a2_foundations4 import move, own_attack
    from tests.worker2_support import ALLY
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True, prepare=True)
    move(combat, table, mid, 5)
    settle(table, mid, own_attack(combat, mid).candidate_id,
           choices={'reaction:typed.' + PREFIX + 'sword_bone_cut': 'USE'})
    engine = reload(tmp_path, mid)
    first_round = engine.state.round_number
    assert len(receipts(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 1
    # This seeded foe acts before Owner: advancing to it crosses the round.
    # Guard can reduce friendly damage too; Ally acts later in the same round.
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Friendly damage', target=OWNER).candidate_id,
           choices={'reaction:typed.' + PREFIX + 'sheath_bone_guard': 'USE'})
    assert prompts and all('shared once-per-round benefit' not in p['table_note'] for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == first_round
    assert len(receipts(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 0
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ALLY)
    assert damage.payload['hp_damage'] == 6
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.round_number > first_round
    assert conversion_bonus(engine, engine.state.actors[OWNER], 'cut') == 4


def test_perfected_clarity_increases_same_native_escape_check_once(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Pin owner', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Escape grapple').candidate_id,
        choices={'reaction:typed.' + PREFIX + 'severing_clarity': 'USE'})
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER]
    assert checks[-1].payload['actor']['modifier'] == 10
    assert len(checks[-1].payload['actor']['dice']) == 1
    assert len(receipts(engine)) == 1
    assert '8' in prompts[-1]['table_note'] and 'Escape' in prompts[-1]['summary']


@pytest.mark.parametrize('conversion,leaf', [
    ('cut', 'refined_tempered_severance'), ('sheath', 'refined_bone_sheath_guard'),
    ('severing_clarity', 'refined_marrow_decision')])
@pytest.mark.parametrize('stage', ['Perfected', 'Refined'])
def test_public_refined_packet_transport_stacks_selected_value_only(tmp_path, monkeypatch, conversion, leaf, stage):
    """Interface proof for peer packets, not a certificate of absent Refined rows.

    The real owner text/stage supplies ownership. A data-only fixture publishes
    the peer's printed +PB row through the documented feature-block schema.
    The production compiler/settings/payment/table/replay paths do the rest.
    """
    import copy
    from combat import typed_reactions
    authored = copy.deepcopy(typed_reactions.rules())
    for kind, refined in [('cut', 'refined_tempered_severance'), ('sheath', 'refined_bone_sheath_guard'),
                          ('severing_clarity', 'refined_marrow_decision')]:
        authored['features'][PREFIX + refined] = {'block': 'foundation_conversion_bonus',
            'resource': 'foundation', 'conversions': [kind], 'extra_pb': 1, 'selected': True}
    monkeypatch.setattr(typed_reactions, 'rules', lambda: authored)
    combat, table, mid = setup(tmp_path, stage=stage, held=1, ask=True, prepare=True)
    engine = reload(tmp_path, mid)
    settings = [c for c in engine.legal_candidates() if 'conversion_expression' in c.source_definition_id]
    assert len(settings) == 3
    selected = next(c for c in settings if c.source_definition_id.endswith(leaf))
    settle(table, mid, selected.candidate_id)
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.legal_candidates() if 'conversion_expression' in c.source_definition_id]
    for kind in ('cut', 'sheath', 'severing_clarity'):
        assert conversion_bonus(engine, engine.state.actors[OWNER], kind) == ((4 if stage == 'Perfected' else 0) + (4 if kind == conversion else 0))
    if conversion == 'cut':
        prompts = cut(combat, table, mid)
    elif conversion == 'sheath':
        from tests.worker2_support import ALLY
        turn(table, mid, ALLY)
        prompts = settle(table, mid, candidate(combat, mid, 'Friendly large damage', target=OWNER).candidate_id,
            choices={'reaction:typed.' + PREFIX + 'sheath_bone_guard': 'USE'})
    else:
        turn(table, mid, FOE)
        prompts = settle(table, mid, candidate(combat, mid, 'Prone pressure', target=OWNER).candidate_id,
            choices={'reaction:typed.' + PREFIX + 'severing_clarity': 'USE'})
    assert prompts
    consent = ' '.join(p['table_note'] for p in prompts)
    assert ('shared once-per-round benefit' in consent) == (stage == 'Perfected')
    assert ('Bone-Deep Severance' in consent) == (stage == 'Perfected')
    engine = reload(tmp_path, mid)
    assert len(receipts(engine)) == 1 and receipts(engine)[0].payload['bonus'] == (8 if stage == 'Perfected' else 4)
    assert PREFIX + leaf in receipts(engine)[0].payload['contributors']
    assert conversion_bonus(engine, engine.state.actors[OWNER], conversion) == 4
    # The selected Refined contribution remains after Perfected is spent,
    # without quoting a second shared-round expenditure on any conversion.
    assert all(conversion_consent_note(engine, engine.state.actors[OWNER], kind) == ''
               for kind in ('cut', 'sheath', 'severing_clarity'))
    assert all(conversion_bonus(engine, engine.state.actors[OWNER], k) == 0
               for k in ('cut', 'sheath', 'severing_clarity') if k != conversion)
    if conversion == 'cut':
        damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
        assert len(damage) == 2 and damage[-1].payload['hp_damage'] == (12 if stage == 'Perfected' else 8)
    elif conversion == 'sheath':
        damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ALLY)
        assert damage.payload['hp_damage'] == (6 if stage == 'Perfected' else 10)
    else:
        save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER)
        assert save.payload['modifier'] == (14 if stage == 'Perfected' else 10)


def test_external_selection_veto_keeps_only_perfected_bonus_on_native_cut(tmp_path, monkeypatch):
    import copy
    from combat import ext, typed_reactions
    leaf = PREFIX + 'refined_tempered_severance'
    authored = copy.deepcopy(typed_reactions.rules())
    authored['features'][leaf] = {'block': 'foundation_conversion_bonus', 'resource': 'foundation',
                                 'conversions': ['cut'], 'extra_pb': 1, 'selected': True}
    monkeypatch.setattr(typed_reactions, 'rules', lambda: authored)
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True)
    engine = reload(tmp_path, mid)
    selection = next(c for c in engine.legal_candidates() if 'conversion_expression' in c.source_definition_id)
    settle(table, mid, selection.candidate_id)
    def veto(engine, actor, feature_id):
        return False if feature_id == leaf else None
    ext.hook('foundation_expression_selected')(veto)
    try:
        cut(combat, table, mid)
        engine = reload(tmp_path, mid)
        used = receipts(engine)
        assert len(used) == 1 and used[0].payload['bonus'] == 4
        assert used[0].payload['contributors'] == PERFECTED
        damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
        assert damage[-1].payload['hp_damage'] == 8
    finally:
        ext._HOOKS['foundation_expression_selected'].remove(veto)
