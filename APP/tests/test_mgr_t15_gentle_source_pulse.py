"""Source-backed builds -> native table commits -> cold reload and mechanical replay.

Public CI resource declarations (existing reviewed inputs, never copied fixtures):
authority/typed_mechanics/rules_text.json
combat/rules/feature_blocks.d/foundations3.json
combat/rules/feature_blocks.d/mgr_t14_spirit_vessel_value.json
combat/rules/concentration.json
"""
import copy
import hashlib
import json

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.fact_consent_admission import NativeFactSession, combat_records, declare, digest
from combat.ext.foundations3 import GENTLE_PULSE, PULSE_EXCLUDED, PULSE_FACT_KIND
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

FID = 'origin_spirit_body_v0_2B'
DEW = 'resource:foundation.spirit_source_dew'
SUPPORT = 'choice:needle.origin_spirit_support_value'
CLEANUP = 'choice:needle.gentle_pulse_cleanup'


def build(*, initial=0, score=8, stage='Awakened', foundation=True):
    # Native Foundation stage acquisition, not a manually granted Pulse action.
    doc = sheet(['LIFE_BASE_MEND_THE_PULSE'], cl=5, score=score)
    doc['identity']['proficiency_bonus'] = 2
    if foundation:
        doc['foundation'] = {'foundation_id': FID, 'stage': stage,
            'resource': {'name': 'Spirit-Source Dew', 'maximum': 1, 'current': initial}}
    return compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})


def setup(tmp_path, *, initial=0, score=8, stage='Awakened', foundation=True, far=False):
    foe = sheet(['TAL_YIN_MOON_ENDING_MERIDIAN_SEAL'], cl=5, dc=100)
    foe['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    return fixture(tmp_path, [], owner_bundle=build(initial=initial, score=score, stage=stage, foundation=foundation),
        foe_sheet=foe, foe_position={'x': 10 if far else 5, 'y': 6}, seed='MGR-T15-GENTLE-PULSE', named=True)


def use(combat, table, mid, name, target=None, **kwargs):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, **kwargs)


def native_dew(combat, table, mid, tmp_path):
    turn(table, mid, FOE)
    use(combat, table, mid, 'Withdrawing Thread', ALLY)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert before.state.actors[ALLY].current_hp < before.state.actors[ALLY].maximum_hp
    use(combat, table, mid, 'Mend the Pulse', ALLY, picks={SUPPORT: None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[DEW] == 1
    gained = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == DEW]
    assert len(gained) == 1 and gained[0].payload['gained'] == 1
    return engine


@pytest.mark.parametrize('caster_mode', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('accept', [False, True])
def test_native_dew_paid_pulse_asks_nonally_on_human_and_ai_turns(tmp_path, monkeypatch, caster_mode, accept):
    combat, table, mid = setup(tmp_path)
    native_dew(combat, table, mid, tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=caster_mode)
    name = 'Gentle Source Pulse (willing creature)'
    if caster_mode == 'LOCAL_AUTO':
        def choose(context):
            chosen = next(c for c in context.legal_candidates if c.display_name == name and c.target_ids == (FOE,))
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
        monkeypatch.setattr(combat.controller, 'choose_primary_action', choose)
    prompts = use(combat, table, mid, name, FOE, auto=caster_mode == 'LOCAL_AUTO',
        picks={'choice:willing.consent': 'accept' if accept else 'refuse', SUPPORT: None})
    consent = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:willing.consent']
    assert len(consent) == 1 and consent[0]['context']['reactor_id'] == FOE
    assert 'Gentle Source Pulse' in consent[0]['choice']['prompt']
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].temporary_hp == int(accept)  # owner's PB2 + key(-1)
    assert engine.state.actors[OWNER].resources[DEW] == 0
    assert not engine.state.actors[OWNER].bonus_action_available
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == DEW]
    assert len(spends) == 1 and spends[0].payload['amount'] == 1


@pytest.mark.parametrize('accept_support', [False, True])
def test_pulse_support_choice_is_independent_from_consent(tmp_path, accept_support):
    combat, table, mid = setup(tmp_path, initial=1)
    prompts = use(combat, table, mid, 'Gentle Source Pulse (willing creature)', FOE,
        picks={'choice:willing.consent': 'accept', SUPPORT: 'increase' if accept_support else None})
    assert any(p['context']['reaction_source_id'] == SUPPORT for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].temporary_hp == (3 if accept_support else 1)


@pytest.mark.parametrize('initial,stage,foundation,far', [
    (0, 'Awakened', True, False), (1, 'Unstable', True, False),
    (1, 'Awakened', False, False), (1, 'Awakened', True, True)])
def test_pulse_rejects_missing_dew_unowned_unavailable_stage_and_range(tmp_path, initial, stage, foundation, far):
    combat, table, mid = setup(tmp_path, initial=initial, stage=stage, foundation=foundation, far=far)
    engine = reload(tmp_path, mid)
    assert not any(c.display_name.startswith('Gentle Source Pulse') and FOE in c.target_ids for c in engine.legal_candidates())


