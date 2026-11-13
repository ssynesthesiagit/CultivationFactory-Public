"""Played-table regressions for AUTO118 review; no browser or live data."""
import importlib
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat import typed_reactions
from combat.ext.end_effect import SUPPRESSED_FLAG
from tests.test_riders_c8_review import service_commit

H = importlib.import_module('tests.test_review_sw-imbuement')
DIAGNOSIS = H.F + 'EIGHT_GATE_DIAGNOSIS'
BODY = 'tianxia.path.body_refining.feature.body_tempering'
IRON_BONE = 'TAL_METAL_IRON_BONE_INTERNAL_METHOD'


def diagnosis_table(tmp_path, scenario):
    my_sheet = H._iron_sheet([DIAGNOSIS], cl=20, dc=40)
    my_sheet['ability_scores_and_statistics']['skills'] = [{'skill': 'Medicine', 'bonus': 100}]
    mine = compile_character(my_sheet, actor_id=H.ME)
    if scenario in ('next', 'next_overlap'):
        # Let the same service turn diagnose, then hit before the ward's next turn.
        strike = next(a for a in mine['action_catalog'] if a['display_name'] == 'Unarmed Strike (Iron Fist)')
        strike['economy'] = 'BONUS_ACTION'
    sheet = H._iron_sheet([H.SOVEREIGN, IRON_BONE] if scenario.startswith('next') else [H.SOVEREIGN], cl=20, dc=-40)
    if scenario == 'passive':
        sheet['path_and_subpath'] = {'path_feature_record_ids': [BODY]}
    theirs = compile_character(sheet, actor_id=H.ENEMY)
    if scenario.startswith('next'):
        theirs['actor_template']['maximum_hp'] = 500
    if scenario == 'next_overlap':
        # Same compiled next-instance ward plus ordinary Resistance to one type.
        bone = next(a for a in theirs['action_catalog'] if a['display_name'] == 'Iron-Bone Internal Method: Resistance to Next Instance')
        bone['parameters']['typed']['effects'].append({'type': 'resistance', 'damage_types': ['BLUDGEONING'],
                                                      'applies_to': 'self', 'duration': '1 minute'})
    ward = next(a for a in theirs['action_catalog'] if a['display_name'] == 'Sovereign Iron-Body Incarnation')
    typed = ward['parameters']['typed']
    if scenario in ('condition', 'grapple'):
        typed['effects'] = [{'type': 'condition', 'condition': 'save_against', 'applies_to': 'self',
                             'condition_data': {'rule': {'condition_immunities': ['prone' if scenario == 'condition' else 'grappled']},
                                                'label': 'Test ward'}}]
    elif scenario == 'piercing':
        typed['effects'] = [{'type': 'resistance', 'damage_types': ['PIERCING'], 'applies_to': 'self',
                             'duration': '1 minute'}]
    service = CombatService(H.ROOT, tmp_path)
    session = service.persistence.create_match(match_seed='AUTO118-DIAGNOSIS', maximum_rounds=20,
        typed_bundles=(mine, theirs), roster_setup={'primary_actor_ids': [H.ME, H.ENEMY],
        'team_by_actor': {H.ME: 'team:a', H.ENEMY: 'team:b'},
        'starting_positions': {H.ME: {'x': 3, 'y': 6}, H.ENEMY: {'x': 4, 'y': 6}}})
    metadata = {'participant_control_modes': {H.ME: 'MANUAL', H.ENEMY: 'MANUAL'}}
    if scenario != 'passive':
        H._advance_to(service, session, metadata, H.ENEMY)
        service_commit(service, session, metadata, 'Iron-Bone Internal Method: Resistance to Next Instance'
                       if scenario.startswith('next') else 'Sovereign Iron-Body Incarnation')
        service_commit(service, session, metadata, 'End turn')
    H._advance_to(service, session, metadata, H.ME)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()['status'] == 'PASS'
    return service, session, metadata


