"""A2R01H review edges through real table commits and cold replay."""
import pytest
from tests.test_a2_r11_foundations import (
    _fight, _strike, _save, _typed_action, _move_20, _condition,
    DRAGON, DREAM, TYRANT, DRAGON_POOL, TRACE, PULSE, GENERATE_MIRROR_TRACE,
)
from tests.worker2_support import OWNER, FOE, candidate, settle, reload

CUT = 'foundation.dream_mirror_soul_anchor_v0_2B.reflection_cut'


def test_sovereign_pairs_drive_and_step_with_one_spend(tmp_path):
    combat, table, mid = _fight(tmp_path, DRAGON, 'Dragon-Wind Momentum',
        stage='Perfected', held=1, owner_actions=[_strike('Strike', OWNER, range_ft=30)])
    settle(table, mid, _move_20(combat, table, mid))
    prompts = settle(table, mid, candidate(combat, mid, 'Strike').candidate_id,
        choices={'reaction:typed.foundation.dragon_wind_vessel_v0_2E.momentum_drive': 'first',
                 'choice:needle.sovereign_second': 'momentum_step'})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.payload.get('resource_id') == DRAGON_POOL]
    assert len(spends) == 1 and spends[0].payload['amount'] == 1
    # The completed hit may generate fresh Momentum after both paid riders;
    # it is not an unrestricted Sovereign refund.
    pair = actor.turn_flags['foundations1_sovereign']
    assert pair['first'].endswith('.momentum_drive')
    assert pair['second'].endswith('.momentum_step')
    assert _condition(engine, actor, 'condition:typed.foundations1_walk_step')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sovereign_second' for p in prompts)
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.source_definition_id.endswith('.sovereign_momentum')]


@pytest.mark.parametrize('success_damage', [False, True])
def test_cut_ignores_non_damaging_failed_save(tmp_path, success_damage):
    restraint = _save('Binding Dream', OWNER, dc=100,
        on_fail=[{'type': 'condition', 'condition': 'restrained', 'applies_to': 'target',
                  'duration': 'until_end_of_next_turn'}],
        on_success=[{'type': 'damage', 'flat': 6, 'damage_types': ['FORCE']}] if success_damage else [])
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', stage='Refined',
                              held=1, owner_actions=[restraint])
    prompts = settle(table, mid, candidate(combat, mid, 'Binding Dream').candidate_id,
                     choices={'choice:needle.dream_mirror_round_cut': 'force'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[TRACE] == 1
    assert engine.state.actors[FOE].current_hp == engine.state.actors[FOE].maximum_hp
    assert _condition(engine, engine.state.actors[FOE], 'condition:typed.restrained')
    assert not _condition(engine, engine.state.actors[FOE], 'condition:typed.dream_mirror_reflection_counter')
    assert not [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.dream_mirror_round_cut']


def _check(name, *, ability='WIS', hazards=(), contest=False):
    action = _typed_action(name, OWNER, [{'type': 'contest_against',
        'actor_check': {'kind': 'check', 'ability': ability, 'hazards': list(hazards)},
        'target_check': ({'kind': 'check', 'ability': 'INT'} if contest else {'kind': 'dc', 'dc': 1})}],
        economy='NONE')
    action['parameters']['free_primary'] = True
    return action


@pytest.mark.parametrize('conversion', ['cut', 'witness'])
def test_mirror_carry_spend_regenerate_spend_same_round(tmp_path, conversion):
    first = _strike('First Cut', OWNER) if conversion == 'cut' else _check('First Witness')
    second = _strike('Second Cut', OWNER) if conversion == 'cut' else _check('Second Witness')
    generate = _save('Trace Dream', OWNER, dc=100,
                     on_fail=[{'type': 'damage', 'flat': 1, 'damage_types': ['FORCE']}])
    for action in (first, second, generate):
        action['economy'] = 'NONE'
        action['parameters']['free_primary'] = True
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', held=1,
                              owner_actions=[first, generate, second])
    choice = 'choice:needle.dream_mirror_round_' + conversion
    value = 'force' if conversion == 'cut' else 'use'
    prompts = settle(table, mid, candidate(combat, mid, first['display_name']).candidate_id,
                     choices={choice: value})
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[TRACE] == 0
    settle(table, mid, candidate(combat, mid, 'Trace Dream').candidate_id,
           picks={'reaction:typed.' + GENERATE_MIRROR_TRACE: 'first'})
    generated = reload(tmp_path, mid)
    assert generated.state.actors[OWNER].resources[TRACE] == 1
    prompts += settle(table, mid, candidate(combat, mid, second['display_name']).candidate_id,
                      choices={choice: value})
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == before.state.round_number
    assert engine.state.actors[OWNER].resources[TRACE] == 0
    actual = [p for p in prompts if p['context']['reaction_source_id'] == choice]
    assert len(actual) == 2
    for prompt, action in zip(actual, (first, second)):
        text = prompt['moment']
        assert action['display_name'] in text
        assert engine.state.actors[FOE if conversion == 'cut' else OWNER].display_name in text
        assert 'proficiency bonus' in text
        assert prompt['action'] == action['display_name']


@pytest.mark.parametrize('contest', [False, True])
@pytest.mark.parametrize('hazards,expected', [((), 0), (('grappled',), 1)])
def test_strength_check_requires_hostile_body_pressure(tmp_path, contest, hazards, expected, monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.raw_d20
    def succeed(self, **kwargs):
        roll = original(self, **kwargs)
        die = 20 if kwargs['actor_id'] == OWNER else 1
        return roll.model_copy(update={'dice': (die,), 'natural_result': die,
                                       'total': die + roll.modifier})
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', succeed)
    combat, table, mid = _fight(tmp_path, TYRANT, 'Tyrant Form Pulse', held=0,
        owner_actions=[_check('Lift or race', ability='STR', hazards=hazards, contest=contest)])
    settle(table, mid, candidate(combat, mid, 'Lift or race').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PULSE] == expected


def test_cut_has_one_compiled_route(tmp_path):
    combat, table, mid = _fight(tmp_path, DREAM, 'Mirror Trace', held=1,
                              owner_actions=[_strike('Strike', OWNER)])
    engine = reload(tmp_path, mid)
    bundle = next(d for d in engine.typed_bundle_documents if d['actor_id'] == OWNER)
    assert not [m for m in bundle['modifiers'] if m.get('id') == CUT]
    assert any(r.get('feature_id') == CUT for r in bundle['typed_passives'])
    assert not any(CUT in str(a.parameters.get('typed', {}).get('attack_modifier_loadout', []))
                   for a in engine.action_catalog.values())
    prompts = settle(table, mid, candidate(combat, mid, 'Strike').candidate_id,
                     choices={'choice:needle.dream_mirror_round_cut': 'force'})
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.dream_mirror_round_cut']) == 1


def test_damage_inheritance_contract_documented():
    from pathlib import Path
    import combat.ext
    text = Path(combat.ext.__file__).read_text()
    assert 'inherit_damage_type (boolean, default false)' in text
