"""Native mode removal, two compiled owners, and accepted table persistence."""
import pytest

from combat import attack_modes, typed_executor as te
from combat.ext.mind_hidden_eye import mark_analyzed
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, CombatServiceError
from tests.h1_support import duel, ME, FOE, ROOT, script, mechanics
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, HOLD
from tests.test_lock2_persistence import act

PIERCING = 'TAL_THE_HIDDEN_EYE_PIERCING_SENSES'
DISCERN = 'tianxia.talent.the_hidden_eye.discern_tells'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}]}}


def strike(e, attacker=ME, target=FOE, *, ranged=False):
    script(e, [11, 12, 1, 1])
    e._resolve_attack_spec(e.state.actors[attacker], e.state.actors[target],
                          {'attack_bonus': 0, 'range_ft' if ranged else 'reach_ft': 100},
                          e._active_intent, source_definition_id='test:native-strike')
    return next(x.payload for x in reversed(e.events) if x.event_type == 'ATTACK_ROLLED')


@pytest.mark.parametrize('field,owner,value', [
    ('attack_mode', ME, 'ADVANTAGE'), ('incoming_attack_mode', FOE, 'ADVANTAGE'),
    ('attack_mode_vs', ME, f'ADVANTAGE:{FOE}')])
def test_removal_precedes_cancellation_of_stored_modes(monkeypatch, field, owner, value):
    e = duel([])
    e._add_modifier(e.state.actors[owner], 'test:benefit', field, 'SET', value, 'NEXT_ATTACK', expires_on='CONSUMED')
    e._add_modifier(e.state.actors[ME], 'test:penalty', 'attack_mode', 'SET', 'DISADVANTAGE', 'NEXT_ATTACK', expires_on='CONSUMED')
    assert e._attack_mode(e.state.actors[ME], e.state.actors[FOE]) == 'NORMAL'
    install(monkeypatch, 'attack_mode_removed', lambda *a: ['ADVANTAGE'])
    install(monkeypatch, 'before_attack', lambda *a: {'mode': 'ADVANTAGE'})
    result = strike(e)
    assert result['mode'] == 'DISADVANTAGE'
    assert result['attack_mode_removed'] == ['ADVANTAGE']


@pytest.mark.parametrize('ranged', [False, True])
def test_native_query_receives_attack_kind_and_empty_is_inert(monkeypatch, ranged):
    seen = []
    e = duel([])
    install(monkeypatch, 'attack_mode_removed', lambda *a: seen.append(a[-1]))
    result = strike(e, ranged=ranged)
    # Menu presentation is a pure unknown-kind query; the committed strike
    # still supplies the exact native attack kind. Neither query changes modes.
    assert seen == [None, ranged]
    assert result['mode'] == 'NORMAL' and 'attack_mode_removed' not in result


@pytest.mark.parametrize('cause', ['invisible', 'blinded'])
def test_piercing_only_removes_named_condition_fields(cause):
    e = duel([PIERCING])
    me, foe = e.state.actors[ME], e.state.actors[FOE]
    owner = foe if cause == 'invisible' else me
    e._apply_condition(owner, 'condition:typed.' + cause, 'test:condition', FOE, expires_on='UNTIL_REMOVED')
    original = owner.model_dump(mode='json')['conditions']
    assert strike(e)['mode'] == 'NORMAL'
    assert owner.model_dump(mode='json')['conditions'] == original
    e._apply_condition(me, 'condition:typed.restrained', 'test:other', FOE, expires_on='UNTIL_REMOVED')
    assert strike(e)['mode'] == 'DISADVANTAGE'


def test_piercing_range_limit_and_no_false_parser_attacks():
    e = duel([PIERCING])
    e.state.actors[FOE].position = Position(x=11, y=6)
    e._apply_condition(e.state.actors[FOE], 'condition:typed.invisible', 'test:condition', FOE, expires_on='UNTIL_REMOVED')
    assert strike(e, ranged=True)['mode'] == 'DISADVANTAGE'
    assert mechanics()[PIERCING]['effects'] == []
    # Round 24's reviewed Insight rider is a passive rule, never a parser attack.
    assert mechanics()[DISCERN]['effects'] == [{'type': 'eye_rider_rule', 'kind': 'discern_tells'}]


