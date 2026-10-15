"""Mixed Forge benefits and continuous zones share recipient policy after reload."""
import json

import pytest

from combat import area_recipient_rules, zones
from combat.area_recipients import scoped_area
from combat.effect_harm import classify_effect
from combat.forged import mechanic_for
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT

COURT = 'tianxia.talent.music.court_of_resonant_measure'


@pytest.mark.parametrize('row,expected', [
    ({'rule': {'no_reactions': True, 'concentration_mode': 'DISADVANTAGE'}}, True),
    ({'rule': {'save_against': {'mode': 'DISADVANTAGE'}}}, True),
    ({'rule': {'attacked_with_if_sight': 'DISADVANTAGE'}}, False),
    ({'rule': {'attacked_with_if_sight': 'ADVANTAGE'}}, True),
    ({'rule': {'music_ac': 1, 'save_against': {'mode': 'ADVANTAGE'}}}, None),
    ({'rule': {'unclassified_rule': True}}, None),
])
def test_continuous_rule_harm_uses_semantics_not_saved_who(row, expected):
    for who in ('hostile', 'ally', 'any'):
        assert classify_effect({**row, 'who': who}) is expected


def finish(table, mid, result, option):
    answers = []
    for _ in range(16):
        if result['status'] == 'COMMITTED':
            return
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
        state = table.state(mid)
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'], answers)
    raise AssertionError(result)


@pytest.mark.parametrize('scope', ['target', 'allies_in_area', 'creatures_in_area'])
def test_forge_separates_harmful_save_and_explicit_benefit_scope(scope):
    mechanics = {'harm': {'effects': [{'type': 'damage', 'flat': 4}]},
                 'help': {'effects': [{'type': 'temp_hp', 'flat': 7, 'applies_to': scope}]}}
    forged = mechanic_for({'name': 'Mixed Burst', 'base_form': {'form_id': 'burst'},
        'primary_sphere_effect': {'talent_id': 'harm'},
        'secondary_sphere_effects': [{'talent_id': 'help'}]}, mechanics)
    harm, benefit = forged['effects']
    assert harm['applies_to'] == 'enemies_in_area'
    assert all(classify_effect(row) is True for row in harm['on_fail'])
    assert benefit['applies_to'] == ('allies_in_area' if scope == 'target' else scope)
    area = scoped_area(forged['area'], forged['effects'])
    assert area['recipients'] == 'all' and not area['exclude_self']
    assert area['harmful_recipients'] == 'hostile'