def native_penalty(combat, table, mid, tmp_path):
    turn(table, mid, FOE)
    use(combat, table, mid, 'Mark the Waning', ALLY)
    use(combat, table, mid, 'Moon-Ending Meridian Seal', ALLY)
    engine = reload(tmp_path, mid)
    penalties = [m for m in engine.state.actors[ALLY].modifiers.values() if m.target_field == 'speed_ft' and m.value < 0]
    assert penalties, 'The native Yin source must actually produce a penalty.'
    return penalties[0]


def declaration(combat, mid, penalty, *, excluded=(), severity='minor', allow=1, readers=(ALLY,)):
    return {'source': GENTLE_PULSE, 'subject': ALLY, 'kind': PULSE_FACT_KIND,
        'scope': digest([penalty.source_definition_id, penalty.source_actor_id]),
        'expires_at': 3600, 'readers': list(readers), 'value': {
            'condition_instances': [], 'modifier_instances': [penalty.modifier_id],
            'source_definition_id': penalty.source_definition_id, 'source_actor_id': penalty.source_actor_id,
            'label': 'Minor spiritual drain slowing your movement', 'category': 'hostile_drain',
            'severity': severity, 'excluded': list(excluded), 'allow_pulse': allow}}


def classify(combat, mid, payload):
    engine = combat._load_session(mid).engine
    result = combat.world_fact(mid, engine.state.state_version, payload)
    assert result['status'] == 'COMMITTED'
    return result


@pytest.mark.parametrize('end_penalty', [False, True])
def test_native_gm_classification_exact_cleanup_survives_commit_reload_replay(tmp_path, end_penalty):
    combat, table, mid = setup(tmp_path, initial=1)
    penalty = native_penalty(combat, table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    before_conditions = set(engine.state.actors[ALLY].conditions)
    payload = declaration(combat, mid, penalty)
    classify(combat, mid, payload)
    engine = reload(tmp_path, mid)
    assert combat_records(engine, engine.state.actors[OWNER], source=GENTLE_PULSE) == []
    assert len(combat_records(engine, engine.state.actors[ALLY], source=GENTLE_PULSE)) == 1
    turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Gentle Source Pulse', ALLY, picks={
        'choice:willing.consent': 'accept', SUPPORT: None,
        CLEANUP: penalty.modifier_id if end_penalty else None})
    assert any(p['context']['reaction_source_id'] == CLEANUP for p in prompts)
    engine = reload(tmp_path, mid)
    assert (penalty.modifier_id in engine.state.actors[ALLY].modifiers) is not end_penalty
    assert before_conditions <= set(engine.state.actors[ALLY].conditions)
    assert engine.state.actors[ALLY].temporary_hp == 1


@pytest.mark.parametrize('excluded', sorted(PULSE_EXCLUDED))
def test_every_printed_major_exclusion_preserves_real_native_penalty(tmp_path, excluded):
    combat, table, mid = setup(tmp_path, initial=1)
    penalty = native_penalty(combat, table, mid, tmp_path)
    classify(combat, mid, declaration(combat, mid, penalty, excluded=[excluded]))
    turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Gentle Source Pulse', ALLY, picks={SUPPORT: None})
    assert not any(p['context']['reaction_source_id'] == CLEANUP for p in prompts)
    assert penalty.modifier_id in reload(tmp_path, mid).state.actors[ALLY].modifiers


def test_gm_input_cannot_invent_sources_or_consent_and_can_revoke_permission(tmp_path):
    combat, table, mid = setup(tmp_path, initial=1)
    penalty = native_penalty(combat, table, mid, tmp_path)
    payload = declaration(combat, mid, penalty)
    engine = reload(tmp_path, mid)
    with pytest.raises(ValueError, match='table-owner'):
        declare(NativeFactSession(engine), ALLY, payload)
    foreign = copy.deepcopy(payload)
    foreign['value']['source_actor_id'] = OWNER
    with pytest.raises(ValueError, match='same exact source'):
        classify(combat, mid, foreign)
    missing = copy.deepcopy(payload)
    missing['value']['modifier_instances'] = ['missing']
    with pytest.raises(ValueError, match='no longer present'):
        classify(combat, mid, missing)
    classify(combat, mid, payload)
    classify(combat, mid, declaration(combat, mid, penalty, allow=0))
    turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Gentle Source Pulse', ALLY, picks={SUPPORT: None})
    assert not any(p['context']['reaction_source_id'] == CLEANUP for p in prompts)
    assert penalty.modifier_id in reload(tmp_path, mid).state.actors[ALLY].modifiers


def test_source_hash_and_signed_amount_are_preserved():
    texts = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(texts[GENTLE_PULSE].encode()).hexdigest() == '554118f088b7d06da0d40a15e5aac7ab37cd8b215dc22f323206fc6950e4885a'
    from combat.effect_harm import rows
    pulse = next(a for a in build()['action_catalog'] if a['display_name'] == 'Gentle Source Pulse')
    grants = [e for e in rows(pulse['parameters']['typed']['effects']) if e['type'] == 'temp_hp']
    assert len(grants) == 1 and grants[0]['formula'] == 'text:your proficiency bonus + your path key ability modifier'