def test_discern_requires_own_analysis_and_preserves_other_penalty():
    e = duel([DISCERN])
    me, foe = e.state.actors[ME], e.state.actors[FOE]
    e._add_modifier(foe, 'test:benefit', 'attack_mode', 'SET', 'ADVANTAGE', 'PERMANENT', expires_on='UNTIL_REMOVED')
    assert strike(e, FOE, ME)['mode'] == 'ADVANTAGE'
    mark_analyzed(e, me, foe, 'test:analyze')
    assert strike(e, FOE, ME)['mode'] == 'NORMAL'
    e._apply_condition(foe, 'condition:typed.restrained', 'test:other', ME, expires_on='UNTIL_REMOVED')
    assert strike(e, FOE, ME)['mode'] == 'DISADVANTAGE'


@pytest.mark.parametrize('unrelated', [False, True])
def test_typed_obscuration_is_scoped_and_does_not_remove_other_disadvantage(monkeypatch, unrelated):
    from combat import zones
    e = duel([PIERCING], kit=KIT)
    me, foe = e.state.actors[ME], e.state.actors[FOE]
    action = next(a for a in e.action_catalog.values() if a.owner_id == ME and a.parameters.get('typed', {}).get('weapon'))
    monkeypatch.setattr(zones, 'attack_mode', lambda *a: 'DISADVANTAGE')
    if unrelated:
        e._add_modifier(me, 'test:other', 'attack_mode', 'SET', 'DISADVANTAGE', 'NEXT_ATTACK', expires_on='CONSUMED')
    ctx = te.Context(e, me, action, e._active_intent, action.parameters['typed'], [foe], foe, {})
    te.block_attack(ctx, {'type': 'attack', 'attack_kind': 'weapon', 'count': 1, 'on_hit': []})
    roll = next(x.payload for x in reversed(e.events) if x.event_type == 'ATTACK_ROLLED')
    assert roll['mode'] == ('DISADVANTAGE' if unrelated else 'NORMAL')
    assert getattr(e, '_attack_mode_provenance', None) is None
    with pytest.raises(RuntimeError):
        with attack_modes.strike(e, me, foe, 'test:outer', {'m': 'DISADVANTAGE:obscured'}):
            assert attack_modes.provenance_for(e, me, foe, 'test:nested') == {}
            raise RuntimeError('abort')
    assert getattr(e, '_attack_mode_provenance', None) is None


@pytest.mark.parametrize('talent', [PIERCING, DISCERN])
def test_compiled_consumers_commit_reload_and_replay(monkeypatch, tmp_path, talent):
    combat, table, mid = table_fight(tmp_path, [talent], ally_talents=[])
    def attack(e):
        left, right = e.state.actors[LEFT], e.state.actors[RIGHT]
        if talent == PIERCING:
            e._apply_condition(right, 'condition:typed.invisible', 'test:condition', RIGHT, expires_on='UNTIL_REMOVED')
            strike(e, LEFT, RIGHT)
        else:
            mark_analyzed(e, left, right, 'test:analyze')
            e._add_modifier(right, 'test:benefit', 'attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK', expires_on='CONSUMED')
            strike(e, RIGHT, LEFT)
    on_hold(monkeypatch, attack)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    roll = next(x.payload for x in reversed(loaded.engine.events) if x.event_type == 'ATTACK_ROLLED')
    assert roll['mode'] == 'NORMAL' and roll['attack_mode_removed']
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_malformed_provider_rolls_back_table_action(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    install(monkeypatch, 'attack_mode_removed', lambda *a: ['invented'])
    on_hold(monkeypatch, lambda e: strike(e, LEFT, RIGHT))
    with pytest.raises(CombatServiceError):
        act(table, mid, HOLD)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json') == before
    assert loaded.mechanical.replay()['status'] == 'PASS'