@pytest.mark.parametrize('overlap', [False, True])
def test_diagnosis_next_resistance_query_damage_commit_reload(tmp_path, monkeypatch, overlap):
    service, session, metadata = diagnosis_table(tmp_path, 'next_overlap' if overlap else 'next')

    def choose(context):
        if context.reaction_source_id.endswith('Diagnosis creature'):
            return [H.ENEMY]
        if context.reaction_source_id.endswith('Diagnosis check'):
            return ['Wisdom (Medicine)']
        if context.reaction_source_id.endswith('Diagnosis information'):
            return ['Resistances', 'Bloodied']
        return context.extension_choice.option_ids[:context.extension_choice.minimum_selections]

    def diagnose():
        events, _, _ = service_commit(service, session, metadata, 'Eight-Gate Diagnosis', H.ME, choose=choose)
        assert any(e.event_type == 'CHECK_ROLLED' and e.payload['success'] for e in events)
        return next(e.payload['text'] for e in events if e.event_type == 'PASSIVE_TRIGGERED'
                    and ('Resistance' in e.payload.get('text', '') or 'GM answers' in e.payload.get('text', '')))

    target = session.engine.state.actors[H.ENEMY]
    before = {mid: m.model_dump(mode='json') for mid, m in target.modifiers.items()}
    count = len(session.engine.events)
    profile = typed_reactions.resistance_profile(session.engine, target, 'BLUDGEONING', {})
    assert typed_reactions.resists_profile(session.engine, target, 'BLUDGEONING', {})
    assert len(session.engine.events) == count
    answer = diagnose()
    if overlap:
        assert 'Resistance to Bludgeoning damage.' in answer
        assert 'Resistance to Piercing and Slashing damage only for the next matching damage instance' in answer
    else:
        assert 'Resistance to Bludgeoning, Piercing and Slashing damage only for the next matching damage instance' in answer
    assert 'Each benefit is used up for every damage type it covers' in answer
    assert profile == {'resist': True, 'ordinary': overlap, 'next_only': not overlap}
    session = service.persistence.load_match(session.match_id)
    assert session.verify()['status'] == 'PASS'
    target = session.engine.state.actors[H.ENEMY]
    assert before == {mid: m.model_dump(mode='json') for mid, m in target.modifiers.items()}
    hp = target.current_hp
    H._scripted_dice(monkeypatch, session, [20])
    events, _, _ = service_commit(service, session, metadata, 'Unarmed Strike (Iron Fist)', H.ENEMY)
    assert target.current_hp < hp
    assert any(e.event_type == 'MODIFIER_REMOVED' and e.payload.get('reason') == 'CONSUMED' for e in events)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()['status'] == 'PASS'
    assert not any(m.target_field == 'damage_resistance_next' for m in session.engine.state.actors[H.ENEMY].modifiers.values())
    service_commit(service, session, metadata, 'End turn')
    H._advance_to(service, session, metadata, H.ME)
    answer = diagnose()
    assert 'next matching' not in answer
    if overlap:
        assert 'Resistance to Bludgeoning damage.' in answer
    else:
        assert 'has Resistance' not in answer and 'GM answers' in answer
    assert service.persistence.load_match(session.match_id).verify()['status'] == 'PASS'


