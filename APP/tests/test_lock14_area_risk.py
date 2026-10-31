"""Non-damage extension outcomes keep per-recipient Table warnings and AI costs."""
import pytest
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.test_lock_choices import install
from tests.test_lock11_friendly_fire import context
from tests.test_lock2_persistence import act

SOURCE = 'test:premise_field'


@pytest.mark.parametrize('scope', ['self', 'creatures_in_area'])
@pytest.mark.parametrize('kind', ['advantage', 'disadvantage'])
def test_incoming_roll_modes_match_table_warning_controller_and_committed_effect(monkeypatch, tmp_path, scope, kind):
    def compile_action(info):
        if info['actor_id'] != H.LEFT:
            return []
        return [ActionDefinition(source_definition_id=SOURCE, display_name='Practice protective field', owner_id=H.LEFT,
            economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF', radius_ft=15,
            parameters={'typed': {'numbers': info['numbers'],
                # This synthetic fixture explicitly includes its user; ordinary
                # harmful areas now exclude them (owner 2026-10-06).
                'area': {'shape': 'sphere', 'size_ft': 15, 'centered_on_self': True, 'include_self': True},
                'effects': [{'type': kind, 'applies_to': scope, 'on': 'attack rolls against you',
                             'expires_on': 'START_OF_SOURCE_NEXT_TURN'}]}})]
    install(monkeypatch, 'compile_actions', compile_action)
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=[])
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    c = next(c for c in engine.legal_candidates() if c.source_definition_id == SOURCE)
    assert engine.state.model_dump(mode='json') == before
    harmful = kind == 'advantage'
    assert bool(c.metadata.get('self_harm')) is (harmful and scope == 'self')
    assert bool(c.metadata.get('unavoidable_allies_in_area')) is (harmful and scope != 'self')
    option = next(o for g in table.state(mid)['menu']['actions'] for o in g['options'] if o['candidate_id'] == c.candidate_id)
    assert ('Hits allies too:' in option['label']) is (harmful and scope != 'self')
    choice = LocalDeterministicController().choose_primary_action(context(engine, [c]))
    scores = {r.component: r.value for r in choice.record.scored_alternatives[0].components}
    assert any(v < 0 for k,v in scores.items() if k in ('friendly_fire', 'self_harm')) is harmful
    assert act(table, mid, SOURCE)['status'] == 'COMMITTED'
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    subjects = [H.LEFT] if scope == 'self' else [H.LEFT, H.ALLY, H.RIGHT]
    for who in subjects:
        assert any(m.target_field == 'incoming_attack_mode' and m.value == kind.upper()
                   for m in loaded.engine.state.actors[who].modifiers.values())
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('scope', ['creatures_in_area', 'enemies_in_area'])
@pytest.mark.parametrize('kind', ['figment_premise', 'disadvantage'])
def test_non_damage_save_warns_scores_and_commits_actual_recipients(monkeypatch, tmp_path, scope, kind):
    def compile_action(info):
        if info['actor_id'] != H.LEFT:
            return []
        return [ActionDefinition(source_definition_id=SOURCE, display_name='Practice illusion field', owner_id=H.LEFT,
            economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF', radius_ft=15,
            parameters={'typed': {'numbers': {**info['numbers'], 'save_dc': 99},
                'area': {'shape': 'sphere', 'size_ft': 15, 'centered_on_self': True, 'include_self': True},
                'effects': [{'type': 'save', 'ability': 'WIS', 'applies_to': scope,
                    'on_fail': [{'type': kind, 'applies_to': 'target', 'on': 'attack rolls',
                                 'expires_on': 'START_OF_SOURCE_NEXT_TURN'}], 'on_success': []}]}})]
    install(monkeypatch, 'compile_actions', compile_action)
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=[])
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    c = next(c for c in engine.legal_candidates() if c.source_definition_id == SOURCE)
    assert engine.state.model_dump(mode='json') == before
    count = 2 if scope == 'creatures_in_area' else 0
    assert c.metadata.get('unavoidable_allies_in_area', 0) == count
    assert c.metadata.get('ally_expected_damage', 0) == 0
    state = table.state(mid)
    option = next(o for g in state['menu']['actions'] for o in g['options'] if o['candidate_id'] == c.candidate_id)
    assert ('Hits allies too:' in option['label']) is bool(count)
    choice = LocalDeterministicController().choose_primary_action(context(engine, [c]))
    scores = {r.component: r.value for r in choice.record.scored_alternatives[0].components}
    assert (scores.get('friendly_fire', 0) < 0) is bool(count)
    assert act(table, mid, SOURCE)['status'] == 'COMMITTED'
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    applied = {who for e in loaded.engine.events if e.sequence > before['event_sequence']
               and e.source_definition_id == SOURCE and e.event_type in ('CONDITION_APPLIED', 'MODIFIER_APPLIED')
               for who in e.target_ids}
    assert applied == ({H.LEFT, H.ALLY, H.RIGHT} if count else {H.RIGHT})
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_unknown_save_leaf_is_conservative_and_extension_can_classify_its_own_effect(monkeypatch):
    from combat.area_safety import harmful_effect
    row = {'type': 'test:extension'}
    assert harmful_effect(None, row, saving_throw=True)
    assert not harmful_effect(None, row)
    assert not harmful_effect(None, {'type': 'healing'}, saving_throw=True)
    install(monkeypatch, 'area_effect_risk', lambda ctx, effect: 'harmless' if effect is row else None)
    assert not harmful_effect(None, row, saving_throw=True)
    assert harmful_effect(None, {'type': 'disadvantage'}, saving_throw=True)
