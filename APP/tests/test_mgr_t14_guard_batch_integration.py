"""Guard's reviewed signed sum must survive regeneration and native integration.

The integration batch lost the reviewed effects from its generated authority.
Keep both the source-to-artifact contract and each affected service path covered.
"""
import json

import pytest

from combat.factory_compiler import TYPED_AUTHORITY
from tests.h1_support import ROOT
from tests.test_mgr_t14_guard_parent import setup, hit
from tests.test_mgr_t14_ling_guard_sum import (
    GUARD, REACTION, DEW, HIT, add_action, owner_bundle, damage_event, resolved, VESSEL_CHOICE,
)
from tests.worker2_support import ALLY, OWNER, FOE, fixture, candidate, settle, turn, reload


def test_generated_guard_keeps_the_reviewed_signed_sum():
    reviewed = json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/foundations3.json')
                          .read_text())['mechanics'][GUARD]
    generated = json.loads(TYPED_AUTHORITY.read_text())['mechanics'][GUARD]
    assert generated['typing_status'] == 'reviewed_final'
    assert generated['effects'] == reviewed['effects']
    assert [effect['formula'] for effect in generated['effects']] == ['pb+key']
    assert generated['effects'][0]['hostile_source_only'] is True


CASES = ('paid_concentration', 'automatic_owner', 'automatic_enemy',
         'prior_support', 'negative_key', 'below_zero_sum', 'cold_reload')


@pytest.mark.parametrize('scenario', CASES)
def test_signed_guard_survives_batch_integration(tmp_path, monkeypatch, scenario):
    """Each of the seven reviewed failures gets a real commit/reload receipt."""
    reduction = 0 if scenario == 'below_zero_sum' else 1
    hit_size = 8 if scenario in CASES[:3] else HIT
    if scenario in CASES[:3]:
        combat, table, mid = setup(tmp_path)
    else:
        def prepare(bundles):
            add_action(bundles[2], 'Hostile strike', [
                {'type': 'damage', 'flat': HIT, 'damage_types': ['force'], 'applies_to': 'target'}])
            if scenario == 'prior_support':
                add_action(bundles[0], 'Earlier support', [
                    {'type': 'temp_hp', 'flat': 1, 'applies_to': 'target'}], target_kind='ALLY_OR_SELF')

        combat, table, mid = fixture(tmp_path, [], seed='GUARD-BATCH-' + scenario,
            owner_bundle=owner_bundle(2, 4 if scenario == 'below_zero_sum' else 8,
                                      initial=0 if scenario == 'prior_support' else 1),
            bundle_transform=prepare)
        if scenario == 'prior_support':
            settle(table, mid, candidate(combat, mid, 'Earlier support', target=ALLY).candidate_id)
            assert reload(tmp_path, mid).state.actors[OWNER].resources[DEW] == 1

    if scenario == 'automatic_owner':
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
        # The full Foundation owns Vessel: automatic consent adds PB 2 to
        # Guard's signed base 1. Manual base-sum scenarios reserve that bonus.
        reduction += 2
    if scenario == 'automatic_enemy':
        from combat.gate4_adapters import ManualControllerAdapter
        turn(table, mid, FOE)
        row = candidate(combat, mid, 'Hostile strike', target=ALLY)
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
        monkeypatch.setattr(combat.controller, 'choose_primary_action',
            lambda context: ManualControllerAdapter(lambda _: (next(
                c.candidate_id for c in context.legal_candidates
                if c.source_definition_id == row.source_definition_id and c.target_ids == (ALLY,)), ()))
            .choose_primary_action(context))
        prompts = settle(table, mid, row.candidate_id, picks={REACTION: 'first', VESSEL_CHOICE: None}, auto=True)
        assert any(p['context']['reactor_id'] == OWNER for p in prompts)
        engine = reload(tmp_path, mid)
    else:
        engine, prompts = hit(tmp_path, combat, table, mid)
        if scenario == 'automatic_owner':
            assert not [p for p in prompts if p['context']['reactor_id'] == OWNER]

    if scenario == 'cold_reload':
        engine = reload(tmp_path, mid)
    assert resolved(engine).payload['reduction'] == reduction
    if scenario == 'automatic_owner':
        value = next(e.payload for e in engine.events
                     if e.payload.get('receipt_kind') == 'origin_spirit_support_value')
        assert value['method'] == GUARD and value['original'] == 1 and value['selected'] == 3
    # Earlier support's one temporary HP absorbs one point before ordinary HP.
    hp_damage = hit_size - reduction - int(scenario == 'prior_support')
    assert damage_event(engine, ALLY).payload['hp_damage'] == hp_damage
    assert engine.state.actors[ALLY].current_hp == 60 - hp_damage
    if scenario in CASES[:3]:
        rolls = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id == 'system:combat.concentration' and e.actor_id == ALLY]
        assert len(rolls) == 1 and rolls[0].payload['mode'] == 'ADVANTAGE'
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.source_definition_id == GUARD]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    assert spent[0].sequence < resolved(engine).sequence
