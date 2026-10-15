"""Equipment integration: causal critical packets, consent and qualified gear."""
import pytest

from combat import ext, falling
from combat.ext import equipment_armor
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script
from tests.test_lock9_critical_range import GAP, HELMET, native
from tests.test_auto_lane4 import _duel, ME, SUBJ, t
from tests.test_mgr_t14_fitted_armor import ACTOR, fight, sheet, support
from tests.test_tabletop_hunt6 import HOLD, on_hold

DAMAGE = 'action:test.mgr-t14.f5.bludgeoning'


def damage_action(bundle):
    if bundle['actor_id'] != support.ATTACKER:
        return
    support._bundle_action(bundle, DAMAGE, 'Bludgeoning test packet', {'typed': {
        'numbers': {}, 'mundane': False, 'duration': {'kind': 'instant'}, 'riders': [],
        'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': 20,
                     'damage_types': ['bludgeoning']}]}}, target_kind='HOSTILE_ENTITY', range_ft=60)
    support._seal(bundle)


@pytest.mark.parametrize('natural,critical', [(18, False), (19, True), (20, True)])
def test_native_critical_helper_keeps_a_causal_packet(natural, critical):
    from combat.ext.mind_hidden_eye import mark_analyzed
    engine = _duel([], attacker_talents=[GAP], attacker_kit=t.AXE_KIT)
    actor, target = engine.state.actors[ME], engine.state.actors[SUBJ]
    mark_analyzed(engine, actor, target, 'test:analyze')
    hit, spec, events = native(engine, natural)
    assert hit
    assert spec['resolved_attack_context'].critical is critical
    rolls = [e for e in events if e.event_type == 'DAMAGE_ROLLED']
    assert len(rolls) == 1 and len(rolls[0].payload['dice']) == 1 + int(critical)
    assert len([e for e in events if e.event_type == 'DAMAGE_COMMITTED']) == 1


def test_equipment_import_preserves_unrelated_critical_and_death_providers():
    engine = _duel(['TAL_BERSERKER_DEATHLESS', HELMET],
                   attacker_talents=[GAP, 'TAL_FENCING_FATAL_OPENING'], attacker_kit=t.AXE_KIT)
    for actor_id, feature in [(ME, GAP), (ME, 'TAL_FENCING_FATAL_OPENING'),
                              (SUBJ, HELMET), (SUBJ, 'TAL_BERSERKER_DEATHLESS')]:
        assert any(row.get('feature_id') == feature for row in engine.typed_passive_rows[actor_id])


@pytest.mark.parametrize('off_turn', [False, True])
def test_empty_fall_answer_is_one_choice_and_survives_reload(monkeypatch, tmp_path, off_turn):
    actor = support.ATTACKER if off_turn else support.DEFENDER
    combat, table, mid = support._table(tmp_path, ['padded_layers'], turn=actor)
    before = support._reload(tmp_path, mid).state.actors[support.DEFENDER].current_hp

    def launch(engine):
        script(engine, [3] * 20)
        falling.displace(engine, engine.state.actors[support.DEFENDER], 8,
                         'test:launch', intent=engine._active_intent)

    on_hold(monkeypatch, launch)
    prompts = support._commit(combat, table, mid, HOLD, actor=actor, answer=lambda p: None)
    assert [p['context']['reaction_source_id'] for p in prompts] == [support.FALLING_PROMPT]
    cold = support._reload(tmp_path, mid)
    target = cold.state.actors[support.DEFENDER]
    assert target.current_hp == before - 8
    assert target.turn_flags[equipment_armor.PADDED_ROUND_FLAG] == cold.state.round_number
    assert 'equipment_padded_fall_ordinary' not in target.turn_flags
    assert equipment_armor.FALLING_CLAIM not in target.turn_flags
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('trained', [False, True])
def test_robes_and_shield_use_only_the_declared_shield_training(tmp_path, trained):
    doc = sheet(['reinforced_robes'])
    doc['equipment'] = [{'starting_kit': {'items': support.SHIELD_ITEMS}}]
    doc['proficiencies'] = {'armor': ['shield'] if trained else []}
    combat, table, mid = fight(tmp_path, doc)
    for engine in (combat._load_session(mid).engine, support._reload(tmp_path, mid)):
        target = engine.state.actors[ACTOR]
        assert target.armor_class + engine._ac_modifier(target) == 13 + 2 * int(trained)
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)['match_id'] == mid


def test_packet_consent_coexists_with_main_defense_row_hook(monkeypatch, tmp_path):
    combat, table, mid = fight(tmp_path, sheet(['padded_layers']), prepare=damage_action)
    calls = []

    def rows(engine, target, amount, damage_type, source, attacker):
        if source != DAMAGE:
            return None
        from combat.pending_damage import packet_scratch
        scratch = packet_scratch(engine)
        assert scratch is not None
        scratch['test_defense_row_calls'] = scratch.get('test_defense_row_calls', 0) + 1
        assert scratch['test_defense_row_calls'] == 1
        calls.append(target.entity_id)
        return [{'kind': 'reduction', 'feature_id': 'test:extra-defense',
                 'damage_types': ['BLUDGEONING'], 'amount': 2}]

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'before_damage_defenses', [rows])
    prompts = support._commit(combat, table, mid, DAMAGE, answer=lambda p: ['use'])
    assert len(prompts) == 1
    assert calls and set(calls) == {ACTOR}
    cold = support._reload(tmp_path, mid)
    packet, = support._packets(cold, DAMAGE)
    assert packet.payload['hp_damage'] == 14
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'