@pytest.mark.parametrize('scenario', ['passive', 'condition', 'piercing', 'grapple', 'enhancement'])
def test_diagnosis_effective_defenses_and_enhancement_commit_reload(tmp_path, scenario, monkeypatch):
    service, session, metadata = diagnosis_table(tmp_path, scenario)
    facts = ('Resistances', 'Bloodied') if scenario in ('passive', 'piercing') else (
        'Immunities', 'Bloodied') if scenario in ('condition', 'grapple') else ('Bodily or martial enhancement', 'Bloodied')

    def choose(context):
        choice = context.reaction_source_id
        if choice.endswith('Diagnosis creature'):
            return [H.ENEMY]
        if choice.endswith('Diagnosis check'):
            return ['Wisdom (Medicine)']
        if choice.endswith('Diagnosis information'):
            return facts
        return context.extension_choice.option_ids[:context.extension_choice.minimum_selections]

    before = session.engine.state.model_dump(mode='json')
    events, prompts, _ = service_commit(service, session, metadata, 'Eight-Gate Diagnosis', H.ME, choose=choose)
    assert any(e.event_type == 'CHECK_ROLLED' and e.payload['success'] for e in events)
    for name in ('Diagnosis creature', 'Diagnosis information'):
        assert any(p.reaction_source_id.endswith(name) for p in prompts)
    texts = [e.payload.get('text', '') for e in events if e.event_type == 'PASSIVE_TRIGGERED'
             and 'Eight-Gate Diagnosis:' in e.payload.get('text', '')]
    assert len(texts) == 2, texts
    answer = next(s for s in texts if 'Bloodied' not in s)
    if scenario == 'passive':
        assert any(r.get('mundane_only') for r in session.engine.typed_passive_rows[H.ENEMY])
        assert 'Resistance to nonmagical Bludgeoning, Piercing and Slashing damage' in answer
        assert 'Force' not in answer
    elif scenario == 'piercing':
        assert 'Resistance to Piercing damage' in answer
        assert 'Bludgeoning' not in answer and 'Slashing' not in answer
    elif scenario == 'condition':
        assert 'immune to Prone' in answer
    elif scenario == 'grapple':
        assert 'immune to Grappled' in answer and 'immune to forced movement' not in answer
    else:
        assert 'is maintaining:' in answer and 'Sovereign Iron-Body Incarnation' in answer
    from combat.gate3_reducer import canonical_state_sha256
    state_hash = canonical_state_sha256(session.engine.state)
    session = service.persistence.load_match(session.match_id)
    assert session.verify()['status'] == 'PASS'
    assert canonical_state_sha256(session.engine.state) == state_hash
    assert [e.payload.get('text') for e in session.engine.events if e.event_type == 'PASSIVE_TRIGGERED'
            and 'Eight-Gate Diagnosis:' in e.payload.get('text', '')] == texts
    assert before['actors'][H.ENEMY] == session.engine.state.model_dump(mode='json')['actors'][H.ENEMY]
    if scenario == 'grapple':
        service_commit(service, session, metadata, 'End turn')
        H._advance_to(service, session, metadata, H.ME)
        old = session.engine.state.actors[H.ENEMY].position.model_copy()
        from combat.typed_executor import condition_immune
        assert condition_immune(session.engine, session.engine.state.actors[H.ENEMY], 'grappled')
        H._scripted_dice(monkeypatch, session, [1])  # Fail the push's Strength save, independently of immunity.
        service_commit(service, session, metadata, 'Shove: Push 5 ft', H.ENEMY)
        assert session.engine.state.actors[H.ENEMY].position != old
        assert service.persistence.load_match(session.match_id).verify()['status'] == 'PASS'


@pytest.mark.parametrize('category', ['Domain', 'Secret Inheritance', 'artifact', 'permanent transformation', 'unclassified ordinary magic'])
def test_internal_hammer_protects_excluded_and_unclassified_sources_at_table(tmp_path, monkeypatch, category):
    service, session, metadata = H._hammer_table(tmp_path, 'MANUAL', source_category=category)
    H._advance_to(service, session, metadata, H.ENEMY)
    service_commit(service, session, metadata, 'Sovereign Iron-Body Incarnation')
    service_commit(service, session, metadata, 'End turn')
    H._prepare_hammer(service, session, metadata)
    H._scripted_dice(monkeypatch, session, [20, 1])
    events, prompts, _ = service_commit(service, session, metadata, 'Unarmed Strike (Iron Fist) + Internal Hammer', H.ENEMY)
    assert any(e.event_type == 'SAVE_ROLLED' and not e.payload['success'] for e in events)
    assert not prompts
    foe = session.engine.state.actors[H.ENEMY]
    assert not foe.turn_flags.get(SUPPRESSED_FLAG)
    assert all('suppressed' not in m.target_field for m in foe.modifiers.values())
    assert typed_reactions.resists(session.engine, foe, 'BLUDGEONING', None)
    assert service.persistence.load_match(session.match_id).verify()['status'] == 'PASS'