def test_mixed_judgment_coagulate_burst_commits_benefits_without_enemy_save_dependency(tmp_path, monkeypatch):
    from tests import test_tabletop_hunt6 as fixtures
    primary, secondary = 'RADIANCE_TAL_JUDGMENT_RAY', 'BLOOD_BASE_COAGULATE'
    original = fixtures.sheet
    def character(*args, **kwargs):
        document = original(*args, **kwargs)
        document['forged_techniques'] = [{
            'technique_id': 'forged:test.judgment-coagulate', 'name': 'Judgment Coagulate Burst',
            'primary_sphere_effect': {'talent_id': primary},
            'secondary_sphere_effects': [{'talent_id': secondary}],
            'base_form': {'form_id': 'burst'}, 'augments': [], 'drawbacks': [],
            'cp_cost': {'final': 1}, 'action_type': 'action'}]
        return document
    monkeypatch.setattr(fixtures, 'sheet', character)
    combat, table, mid = table_fight(tmp_path, [primary, secondary], cl=10, ally_talents=[])
    result, option = _commit_area_action(table, mid, 'Judgment Coagulate Burst', {'x': 3, 'y': 4})
    finish(table, mid, result, option)
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    sources = {key for key, action in loaded.engine.action_catalog.items()
               if action.display_name == 'Judgment Coagulate Burst'}
    events = [e for e in loaded.engine.events if e.source_definition_id in sources]
    assert {e.actor_id for e in events if e.event_type == 'SAVE_ROLLED'} == {RIGHT}
    assert {t for e in events if e.event_type == 'DAMAGE_COMMITTED' for t in e.target_ids} == {RIGHT}
    for who in (LEFT, ALLY):
        actor = loaded.engine.state.actors[who]
        assert actor.current_hp == 60
        assert actor.temporary_hp > 0
        assert not any('dawnmark' in c.condition_id for c in actor.conditions.values())
    enemy = loaded.engine.state.actors[RIGHT]
    assert enemy.current_hp < 60 and enemy.temporary_hp == 0
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('mode', ['Dissonant Court', 'Harmonious Court'])
def test_court_continuous_and_trigger_rosters_follow_override_changes_after_cold_reload(tmp_path, monkeypatch, mode):
    path = tmp_path / 'owner-area-rulings.json'
    def ruling(call):
        path.write_text(json.dumps({'abilities': {COURT: {
            'recipients': call, 'reason': 'Owner test ruling'}}}))
    ruling('enemies')
    monkeypatch.setattr(area_recipient_rules, 'OVERRIDES', path)
    combat, table, mid = table_fight(tmp_path / 'fight', [COURT], ally_talents=[])
    result, option = _commit_area_action(table, mid, 'Court of Resonant Measure: ' + mode, None)
    finish(table, mid, result, option)
    for call in ('enemies', 'everyone', 'enemies'):
        ruling(call)
        # No service cache is carried between calls. Turn commits reconcile the
        # saved continuous conditions and fire each actor's start-turn packet.
        combat = CombatService(ROOT, combat.userdata_root)
        table = TabletopService(combat, combat.userdata_root)
        start = len(combat._load_session(mid).engine.events)
        for _ in range(3):
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
        loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
        continuous = {who for who, actor in loaded.engine.state.actors.items()
                      if any(c.condition_id == zones.ZONE_EFFECT and COURT in c.source_definition_id
                             for c in actor.conditions.values())}
        saves = {e.actor_id for e in loaded.engine.events[start:] if e.event_type == 'SAVE_ROLLED'
                 and COURT in (e.source_definition_id or '')}
        if mode == 'Dissonant Court':
            from combat.ext.music import dissonance_spares_friends
            expected = {LEFT, ALLY, RIGHT} if call == 'everyone' else {RIGHT}
            assert continuous == saves == expected
            assert {who for who, actor in loaded.engine.state.actors.items()
                    if not dissonance_spares_friends(loaded.engine, actor)} == expected
            for who in continuous:
                rules = [c.data['rule'] for c in loaded.engine.state.actors[who].conditions.values()
                         if c.condition_id == zones.ZONE_EFFECT]
                assert any(r.get('no_reactions') and r.get('concentration_mode') == 'DISADVANTAGE' for r in rules)
        else:
            assert continuous == {LEFT, ALLY} and not saves
        assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_continuous_harm_override_keeps_zone_eligibility_veto(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    path = tmp_path / 'owner-area-rulings.json'
    path.write_text(json.dumps({'abilities': {COURT: {'recipients': 'everyone', 'reason': 'Owner test'}}}))
    monkeypatch.setattr(area_recipient_rules, 'OVERRIDES', path)
    install(monkeypatch, 'zone_recipient_allowed',
            lambda engine, zone, actor, spec: False if actor.entity_id == ALLY else None)
    combat, table, mid = table_fight(tmp_path / 'fight', [COURT], ally_talents=[])
    result, option = _commit_area_action(table, mid, 'Court of Resonant Measure: Dissonant Court', None)
    finish(table, mid, result, option)
    for _ in range(3):
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    for who, actor in loaded.engine.state.actors.items():
        assert any(c.condition_id == zones.ZONE_EFFECT for c in actor.conditions.values()) == (who != ALLY)
    assert {e.actor_id for e in loaded.engine.events if e.event_type == 'SAVE_ROLLED'
            and COURT in (e.source_definition_id or '')} == {LEFT, RIGHT}
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
